"""Тесты админских скриптов заявок и создания пользователя (T-112)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.auth import verify_password
from app.database import (
    Database,
    create_access_request,
    get_user_by_email,
)
from scripts.create_user import main as create_user_main
from scripts.list_access_requests import main as list_access_main


def _db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'admin.db').as_posix()}"


def test_create_user_script_creates_hashed_account(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_url = _db_url(tmp_path)

    result = create_user_main(
        [
            "--email",
            "Admin@Example.com",
            "--password",
            "strong-pass-1",
            "--database-url",
            db_url,
        ],
    )

    assert result == 0
    assert "admin@example.com" in capsys.readouterr().out

    async def fetch_hash() -> str:
        database = Database(db_url)
        try:
            async with database.session() as session:
                user = await get_user_by_email(session, "admin@example.com")
                assert user is not None
                return user.hashed_password
        finally:
            await database.dispose()

    hashed = asyncio.run(fetch_hash())
    assert hashed != "strong-pass-1"
    assert verify_password("strong-pass-1", hashed)


def test_create_user_script_rejects_duplicate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_url = _db_url(tmp_path)
    args = [
        "--email",
        "admin@example.com",
        "--password",
        "strong-pass-1",
        "--database-url",
        db_url,
    ]

    assert create_user_main(args) == 0
    assert create_user_main(args) == 1
    assert "уже существует" in capsys.readouterr().out


def test_create_user_script_rejects_short_password(
    tmp_path: Path,
) -> None:
    result = create_user_main(
        [
            "--email",
            "admin@example.com",
            "--password",
            "short",
            "--database-url",
            _db_url(tmp_path),
        ],
    )

    assert result == 1


def test_list_access_requests_prints_pending(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_url = _db_url(tmp_path)

    async def seed() -> None:
        database = Database(db_url)
        try:
            await database.create_tables()
            async with database.session() as session:
                await create_access_request(
                    session,
                    email="guest@example.com",
                    reason="Ветеринар, хочу протестировать",
                )
        finally:
            await database.dispose()

    asyncio.run(seed())

    assert list_access_main(["--database-url", db_url]) == 0
    output = capsys.readouterr().out
    assert "guest@example.com" in output
    assert "Ветеринар, хочу протестировать" in output
