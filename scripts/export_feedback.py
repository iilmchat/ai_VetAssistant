#!/usr/bin/env python
"""Экспорт оценок ответов в JSONL для DPO/SFT (T-150).

Выгружает таблицу ``feedback`` (T-139) в JSONL: по одной записи на строку.
Поля: ``message_id``, ``rating``, ``created_at`` — и ``user_id`` только по
флагу ``--include-user-id``, причём в виде псевдонима (HMAC-SHA256 с солью из
переменной окружения ``VET_EXPORT_PSEUDONYM_SALT``), а не настоящего id.

Приватность (152-ФЗ): текстов диалогов в БД нет, поэтому в выгрузке могут
быть только идентификатор сообщения и оценка. Псевдоним пользователя
позволяет группировать оценки одного человека между запусками, но не
раскрывает его id.

Примеры::

    # В stdout: все оценки
    python scripts/export_feedback.py

    # Только 👎 за последнюю неделю, в файл
    python scripts/export_feedback.py --since 2026-11-02 --rating -1 \
        --output data/feedback_negative.jsonl

    # С псевдонимом пользователя (нужна соль в окружении)
    VET_EXPORT_PSEUDONYM_SALT=change-me python scripts/export_feedback.py \
        --include-user-id --output data/feedback_dpo.jsonl

В stdout идут только JSONL-строки (удобно писать в пайп), служебные
сообщения — в stderr. Коды выхода: 0 — успех, 1 — ошибка БД/записи файла,
2 — неверные аргументы или отсутствует соль для ``--include-user-id``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# T-147: скрипт должен одинаково работать как `python scripts/export_feedback.py`,
# так и `python -m scripts.export_feedback`, не завися от установки пакета.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.database import Database, Feedback  # noqa: E402
from app.settings import get_app_settings  # noqa: E402

#: Переменная окружения с солью для псевдонимов пользователей.
PSEUDONYM_SALT_ENV = "VET_EXPORT_PSEUDONYM_SALT"

#: Префикс псевдонима: сразу видно, что это не настоящий user_id.
PSEUDONYM_PREFIX = "u_"

#: Сколько hex-символов HMAC оставляем в псевдониме (64 бита).
PSEUDONYM_HEX_LEN = 16


def pseudonymize(user_id: int, salt: str) -> str:
    """Детерминированный псевдоним пользователя: HMAC-SHA256(id, salt).

    Один и тот же пользователь при одной и той же соли получает один и тот
    же псевдоним в разных выгрузках — это нужно для группировки оценок, —
    но по псевдониму нельзя восстановить id без соли.
    """
    digest = hmac.new(
        salt.encode("utf-8"),
        str(user_id).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{PSEUDONYM_PREFIX}{digest[:PSEUDONYM_HEX_LEN]}"


def _parse_moment(value: str, *, end_of_day: bool) -> datetime:
    """Разобрать дату или datetime в UTC.

    ``YYYY-MM-DD`` — начало дня; для ``--until`` (``end_of_day=True``)
    добавляются сутки, чтобы в выборку попал весь день. Полный ISO-datetime
    возвращается как есть (naive считается UTC).
    """
    raw = value.strip()
    if not raw:
        raise argparse.ArgumentTypeError("пустая дата")

    try:
        day = date.fromisoformat(raw)
    except ValueError:
        day = None
    if day is not None:
        moment = datetime.combine(day, time.min, tzinfo=UTC)
        return moment + timedelta(days=1) if end_of_day else moment

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"ожидается YYYY-MM-DD или ISO-datetime, получено: {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _since_moment(value: str) -> datetime:
    return _parse_moment(value, end_of_day=False)


def _until_moment(value: str) -> datetime:
    return _parse_moment(value, end_of_day=True)


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"ожидается целое число, получено {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("значение не может быть отрицательным")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description=(
            "Выгрузить оценки ответов (👍/👎) из таблицы feedback в JSONL. "
            "Тексты диалогов не выгружаются (152-ФЗ)."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        metavar="URL",
        help="SQLAlchemy async URL (по умолчанию VET_API_DATABASE_URL)",
    )
    parser.add_argument(
        "--since",
        type=_since_moment,
        default=None,
        metavar="DATE",
        help="начало периода включительно: YYYY-MM-DD или ISO-datetime (UTC)",
    )
    parser.add_argument(
        "--until",
        type=_until_moment,
        default=None,
        metavar="DATE",
        help=(
            "конец периода: YYYY-MM-DD включает весь день; ISO-datetime — "
            "строго до момента"
        ),
    )
    parser.add_argument(
        "--rating",
        type=int,
        choices=(1, -1),
        default=None,
        metavar="RATING",
        help="только оценки 1 (👍) или -1 (👎)",
    )
    parser.add_argument(
        "--limit",
        type=_non_negative_int,
        default=0,
        metavar="N",
        help="максимум строк (0 — без ограничения, по умолчанию)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="FILE",
        help="записать JSONL в FILE вместо stdout",
    )
    parser.add_argument(
        "--include-user-id",
        action="store_true",
        help=(
            "добавить псевдоним пользователя (HMAC-SHA256 с солью из "
            f"{PSEUDONYM_SALT_ENV})"
        ),
    )
    return parser.parse_args(argv)


async def fetch_feedback_rows(
    database_url: str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    rating: int | None = None,
    limit: int = 0,
) -> list[Feedback]:
    """Прочитать оценки с фильтрами; стабильный порядок ``created_at, id``."""
    database = Database(database_url)
    try:
        async with database.session() as session:
            return await select_feedback_rows(
                session,
                since=since,
                until=until,
                rating=rating,
                limit=limit,
            )
    finally:
        await database.dispose()


async def select_feedback_rows(
    session: AsyncSession,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    rating: int | None = None,
    limit: int = 0,
) -> list[Feedback]:
    """Собрать SELECT по таблице ``feedback`` с фильтрами (T-150)."""
    statement = select(Feedback).order_by(Feedback.created_at, Feedback.id)
    if since is not None:
        statement = statement.where(Feedback.created_at >= since)
    if until is not None:
        statement = statement.where(Feedback.created_at < until)
    if rating is not None:
        statement = statement.where(Feedback.rating == rating)
    if limit > 0:
        statement = statement.limit(limit)

    result = await session.execute(statement)
    return list(result.scalars().all())


def _isoformat_utc(value: datetime) -> str:
    """ISO-8601 в UTC с суффиксом ``Z`` (SQLite отдаёт naive datetime)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_records(
    rows: Sequence[Feedback],
    *,
    include_user_id: bool,
    salt: str,
) -> list[dict[str, Any]]:
    """Собрать JSONL-записи: без текстов, только id/оценка/время.

    ``user_id`` добавляется только по флагу и только как псевдоним.
    """
    records: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {
            "message_id": row.message_id,
            "rating": row.rating,
            "created_at": _isoformat_utc(row.created_at),
        }
        if include_user_id:
            record["user_id"] = pseudonymize(row.user_id, salt)
        records.append(record)
    return records


