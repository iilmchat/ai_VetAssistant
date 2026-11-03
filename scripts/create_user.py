#!/usr/bin/env python
"""Ручное создание пользователя после одобрения заявки (T-112).

Регистрация через API закрыта. Админ создаёт аккаунт этим скриптом:

    python scripts/create_user.py --email owner@example.com
    python scripts/create_user.py --email owner@example.com --password 'strong-pass-1'

Если пароль не передан, он запрашивается через ``getpass``.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
from collections.abc import Sequence

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError

from app.auth import MAX_PASSWORD_BYTES, hash_password
from app.database import Database, User, create_user, get_user_by_email
from app.settings import get_app_settings

MIN_PASSWORD_LENGTH = 8
_email_adapter = TypeAdapter(EmailStr)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Создать пользователя напрямую в БД (в обход API).",
    )
    parser.add_argument("--email", required=True, metavar="EMAIL")
    parser.add_argument(
        "--password",
        default=None,
        metavar="PASSWORD",
        help="если не задан, будет запрошен через getpass",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        metavar="URL",
        help="SQLAlchemy async URL (по умолчанию VET_API_DATABASE_URL)",
    )
    return parser.parse_args(argv)


async def create_user_in_db(
    database_url: str,
    *,
    email: str,
    password: str,
) -> User:
    """Создать пользователя в указанной БД."""
    database = Database(database_url)
    try:
        await database.create_tables()
        async with database.session() as session:
            if await get_user_by_email(session, email) is not None:
                raise ValueError("пользователь с таким email уже существует")
            return await create_user(
                session,
                email=email,
                hashed_password=hash_password(password),
            )
    finally:
        await database.dispose()


def _normalize_email(value: str) -> str:
    """Проверить email и привести к нижнему регистру."""
    try:
        return str(_email_adapter.validate_python(value.strip())).lower()
    except ValidationError as exc:
        raise ValueError("некорректный email") from exc


def _validate_password(value: str) -> str:
    """Проверить минимальную длину и лимит bcrypt."""
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("пароль длиннее 72 байт")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    database_url = args.database_url or get_app_settings().database_url

    try:
        email = _normalize_email(args.email)
        password = args.password
        if password is None:
            password = getpass.getpass("Пароль нового пользователя: ")
        password = _validate_password(password)
    except ValueError as exc:
        print(f"Ошибка: {exc}")
        return 1

    try:
        user = asyncio.run(
            create_user_in_db(database_url, email=email, password=password),
        )
    except IntegrityError:
        print(f"Ошибка: пользователь {email} уже существует")
        return 1
    except ValueError as exc:
        print(f"Ошибка: {exc}")
        return 1

    print(f"Пользователь создан: {user.email} (id={user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
