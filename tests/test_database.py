"""Тесты async SQLAlchemy-хранилища инструментов (T-033)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.database import (
    Database,
    book_appointment,
    list_appointments,
    list_reminders,
    set_reminder,
)


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'tools.db').as_posix()}")
    await db.create_tables()
    yield db
    await db.dispose()


async def test_book_appointment_persists_record(database: Database) -> None:
    async with database.session() as session:
        appointment = await book_appointment(
            session,
            pet_name="Мурзик",
            date="2026-11-04",
            time="10:00",
        )

    async with database.session() as session:
        appointments = await list_appointments(session)

    assert appointment.id == 1
    assert len(appointments) == 1
    assert appointments[0].pet_name == "Мурзик"
    assert appointments[0].date == "2026-11-04"


async def test_set_reminder_persists_record(database: Database) -> None:
    async with database.session() as session:
        reminder = await set_reminder(
            session,
            text="Дать таблетку",
            time="20:00",
        )

    async with database.session() as session:
        reminders = await list_reminders(session)

    assert reminder.id == 1
    assert len(reminders) == 1
    assert reminders[0].text == "Дать таблетку"
    assert reminders[0].time == "20:00"


async def test_database_survives_new_session(database: Database) -> None:
    async with database.session() as session:
        await book_appointment(
            session,
            pet_name="Барсик",
            date="2026-11-05",
            time="12:30",
        )

    async with database.session() as session:
        appointments = await list_appointments(session)

    assert len(appointments) == 1
    assert appointments[0].pet_name == "Барсик"


async def test_empty_database_returns_empty_lists(database: Database) -> None:
    async with database.session() as session:
        assert await list_appointments(session) == []
        assert await list_reminders(session) == []
