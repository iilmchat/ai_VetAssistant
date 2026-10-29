#!/usr/bin/env python
"""Шаг A: генерация вопросов владельцев из сидов (T-003).

Читает `data/seeds.jsonl`, для каждого сида рендерит промпт из
`configs/prompts.yaml` и просит учителя написать реалистичный вопрос
владельца животного. Результат дописывается в `data/stage_a_output.jsonl`.

Примеры::

    python scripts/run_stage_a.py --dry-run
    python scripts/run_stage_a.py --limit 2
    python scripts/run_stage_a.py --resume
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from openai import OpenAIError
from pydantic import ValidationError

from configs.prompts import PromptError, PromptRenderer, get_prompts
from configs.settings import PROJECT_ROOT, get_provider
from data_pipeline.cli import configure_logging, positive_int
from data_pipeline.dataset_io import (
    append_jsonl,
    collect_existing_ids,
    read_seed_records,
    select_pending,
)
from data_pipeline.generator import GenerationError, StageAGenerator
from data_pipeline.llm_client import TeacherClient
from data_pipeline.schemas import SeedRecord

DEFAULT_SEEDS = PROJECT_ROOT / "data" / "seeds.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "stage_a_output.jsonl"
PREVIEW_SIZE = 2


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Шаг A: генерация вопросов владельцев животных из сидов.",
        epilog="Промпт берётся из configs/prompts.yaml, ключи API — из .env.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="не вызывать API: показать первые 2 готовых промпта и выйти",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=None,
        metavar="N",
        help="обработать не больше N сидов",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="пропустить сиды, чьи id уже есть в выходном JSONL",
    )
    parser.add_argument(
        "--seeds",
        type=Path,
        default=DEFAULT_SEEDS,
        metavar="PATH",
        help=f"входной JSONL с сидами (по умолчанию {DEFAULT_SEEDS.name})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"выходной JSONL в режиме append (по умолчанию {DEFAULT_OUTPUT.name})",
    )
    return parser.parse_args(argv)


def _preview(seeds: Sequence[SeedRecord], prompts: PromptRenderer) -> None:
    """Показать готовые промпты без обращения к API (--dry-run)."""
    for index, seed in enumerate(seeds, start=1):
        prompt = prompts.render_stage_a(topic=seed.topic, seed_text=seed.seed_text)
        logger.info(
            "--- Промпт {}/{} | seed={} | topic={} ---\n{}",
            index,
            len(seeds),
            seed.id,
            seed.topic,
            prompt,
        )


async def _generate(
    seeds: Sequence[SeedRecord],
    output: Path,
    prompts: PromptRenderer,
) -> int:
    """Сгенерировать вопросы и дописать их в JSONL. Возвращает код выхода."""
    async with TeacherClient(get_provider()) as client:
        generator = StageAGenerator(client, prompts=prompts)
        for index, seed in enumerate(seeds, start=1):
            try:
                record = await generator.generate_query(seed.topic, seed.seed_text, seed_id=seed.id)
            except (OpenAIError, GenerationError) as exc:
                # RULES §6: остановиться, записать ошибку, сообщить Архитектору.
                logger.error(
                    "[{}/{}] {} — ошибка: {}: {}",
                    index,
                    len(seeds),
                    seed.id,
                    type(exc).__name__,
                    exc,
                )
                logger.error("Прогресс сохранён, продолжить можно флагом --resume")
                return 1

            append_jsonl(output, record.model_dump(mode="json"))
            logger.info("[{}/{}] {} → {}", index, len(seeds), seed.id, record.user_query)

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    try:
        seeds = read_seed_records(args.seeds)
        prompts = get_prompts()
    except (FileNotFoundError, ValueError, PromptError) as exc:
        logger.error("Не удалось подготовить генерацию: {}", exc)
        return 1

    existing_ids = collect_existing_ids(args.output) if args.resume else set()
    pending = select_pending(seeds, existing_ids=existing_ids, limit=args.limit)

    logger.info(
        "Сидов: {} | к обработке: {} | режим: {}",
        len(seeds),
        len(pending),
        "dry-run" if args.dry_run else "generate",
    )
    if args.resume:
        logger.info("--resume: уже обработано {}", len(existing_ids))

    if not pending:
        logger.info("Нечего обрабатывать")
        return 0

    if args.dry_run:
        _preview(pending[:PREVIEW_SIZE], prompts)
        return 0

    try:
        return asyncio.run(_generate(pending, args.output, prompts))
    except ValidationError as exc:  # настройки .env неполные
        logger.error("Проверьте .env: {}", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
