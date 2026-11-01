#!/usr/bin/env python
"""Подготовка русских вопросов PetQA для генерации сидов (T-011).

Скачивает текстовую часть PetQA (train/validation) с официального датасета,
переводит вопросы на русский через учителя и сохраняет JSONL в формате
`SeedRecord`:

    {"id": "petqa-01234", "topic": "...", "seed_text": "..."}

Если сеть недоступна, используется локальный ``data/petqa_raw.jsonl``
(JSONL или JSON-массив). Перевод всегда идёт через `TeacherClient`; для
GigaChat конкурентность автоматически ограничивается единицей.

Примеры::

    python scripts/prepare_petqa.py --dry-run
    python scripts/prepare_petqa.py --limit 500 --concurrency 8
    python scripts/prepare_petqa.py --no-download --resume
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

from configs.prompts import PromptError, PromptRenderer, get_prompts
from configs.settings import (
    PROVIDER_NAMES,
    ProviderName,
    ProviderNotConfiguredError,
    get_provider,
    resolve_concurrency,
)
from data_pipeline.cli import configure_logging, positive_int
from data_pipeline.dataset_io import append_jsonl, collect_existing_ids, write_jsonl
from data_pipeline.llm_client import TeacherAPIError, TeacherClient
from data_pipeline.petqa import (
    DEFAULT_RAW_PATH,
    DEFAULT_SEEDS_PATH,
    PETQA_TOPICS,
    PetQAError,
    RawPetQARecord,
    download_petqa_text,
    load_petqa_raw,
    to_seed_record,
    translate_raw_record,
)

DEFAULT_CONCURRENCY = 8
DEFAULT_MAX_TOKENS = 1024


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Скачать PetQA и перевести вопросы на русский для сидов.",
        epilog="Без --limit обрабатываются все train+validation записи.",
    )
    parser.add_argument(
        "--raw-path",
        type=Path,
        default=DEFAULT_RAW_PATH,
        metavar="PATH",
        help=f"сырой JSONL/JSON PetQA (по умолчанию {DEFAULT_RAW_PATH.name})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_SEEDS_PATH,
        metavar="PATH",
        help=f"русские вопросы (по умолчанию {DEFAULT_SEEDS_PATH.name})",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDER_NAMES,
        default="primary",
        help="провайдер перевода (по умолчанию primary)",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=None,
        metavar="N",
        help="перевести не больше N записей",
    )
    parser.add_argument(
        "--concurrency",
        type=positive_int,
        default=DEFAULT_CONCURRENCY,
        metavar="N",
        help=f"параллельных переводов (по умолчанию {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "--max-tokens",
        type=positive_int,
        default=DEFAULT_MAX_TOKENS,
        metavar="N",
        help=f"лимит токенов ответа переводчика (по умолчанию {DEFAULT_MAX_TOKENS})",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="пропустить id, которые уже есть в выходном JSONL",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="не скачивать, читать только локальный --raw-path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать промпты первых записей, не вызывая API",
    )
    return parser.parse_args(argv)


def _load_records(args: argparse.Namespace) -> list[RawPetQARecord]:
    """Загрузить сырые записи из сети или локальной заглушки."""
    if args.no_download:
        return load_petqa_raw(args.raw_path)
    return download_petqa_text(args.raw_path)


def _seed_candidates(records: Sequence[RawPetQARecord]) -> list[RawPetQARecord]:
    """Train/validation — сиды; test зарезервирован под PetQA-Bench."""
    candidates = [record for record in records if record.split in (None, "train", "validation")]
    return candidates


def _preview(
    records: Sequence[RawPetQARecord],
    prompts: PromptRenderer,
    output: Path,
) -> None:
    """Показать промпты без обращения к API."""
    logger.info("PetQA: к переводу {}, выход: {}", len(records), output)
    for index, raw in enumerate(records[:2], start=1):
        prompt = prompts.render_petqa_translate(
            question=raw.question,
            answer=raw.gold_answer,
            topics=", ".join(PETQA_TOPICS),
        )
        logger.info("--- PetQA {}/{} | q_id={} ---\n{}", index, len(records), raw.q_id, prompt)
    logger.info("--dry-run: API не вызывается; {} не записан", output)


async def _translate_all(
    records: Sequence[RawPetQARecord],
    output: Path,
    provider_name: ProviderName,
    *,
    concurrency: int,
    max_tokens: int,
    prompts: PromptRenderer,
) -> tuple[int, int]:
    """Перевести записи и дописать результат. Возвращает (успех, ошибки)."""
    provider = get_provider(provider_name)
    effective_concurrency = resolve_concurrency(provider, concurrency)
    if effective_concurrency != concurrency:
        logger.warning(
            "GigaChat: concurrency перевода ограничена до {} (запрошено {})",
            effective_concurrency,
            concurrency,
        )

    semaphore = asyncio.Semaphore(effective_concurrency)
    success = 0
    errors = 0
    started = time.perf_counter()

    async with TeacherClient(provider, disable_thinking=True) as client:

        async def process(raw: RawPetQARecord) -> None:
            nonlocal success, errors
            async with semaphore:
                try:
                    translation = await translate_raw_record(
                        client,
                        prompts,
                        raw,
                        max_tokens=max_tokens,
                    )
                    record = to_seed_record(raw, translation)
                except (OpenAIError, TeacherAPIError, PetQAError, ValidationError) as exc:
                    errors += 1
                    logger.error("PetQA q_id={} — {}: {}", raw.q_id, type(exc).__name__, exc)
                    return

                append_jsonl(output, record.model_dump(mode="json"))
                success += 1
                logger.info(
                    "PetQA q_id={} → {} ({}/{})",
                    raw.q_id,
                    record.id,
                    success,
                    len(records),
                )

        await asyncio.gather(*(process(raw) for raw in records))

    elapsed = time.perf_counter() - started
    logger.info(
        "PetQA: успешно {}, ошибок {}, время {:.1f} с",
        success,
        errors,
        elapsed,
    )
    return success, errors


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    try:
        records = _load_records(args)
        candidates = _seed_candidates(records)
        if args.limit is not None:
            candidates = candidates[: args.limit]
        if not candidates:
            raise PetQAError("в PetQA нет train/validation записей для сидов")
        prompts = get_prompts()
    except (PetQAError, PromptError, ProviderNotConfiguredError, ValidationError) as exc:
        logger.error("PetQA не подготовлен: {}", exc)
        return 1

    existing_ids = collect_existing_ids(args.output) if args.resume else set()
    if existing_ids:
        candidates = [raw for raw in candidates if f"petqa-{raw.q_id:05d}" not in existing_ids]
        logger.info("--resume: уже готово {}, осталось {}", len(existing_ids), len(candidates))

    if not candidates:
        logger.info("Нечего переводить")
        return 0

    if args.dry_run:
        _preview(candidates, prompts, args.output)
        return 0

    if not args.resume:
        write_jsonl(args.output, [])

    try:
        success, errors = asyncio.run(
            _translate_all(
                candidates,
                args.output,
                args.provider,
                concurrency=args.concurrency,
                max_tokens=args.max_tokens,
                prompts=prompts,
            )
        )
    except ValidationError as exc:
        logger.error("Проверьте .env: {}", exc)
        return 1
    except ProviderNotConfiguredError as exc:
        logger.error("{}", exc)
        return 1
    except PromptError as exc:
        logger.error("Проблема с промптами: {}", exc)
        return 1

    logger.info("Результат: {} (успешно {}, ошибок {})", args.output, success, errors)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
