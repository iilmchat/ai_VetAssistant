#!/usr/bin/env python
"""Ручная проверка LLM-Judge на одном ответе (T-007).

Берёт запись из `data/eval_dataset.jsonl` и ответ модели из
`data/model_answers.jsonl`, прогоняет через `LLMJudge.evaluate_reasoning()`
и печатает вердикт JSON. `--dry-run` показывает готовый промпт судьи
без обращения к API.

Примеры::

    python scripts/test_judge.py --dry-run
    python scripts/test_judge.py
    python scripts/test_judge.py --record-id eval-safety-002
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from loguru import logger
from openai import OpenAIError
from pydantic import ValidationError

from configs.prompts import PromptError, get_prompts
from configs.settings import get_provider
from data_pipeline.cli import configure_logging
from data_pipeline.llm_client import TeacherAPIError, TeacherClient
from evaluation.evaluate import (
    DEFAULT_ANSWERS,
    DEFAULT_DATASET,
    EvalDataError,
    load_eval_dataset,
    load_model_answers,
)
from evaluation.judge import JudgeError, LLMJudge, build_judge_prompt
from evaluation.schemas import EvalRecord

DEFAULT_RECORD_ID = "eval-safety-001"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Прогнать один ответ через LLM-Judge и увидеть JSON-вердикт.",
        epilog=(
            "Ключи API берутся из .env "
            "(TEACHER_PRIMARY_API_KEY/TEACHER_PRIMARY_BASE_URL/TEACHER_PRIMARY_MODEL)."
        ),
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        metavar="PATH",
        help=f"eval-датасет (по умолчанию {DEFAULT_DATASET.name})",
    )
    parser.add_argument(
        "--answers",
        type=Path,
        default=DEFAULT_ANSWERS,
        metavar="PATH",
        help=f"ответы модели (по умолчанию {DEFAULT_ANSWERS.name})",
    )
    parser.add_argument(
        "--record-id",
        default=DEFAULT_RECORD_ID,
        metavar="ID",
        help=f"id записи для оценки (по умолчанию {DEFAULT_RECORD_ID})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать промпт судьи, не вызывая API",
    )
    return parser.parse_args(argv)


def _find_record(records: Sequence[EvalRecord], record_id: str) -> EvalRecord:
    """Найти запись по id или выбросить понятную ошибку."""
    for record in records:
        if record.id == record_id:
            return record
    available = ", ".join(record.id for record in records)
    raise EvalDataError(f"запись {record_id!r} не найдена; доступны: {available}")


async def _run(args: argparse.Namespace) -> int:
    """Выполнить оценку одной записи."""
    try:
        records = load_eval_dataset(args.dataset)
        answers = load_model_answers(args.answers)
        prompts = get_prompts()
    except (EvalDataError, PromptError) as exc:
        logger.error("Не удалось подготовить оценку: {}", exc)
        return 1

    try:
        record = _find_record(records, args.record_id)
    except EvalDataError as exc:
        logger.error("{}", exc)
        return 1

    response = answers.get(record.id)
    if response is None and not args.dry_run:
        logger.error("В {} нет ответа для записи {!r}", args.answers, record.id)
        return 1

    if args.dry_run:
        prompt = build_judge_prompt(prompts, record, response or "<ответ отсутствует>")
        logger.info("--- Промпт судьи для {} ---\n{}", record.id, prompt)
        return 0

    assert response is not None  # проверено выше; нужно для mypy
    try:
        async with TeacherClient(get_provider()) as client:
            judge = LLMJudge(client, prompts=prompts)
            verdict = await judge.evaluate_reasoning(record, response)
    except (OpenAIError, TeacherAPIError, JudgeError) as exc:
        logger.error("Судья не смог оценить ответ: {}: {}", type(exc).__name__, exc)
        return 1

    logger.info("Запись: {} | ответ: {}", record.id, response)
    logger.info("Вердикт: {}", json.dumps(verdict, ensure_ascii=False))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    try:
        return asyncio.run(_run(args))
    except ValidationError as exc:  # .env неполный
        logger.error("Проверьте .env: {}", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
