#!/usr/bin/env python
"""Пилотный прогон Шагов A+B на выбранном провайдере (T-008).

Читает сиды (`data/seeds_bulk.jsonl`), для каждого запускает генерацию
вопроса владельца (Шаг A) и многотурного диалога (Шаг B), пишет диалоги в
`data/pilot_{provider}.jsonl` и печатает сводку: успехи, ошибки, время, токены.

Примеры::

    python scripts/run_pilot.py --dry-run
    python scripts/run_pilot.py --provider primary --limit 10
    python scripts/run_pilot.py --provider fallback --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from openai import OpenAIError
from pydantic import ValidationError

from configs.prompts import PromptError, get_prompts
from configs.settings import (
    PROJECT_ROOT,
    PROVIDER_NAMES,
    ProviderName,
    ProviderNotConfiguredError,
    get_provider,
)
from data_pipeline.cli import configure_logging, positive_int
from data_pipeline.dataset_io import (
    append_jsonl,
    read_seed_records,
    select_pending,
    write_jsonl,
)
from data_pipeline.generator import GenerationError, StageAGenerator, StageBGenerator
from data_pipeline.llm_client import TeacherClient
from data_pipeline.schemas import SeedRecord

DEFAULT_SEEDS = PROJECT_ROOT / "data" / "seeds_bulk.jsonl"
DEFAULT_LIMIT = 10
PREVIEW_SIZE = 2


def pilot_output_path(provider: ProviderName) -> Path:
    """Стандартный путь результата пилота для провайдера."""
    return PROJECT_ROOT / "data" / f"pilot_{provider}.jsonl"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Пилот: Шаг A + Шаг B на N сидах с выбранным провайдером.",
        epilog="Итог содержит число успехов/ошибок, время работы и токены.",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDER_NAMES,
        default="primary",
        help="какой провайдер использовать (по умолчанию primary)",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=DEFAULT_LIMIT,
        metavar="N",
        help=f"сколько сидов обработать (по умолчанию {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--seeds",
        type=Path,
        default=DEFAULT_SEEDS,
        metavar="PATH",
        help=f"входной JSONL сидов (по умолчанию {DEFAULT_SEEDS.name})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="выходной JSONL (по умолчанию data/pilot_{provider}.jsonl)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать промпты Шага A для первых 2 сидов, не вызывая API",
    )
    return parser.parse_args(argv)


def _preview(seeds: Sequence[SeedRecord], provider: ProviderName, output: Path) -> None:
    """Показать промпты без обращения к API (--dry-run)."""
    prompts = get_prompts()
    logger.info(
        "Провайдер: {} | выход: {} | сидов к обработке: {}",
        provider,
        output,
        len(seeds),
    )
    for index, seed in enumerate(seeds[:PREVIEW_SIZE], start=1):
        prompt = prompts.render_stage_a(topic=seed.topic, seed_text=seed.seed_text)
        logger.info(
            "--- Шаг A, промпт {}/{} | id={} | topic={} ---\n{}",
            index,
            len(seeds),
            seed.id,
            seed.topic,
            prompt,
        )
    logger.info("--dry-run: API не вызывается; Шаг B выполняется после Шага A")


async def _run_pilot(
    seeds: Sequence[SeedRecord],
    output: Path,
    provider_name: ProviderName,
) -> int:
    """Прогнать Шаги A+B и записать диалоги. Возвращает код выхода."""
    provider = get_provider(provider_name)
    logger.info(
        "Провайдер: {} | model={} | base_url={}",
        provider.name,
        provider.model,
        provider.base_url,
    )

    write_jsonl(output, [])  # перезапуск пилота перезаписывает результат
    started = time.perf_counter()
    success = 0
    errors = 0
    total_tokens = 0

    async with TeacherClient(provider) as client:
        stage_a = StageAGenerator(client)
        stage_b = StageBGenerator(client)

        for index, seed in enumerate(seeds, start=1):
            try:
                stage_a_record = await stage_a.generate_query(
                    seed.topic, seed.seed_text, seed_id=seed.id
                )
                dialogue = await stage_b.generate_dialogue(
                    stage_a_record.user_query, seed.topic, seed_id=seed.id
                )
            except (OpenAIError, GenerationError) as exc:
                errors += 1
                logger.error(
                    "[{}/{}] {} — {}: {}",
                    index,
                    len(seeds),
                    seed.id,
                    type(exc).__name__,
                    exc,
                )
                continue

            append_jsonl(output, dialogue.model_dump(mode="json"))
            success += 1
            total_tokens += stage_a_record.total_tokens + dialogue.total_tokens
            logger.info(
                "[{}/{}] {} → {} реплик, {} токенов",
                index,
                len(seeds),
                seed.id,
                len(dialogue.messages),
                stage_a_record.total_tokens + dialogue.total_tokens,
            )

    elapsed_s = time.perf_counter() - started
    logger.info(
        "Итог пилота ({}): успешно {}, ошибок {}, время {:.2f} с, токенов {}",
        provider.name,
        success,
        errors,
        elapsed_s,
        total_tokens,
    )
    logger.info("Результат: {}", output)
    return 0 if success else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    try:
        seeds = read_seed_records(args.seeds)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Не удалось прочитать сиды: {}", exc)
        return 1

    pending = select_pending(seeds, limit=args.limit)
    if not pending:
        logger.error("Нет сидов для пилота: {}", args.seeds)
        return 1

    provider_name: ProviderName = args.provider
    output: Path = args.output if args.output is not None else pilot_output_path(provider_name)

    if args.dry_run:
        try:
            _preview(pending, provider_name, output)
        except PromptError as exc:
            logger.error("Проблема с промптами: {}", exc)
            return 1
        return 0

    try:
        return asyncio.run(_run_pilot(pending, output, provider_name))
    except ValidationError as exc:
        logger.error("Проверьте .env: {}", exc)
        return 1
    except ProviderNotConfiguredError as exc:
        logger.error("{}", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
