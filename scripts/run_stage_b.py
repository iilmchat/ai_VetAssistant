#!/usr/bin/env python
"""Шаг B: генерация многотурных диалогов (T-004).

Читает `data/stage_a_output.jsonl` (вопросы владельцев из Шага A), для каждой
записи рендерит промпт Шага B из `configs/prompts.yaml`, просит учителя
написать диалог и дописывает результат в `data/dialogues_v1.jsonl`.

Примеры::

    python scripts/run_stage_b.py --dry-run
    python scripts/run_stage_b.py --limit 2
    python scripts/run_stage_b.py --resume
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
from configs.settings import PROJECT_ROOT
from data_pipeline.cli import configure_logging, positive_int
from data_pipeline.dataset_io import (
    append_jsonl,
    collect_existing_ids,
    read_stage_a_records,
    select_pending,
)
from data_pipeline.generator import GenerationError, StageBGenerator
from data_pipeline.llm_client import TeacherClient
from data_pipeline.schemas import StageARecord

DEFAULT_INPUT = PROJECT_ROOT / "data" / "stage_a_output.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "dialogues_v1.jsonl"
PREVIEW_SIZE = 2


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Шаг B: генерация многотурных диалогов из вопросов Шага A.",
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
        help="обработать не больше N записей",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="пропустить id, которые уже есть в выходном JSONL",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        metavar="PATH",
        help=f"входной JSONL Шага A (по умолчанию {DEFAULT_INPUT.name})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"выходной JSONL в режиме append (по умолчанию {DEFAULT_OUTPUT.name})",
    )
    return parser.parse_args(argv)


def _preview(records: Sequence[StageARecord], prompts: PromptRenderer) -> None:
    """Показать готовые промпты Шага B без обращения к API (--dry-run)."""
    for index, record in enumerate(records, start=1):
        prompt = prompts.render_stage_b(topic=record.topic, user_query=record.user_query)
        logger.info(
            "--- Промпт {}/{} | id={} | topic={} ---\n{}",
            index,
            len(records),
            record.id,
            record.topic,
            prompt,
        )


async def _generate(
    records: Sequence[StageARecord],
    output: Path,
    prompts: PromptRenderer,
) -> int:
    """Сгенерировать диалоги и дописать их в JSONL. Возвращает код выхода."""
    async with TeacherClient() as client:
        generator = StageBGenerator(client, prompts=prompts)
        for index, record in enumerate(records, start=1):
            try:
                dialogue = await generator.generate_dialogue(
                    record.user_query, record.topic, seed_id=record.id
                )
            except (OpenAIError, GenerationError) as exc:
                # RULES §6: остановиться, записать ошибку, сообщить Архитектору.
                logger.error(
                    "[{}/{}] {} — ошибка: {}: {}",
                    index,
                    len(records),
                    record.id,
                    type(exc).__name__,
                    exc,
                )
                logger.error("Прогресс сохранён, продолжить можно флагом --resume")
                return 1

            append_jsonl(output, dialogue.model_dump(mode="json"))
            logger.info(
                "[{}/{}] {} → {} реплик, {} токенов",
                index,
                len(records),
                record.id,
                len(dialogue.messages),
                dialogue.total_tokens,
            )

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    try:
        records = read_stage_a_records(args.input)
        prompts = get_prompts()
    except (FileNotFoundError, ValueError, PromptError) as exc:
        logger.error("Не удалось подготовить генерацию: {}", exc)
        return 1

    existing_ids = collect_existing_ids(args.output) if args.resume else set()
    pending = select_pending(records, existing_ids=existing_ids, limit=args.limit)

    logger.info(
        "Записей Шага A: {} | к обработке: {} | режим: {}",
        len(records),
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
