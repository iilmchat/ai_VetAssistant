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

from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy import (
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
        """Создать таблицы и мягко мигрировать схему до T-039."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(_migrate_legacy_tables)

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
) -> User:
    """Создать пользователя и вернуть его."""
    user = User(email=email, hashed_password=hashed_password)
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


async def update_user_password(
    session: AsyncSession,
    *,
    user_id: int,
    hashed_password: str,
) -> User | None:
    """Заменить bcrypt-хэш пароля пользователя."""
    user = await get_user_by_id(session, user_id)
    if user is None:
        return None
    user.hashed_password = hashed_password
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