def write_jsonl(records: Sequence[dict[str, Any]], output: Path | None) -> None:
    """Записать JSONL в файл или в stdout (создаёт родительские каталоги)."""
    lines = [json.dumps(record, ensure_ascii=False) for record in records]

    if output is None:
        for line in lines:
            print(line)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(lines)
    if body:
        body += "\n"
    output.write_text(body, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)

    salt = os.environ.get(PSEUDONYM_SALT_ENV, "").strip()
    if args.include_user_id and not salt:
        print(
            "Ошибка: для --include-user-id нужна соль в переменной окружения "
            f"{PSEUDONYM_SALT_ENV} (например: export {PSEUDONYM_SALT_ENV}=...). "
            "Без соли псевдонимы были бы тривиально обратимы.",
            file=sys.stderr,
        )
        return 2

    database_url = args.database_url or get_app_settings().database_url
    try:
        rows = asyncio.run(
            fetch_feedback_rows(
                database_url,
                since=args.since,
                until=args.until,
                rating=args.rating,
                limit=args.limit,
            )
        )
    except Exception as exc:
        print(f"Ошибка чтения оценок: {exc}", file=sys.stderr)
        return 1

    records = build_records(
        rows,
        include_user_id=bool(args.include_user_id),
        salt=salt,
    )
    try:
        write_jsonl(records, args.output)
    except OSError as exc:
        print(f"Ошибка записи файла: {exc}", file=sys.stderr)
        return 1

    destination = f" → {args.output}" if args.output is not None else ""
    print(f"Выгружено оценок: {len(records)}{destination}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
