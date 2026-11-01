#!/usr/bin/env python
"""Генератор тестового массива сидов для пилота (T-008).

Создаёт `data/seeds_bulk.jsonl` с N синтетическими сидами: тема выбирается
случайно из таксономии, `seed_text` — заглушка (реальный MSD-контент для
масштабирования подставим позже). Генератор детерминирован при одном `--seed`,
поэтому массив воспроизводим.

Примеры::

    python scripts/generate_seeds.py --dry-run
    python scripts/generate_seeds.py --count 100
    python scripts/generate_seeds.py --count 20 --seed 7 --output data/seeds_bulk.jsonl
"""

from __future__ import annotations

import argparse
import random
from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from configs.settings import PROJECT_ROOT
from data_pipeline.cli import configure_logging, positive_int
from data_pipeline.dataset_io import read_jsonl, write_jsonl
from data_pipeline.schemas import SeedRecord, Topic

DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "seeds_bulk.jsonl"
DEFAULT_PETQA_OUTPUT = PROJECT_ROOT / "data" / "seeds_petqa.jsonl"
DEFAULT_PETQA_PATH = PROJECT_ROOT / "data" / "petqa_ru_questions.jsonl"
DEFAULT_COUNT = 100
DEFAULT_SEED = 42

#: Полная таксономия v1 (Design §3.2).
TOPICS: tuple[Topic, ...] = (
    "gastroenterology",
    "dermatology",
    "toxicology",
    "urology",
    "ophthalmology",
    "emergency",
    "behavior",
    "orthopedics",
    "cardiology",
    "endocrinology",
)


def build_seeds(count: int, *, rng: random.Random) -> list[SeedRecord]:
    """Сгенерировать `count` валидных сидов с уникальными id.

    Args:
        count: число записей (>= 1).
        rng: инициализированный `random.Random` (детерминизм задаёт вызывающий).
    """
    if count < 1:
        raise ValueError("count должен быть >= 1")

    records: list[SeedRecord] = []
    for index in range(1, count + 1):
        topic = rng.choice(TOPICS)
        seed_text = (
            f"Факт из MSD Vet Manual по теме {topic}, номер {index}: тестовый материал для пилота."
        )
        records.append(
            SeedRecord(
                id=f"bulk-{index:04d}",
                topic=topic,
                seed_text=seed_text,
            )
        )
    return records


def build_petqa_seeds(path: Path, count: int) -> list[SeedRecord]:
    """Прочитать русские вопросы PetQA и вернуть первые `count` валидных сидов."""
    if count < 1:
        raise ValueError("count должен быть >= 1")

    records = [SeedRecord.model_validate(payload) for payload in read_jsonl(path)]
    if not records:
        raise ValueError(f"файл PetQA-сидов пуст: {path}")
    return records[:count]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Сгенерировать тестовый массив сидов (JSONL) для пилота.",
        epilog="Темы выбираются случайно, seed_text — заглушка для проверки объёмов.",
    )
    parser.add_argument(
        "--source",
        choices=("synthetic", "petqa"),
        default="synthetic",
        help="источник сидов: synthetic (MSD-заглушка) или petqa (T-011)",
    )
    parser.add_argument(
        "--petqa-path",
        type=Path,
        default=DEFAULT_PETQA_PATH,
        metavar="PATH",
        help=f"русские вопросы PetQA (по умолчанию {DEFAULT_PETQA_PATH.name})",
    )
    parser.add_argument(
        "--count",
        type=positive_int,
        default=DEFAULT_COUNT,
        metavar="N",
        help=f"сколько сидов создать (по умолчанию {DEFAULT_COUNT})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        metavar="N",
        help=f"зерно генератора для воспроизводимости (по умолчанию {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "выходной JSONL (по умолчанию "
            f"{DEFAULT_OUTPUT.name} или {DEFAULT_PETQA_OUTPUT.name} для --source petqa)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="сгенерировать в памяти и показать первые записи, не записывая файл",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()
    output = args.output or (DEFAULT_PETQA_OUTPUT if args.source == "petqa" else DEFAULT_OUTPUT)

    try:
        if args.source == "petqa":
            records = build_petqa_seeds(args.petqa_path, args.count)
            logger.info(
                "Взято {} сидов из PetQA (запрошено {}, файл {})",
                len(records),
                args.count,
                args.petqa_path,
            )
        else:
            rng = random.Random(args.seed)
            records = build_seeds(args.count, rng=rng)
            logger.info(
                "Сгенерировано {} сидов (seed={}); тем: {}",
                len(records),
                args.seed,
                len({record.topic for record in records}),
            )
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        logger.error("Не удалось подготовить сиды: {}", exc)
        return 1

    if args.dry_run:
        for record in records[:2]:
            logger.info("{} | {} | {}", record.id, record.topic, record.seed_text)
        logger.info("--dry-run: {} не записан", output)
        return 0

    written = write_jsonl(output, [record.model_dump(mode="json") for record in records])
    logger.info("Записано: {} ({} записей)", output, written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
