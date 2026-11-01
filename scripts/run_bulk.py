#!/usr/bin/env python
"""Bulk-генерация датасета: Шаги A+B с ограниченной конкурентностью (T-009).

Для каждого сида выполняется цепочка «вопрос владельца (Шаг A) → многотурный
диалог (Шаг B)». Одновременно в работе не больше ``--concurrency`` цепочек
(`asyncio.Semaphore`). Ошибки отдельных кейсов логируются и пропускаются:
ретраи 429/5xx уже делает `TeacherClient`, здесь — учёт и продолжение.

Результат дописывается в JSONL по мере готовности, поэтому прерванный прогон
продолжается флагом ``--resume`` без повторной генерации.

Примеры::

    python scripts/run_bulk.py --dry-run
    python scripts/run_bulk.py --limit 100 --concurrency 10
    python scripts/run_bulk.py --resume --concurrency 16
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
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
    resolve_concurrency,
)
from data_pipeline.cli import configure_logging, positive_int
from data_pipeline.dataset_io import (
    append_jsonl,
    collect_existing_ids,
    read_seed_records,
    select_pending,
    write_jsonl,
)
from data_pipeline.generator import GenerationError, StageAGenerator, StageBGenerator
from data_pipeline.llm_client import TeacherAPIError, TeacherClient, is_fatal_provider_error
from data_pipeline.schemas import SeedRecord

DEFAULT_SEEDS = PROJECT_ROOT / "data" / "seeds_bulk.jsonl"
DEFAULT_CONCURRENCY = 10
PREVIEW_SIZE = 2


class FatalProviderError(RuntimeError):
    """Провайдер отклонил запросы из-за ключа, доступа или баланса."""


@dataclass(frozen=True, slots=True)
class BulkStats:
    """Итоги одного bulk-прогона."""

    processed: int
    success: int
    errors: int
    tokens: int
    elapsed_s: float


def bulk_output_path(provider: ProviderName) -> Path:
    """Стандартный путь результата bulk-генерации для провайдера."""
    return PROJECT_ROOT / "data" / f"dialogues_bulk_{provider}.jsonl"


async def generate_bulk(
    seeds: Sequence[SeedRecord],
    output: Path,
    client: TeacherClient,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    prompts: PromptRenderer | None = None,
) -> BulkStats:
    """Сгенерировать диалоги для `seeds` с лимитом одновременных цепочек.

    Args:
        seeds: сиды к обработке (уже отфильтрованные по `--resume`/`--limit`).
        output: JSONL, куда дописывается каждый успешный диалог.
        client: клиент учителя (в тестах — замоканный).
        concurrency: максимум одновременно выполняющихся цепочек A+B (>= 1).
        prompts: библиотека промптов; по умолчанию — `configs/prompts.yaml`.

    Returns:
        Статистика: обработано, успешно, ошибок, токенов, время.
    """
    if concurrency < 1:
        raise ValueError("concurrency должен быть >= 1")

    stage_a = StageAGenerator(client, prompts=prompts)
    stage_b = StageBGenerator(client, prompts=prompts)
    semaphore = asyncio.Semaphore(concurrency)

    success = 0
    errors = 0
    tokens = 0
    fatal_error: FatalProviderError | None = None
    started = time.perf_counter()

    async def process(seed: SeedRecord) -> None:
        nonlocal success, errors, tokens, fatal_error
        if fatal_error is not None:
            return
        async with semaphore:
            if fatal_error is not None:
                return
            try:
                stage_a_record = await stage_a.generate_query(
                    seed.topic, seed.seed_text, seed_id=seed.id
                )
                dialogue = await stage_b.generate_dialogue(
                    stage_a_record.user_query, seed.topic, seed_id=seed.id
                )
            except APIStatusError as exc:
                if is_fatal_provider_error(exc):
                    fatal_error = FatalProviderError(
                        "провайдер отклонил запросы "
                        f"(HTTP {exc.status_code}: {exc.message}) — проверьте ключ и баланс"
                    )
                    logger.error("{}; генерация остановлена", fatal_error)
                    return
                errors += 1
                logger.error("{} — APIStatusError {}: {}", seed.id, exc.status_code, exc)
                return
            except (OpenAIError, GenerationError, TeacherAPIError) as exc:
                errors += 1
                logger.error("{} — {}: {}", seed.id, type(exc).__name__, exc)
                return

            append_jsonl(output, dialogue.model_dump(mode="json"))
            success += 1
            spent = stage_a_record.total_tokens + dialogue.total_tokens
            tokens += spent
            logger.info(
                "{} → {} реплик, {} токенов (успешно {}/{})",
                seed.id,
                len(dialogue.messages),
                spent,
                success,
                len(seeds),
            )

    await asyncio.gather(*(process(seed) for seed in seeds))
    if fatal_error is not None:
        raise fatal_error
    elapsed_s = time.perf_counter() - started
    return BulkStats(
        processed=len(seeds),
        success=success,
        errors=errors,
        tokens=tokens,
        elapsed_s=elapsed_s,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Bulk-генерация диалогов: Шаги A+B с ограниченной конкурентностью.",
        epilog="Ошибки отдельных кейсов не прерывают прогон; прогресс пишется в JSONL.",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDER_NAMES,
        default="primary",
        help="какой провайдер использовать (по умолчанию primary)",
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
        help="выходной JSONL (по умолчанию data/dialogues_bulk_{provider}.jsonl)",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=None,
        metavar="N",
        help="обработать не больше N новых сидов",
    )
    parser.add_argument(
        "--concurrency",
        type=positive_int,
        default=DEFAULT_CONCURRENCY,
        metavar="N",
        help=f"максимум одновременных цепочек A+B (по умолчанию {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="пропустить id, которые уже есть в выходном JSONL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать промпты первых 2 сидов, не вызывая API",
    )
    return parser.parse_args(argv)


def _preview(seeds: Sequence[SeedRecord], provider: ProviderName, output: Path) -> None:
    """Показать промпты без обращения к API (--dry-run)."""
    prompts = get_prompts()
    logger.info(
        "Провайдер: {} | выход: {} | к обработке: {}",
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


async def _run(
    seeds: Sequence[SeedRecord],
    output: Path,
    provider_name: ProviderName,
    concurrency: int,
) -> int:
    """Запустить генерацию и напечатать статистику."""
    provider = get_provider(provider_name)
    effective_concurrency = resolve_concurrency(provider, concurrency)
    if effective_concurrency != concurrency:
        logger.warning(
            "GigaChat: concurrency принудительно ограничена до {} (запрошено {})",
            effective_concurrency,
            concurrency,
        )
    logger.info(
        "Провайдер: {} | model={} | base_url={} | concurrency={}",
        provider.name,
        provider.model,
        provider.base_url,
        effective_concurrency,
    )

    async with TeacherClient(provider, disable_thinking=True) as client:
        stats = await generate_bulk(seeds, output, client, concurrency=effective_concurrency)

    logger.info(
        "Итог bulk: обработано {}, успешно {}, ошибок {}, время {:.2f} с, токенов {}",
        stats.processed,
        stats.success,
        stats.errors,
        stats.elapsed_s,
        stats.tokens,
    )
    logger.info("Результат: {}", output)
    return 0 if stats.success else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    try:
        seeds = read_seed_records(args.seeds)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Не удалось прочитать сиды: {}", exc)
        return 1

    provider_name: ProviderName = args.provider
    output: Path = args.output if args.output is not None else bulk_output_path(provider_name)

    existing_ids = collect_existing_ids(output) if args.resume else set()
    pending = select_pending(seeds, existing_ids=existing_ids, limit=args.limit)

    logger.info(
        "Сидов: {} | уже готово: {} | к обработке: {} | режим: {}",
        len(seeds),
        len(existing_ids),
        len(pending),
        "dry-run" if args.dry_run else f"bulk (concurrency={args.concurrency})",
    )

    if not pending:
        logger.info("Нечего обрабатывать")
        return 0

    if args.dry_run:
        try:
            _preview(pending, provider_name, output)
        except PromptError as exc:
            logger.error("Проблема с промптами: {}", exc)
            return 1
        return 0

    if not args.resume:
        write_jsonl(output, [])  # свежий прогон начинается с чистого файла

    try:
        return asyncio.run(_run(pending, output, provider_name, args.concurrency))
    except FatalProviderError as exc:
        logger.error("Bulk остановлен: {}", exc)
        return 1
    except ValidationError as exc:
        logger.error("Проверьте .env: {}", exc)
        return 1
    except ProviderNotConfiguredError as exc:
        logger.error("{}", exc)
        return 1
    except PromptError as exc:
        logger.error("Проблема с промптами: {}", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
