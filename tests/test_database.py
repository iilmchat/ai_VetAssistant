"""Тесты SQLite-хранилища инструментов (T-032)."""

from __future__ import annotations

from pathlib import Path

from app.database import (
    book_appointment,
    init_db,
    list_appointments,
    list_reminders,
    set_reminder,
)


def test_book_appointment_persists_record(tmp_path: Path) -> None:
    path = tmp_path / "tools.db"

    appointment = book_appointment(
        pet_name="Мурзик",
        date="2026-11-04",
        time="10:00",
        path=path,
    )

    assert appointment.id == 1
    appointments = list_appointments(path)
    assert len(appointments) == 1
    assert appointments[0] == appointment


def test_set_reminder_persists_record(tmp_path: Path) -> None:
    path = tmp_path / "tools.db"

    reminder = set_reminder(
        text="Дать таблетку",
        time="20:00",
        path=path,
    )

    assert reminder.id == 1
    reminders = list_reminders(path)
    assert len(reminders) == 1
    assert reminders[0] == reminder


def test_database_survives_new_connection(tmp_path: Path) -> None:
    path = init_db(tmp_path / "tools.db")
    book_appointment(
        pet_name="Барсик",
        date="2026-11-05",
        time="12:30",
        path=path,
    )

    assert list_appointments(path)[0].pet_name == "Барсик"


def test_empty_database_returns_empty_lists(tmp_path: Path) -> None:
    path = init_db(tmp_path / "empty.db")

    assert list_appointments(path) == []
    assert list_reminders(path) == []
