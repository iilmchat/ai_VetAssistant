"""Async SQLAlchemy-хранилище для инструментов VetAssistant (T-033).

В Docker используется PostgreSQL 16 + asyncpg; локально и в тестах — async
SQLite через aiosqlite. Таблицы создаются в lifespan FastAPI через
``Base.metadata.create_all``.
"""

from __future__ import annotations

from sqlalchemy import String, select
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


class Appointment(Base):
    """Запись на приём."""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pet_name: Mapped[str] = mapped_column(String(120), nullable=False)
    date: Mapped[str] = mapped_column(String(32), nullable=False)
    time: Mapped[str] = mapped_column(String(32), nullable=False)


class Reminder(Base):
    """Напоминание."""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    time: Mapped[str] = mapped_column(String(32), nullable=False)


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
        """Создать таблицы, если их ещё нет."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    def session(self) -> AsyncSession:
        """Открыть новую сессию (используйте ``async with``)."""
        return self.session_factory()

    async def dispose(self) -> None:
        """Закрыть пул соединений."""
        await self.engine.dispose()


async def book_appointment(
    session: AsyncSession,
    *,
    pet_name: str,
    date: str,
    time: str,
) -> Appointment:
    """Сохранить запись на приём и вернуть её."""
    appointment = Appointment(pet_name=pet_name, date=date, time=time)
    session.add(appointment)
    await session.commit()
    await session.refresh(appointment)
    return appointment


async def set_reminder(
    session: AsyncSession,
    *,
    text: str,
    time: str,
) -> Reminder:
    """Сохранить напоминание и вернуть его."""
    reminder = Reminder(text=text, time=time)
    session.add(reminder)
    await session.commit()
    await session.refresh(reminder)
    return reminder


async def list_appointments(session: AsyncSession) -> list[Appointment]:
    """Вернуть все записи на приём."""
    result = await session.execute(select(Appointment).order_by(Appointment.id))
    return list(result.scalars().all())


async def list_reminders(session: AsyncSession) -> list[Reminder]:
    """Вернуть все напоминания."""
    result = await session.execute(select(Reminder).order_by(Reminder.id))
    return list(result.scalars().all())
