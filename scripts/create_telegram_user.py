#!/usr/bin/env python
"""Создать синтетического пользователя для Telegram-бота.

Бот входит в API под email ``telegram-<id>@bot.vetassistant.local`` и
паролем, производным от ``VET_BOT_AUTH_SECRET`` (fallback —
``TELEGRAM_BOT_TOKEN``). Этот скрипт создаёт такого пользователя заранее,
чтобы после approve в allowlist бот мог авторизоваться.

Пример:

    python scripts/create_telegram_user.py --telegram-id 1133302963

Пароль не выводится. Если пользователь уже есть, скрипт сообщает об этом.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Sequence

from app.auth import hash_password
from app.database import Database, User, create_user, get_user_by_email
from app.settings import get_app_settings
from bot.client import telegram_credentials


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Создать synthetic-пользователя Telegram-бота.",
    )
    parser.add_argument(
        "--telegram-id",
        required=True,
        type=int,
        metavar="ID",
        help="Numeric Telegram user ID",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        metavar="URL",
        help="SQLAlchemy async URL (по умолчанию VET_API_DATABASE_URL)",
    )
    parser.add_argument(
        "--auth-secret",
        default=None,
        metavar="SECRET",
        help="HMAC secret (по умолчанию VET_BOT_AUTH_SECRET или TELEGRAM_BOT_TOKEN)",
    )
    return parser.parse_args(argv)


async def create_telegram_user_in_db(
    database_url: str,
    *,
    telegram_id: int,
    secret: str,
) -> tuple[User, bool]:
    """Создать пользователя; вернуть (user, created)."""
    email, password = telegram_credentials(telegram_id, secret)
    database = Database(database_url)
    try:
        await database.create_tables()
        async with database.session() as session:
            existing = await get_user_by_email(session, email)
            if existing is not None:
                return existing, False
            user = await create_user(
                session,
                email=email,
                hashed_password=hash_password(password),
            )
            return user, True
    finally:
        await database.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    database_url = args.database_url or get_app_settings().database_url
    secret = (
        args.auth_secret
        or os.environ.get("VET_BOT_AUTH_SECRET", "").strip()
        or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    )
    if not secret:
        print("Ошибка: задайте VET_BOT_AUTH_SECRET или TELEGRAM_BOT_TOKEN")
        return 1

    user, created = asyncio.run(
        create_telegram_user_in_db(
            database_url,
            telegram_id=args.telegram_id,
            secret=secret,
        ),
    )
    action = "создан" if created else "уже существует"
    print(f"Пользователь {action}: {user.email} (id={user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
