#!/usr/bin/env python
"""Скрипт фильтрации датасета: PII + дедупликация (T-005).

Читает один или несколько JSONL (например, `dialogues_v1.jsonl` и
`safety_dialogues.jsonl`), отсеивает записи с e-mail/телефонами/именами
и дубликаты, пишет чистый результат в `--output`.

Примеры::

    python scripts/filter_data.py --input data/dialogues_v1.jsonl
    python scripts/filter_data.py --input data/dialogues_v1.jsonl data/safety_dialogues.jsonl \\
        --output data/dataset_v1_clean.jsonl
    python scripts/filter_data.py --input data/dialogues_v1.jsonl --dry-run
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from loguru import logger

from configs.settings import PROJECT_ROOT
from data_pipeline.cli import configure_logging
from data_pipeline.dataset_io import read_jsonl, write_jsonl
from data_pipeline.filter import filter_dataset

DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "dataset_v1_clean.jsonl"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Фильтрация датасета: PII (e-mail, телефоны, имена) и дубликаты.",
        epilog="Статистика: Всего: X, PII: Y, Дубликаты: Z, Осталось: W",
    )
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        required=True,
        metavar="PATH",
        help="один или несколько входных JSONL",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"выходной JSONL (перезаписывается; по умолчанию {DEFAULT_OUTPUT.name})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="посчитать статистику, но не записывать выходной файл",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    records: list[dict[str, object]] = []
    for path in args.input:
        if not path.exists():
            logger.error("Входной файл не найден: {}", path)
            return 1
        batch = list(read_jsonl(path))
        logger.info("{}: прочитано {}", path.name, len(batch))
        records.extend(batch)

    if not records:
        logger.warning("Входные файлы пусты — нечего фильтровать")
        return 1

    cleaned, report = filter_dataset(records)

    logger.info(
        "Всего: {}, PII: {}, Дубликаты: {}, Осталось: {}",
        report.total,
        report.pii_dropped,
        report.duplicates_dropped,
        report.remaining,
    )
    by_kind = ", ".join(f"{kind}={count}" for kind, count in report.pii_by_kind.items())
    logger.info("PII по типам: {}", by_kind)

    if args.dry_run:
        logger.info("--dry-run: {} не записан", args.output)
        return 0

    written = write_jsonl(args.output, cleaned)
    logger.info("Записано: {} ({} записей)", args.output, written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
