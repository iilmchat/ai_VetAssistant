"""Async SQLAlchemy-хранилище VetAssistant (T-033, T-039, T-140.1, T-139.1).

В Docker используется PostgreSQL 16 + asyncpg; локально и в тестах — async
SQLite через aiosqlite. Таблицы создаются в lifespan FastAPI через
``Base.metadata.create_all``.

С T-039 данные изолированы по пользователям: ``appointments`` и
``reminders`` ссылаются на ``users.id``. Для уже существующих баз
``create_tables`` добавляет недостающую колонку ``user_id`` без потери
старых строк (они остаются невидимыми до привязки к пользователю).
С T-140.1 у пользователей есть ``is_active``, а действия администраторов
пишутся в ``admin_actions``. С T-139.1 оценки ответов лежат в ``feedback``:
только идентификатор сообщения и оценка, без текстов диалога (152-ФЗ).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from math import sqrt
from typing import Any, cast

from fastapi import HTTPException, Request
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    delete,
    func,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.elements import ColumnElement

from app.settings import DEFAULT_DATABASE_URL


class Base(DeclarativeBase):
    """Базовый класс ORM-моделей."""


#: Допустимые виды питомцев (T-160).
PATIENT_SPECIES: frozenset[str] = frozenset({"dog", "cat"})

#: Допустимые типы эпизодов памяти (T-160).
EPISODE_TYPES: frozenset[str] = frozenset(
    {"chat", "appointment", "reminder", "manual"}
)

#: Максимальная длина выжимки эпизода (152-ФЗ, T-160/T-162).
EPISODE_MAX_CONTENT_LENGTH = 500

#: Размерность эмбеддингов RAG-модели paraphrase-multilingual-MiniLM-L12-v2.
MEMORY_EMBEDDING_DIM = 384

#: Минимальное косинусное сходство для попадания в семантическую память.
MEMORY_MIN_SIMILARITY = 0.25

#: Сколько последних эпизодов просматривать на SQLite-фолбэке поиска.
MEMORY_SQLITE_SCAN_LIMIT = 200


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
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
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


class AdminAction(Base):
    """Аудит действий администратора над пользователями (T-140.1).

    ``admin_id`` — внешний ключ с ``ON DELETE SET NULL``: запись аудита
    переживает удаление администратора. ``target_user_id`` намеренно объявлен
    без внешнего ключа, чтобы действие ``delete`` не теряло идентификатор
    удалённого пользователя; это исторический журнал, а не живая ссылка.
    """

    __tablename__ = "admin_actions"
    __table_args__ = (
        CheckConstraint(
            "action IN ('block', 'unblock', 'delete')",
            name="ck_admin_actions_action",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    target_user_id: Mapped[int] = mapped_column(index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class Feedback(Base):
    """Оценка ответа ассистента 👍/👎 (T-139.1).

    Храним минимум: пользователя, идентификатор сообщения, оценку и время.
    Тексты диалогов в БД не попадают (152-ФЗ) — ``message_id`` это непрозрачный
    идентификатор сообщения на клиенте, а не его содержимое.

    Один пользователь может оценить сообщение только один раз:
    ``UNIQUE(user_id, message_id)``. Повторная оценка перезаписывает прежнюю
    (upsert в :func:`upsert_feedback`), поэтому история оценок не раздувается.
    """

    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "message_id",
            name="uq_feedback_user_message",
        ),
        CheckConstraint("rating IN (1, -1)", name="ck_feedback_rating"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    message_id: Mapped[str] = mapped_column(
        String(128),
        index=True,
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class Patient(Base):
    """Карточка питомца пользователя (T-160).

    ``user_id`` — владелец; удаление пользователя каскадно удаляет карточку.
    Обязательны только имя и вид, остальные поля дозаполняются через PATCH.
    """

    __tablename__ = "patients"
    __table_args__ = (
        CheckConstraint("species IN ('dog', 'cat')", name="ck_patients_species"),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_patients_name_not_blank",
        ),
        CheckConstraint(
            "weight IS NULL OR weight > 0",
            name="ck_patients_weight_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    species: Mapped[str] = mapped_column(String(16), nullable=False)
    breed: Mapped[str | None] = mapped_column(String(120), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    known_allergies: Mapped[str | None] = mapped_column(Text, nullable=True)
    chronic_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class Episode(Base):
    """Эпизод памяти питомца: краткая выжимка обсуждения (T-160).

    ``content`` ограничен 500 символами и не содержит полных диалогов или
    контактных данных (152-ФЗ). ``embedding`` — вектор RAG-модели
    (384 измерения) для семантического поиска; в SQLite хранится как JSON,
    чтобы локальные тесты шли без pgvector.
    """

    __tablename__ = "episodes"
    __table_args__ = (
        CheckConstraint(
            "type IN ('chat', 'appointment', 'reminder', 'manual')",
            name="ck_episodes_type",
        ),
        CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_episodes_content_not_blank",
        ),
        CheckConstraint(
            f"length(content) <= {EPISODE_MAX_CONTENT_LENGTH}",
            name="ck_episodes_content_length",
        ),
        Index("ix_episodes_patient_created", "patient_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(MEMORY_EMBEDDING_DIM).with_variant(JSON, "sqlite"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


@dataclass(frozen=True, slots=True)
class FeedbackStats:
    """Сводка оценок для админской аналитики (T-139.2)."""

    total: int
    positive: int
    negative: int

    @property
    def positive_ratio(self) -> float:
        """Доля положительных оценок: 0.0, если оценок ещё нет."""
        return self.positive / self.total if self.total else 0.0


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
    """Запись на приём, принадлежащая пользователю (T-173).

    ``patient_id`` связывает запись с карточкой питомца. Для старых строк и
    баз без карточек поле остаётся ``NULL``; новые записи создаются только
    после проверки/создания карточки в ``book_appointment``.
    """

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    patient_id: Mapped[int | None] = mapped_column(
        ForeignKey("patients.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
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

    # T-173: старые базы получают ссылку на карточку питомца. Для SQLite
    # REFERENCES в ALTER TABLE допустим, потому что колонка nullable.
    if "appointments" in existing_tables and "patients" in existing_tables:
        columns = {
            column["name"] for column in inspector.get_columns("appointments")
        }
        if "patient_id" not in columns:
            connection.execute(
                text(
                    "ALTER TABLE appointments ADD COLUMN patient_id INTEGER "
                    "REFERENCES patients(id) ON DELETE SET NULL"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_appointments_patient_id "
                    "ON appointments (patient_id)"
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


def _migrate_user_management(connection: Connection) -> None:
    """Добавить ``users.is_active`` в базы, созданные до T-140.1.

    Таблицу ``admin_actions`` создаёт ``Base.metadata.create_all``. Для старой
    таблицы ``users`` нужен отдельный ``ALTER TABLE``: ``create_all`` не меняет
    существующие таблицы. Существующие пользователи остаются активными.
    """
    inspector = inspect(connection)
    if "users" not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    if "is_active" in columns:
        return

    default = "TRUE" if connection.dialect.name == "postgresql" else "1"
    connection.execute(
        text(
            f"ALTER TABLE users ADD COLUMN is_active BOOLEAN "
            f"NOT NULL DEFAULT {default}"
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
        """Создать таблицы и мягко мигрировать схему до T-160."""
        async with self.engine.begin() as connection:
            # Для PostgreSQL векторный тип требует расширения pgvector.
            # В проде миграция применяется заранее; здесь — для dev/CI
            # и для идемпотентности при чистой базе.
            if connection.dialect.name == "postgresql":
                await connection.execute(
                    text("CREATE EXTENSION IF NOT EXISTS vector")
                )
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(_migrate_legacy_tables)
            await connection.run_sync(_migrate_admin_panel)
            await connection.run_sync(_migrate_telegram_link)
            await connection.run_sync(_migrate_user_management)

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


async def get_user_by_telegram_id(
    session: AsyncSession,
    telegram_id: int,
) -> User | None:
    """Найти пользователя, к которому привязан Telegram ID (T-134.3)."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
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
    patient_id: int | None = None,
) -> Appointment:
    """Сохранить запись на приём указанному пользователю (T-173)."""
    appointment = Appointment(
        user_id=user_id,
        patient_id=patient_id,
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


# --- Управление пользователями (T-140.2) -------------------------------------


async def list_users(
    session: AsyncSession,
    *,
    query: str | None = None,
    is_active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[User], int]:
    """Вернуть страницу пользователей и общее число по фильтру (T-140.2)."""
    filters: list[ColumnElement[bool]] = []
    if query:
        filters.append(User.email.icontains(query, autoescape=True))
    if is_active is not None:
        filters.append(User.is_active.is_(is_active))

    total_result = await session.execute(
        select(func.count()).select_from(User).where(*filters)
    )
    total = int(total_result.scalar_one())
    result = await session.execute(
        select(User)
        .where(*filters)
        .order_by(User.id)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def count_active_admins(session: AsyncSession) -> int:
    """Сколько администраторов могут войти прямо сейчас (T-140.2)."""
    result = await session.execute(
        select(func.count())
        .select_from(User)
        .where(User.is_admin.is_(True), User.is_active.is_(True))
    )
    return int(result.scalar_one())


def record_admin_action(
    session: AsyncSession,
    *,
    admin_id: int,
    target_user_id: int,
    action: str,
    reason: str | None = None,
) -> AdminAction:
    """Добавить запись аудита в текущую транзакцию (commit — у вызывающего)."""
    entry = AdminAction(
        admin_id=admin_id,
        target_user_id=target_user_id,
        action=action,
        reason=reason,
    )
    session.add(entry)
    return entry


async def delete_user_account(session: AsyncSession, user_id: int) -> bool:
    """Удалить пользователя и связанные данные (T-140.2).

    Каскад выполняется явно, чтобы поведение не зависело от ``PRAGMA
    foreign_keys`` в SQLite. Коммит остаётся за вызывающим: запись аудита и
    удаление должны попасть в одну транзакцию.
    """
    user = await get_user_by_id(session, user_id)
    if user is None:
        return False

    await session.execute(delete(Appointment).where(Appointment.user_id == user_id))
    await session.execute(delete(Reminder).where(Reminder.user_id == user_id))
    await session.execute(
        delete(TelegramLinkCode).where(TelegramLinkCode.user_id == user_id)
    )
    await session.execute(delete(Feedback).where(Feedback.user_id == user_id))
    # Сначала эпизоды: они ссылаются и на пациента, и на пользователя.
    # Затем карточки. Явно, чтобы не зависеть от PRAGMA foreign_keys в SQLite.
    await session.execute(delete(Episode).where(Episode.user_id == user_id))
    await session.execute(delete(Patient).where(Patient.user_id == user_id))
    await session.execute(
        update(AccessRequest)
        .where(AccessRequest.reviewed_by == user_id)
        .values(reviewed_by=None)
    )
    await session.execute(
        update(AccessRequest)
        .where(AccessRequest.approved_user_id == user_id)
        .values(approved_user_id=None)
    )
    # Запись аудита переживает удаление администратора.
    await session.execute(
        update(AdminAction)
        .where(AdminAction.admin_id == user_id)
        .values(admin_id=None)
    )
    await session.delete(user)
    return True


# --- Обратная связь по ответам (T-139) ---------------------------------------


async def upsert_feedback(
    session: AsyncSession,
    *,
    user_id: int,
    message_id: str,
    rating: int,
) -> Feedback:
    """Поставить или заменить оценку сообщения (T-139.2).

    Одна оценка на пользователя и сообщение: повторный запрос перезаписывает
    ``rating``, а не добавляет строку. Гонка двух одновременных запросов
    разрешается через ``IntegrityError`` на уникальном индексе — после откаты
    оценка заменяется на актуальную.
    """
    statement = select(Feedback).where(
        Feedback.user_id == user_id,
        Feedback.message_id == message_id,
    )
    result = await session.execute(statement)
    feedback = result.scalar_one_or_none()

    if feedback is None:
        feedback = Feedback(user_id=user_id, message_id=message_id, rating=rating)
        session.add(feedback)
        try:
            await session.commit()
        except IntegrityError:
            # Параллельный запрос успел вставить оценку — обновляем её.
            await session.rollback()
            result = await session.execute(statement)
            feedback = result.scalar_one()
            feedback.rating = rating
            await session.commit()
    else:
        feedback.rating = rating
        await session.commit()

    await session.refresh(feedback)
    return feedback


async def get_feedback_stats(session: AsyncSession) -> FeedbackStats:
    """Посчитать общее число оценок и расклад 👍/👎 (T-139.2)."""
    total = int(
        (await session.execute(select(func.count()).select_from(Feedback))).scalar_one()
    )
    positive = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Feedback)
                .where(Feedback.rating == 1)
            )
        ).scalar_one()
    )
    return FeedbackStats(total=total, positive=positive, negative=total - positive)


