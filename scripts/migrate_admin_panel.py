#!/usr/bin/env python
"""Накатить схему админ-панели (T-120) на существующую БД.

Скрипт идемпотентен: ``create_all`` создаёт отсутствующие таблицы, а мягкие
миграции добавляют в ``users`` поля ``is_admin``/``must_change_password`` и в
``access_requests`` поля аудита (``reviewed_at``, ``reviewed_by``,
``approved_user_id``, ``rejection_reason``). Существующие данные не удаляются.

Запуск в контейнере::

    docker compose -f docker-compose.edge.yml exec api \
      python scripts/migrate_admin_panel.py
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from app.database import Database
from app.settings import get_app_settings


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Применить миграции админ-панели к базе VetAssistant.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="SQLAlchemy async URL (по умолчанию VET_API_DATABASE_URL из настроек)",
    )
    return parser.parse_args(argv)


async def _migrate(url: str) -> None:
    database = Database(url)
    try:
        await database.create_tables()
        print(f"Схема обновлена: {database.engine.url.render_as_string(hide_password=True)}")
    finally:
        await database.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    url = args.database_url or get_app_settings().database_url
    asyncio.run(_migrate(url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
