#!/usr/bin/env python
"""Safety-блок: генерация провокационных диалогов (T-005).

Берёт темы из `data/seeds.jsonl` (текст сида не используется — только тема),
рендерит Safety-промпт из `configs/prompts.yaml`, просит учителя написать
диалог, в котором ассистент отказывает в опасной просьбе и эскалирует
к врачу. Результат — append в `data/safety_dialogues.jsonl`.

Идентификаторы кейсов: ``safety-<id сида>`` — не пересекаются с Шагом B.

Примеры::

    python scripts/run_safety.py --dry-run
    python scripts/run_safety.py --limit 3
    python scripts/run_safety.py --resume
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from openai import APIStatusError, OpenAIError
from pydantic import ValidationError

from configs.prompts import PromptError, PromptRenderer, get_prompts
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
    collect_existing_ids,
    read_seed_records,
    select_pending,
)
from data_pipeline.generator import GenerationError, StageSafetyGenerator
from data_pipeline.llm_client import TeacherClient, is_fatal_provider_error
from data_pipeline.schemas import SeedRecord

DEFAULT_SEEDS = PROJECT_ROOT / "data" / "seeds.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "safety_dialogues.jsonl"
PREVIEW_SIZE = 2


def safety_case_id(seed_id: str) -> str:
    """Id Safety-кейса: не конфликтует с id Шага B."""
    return f"safety-{seed_id}"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Safety-блок: генерация диалогов с провокацией правил безопасности.",
        epilog="Темы берутся из data/seeds.jsonl, ключи API — из .env.",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDER_NAMES,
        default="primary",
        help="какой провайдер использовать (по умолчанию primary)",
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
        "--seeds",
        type=Path,
        default=DEFAULT_SEEDS,
        metavar="PATH",
        help=f"JSONL с темами (по умолчанию {DEFAULT_SEEDS.name})",
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
    """Показать готовые Safety-промпты без обращения к API (--dry-run)."""
    for index, seed in enumerate(seeds, start=1):
        prompt = prompts.render_safety(topic=seed.topic)
        logger.info(
            "--- Safety-промпт {}/{} | id={} | topic={} ---\n{}",
            index,
            len(seeds),
            safety_case_id(seed.id),
            seed.topic,
            prompt,
        )


async def _generate(
    seeds: Sequence[SeedRecord],
    output: Path,
    prompts: PromptRenderer,
    provider_name: ProviderName,
) -> int:
    """Сгенерировать Safety-кейсы и дописать их в JSONL. Возвращает код выхода.

    Ошибка одного кейса (битый JSON, обрыв по max_tokens, сбой API) логируется
    и пропускается, чтобы 500-кейсовый прогон не останавливался из-за одной
    неудачи. Пропущенные id доберёт повторный запуск с ``--resume``.
    """
    success = 0
    errors = 0
    async with TeacherClient(get_provider(provider_name), disable_thinking=True) as client:
        generator = StageSafetyGenerator(client, prompts=prompts)
        for index, seed in enumerate(seeds, start=1):
            case_id = safety_case_id(seed.id)
            try:
                record = await generator.generate_case(seed.topic, case_id=case_id)
            except APIStatusError as exc:
                if is_fatal_provider_error(exc):
                    logger.error(
                        "Провайдер отклонил запросы (HTTP {}): {} — safety остановлен",
                        exc.status_code,
                        exc.message,
                    )
                    return 1
                errors += 1
                logger.error(
                    "[{}/{}] {} — APIStatusError {}: {}",
                    index,
                    len(seeds),
                    case_id,
                    exc.status_code,
                    exc,
                )
                continue
            except (OpenAIError, GenerationError) as exc:
                errors += 1
                logger.error(
                    "[{}/{}] {} — ошибка: {}: {}",
                    index,
                    len(seeds),
                    case_id,
                    type(exc).__name__,
                    exc,
                )
                continue

            append_jsonl(output, record.model_dump(mode="json"))
            success += 1
            logger.info(
                "[{}/{}] {} → {} реплик, {} токенов",
                index,
                len(seeds),
                case_id,
                len(record.messages),
                record.total_tokens,
            )

    logger.info("Итог safety: успешно {}, ошибок {}", success, errors)
    if errors:
        logger.warning("Пропущенные кейсы можно добрать повторным запуском с --resume")
    return 0 if success else 1


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
    pending = select_pending(
        seeds,
        existing_ids=existing_ids,
        limit=args.limit,
        key=lambda seed: safety_case_id(seed.id),
    )

    logger.info(
        "Тем: {} | к обработке: {} | режим: {}",
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
        return asyncio.run(_generate(pending, args.output, prompts, args.provider))
    except ValidationError as exc:  # настройки .env неполные
        logger.error("Проверьте .env: {}", exc)
        return 1
    except ProviderNotConfiguredError as exc:
        logger.error("{}", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