# --- Карточки пациентов и память (T-160) -------------------------------------


_PATIENT_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "species",
        "breed",
        "birth_date",
        "weight",
        "known_allergies",
        "chronic_conditions",
    }
)


def _clean_optional_text(value: str | None) -> str | None:
    """Обрезать необязательный текст; пустая строка превращается в ``None``."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_patient_fields(
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Проверить и нормализовать поля карточки питомца.

    Raises:
        ValueError: неизвестное поле, пустое имя или некорректный вид/вес/дата.
    """
    unknown = set(fields) - _PATIENT_FIELDS
    if unknown:
        raise ValueError(f"неизвестные поля пациента: {sorted(unknown)}")

    normalized: dict[str, Any] = {}

    if "name" in fields:
        name = fields["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("имя питомца не может быть пустым")
        name = name.strip()
        if len(name) > 120:
            raise ValueError("имя питомца длиннее 120 символов")
        normalized["name"] = name

    if "species" in fields:
        species = fields["species"]
        if species not in PATIENT_SPECIES:
            raise ValueError("вид питомца должен быть dog или cat")
        normalized["species"] = species

    if "breed" in fields:
        breed = _clean_optional_text(fields["breed"])
        if breed is not None and len(breed) > 120:
            raise ValueError("порода длиннее 120 символов")
        normalized["breed"] = breed

    if "birth_date" in fields:
        birth_date = fields["birth_date"]
        if birth_date is not None:
            if not isinstance(birth_date, date):
                raise ValueError("дата рождения должна быть датой")
            if birth_date > date.today():
                raise ValueError("дата рождения не может быть в будущем")
        normalized["birth_date"] = birth_date

    if "weight" in fields:
        weight = fields["weight"]
        if weight is not None:
            try:
                weight = Decimal(str(weight))
            except (ArithmeticError, ValueError) as exc:
                raise ValueError("вес должен быть числом") from exc
            if not weight.is_finite() or weight <= 0:
                raise ValueError("вес должен быть положительным")
            if weight >= Decimal("10000"):
                raise ValueError("вес слишком большой")
        normalized["weight"] = weight

    if "known_allergies" in fields:
        normalized["known_allergies"] = _clean_optional_text(
            fields["known_allergies"]
        )

    if "chronic_conditions" in fields:
        normalized["chronic_conditions"] = _clean_optional_text(
            fields["chronic_conditions"]
        )

    return normalized


async def create_patient(
    session: AsyncSession,
    *,
    user_id: int,
    name: str,
    species: str,
    breed: str | None = None,
    birth_date: date | None = None,
    weight: Decimal | float | None = None,
    known_allergies: str | None = None,
    chronic_conditions: str | None = None,
) -> Patient:
    """Создать карточку питомца, принадлежащую пользователю."""
    fields = _normalize_patient_fields(
        {
            "name": name,
            "species": species,
            "breed": breed,
            "birth_date": birth_date,
            "weight": weight,
            "known_allergies": known_allergies,
            "chronic_conditions": chronic_conditions,
        }
    )
    patient = Patient(user_id=user_id, **fields)
    session.add(patient)
    await session.commit()
    await session.refresh(patient)
    return patient


async def list_patients(
    session: AsyncSession,
    *,
    user_id: int,
) -> list[Patient]:
    """Вернуть карточки только указанного пользователя."""
    result = await session.execute(
        select(Patient)
        .where(Patient.user_id == user_id)
        .order_by(Patient.created_at, Patient.id)
    )
    return list(result.scalars().all())


async def get_patient(
    session: AsyncSession,
    *,
    user_id: int,
    patient_id: int,
) -> Patient | None:
    """Найти карточку пользователя по id (чужие карточки не видны)."""
    result = await session.execute(
        select(Patient).where(
            Patient.id == patient_id,
            Patient.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def update_patient(
    session: AsyncSession,
    *,
    user_id: int,
    patient_id: int,
    changes: Mapping[str, Any],
) -> Patient | None:
    """Дозаполнить карточку питомца.

    ``changes`` содержит только переданные клиентом поля (PATCH-семантика):
    отсутствующие ключи не меняются, явный ``None`` очищает необязательное
    поле. Чужая карточка возвращает ``None``.
    """
    patient = await get_patient(session, user_id=user_id, patient_id=patient_id)
    if patient is None:
        return None

    normalized = _normalize_patient_fields(changes)
    for key, value in normalized.items():
        setattr(patient, key, value)
    patient.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(patient)
    return patient


async def add_episode(
    session: AsyncSession,
    *,
    user_id: int,
    patient_id: int,
    content: str,
    episode_type: str = "chat",
    embedding: Sequence[float] | None = None,
) -> Episode:
    """Сохранить краткую выжимку эпизода в память питомца.

    Raises:
        LookupError: карточка не найдена или принадлежит другому пользователю.
        ValueError: неверный тип, пустой/слишком длинный текст или вектор.
    """
    episode_type = episode_type.strip().lower()
    if episode_type not in EPISODE_TYPES:
        raise ValueError(f"неизвестный тип эпизода: {episode_type}")

    content = content.strip()
    if not content:
        raise ValueError("описание эпизода не может быть пустым")
    if len(content) > EPISODE_MAX_CONTENT_LENGTH:
        raise ValueError(
            f"описание эпизода длиннее {EPISODE_MAX_CONTENT_LENGTH} символов"
        )

    vector: list[float] | None = None
    if embedding is not None:
        vector = [float(value) for value in embedding]
        if len(vector) != MEMORY_EMBEDDING_DIM:
            raise ValueError(
                f"эмбеддинг должен быть длины {MEMORY_EMBEDDING_DIM}"
            )

    patient = await get_patient(session, user_id=user_id, patient_id=patient_id)
    if patient is None:
        raise LookupError("питомец не найден")

    episode = Episode(
        patient_id=patient_id,
        user_id=user_id,
        type=episode_type,
        content=content,
        embedding=vector,
    )
    session.add(episode)
    await session.commit()
    await session.refresh(episode)
    return episode


async def list_episodes(
    session: AsyncSession,
    *,
    user_id: int,
    patient_id: int,
    limit: int = 20,
    offset: int = 0,
) -> list[Episode]:
    """Вернуть эпизоды питомца, новые сверху."""
    result = await session.execute(
        select(Episode)
        .where(
            Episode.user_id == user_id,
            Episode.patient_id == patient_id,
        )
        .order_by(Episode.created_at.desc(), Episode.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def count_episodes(
    session: AsyncSession,
    *,
    user_id: int,
    patient_id: int,
) -> int:
    """Посчитать эпизоды питомца для пагинации."""
    result = await session.execute(
        select(func.count())
        .select_from(Episode)
        .where(
            Episode.user_id == user_id,
            Episode.patient_id == patient_id,
        )
    )
    return int(result.scalar_one())


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Косинусное сходство двух векторов без numpy."""
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = sqrt(sum(a * a for a in left))
    right_norm = sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


async def search_similar_episodes(
    session: AsyncSession,
    *,
    user_id: int,
    patient_id: int,
    embedding: Sequence[float],
    limit: int = 3,
    exclude_ids: Sequence[int] = (),
    min_similarity: float = MEMORY_MIN_SIMILARITY,
) -> list[Episode]:
    """Найти эпизоды питомца, близкие к запросу, по косинусу.

    На PostgreSQL используется pgvector (`<=>` + HNSW), на SQLite —
    косинус в Python по последним ``MEMORY_SQLITE_SCAN_LIMIT`` эпизодам.
    Эпизоды без эмбеддинга пропускаются.
    """
    vector = [float(value) for value in embedding]
    if len(vector) != MEMORY_EMBEDDING_DIM:
        raise ValueError(f"эмбеддинг должен быть длины {MEMORY_EMBEDDING_DIM}")

    if session.get_bind().dialect.name == "postgresql":
        node = cast(Any, Episode.embedding)
        distance = node.cosine_distance(vector)
        statement = (
            select(Episode)
            .where(
                Episode.user_id == user_id,
                Episode.patient_id == patient_id,
                Episode.embedding.is_not(None),
                distance <= 1.0 - min_similarity,
            )
            .order_by(distance)
            .limit(limit)
        )
        if exclude_ids:
            statement = statement.where(Episode.id.not_in(exclude_ids))
        result = await session.execute(statement)
        return list(result.scalars().all())

    statement = (
        select(Episode)
        .where(
            Episode.user_id == user_id,
            Episode.patient_id == patient_id,
            Episode.embedding.is_not(None),
        )
        .order_by(Episode.created_at.desc(), Episode.id.desc())
        .limit(MEMORY_SQLITE_SCAN_LIMIT)
    )
    if exclude_ids:
        statement = statement.where(Episode.id.not_in(exclude_ids))
    result = await session.execute(statement)
    scored: list[tuple[float, Episode]] = []
    for episode in result.scalars().all():
        stored = episode.embedding
        if not stored:
            continue
        similarity = _cosine_similarity(vector, [float(value) for value in stored])
        if similarity >= min_similarity:
            scored.append((similarity, episode))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [episode for _, episode in scored[:limit]]
