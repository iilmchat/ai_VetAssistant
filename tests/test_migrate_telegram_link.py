"""Тесты скрипта переноса данных Telegram (T-134.3)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select

from app.database import (
    Appointment,
    Database,
    Reminder,
    book_appointment,
    create_user,
    get_user_by_email,
    set_reminder,
)
from scripts.migrate_telegram_link import (
    MergeError,
    list_synthetic_accounts,
    main,
    merge_synthetic_account,
)

WEB_EMAIL = "owner@example.com"
TELEGRAM_ID = 1_133_302_963
SYNTHETIC_EMAIL = f"telegram-{TELEGRAM_ID}@bot.vetassistant.local"


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'telegram_merge.db').as_posix()}"


async def _seed(
    db_url: str,
    *,
    synthetic_telegram_id: int | None = None,
    appointments: int = 1,
    reminders: int = 1,
) -> tuple[int, int]:
    """Создать веб-аккаунт, synthetic-аккаунт и его данные."""
    database = Database(db_url)
    try:
        await database.create_tables()
        async with database.session() as session:
            web = await create_user(
                session,
                email=WEB_EMAIL,
                hashed_password="hash-web",
            )
            synthetic = await create_user(
                session,
                email=SYNTHETIC_EMAIL,
                hashed_password="hash-bot",
            )
            if synthetic_telegram_id is not None:
                synthetic.telegram_id = synthetic_telegram_id
                await session.commit()
            for index in range(appointments):
                await book_appointment(
                    session,
                    user_id=synthetic.id,
                    pet_name=f"Питомец {index}",
                    date="2026-11-06",
                    time="10:00",
                )
            for index in range(reminders):
                await set_reminder(
                    session,
                    user_id=synthetic.id,
                    text=f"Напоминание {index}",
                    time="20:00",
                )
            return web.id, synthetic.id
    finally:
        await database.dispose()


async def _state(
    db_url: str,
) -> tuple[int | None, int | None, list[tuple[int, str]], list[tuple[int, str]]]:
    """Прочитать привязки и принадлежность записей/напоминаний."""
    database = Database(db_url)
    try:
        async with database.session() as session:
            web = await get_user_by_email(session, WEB_EMAIL)
            synthetic = await get_user_by_email(session, SYNTHETIC_EMAIL)
            appointments = await session.execute(
                select(Appointment).order_by(Appointment.id)
            )
            reminders = await session.execute(
                select(Reminder).order_by(Reminder.id)
            )
            return (
                web.telegram_id if web is not None else None,
                synthetic.telegram_id if synthetic is not None else None,
                [
                    (item.user_id, item.pet_name)
                    for item in appointments.scalars().all()
                ],
                [(item.user_id, item.text) for item in reminders.scalars().all()],
            )
    finally:
        await database.dispose()


async def test_list_reports_synthetic_accounts(db_url: str) -> None:
    await _seed(db_url)

    reports = await list_synthetic_accounts(db_url)

    assert len(reports) == 1
    assert reports[0].email == SYNTHETIC_EMAIL
    assert reports[0].telegram_id is None
    assert reports[0].appointments == 1
    assert reports[0].reminders == 1


async def test_dry_run_reports_changes_without_writing(db_url: str) -> None:
    web_id, synthetic_id = await _seed(db_url)

    report = await merge_synthetic_account(
        db_url,
        email=WEB_EMAIL,
        telegram_id=TELEGRAM_ID,
        dry_run=True,
    )

    assert report.changed is True
    assert report.target_user_id == web_id
    assert report.synthetic_email == SYNTHETIC_EMAIL
    assert report.appointments == 1
    assert report.reminders == 1

    web_telegram_id, synthetic_telegram_id, appointments, reminders = await _state(
        db_url
    )
    assert web_telegram_id is None
    assert synthetic_telegram_id is None
    assert [owner for owner, _ in appointments] == [synthetic_id]
    assert [owner for owner, _ in reminders] == [synthetic_id]


async def test_merge_moves_data_and_keeps_synthetic_account(db_url: str) -> None:
    web_id, synthetic_id = await _seed(
        db_url,
        synthetic_telegram_id=TELEGRAM_ID,
    )

    report = await merge_synthetic_account(
        db_url,
        email=WEB_EMAIL,
        telegram_id=TELEGRAM_ID,
    )

    assert report.changed is True
    web_telegram_id, synthetic_telegram_id, appointments, reminders = await _state(
        db_url
    )
    assert web_telegram_id == TELEGRAM_ID
    assert synthetic_telegram_id is None
    assert [owner for owner, _ in appointments] == [web_id]
    assert [owner for owner, _ in reminders] == [web_id]

    # Synthetic-аккаунт остаётся: иначе бот не сможет войти под своим паролем.
    database = Database(db_url)
    try:
        async with database.session() as session:
            synthetic = await get_user_by_email(session, SYNTHETIC_EMAIL)
            assert synthetic is not None
            assert synthetic.id == synthetic_id
    finally:
        await database.dispose()


async def test_merge_is_idempotent(db_url: str) -> None:
    await _seed(db_url)
    await merge_synthetic_account(
        db_url,
        email=WEB_EMAIL,
        telegram_id=TELEGRAM_ID,
    )

    again = await merge_synthetic_account(
        db_url,
        email=WEB_EMAIL,
        telegram_id=TELEGRAM_ID,
    )

    assert again.changed is False
    assert again.appointments == 0
    assert again.reminders == 0


async def test_merge_rejects_missing_target(db_url: str) -> None:
    await _seed(db_url)

    with pytest.raises(MergeError, match="не найден"):
        await merge_synthetic_account(
            db_url,
            email="nobody@example.com",
            telegram_id=TELEGRAM_ID,
        )


async def test_merge_rejects_telegram_owned_by_another_account(
    db_url: str,
) -> None:
    await _seed(db_url)
    database = Database(db_url)
    try:
        async with database.session() as session:
            other = await create_user(
                session,
                email="other@example.com",
                hashed_password="hash-other",
            )
            other.telegram_id = TELEGRAM_ID
            await session.commit()
    finally:
        await database.dispose()

    with pytest.raises(MergeError, match="уже привязан"):
        await merge_synthetic_account(
            db_url,
            email=WEB_EMAIL,
            telegram_id=TELEGRAM_ID,
        )


async def test_merge_links_target_when_synthetic_is_absent(db_url: str) -> None:
    database = Database(db_url)
    try:
        await database.create_tables()
        async with database.session() as session:
            await create_user(
                session,
                email=WEB_EMAIL,
                hashed_password="hash-web",
            )
    finally:
        await database.dispose()

    report = await merge_synthetic_account(
        db_url,
        email=WEB_EMAIL,
        telegram_id=TELEGRAM_ID,
    )

    assert report.changed is True
    assert report.synthetic_email is None
    web_telegram_id, _, _, _ = await _state(db_url)
    assert web_telegram_id == TELEGRAM_ID


def test_cli_reports_and_dry_run(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    asyncio.run(_seed(db_url))

    assert main(["--database-url", db_url]) == 0
    report_output = capsys.readouterr().out
    assert "Synthetic-аккаунтов найдено: 1" in report_output
    assert "записей 1, напоминаний 1" in report_output

    code = main(
        [
            "--database-url",
            db_url,
            "--merge-user",
            WEB_EMAIL,
            str(TELEGRAM_ID),
            "--dry-run",
        ]
    )

    assert code == 0
    merge_output = capsys.readouterr().out
    assert "[dry-run]" in merge_output
    assert "записей 1" in merge_output


def test_cli_returns_error_on_conflict(
    db_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def seed_with_conflict() -> None:
        await _seed(db_url)
        database = Database(db_url)
        try:
            async with database.session() as session:
                other = await create_user(
                    session,
                    email="other@example.com",
                    hashed_password="hash-other",
                )
                other.telegram_id = TELEGRAM_ID
                await session.commit()
        finally:
            await database.dispose()

    asyncio.run(seed_with_conflict())

    code = main(
        [
            "--database-url",
            db_url,
            "--merge-user",
            WEB_EMAIL,
            str(TELEGRAM_ID),
        ]
    )

    assert code == 1
    assert "Ошибка" in capsys.readouterr().out


def test_cli_rejects_non_numeric_telegram_id(
    db_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            "--database-url",
            db_url,
            "--merge-user",
            WEB_EMAIL,
            "not-a-number",
        ]
    )

    assert code == 2
    assert "целым числом" in capsys.readouterr().out
