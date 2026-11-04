"""Тесты скрипта создания/сброса synthetic-пользователя Telegram (T-133)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.auth import verify_password
from app.database import Database, get_user_by_email
from bot.client import telegram_credentials
from scripts import create_telegram_user as script


def _db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'telegram.db').as_posix()}"


async def _fetch_user(database_url: str, email: str) -> object:
    database = Database(database_url)
    try:
        async with database.session() as session:
            return await get_user_by_email(session, email)
    finally:
        await database.dispose()


def test_creates_user_with_derived_credentials(tmp_path: Path) -> None:
    database_url = _db_url(tmp_path)
    email, password = telegram_credentials(42, "s3cret")

    user, action = asyncio.run(
        script.create_telegram_user_in_db(
            database_url,
            telegram_id=42,
            secret="s3cret",
        )
    )

    assert action == script.ACTION_CREATED
    assert user.email == email
    assert user.is_admin is False
    assert verify_password(password, user.hashed_password)


def test_existing_user_is_reported_without_password_change(tmp_path: Path) -> None:
    database_url = _db_url(tmp_path)
    first, _ = asyncio.run(
        script.create_telegram_user_in_db(
            database_url,
            telegram_id=42,
            secret="s3cret",
        )
    )

    second, action = asyncio.run(
        script.create_telegram_user_in_db(
            database_url,
            telegram_id=42,
            secret="s3cret",
        )
    )

    assert action == script.ACTION_EXISTS
    assert second.id == first.id
    assert second.hashed_password == first.hashed_password


def test_reset_password_rewrites_hash_for_new_secret(tmp_path: Path) -> None:
    """После ротации секрета пароль старого аккаунта обновляется."""
    database_url = _db_url(tmp_path)
    asyncio.run(
        script.create_telegram_user_in_db(
            database_url,
            telegram_id=42,
            secret="old-secret",
        )
    )

    user, action = asyncio.run(
        script.create_telegram_user_in_db(
            database_url,
            telegram_id=42,
            secret="new-secret",
            reset_password=True,
        )
    )

    assert action == script.ACTION_RESET
    _, new_password = telegram_credentials(42, "new-secret")
    _, old_password = telegram_credentials(42, "old-secret")
    assert verify_password(new_password, user.hashed_password)
    assert not verify_password(old_password, user.hashed_password)

    stored = asyncio.run(_fetch_user(database_url, user.email))
    assert stored is not None
    assert stored.hashed_password == user.hashed_password  # type: ignore[attr-defined]


def test_main_reports_password_reset(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = _db_url(tmp_path)
    args = [
        "--telegram-id",
        "42",
        "--database-url",
        database_url,
        "--auth-secret",
        "s3cret",
    ]

    assert script.main(args) == 0
    capsys.readouterr()

    assert script.main([*args, "--reset-password"]) == 0
    output = capsys.readouterr().out
    assert "пароль сброшен" in output


def test_too_long_password_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        script,
        "telegram_credentials",
        lambda _telegram_id, _secret: ("user@example.com", "a" * 100),
    )

    with pytest.raises(script.PasswordTooLongError):
        asyncio.run(
            script.create_telegram_user_in_db(
                _db_url(tmp_path),
                telegram_id=1,
                secret="s3cret",
            )
        )
