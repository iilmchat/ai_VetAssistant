#!/usr/bin/env python
"""Список pending-заявок на доступ (T-112).

Примеры::

    python scripts/list_access_requests.py
    python scripts/list_access_requests.py --database-url sqlite+aiosqlite:///...
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from app.database import AccessRequest, Database, list_pending_access_requests
from app.settings import get_app_settings


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Показать заявки на доступ со статусом pending.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        metavar="URL",
        help="SQLAlchemy async URL (по умолчанию VET_API_DATABASE_URL)",
    )
    return parser.parse_args(argv)


async def fetch_pending(database_url: str) -> list[AccessRequest]:
    """Прочитать pending-заявки из БД."""
    database = Database(database_url)
    try:
        async with database.session() as session:
            return await list_pending_access_requests(session)
    finally:
        await database.dispose()


def format_request(request: AccessRequest) -> str:
    """Отформатировать одну заявку для консоли."""
    created = request.created_at.strftime("%Y-%m-%d %H:%M")
    return f"#{request.id:<4} {created}  {request.email:<32} {request.reason}"


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    database_url = args.database_url or get_app_settings().database_url

    try:
        requests = asyncio.run(fetch_pending(database_url))
    except Exception as exc:
        print(f"Ошибка чтения заявок: {exc}")
        return 1

    if not requests:
        print("Pending-заявок нет.")
        return 0

    print(f"Pending-заявки: {len(requests)}")
    print("ID    Создана            Email                            Причина")
    for request in requests:
        print(format_request(request))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
