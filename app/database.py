"""SQLite-хранилище для инструментов VetAssistant (T-032).

Таблицы создаются лениво при первом обращении. Каждая операция открывает
отдельное соединение, поэтому модуль безопасно использовать из sync-эндпоинтов
FastAPI и тестов.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from configs.settings import PROJECT_ROOT

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "vetassistant.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pet_name TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    time TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Appointment:
    """Запись на приём."""

    id: int
    pet_name: str
    date: str
    time: str


@dataclass(frozen=True)
class Reminder:
    """Созданное напоминание."""

    id: int
    text: str
    time: str


def resolve_db_path(path: Path | None = None) -> Path:
    """Вернуть путь к БД (или путь по умолчанию)."""
    return path if path is not None else DEFAULT_DB_PATH


def _connect(path: Path) -> sqlite3.Connection:
    """Открыть соединение SQLite, создав родительскую папку."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(path: Path | None = None) -> Path:
    """Создать таблицы, если их ещё нет."""
    db_path = resolve_db_path(path)
    with _connect(db_path) as connection:
        connection.executescript(SCHEMA)
    return db_path


def book_appointment(
    *,
    pet_name: str,
    date: str,
    time: str,
    path: Path | None = None,
) -> Appointment:
    """Сохранить запись на приём и вернуть её."""
    db_path = init_db(path)
    with _connect(db_path) as connection:
        cursor = connection.execute(
            "INSERT INTO appointments (pet_name, date, time) VALUES (?, ?, ?)",
            (pet_name, date, time),
        )
        appointment_id = int(cursor.lastrowid or 0)
    return Appointment(id=appointment_id, pet_name=pet_name, date=date, time=time)


def set_reminder(
    *,
    text: str,
    time: str,
    path: Path | None = None,
) -> Reminder:
    """Сохранить напоминание и вернуть его."""
    db_path = init_db(path)
    with _connect(db_path) as connection:
        cursor = connection.execute(
            "INSERT INTO reminders (text, time) VALUES (?, ?)",
            (text, time),
        )
        reminder_id = int(cursor.lastrowid or 0)
    return Reminder(id=reminder_id, text=text, time=time)


def list_appointments(path: Path | None = None) -> list[Appointment]:
    """Вернуть все записи на приём (для проверок и отладки)."""
    db_path = init_db(path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, pet_name, date, time FROM appointments ORDER BY id"
        ).fetchall()
    return [
        Appointment(
            id=int(row["id"]),
            pet_name=str(row["pet_name"]),
            date=str(row["date"]),
            time=str(row["time"]),
        )
        for row in rows
    ]


def list_reminders(path: Path | None = None) -> list[Reminder]:
    """Вернуть все напоминания (для проверок и отладки)."""
    db_path = init_db(path)
    with _connect(db_path) as connection:
        rows = connection.execute("SELECT id, text, time FROM reminders ORDER BY id").fetchall()
    return [
        Reminder(
            id=int(row["id"]),
            text=str(row["text"]),
            time=str(row["time"]),
        )
        for row in rows
    ]
