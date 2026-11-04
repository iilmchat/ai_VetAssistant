#!/usr/bin/env python
"""Создать или обновить синтетического пользователя Telegram-бота (T-133).

Бот входит в API под email ``telegram-<id>@bot.vetassistant.local`` и
паролем, производным от ``VET_BOT_AUTH_SECRET`` (fallback —
``TELEGRAM_BOT_TOKEN``). Этот скрипт создаёт такого пользователя заранее,
чтобы после approve в allowlist бот мог авторизоваться.

Если пользователь уже существует и передан ``--reset-password``, скрипт
перезаписывает bcrypt-хэш новым паролем, вычисленным из текущего секрета.
Это нужно после ротации ``VET_BOT_AUTH_SECRET``: без сброса бот не сможет
войти в старый аккаунт.

Примеры:

    python scripts/create_telegram_user.py --telegram-id 1133302963
    python scripts/create_telegram_user.py --telegram-id 1133302963 --reset-password

Пароль не выводится.
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

Action = str

ACTION_CREATED = "created"
ACTION_EXISTS = "exists"
ACTION_RESET = "password_reset"


class PasswordTooLongError(ValueError):
    """Пароль не влезает в ограничение bcrypt (72 байта)."""


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
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="перезаписать пароль существующего пользователя новым секретом",
    )
    return parser.parse_args(argv)


async def create_telegram_user_in_db(
    database_url: str,
    *,
    telegram_id: int,
    secret: str,
    reset_password: bool = False,
) -> tuple[User, Action]:
    """Создать пользователя или сбросить ему пароль.

    Returns:
        (user, action), где ``action`` — ``created``, ``exists`` или
        ``password_reset``.

    Raises:
        PasswordTooLongError: вычисленный пароль длиннее 72 байт (bcrypt).
    """
    email, password = telegram_credentials(telegram_id, secret)
    if len(password.encode("utf-8")) > 72:
        raise PasswordTooLongError(
            "вычисленный пароль длиннее 72 байт; используйте другой secret",
        )

    database = Database(database_url)
    try:
        await database.create_tables()
        async with database.session() as session:
            existing = await get_user_by_email(session, email)
            if existing is not None:
                if not reset_password:
                    return existing, ACTION_EXISTS
                existing.hashed_password = hash_password(password)
                await session.commit()
                await session.refresh(existing)
                return existing, ACTION_RESET
            user = await create_user(
                session,
                email=email,
                hashed_password=hash_password(password),
            )
            return user, ACTION_CREATED
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

    try:
        user, action = asyncio.run(
            create_telegram_user_in_db(
                database_url,
                telegram_id=args.telegram_id,
                secret=secret,
                reset_password=bool(args.reset_password),
            ),
        )
    except PasswordTooLongError as exc:
        print(f"Ошибка: {exc}")
        return 1

    message = {
        ACTION_CREATED: "создан",
        ACTION_EXISTS: "уже существует (пароль не менялся)",
        ACTION_RESET: "существует, пароль сброшен по текущему секрету",
    }.get(action, action)
    print(f"Пользователь {message}: {user.email} (id={user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
