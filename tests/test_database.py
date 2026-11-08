"""Тесты async SQLAlchemy-хранилища инструментов (T-033, T-039)."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import (
    AdminAction,
    Database,
    TelegramLinkCode,
    User,
    book_appointment,
    create_user,
    get_user_by_email,
    get_user_by_id,
    list_appointments,
    list_reminders,
    set_reminder,
)
from configs.settings import PROJECT_ROOT


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


async def test_create_tables_migrates_telegram_link(tmp_path: Path) -> None:
    """Старая база получает users.telegram_id и таблицу кодов (T-134.1)."""
    path = tmp_path / "legacy_users.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE users ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "email VARCHAR(320) NOT NULL, "
            "hashed_password VARCHAR(255) NOT NULL, "
            "created_at DATETIME NOT NULL)"
        )
        connection.execute(
            "INSERT INTO users (email, hashed_password, created_at) "
            "VALUES ('old@example.com', 'hash', '2026-01-01 00:00:00')"
        )

    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    try:
        await database.create_tables()
        # Повторный запуск не должен падать или дублировать индексы.
        await database.create_tables()

        async with database.engine.connect() as connection:
            columns = await connection.execute(text("PRAGMA table_info(users)"))
            names = {row[1] for row in columns}
            indexes = await connection.execute(text("PRAGMA index_list(users)"))
            index_names = {row[1] for row in indexes}
            code_indexes = await connection.execute(
                text("PRAGMA index_list(telegram_link_codes)")
            )
            code_index_names = {row[1] for row in code_indexes}

        assert "telegram_id" in names
        assert "ix_users_telegram_id" in index_names
        assert {
            "ix_telegram_link_codes_code_hash",
            "ix_telegram_link_codes_user_id",
            "ix_telegram_link_codes_expires_at",
        } <= code_index_names

        async with database.session() as session:
            user = await get_user_by_email(session, "old@example.com")
            assert user is not None
            user.telegram_id = 42
            await session.commit()

        async with database.session() as session:
            refreshed = await get_user_by_email(session, "old@example.com")
            assert refreshed is not None
            assert refreshed.telegram_id == 42
    finally:
        await database.dispose()


async def test_telegram_id_is_unique(
    database: Database,
    users: tuple[User, User],
) -> None:
    """Один Telegram-аккаунт нельзя привязать к двум пользователям."""
    owner, other = users
    async with database.session() as session:
        first = await get_user_by_id(session, owner.id)
        second = await get_user_by_id(session, other.id)
        assert first is not None
        assert second is not None
        first.telegram_id = 777
        second.telegram_id = 777
        with pytest.raises(IntegrityError):
            await session.commit()


def test_telegram_migration_sql_matches_models() -> None:
    """Сырой SQL для сисадмина не расходится с ORM-моделью (T-134.1)."""
    script_path = (
        PROJECT_ROOT / "scripts" / "migrations" / "2026-11-05_telegram_linking.sql"
    )
    script = script_path.read_text(encoding="utf-8")

    marker = "CREATE TABLE IF NOT EXISTS telegram_link_codes ("
    assert marker in script
    table_block = script.split(marker, 1)[1].split(");", 1)[0]
    columns = {
        line.split()[0].rstrip(",").strip()
        for line in table_block.splitlines()
        if line.strip()
    }

    assert columns == {column.name for column in TelegramLinkCode.__table__.columns}
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_telegram_id" in script
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ix_telegram_link_codes_code_hash" in script
    assert "ON DELETE CASCADE" in script


async def test_create_tables_migrates_user_management(tmp_path: Path) -> None:
    """Старая база получает users.is_active и admin_actions (T-140.1)."""
    path = tmp_path / "legacy_admin.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE users ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "email VARCHAR(320) NOT NULL, "
            "hashed_password VARCHAR(255) NOT NULL, "
            "created_at DATETIME NOT NULL)"
        )
        connection.execute(
            "INSERT INTO users (email, hashed_password, created_at) "
            "VALUES ('old@example.com', 'hash', '2026-01-01 00:00:00')"
        )

    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    try:
        await database.create_tables()
        # Повторный запуск не должен падать или дублировать колонку.
        await database.create_tables()

        async with database.engine.connect() as connection:
            user_columns = await connection.execute(text("PRAGMA table_info(users)"))
            user_column_names = {row[1] for row in user_columns}
            action_columns = await connection.execute(
                text("PRAGMA table_info(admin_actions)")
            )
            action_column_names = {row[1] for row in action_columns}

        assert "is_active" in user_column_names
        assert action_column_names == {
            "id",
            "admin_id",
            "target_user_id",
            "action",
            "reason",
            "created_at",
        }

        async with database.session() as session:
            user = await get_user_by_email(session, "old@example.com")
            assert user is not None
            assert user.is_active is True
            session.add(
                AdminAction(
                    admin_id=user.id,
                    target_user_id=user.id,
                    action="block",
                    reason="тест",
                )
            )
            await session.commit()

        async with database.session() as session:
            session.add(
                AdminAction(
                    admin_id=1,
                    target_user_id=1,
                    action="unknown",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        await database.dispose()


def test_user_management_migration_sql_matches_models() -> None:
    """Сырой SQL управления пользователями не расходится с ORM-моделью."""
    script_path = (
        PROJECT_ROOT
        / "scripts"
        / "migrations"
        / "2026-11-08_user_management.sql"
    )
    script = script_path.read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE" in script

    marker = "CREATE TABLE IF NOT EXISTS admin_actions ("
    assert marker in script
    table_block = script.split(marker, 1)[1].split(");", 1)[0]
    columns: set[str] = set()
    for line in table_block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("CONSTRAINT", "CHECK")):
            continue
        columns.add(stripped.split()[0].rstrip(","))

    assert columns == {column.name for column in AdminAction.__table__.columns}
    assert "ON DELETE SET NULL" in table_block
    assert "target_user_id  INTEGER NOT NULL" in table_block
    assert "CHECK (action IN ('block', 'unblock', 'delete'))" in table_block
    assert "CREATE INDEX IF NOT EXISTS ix_admin_actions_admin_id" in script
    assert "CREATE INDEX IF NOT EXISTS ix_admin_actions_target_user_id" in script
