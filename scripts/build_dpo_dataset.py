#!/usr/bin/env python
"""Собрать каркас датасета для DPO из оценок 👍/👎 (T-155).

Скрипт читает таблицу ``feedback`` (T-139) или готовый JSONL
``scripts/export_feedback.py`` (T-150), дедуплицирует оценки по
``message_id`` и делит их на детерминированные train/val-сплиты (по
умолчанию 80/20). Результат — JSONL-файлы и JSON-манифест::

    data/dpo/train.jsonl
    data/dpo/val.jsonl
    data/dpo/manifest.json

В каждой строке только ``message_id``, ``rating`` и ``split``::

    {"message_id": "msg-abc", "rating": 1, "split": "train"}

Приватность (152-ФЗ): текстов диалогов в БД нет, и скрипт их не добавляет.
Реальные ``user_id`` и псевдонимы тоже не выгружаются — датасет остаётся
каркасом, который на этапе обучения связывается с локальными логами по
``message_id``. Формат ``prompt → chosen/rejected`` без текстов не строится:
это отдельный этап после согласования ПДн.

Примеры::

    # Из БД по VET_API_DATABASE_URL
    python scripts/build_dpo_dataset.py

    # В контейнере api, только 👎 за ноябрь
    python scripts/build_dpo_dataset.py --rating -1 --since 2026-11-01 \\
        --output-dir /app/data/dpo

    # Из готового экспорта, без подключения к БД
    python scripts/build_dpo_dataset.py --input data/feedback.jsonl

    # Посмотреть сводку, ничего не записывая
    python scripts/build_dpo_dataset.py --dry-run

Коды выхода: 0 — успех, 1 — ошибка БД/чтения/записи, 2 — неверные
аргументы или некорректный JSONL.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# T-147: одинаково работаем и как `python scripts/build_dpo_dataset.py`,
# и как `python -m scripts.build_dpo_dataset`.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.settings import get_app_settings  # noqa: E402
from scripts.export_feedback import (  # noqa: E402
    _non_negative_int,
    _since_moment,
    _until_moment,
    fetch_feedback_rows,
)

DEFAULT_OUTPUT_DIR = Path("data") / "dpo"
DEFAULT_TRAIN_RATIO = 0.8
DEFAULT_SEED = 42
FORMAT_VERSION = "1.0"
SPLIT_TRAIN = "train"
SPLIT_VAL = "val"
RATING_VALUES = frozenset({1, -1})
MESSAGE_ID_LIMIT = 128


@dataclass(frozen=True)
class FeedbackRecord:
    """Минимум, который нужен для каркаса DPO: без текстов и без user_id."""

    message_id: str
    rating: int
    created_at: datetime | None = None


def _isoformat_utc(value: datetime) -> str:
    """ISO-8601 в UTC с суффиксом ``Z``."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validate_message_id(value: object, *, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: message_id должен быть непустой строкой")
    if len(value) > MESSAGE_ID_LIMIT:
        raise ValueError(
            f"{where}: message_id длиннее {MESSAGE_ID_LIMIT} символов"
        )
    return value


