"""Тесты async SQLAlchemy-хранилища инструментов (T-033, T-039)."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text

from app.database import (
    Database,
    User,
    book_appointment,
    create_user,
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


@pytest.fixture
async def users(database: Database) -> tuple[User, User]:
    """Два пользователя для проверки мультитенантной изоляции."""
    async with database.session() as session:
        first = await create_user(
            session,
            email="owner@example.com",
            hashed_password="hash-1",
        )
        second = await create_user(
            session,
            email="other@example.com",
            hashed_password="hash-2",
        )
    return first, second


async def test_book_appointment_persists_record(
    database: Database,
    users: tuple[User, User],
) -> None:
    owner, _ = users
    async with database.session() as session:
        appointment = await book_appointment(
            session,
            user_id=owner.id,
            pet_name="Мурзик",
            date="2026-11-04",
            time="10:00",
        )

    async with database.session() as session:
        appointments = await list_appointments(session, user_id=owner.id)

    assert appointment.id == 1
    assert appointment.user_id == owner.id
    assert len(appointments) == 1
    assert appointments[0].pet_name == "Мурзик"
    assert appointments[0].date == "2026-11-04"


async def test_set_reminder_persists_record(
    database: Database,
    users: tuple[User, User],
) -> None:
    owner, _ = users
    async with database.session() as session:
        reminder = await set_reminder(
            session,
            user_id=owner.id,
            text="Дать таблетку",
            time="20:00",
        )

    async with database.session() as session:
        reminders = await list_reminders(session, user_id=owner.id)

    assert reminder.id == 1
    assert reminder.user_id == owner.id
    assert len(reminders) == 1
    assert reminders[0].text == "Дать таблетку"
    assert reminders[0].time == "20:00"


async def test_database_survives_new_session(
    database: Database,
    users: tuple[User, User],
) -> None:
    owner, _ = users
    async with database.session() as session:
        await book_appointment(
            session,
            user_id=owner.id,
            pet_name="Барсик",
            date="2026-11-05",
            time="12:30",
        )

    async with database.session() as session:
        appointments = await list_appointments(session, user_id=owner.id)

    assert len(appointments) == 1
    assert appointments[0].pet_name == "Барсик"


async def test_empty_database_returns_empty_lists(
    database: Database,
    users: tuple[User, User],
) -> None:
    owner, _ = users
    async with database.session() as session:
        assert await list_appointments(session, user_id=owner.id) == []
        assert await list_reminders(session, user_id=owner.id) == []


async def test_user_data_is_isolated(
    database: Database,
    users: tuple[User, User],
) -> None:
    owner, other = users
    async with database.session() as session:
        await book_appointment(
            session,
            user_id=owner.id,
            pet_name="Мурзик",
            date="2026-11-04",
            time="10:00",
        )
        await set_reminder(
            session,
            user_id=other.id,
            text="Купить корм",
            time="09:00",
        )

    async with database.session() as session:
        owner_appointments = await list_appointments(session, user_id=owner.id)
        other_appointments = await list_appointments(session, user_id=other.id)
        owner_reminders = await list_reminders(session, user_id=owner.id)
        other_reminders = await list_reminders(session, user_id=other.id)

    assert [item.pet_name for item in owner_appointments] == ["Мурзик"]
    assert other_appointments == []
    assert owner_reminders == []
    assert [item.text for item in other_reminders] == ["Купить корм"]


async def test_create_tables_migrates_legacy_rows(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE appointments ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "pet_name VARCHAR(120) NOT NULL, "
            "date VARCHAR(32) NOT NULL, "
            "time VARCHAR(32) NOT NULL)"
        )
        connection.execute(
            "INSERT INTO appointments (pet_name, date, time) "
            "VALUES ('Старый', '2026-01-01', '09:00')"
        )

    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    await database.create_tables()

    async with database.engine.connect() as connection:
        columns = await connection.execute(text("PRAGMA table_info(appointments)"))
        names = {row[1] for row in columns}

    assert "user_id" in names

    async with database.session() as session:
        user = await create_user(
            session,
            email="owner@example.com",
            hashed_password="hash",
        )
        await book_appointment(
            session,
            user_id=user.id,
            pet_name="Новый",
            date="2026-11-04",
            time="10:00",
        )

    async with database.session() as session:
        appointments = await list_appointments(session, user_id=user.id)

    assert [item.pet_name for item in appointments] == ["Новый"]
    await database.dispose()
