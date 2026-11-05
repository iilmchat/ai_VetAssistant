"""Async SQLAlchemy-хранилище VetAssistant (T-033, T-039).

В Docker используется PostgreSQL 16 + asyncpg; локально и в тестах — async
SQLite через aiosqlite. Таблицы создаются в lifespan FastAPI через
``Base.metadata.create_all``.

С T-039 данные изолированы по пользователям: ``appointments`` и
``reminders`` ссылаются на ``users.id``. Для уже существующих баз
``create_tables`` добавляет недостающую колонку ``user_id`` без потери
старых строк (они остаются невидимыми до привязки к пользователю).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.settings import DEFAULT_DATABASE_URL


class Base(DeclarativeBase):
    """Базовый класс ORM-моделей."""


class User(Base):
    """Зарегистрированный пользователь сервиса."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(
        String(320),
        unique=True,
        index=True,
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    telegram_id: Mapped[int | None] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class AccessRequest(Base):
    """Заявка на доступ к закрытому сервису."""

    __tablename__ = "access_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_access_requests_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Appointment(Base):
    """Запись на приём, принадлежащая пользователю."""
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    pet_name: Mapped[str] = mapped_column(String(120), nullable=False)
    date: Mapped[str] = mapped_column(String(32), nullable=False)
    time: Mapped[str] = mapped_column(String(32), nullable=False)


class Reminder(Base):
    """Напоминание, принадлежащее пользователю."""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    time: Mapped[str] = mapped_column(String(32), nullable=False)


class TelegramLinkCode(Base):
    """Одноразовый код привязки Telegram к веб-аккаунту (T-134).

    Хранится только HMAC-SHA256 от кода (``code_hash``), сам код показывается
    пользователю один раз. ``telegram_id`` и ``used_at`` заполняются при
    успешном подтверждении ботом и служат источником ``linked_at``.
    """

    __tablename__ = "telegram_link_codes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


def _migrate_legacy_tables(connection: Connection) -> None:
    """Добавить ``user_id`` в таблицы, созданные до T-039."""
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    for table in ("appointments", "reminders"):
        if table not in existing_tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "user_id" in columns:
            continue

        references = "REFERENCES users(id)"
        if connection.dialect.name == "postgresql":
            references += " ON DELETE CASCADE"
        connection.execute(
            text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER {references}")
        )
        connection.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS ix_{table}_user_id "
                f"ON {table} (user_id)"
            )
        )


def _migrate_admin_panel(connection: Connection) -> None:
    """Добавить поля админ-панели в существующие таблицы (T-120)."""
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    is_postgres = connection.dialect.name == "postgresql"
    bool_default = "FALSE" if is_postgres else "0"
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if is_postgres else "DATETIME"
    reference = " REFERENCES users(id) ON DELETE SET NULL" if is_postgres else ""

    if "users" in existing_tables:
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "is_admin" not in columns:
            connection.execute(
                text(
                    f"ALTER TABLE users ADD COLUMN is_admin BOOLEAN "
                    f"NOT NULL DEFAULT {bool_default}"
                )
            )
        if "must_change_password" not in columns:
            connection.execute(
                text(
                    f"ALTER TABLE users ADD COLUMN must_change_password BOOLEAN "
                    f"NOT NULL DEFAULT {bool_default}"
                )
            )

    if "access_requests" in existing_tables:
        columns = {
            column["name"] for column in inspector.get_columns("access_requests")
        }
        additions = {
            "reviewed_at": timestamp_type,
            "reviewed_by": f"INTEGER{reference}",
            "approved_user_id": f"INTEGER{reference}",
            "rejection_reason": "TEXT",
        }
        for name, column_type in additions.items():
            if name not in columns:
                connection.execute(
                    text(
                        f"ALTER TABLE access_requests ADD COLUMN {name} {column_type}"
                    )
                )


def _migrate_telegram_link(connection: Connection) -> None:
    """Добавить ``users.telegram_id`` и уникальный индекс (T-134).

    ``Base.metadata.create_all`` не меняет существующие таблицы, поэтому для
    старых баз колонка добавляется отдельным ``ALTER TABLE``. Уникальный
    индекс создаётся с ``IF NOT EXISTS`` и позволяет несколько ``NULL``
    (в обеих СУБД ``NULL`` не конфликтует с ``NULL``). Таблицу
    ``telegram_link_codes`` создаёт сам ``create_all``.
    """
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    if "users" not in existing_tables:
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "telegram_id" not in columns:
        connection.execute(text("ALTER TABLE users ADD COLUMN telegram_id BIGINT"))

    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_telegram_id "
            "ON users (telegram_id)"
        )
    )