def _validate_rating(value: object, *, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in RATING_VALUES:
        raise ValueError(f"{where}: rating должен быть 1 или -1, получено {value!r}")
    return value


def records_from_feedback(rows: Iterable[Any]) -> list[FeedbackRecord]:
    """Преобразовать строки ``Feedback`` в записи датасета."""
    return [
        FeedbackRecord(
            message_id=row.message_id,
            rating=row.rating,
            created_at=row.created_at,
        )
        for row in rows
    ]


def read_jsonl(path: Path) -> list[FeedbackRecord]:
    """Прочитать JSONL прошлого экспорта; ``created_at`` необязателен.

    Raises:
        ValueError: строка не JSON, нет полей или неверные значения.
        OSError: файл не читается.
    """
    records: list[FeedbackRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            where = f"{path}:{line_number}"
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{where}: некорректный JSON ({exc})") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{where}: ожидался JSON-объект")

            message_id = _validate_message_id(payload.get("message_id"), where=where)
            rating = _validate_rating(payload.get("rating"), where=where)
            created_at: datetime | None = None
            raw_created = payload.get("created_at")
            if isinstance(raw_created, str) and raw_created.strip():
                try:
                    created_at = datetime.fromisoformat(
                        raw_created.replace("Z", "+00:00")
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"{where}: created_at не ISO-datetime"
                    ) from exc
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
            records.append(
                FeedbackRecord(
                    message_id=message_id,
                    rating=rating,
                    created_at=created_at,
                )
            )
    return records


def deduplicate(records: Iterable[FeedbackRecord]) -> tuple[list[FeedbackRecord], int]:
    """Оставить одну оценку на ``message_id`` — самую свежую.

    В БД уникальность действует на пару ``(user_id, message_id)``, поэтому
    одинаковый клиентский ``message_id`` теоретически может встретиться у
    разных пользователей. Для обучения нужна одна запись на сообщение:
    побеждает более поздняя оценка, при равном времени — последняя во входе.
    """
    selected: dict[str, FeedbackRecord] = {}
    seen = 0
    for record in records:
        seen += 1
        previous = selected.get(record.message_id)
        if previous is None:
            selected[record.message_id] = record
            continue
        previous_moment = previous.created_at or datetime.min.replace(tzinfo=UTC)
        current_moment = record.created_at or datetime.min.replace(tzinfo=UTC)
        if current_moment >= previous_moment:
            selected[record.message_id] = record
    return list(selected.values()), seen - len(selected)


def _split_key(message_id: str) -> str:
    """Стабильный ключ сортировки до перемешивания."""
    return hashlib.sha256(message_id.encode("utf-8")).hexdigest()


def build_split(
    records: Iterable[FeedbackRecord],
    *,
    train_ratio: float = DEFAULT_TRAIN_RATIO,
    seed: int = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    """Детерминированно разложить записи на train/val.

    Порядок не зависит от порядка строк в БД: записи сортируются по
    SHA-256 от ``message_id`` и перемешиваются ``random.Random(seed)``.
    Размер train — ``floor(total * train_ratio)``; для двух и более записей
    val всегда получает хотя бы одну строку.
    """
    if not 0.0 < train_ratio < 1.0:
        raise ValueError("train_ratio должен быть в диапазоне (0, 1)")

    ordered = sorted(records, key=lambda item: _split_key(item.message_id))
    random.Random(seed).shuffle(ordered)

    total = len(ordered)
    train_count = int(total * train_ratio)
    train_count = min(max(train_count, 1), total - 1) if total >= 2 else total

    rows: list[dict[str, Any]] = []
    for index, record in enumerate(ordered):
        rows.append(
            {
                "message_id": record.message_id,
                "rating": record.rating,
                "split": SPLIT_TRAIN if index < train_count else SPLIT_VAL,
            }
        )
    return rows


def summarize(
    rows: Sequence[dict[str, Any]],
    *,
    source: str,
    train_ratio: float,
    seed: int,
    duplicates_dropped: int,
    period_from: datetime | None,
    period_to: datetime | None,
) -> dict[str, Any]:
    """Сводка для ``manifest.json`` и ``--dry-run``."""
    train = sum(1 for row in rows if row["split"] == SPLIT_TRAIN)
    val = sum(1 for row in rows if row["split"] == SPLIT_VAL)
    positive = sum(1 for row in rows if row["rating"] == 1)
    negative = sum(1 for row in rows if row["rating"] == -1)
    return {
        "format_version": FORMAT_VERSION,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": source,
        "train_ratio": train_ratio,
        "seed": seed,
        "split_strategy": "sort by sha256(message_id), shuffle(seed)",
        "total": len(rows),
        "duplicates_dropped": duplicates_dropped,
        "splits": {SPLIT_TRAIN: train, SPLIT_VAL: val},
        "ratings": {"1": positive, "-1": negative},
        "period": (
            {
                "from": _isoformat_utc(period_from),
                "to": _isoformat_utc(period_to),
            }
            if period_from is not None and period_to is not None
            else None
        ),
        "files": {
            SPLIT_TRAIN: f"{SPLIT_TRAIN}.jsonl",
            SPLIT_VAL: f"{SPLIT_VAL}.jsonl",
        },
        "notes": (
            "Только message_id, rating и split: тексты диалогов не выгружаются "
            "(152-ФЗ), user_id и псевдонимы отсутствуют. Тексты связываются "
            "с message_id на этапе обучения из локальных логов."
        ),
    }


def write_jsonl(rows: Iterable[dict[str, Any]], path: Path) -> None:
    """Записать JSONL с завершающим переводом строки."""
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    body = "\n".join(lines)
    if body:
        body += "\n"
    path.write_text(body, encoding="utf-8", newline="\n")


def write_dataset(
    rows: Sequence[dict[str, Any]],
    *,
    output_dir: Path,
    manifest: dict[str, Any],
) -> None:
    """Создать каталог, train/val-файлы и манифест."""
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(
        (row for row in rows if row["split"] == SPLIT_TRAIN),
        output_dir / f"{SPLIT_TRAIN}.jsonl",
    )
    write_jsonl(
        (row for row in rows if row["split"] == SPLIT_VAL),
        output_dir / f"{SPLIT_VAL}.jsonl",
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description=(
            "Собрать каркас DPO-датасета из feedback: message_id, rating, "
            "split (train/val). Тексты и user_id не выгружаются (152-ФЗ)."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        metavar="URL",
        help="SQLAlchemy async URL (по умолчанию VET_API_DATABASE_URL)",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        metavar="FILE",
        help="готовый JSONL экспорта feedback вместо запроса к БД",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        metavar="PATH",
        help=f"каталог для train.jsonl/val.jsonl/manifest.json (по умолчанию {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=DEFAULT_TRAIN_RATIO,
        metavar="RATIO",
        help=f"доля train, 0 < ratio < 1 (по умолчанию {DEFAULT_TRAIN_RATIO})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        metavar="N",
        help=f"seed детерминированного перемешивания (по умолчанию {DEFAULT_SEED})",
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
        help="конец периода: YYYY-MM-DD включает весь день; ISO-datetime — строго до",
    )
    parser.add_argument(
        "--rating",
        type=int,
        choices=(1, -1),
        default=None,
        metavar="RATING",
        help="только оценки 1 (лайк) или -1 (дизлайк)",
    )
    parser.add_argument(
        "--limit",
        type=_non_negative_int,
        default=0,
        metavar="N",
        help="максимум строк из БД (0 — без ограничения)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать сводку, не записывая файлы",
    )
    return parser.parse_args(argv)


def _period(records: Iterable[FeedbackRecord]) -> tuple[datetime | None, datetime | None]:
    moments = [record.created_at for record in records if record.created_at is not None]
    if not moments:
        return None, None
    return min(moments), max(moments)


def _load_records(args: argparse.Namespace) -> tuple[list[FeedbackRecord], str]:
    if args.input is not None:
        return read_jsonl(args.input), str(args.input)

    database_url = args.database_url or get_app_settings().database_url
    rows = asyncio.run(
        fetch_feedback_rows(
            database_url,
            since=args.since,
            until=args.until,
            rating=args.rating,
            limit=args.limit,
        )
    )
    return records_from_feedback(rows), "database"


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)

    if args.input is not None and args.database_url is not None:
        print("Ошибка: --input и --database-url взаимоисключающие", file=sys.stderr)
        return 2
    if not 0.0 < args.train_ratio < 1.0:
        print("Ошибка: --train-ratio должен быть в диапазоне (0, 1)", file=sys.stderr)
        return 2

    try:
        records, source = _load_records(args)
    except (OSError, ValueError) as exc:
        print(f"Ошибка чтения оценок: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Ошибка чтения оценок: {exc}", file=sys.stderr)
        return 1

    unique, duplicates_dropped = deduplicate(records)
    period_from, period_to = _period(unique)
    rows = build_split(unique, train_ratio=args.train_ratio, seed=args.seed)
    manifest = summarize(
        rows,
        source=source,
        train_ratio=args.train_ratio,
        seed=args.seed,
        duplicates_dropped=duplicates_dropped,
        period_from=period_from,
        period_to=period_to,
    )

    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    try:
        write_dataset(rows, output_dir=args.output_dir, manifest=manifest)
    except OSError as exc:
        print(f"Ошибка записи датасета: {exc}", file=sys.stderr)
        return 1

    splits = manifest["splits"]
    print(
        f"Собрано записей: {manifest['total']} "
        f"(train {splits[SPLIT_TRAIN]}, val {splits[SPLIT_VAL]}, "
        f"дублей отброшено {duplicates_dropped}) → {args.output_dir}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