class Database:
    """Async-движок и фабрика сессий SQLAlchemy."""

    def __init__(self, url: str = DEFAULT_DATABASE_URL) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(url, future=True)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    async def create_tables(self) -> None:
        """Создать таблицы и мягко мигрировать схему до T-039/T-120/T-134."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(_migrate_legacy_tables)
            await connection.run_sync(_migrate_admin_panel)
            await connection.run_sync(_migrate_telegram_link)

    def session(self) -> AsyncSession:
        """Открыть новую сессию (используйте ``async with``)."""
        return self.session_factory()

    async def dispose(self) -> None:
        """Закрыть пул соединений."""
        await self.engine.dispose()


def get_database(request: Request) -> Database:
    """FastAPI-зависимость: БД, созданная в lifespan."""
    database = getattr(request.app.state, "db", None)
    if not isinstance(database, Database):
        raise HTTPException(status_code=503, detail="База данных недоступна")
    return database


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    hashed_password: str,
    is_admin: bool = False,
    must_change_password: bool = False,
) -> User:
    """Создать пользователя и вернуть его."""
    user = User(
        email=email,
        hashed_password=hashed_password,
        is_admin=is_admin,
        must_change_password=must_change_password,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Найти пользователя по email."""
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    """Найти пользователя по идентификатору."""
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_users_by_ids(session: AsyncSession, user_ids: Sequence[int]) -> list[User]:
    """Найти пользователей списком id (для админской аналитики, T-135)."""
    unique_ids = list(dict.fromkeys(user_ids))
    if not unique_ids:
        return []
    result = await session.execute(select(User).where(User.id.in_(unique_ids)))
    return list(result.scalars().all())


async def update_user_password(
    session: AsyncSession,
    *,
    user_id: int,
    hashed_password: str,
    must_change_password: bool | None = None,
) -> User | None:
    """Заменить bcrypt-хэш пароля пользователя."""
    user = await get_user_by_id(session, user_id)
    if user is None:
        return None
    user.hashed_password = hashed_password
    if must_change_password is not None:
        user.must_change_password = must_change_password
    await session.commit()
    await session.refresh(user)
    return user


async def create_access_request(
    session: AsyncSession,
    *,
    email: str,
    reason: str,
) -> AccessRequest:
    """Сохранить заявку на доступ со статусом pending."""
    request = AccessRequest(email=email, reason=reason, status="pending")
    session.add(request)
    await session.commit()
    await session.refresh(request)
    return request


async def get_pending_access_request(
    session: AsyncSession,
    email: str,
) -> AccessRequest | None:
    """Найти последнюю pending-заявку по email."""
    result = await session.execute(
        select(AccessRequest)
        .where(
            AccessRequest.email == email,
            AccessRequest.status == "pending",
        )
        .order_by(AccessRequest.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_pending_access_requests(
    session: AsyncSession,
) -> list[AccessRequest]:
    """Вернуть все pending-заявки в порядке поступления."""
    result = await session.execute(
        select(AccessRequest)
        .where(AccessRequest.status == "pending")
        .order_by(AccessRequest.created_at, AccessRequest.id)
    )
    return list(result.scalars().all())


async def list_access_requests(
    session: AsyncSession,
    *,
    status: str | None = None,
) -> list[AccessRequest]:
    """Вернуть заявки, опционально отфильтрованные по статусу."""
    statement = select(AccessRequest).order_by(
        AccessRequest.created_at,
        AccessRequest.id,
    )
    if status is not None:
        statement = statement.where(AccessRequest.status == status)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def get_access_request_by_id(
    session: AsyncSession,
    request_id: int,
) -> AccessRequest | None:
    """Найти заявку по идентификатору."""
    result = await session.execute(
        select(AccessRequest).where(AccessRequest.id == request_id)
    )
    return result.scalar_one_or_none()


async def book_appointment(
    session: AsyncSession,
    *,
    user_id: int,
    pet_name: str,
    date: str,
    time: str,
) -> Appointment:
    """Сохранить запись на приём указанному пользователю."""
    appointment = Appointment(
        user_id=user_id,
        pet_name=pet_name,
        date=date,
        time=time,
    )
    session.add(appointment)
    await session.commit()
    await session.refresh(appointment)
    return appointment


async def set_reminder(
    session: AsyncSession,
    *,
    user_id: int,
    text: str,
    time: str,
) -> Reminder:
    """Сохранить напоминание указанному пользователю."""
    reminder = Reminder(user_id=user_id, text=text, time=time)
    session.add(reminder)
    await session.commit()
    await session.refresh(reminder)
    return reminder


async def list_appointments(
    session: AsyncSession,
    *,
    user_id: int,
) -> list[Appointment]:
    """Вернуть записи на приём только указанного пользователя."""
    result = await session.execute(
        select(Appointment)
        .where(Appointment.user_id == user_id)
        .order_by(Appointment.id)
    )
    return list(result.scalars().all())


async def list_reminders(
    session: AsyncSession,
    *,
    user_id: int,
) -> list[Reminder]:
    """Вернуть напоминания только указанного пользователя."""
    result = await session.execute(
        select(Reminder)
        .where(Reminder.user_id == user_id)
        .order_by(Reminder.id)
    )
    return list(result.scalars().all())
