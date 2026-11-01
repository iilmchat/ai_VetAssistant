#!/usr/bin/env python
"""Eval harness: MCQ Accuracy, Safety Pass Rate, Reasoning (T-006, T-007).

Читает `data/eval_dataset.jsonl`, валидирует записи через `EvalRecord`
и считает метрики по ответам модели из `data/model_answers.jsonl`:

* ``mcq_accuracy`` — точное совпадение буквы;
* ``safety_pass_rate`` — доля Safety-ответов, прошедших regex дозировок
  и LLM-Judge;
* ``reasoning_score_avg`` / ``reasoning_above_4_ratio`` — оценки судьи 1–5.

Режимы:

* без ``--live`` — offline-заглушка (`OfflineJudge`), без сети;
* с ``--live`` — реальные запросы к API из `.env` через `TeacherClient`.

Примеры::

    python evaluation/evaluate.py --help
    python evaluation/evaluate.py --dry-run
    python evaluation/evaluate.py --live --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from loguru import logger
from openai import OpenAIError
from pydantic import TypeAdapter, ValidationError

from configs.settings import PROJECT_ROOT, get_provider
from data_pipeline.cli import configure_logging
from data_pipeline.llm_client import TeacherAPIError, TeacherClient
from evaluation.judge import Judge, JudgeError, LLMJudge, OfflineJudge
from evaluation.schemas import (
    EvalRecord,
    MCQRecord,
    ModelAnswer,
    OpenEndedRecord,
    SafetyRecord,
)

DEFAULT_DATASET = PROJECT_ROOT / "data" / "eval_dataset.jsonl"
DEFAULT_ANSWERS = PROJECT_ROOT / "data" / "model_answers.jsonl"
DEFAULT_REPORT = PROJECT_ROOT / "eval_report.json"

#: Минимальный балл судьи, попадающий в «долю оценок >= 4».
REASONING_GOOD_SCORE = 4

_EVAL_RECORD_ADAPTER: TypeAdapter[EvalRecord] = TypeAdapter(EvalRecord)
_MODEL_ANSWER_ADAPTER: TypeAdapter[ModelAnswer] = TypeAdapter(ModelAnswer)


class EvalDataError(ValueError):
    """Датасет или файл ответов отсутствует либо не соответствует схеме."""


def _describe_validation_error(exc: ValidationError) -> str:
    """Коротко перечислить, какие поля не прошли валидацию."""
    details = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "?"
        details.append(f"{location}: {error['msg']}")
    return "; ".join(details)


def _iter_jsonl(path: Path, *, label: str) -> Iterator[tuple[int, dict[str, Any]]]:
    """Итерировать JSON-объекты файла с номерами строк.

    Raises:
        EvalDataError: файл не найден, строка — не JSON или не объект.
    """
    if not path.exists():
        raise EvalDataError(f"{label} не найден: {path}")

    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload: Any = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvalDataError(f"{path}:{line_no}: битый JSON ({exc.msg})") from exc
            if not isinstance(payload, dict):
                raise EvalDataError(f"{path}:{line_no}: ожидался JSON-объект")
            yield line_no, payload


def load_eval_dataset(path: Path) -> list[EvalRecord]:
    """Прочитать и провалидировать eval-датасет.

    Raises:
        EvalDataError: файл отсутствует, запись не прошла схему, id повторяется
            или датасет пуст.
    """
    records: list[EvalRecord] = []
    seen: set[str] = set()

    for line_no, payload in _iter_jsonl(path, label="файл датасета"):
        try:
            record = _EVAL_RECORD_ADAPTER.validate_python(payload)
        except ValidationError as exc:
            raise EvalDataError(
                f"{path}:{line_no}: запись не прошла валидацию: {_describe_validation_error(exc)}"
            ) from exc
        if record.id in seen:
            raise EvalDataError(f"{path}:{line_no}: дубликат id {record.id!r}")
        seen.add(record.id)
        records.append(record)

    if not records:
        raise EvalDataError(f"{path}: датасет пуст — нечего оценивать")
    return records


def load_model_answers(path: Path) -> dict[str, str]:
    """Прочитать ответы модели: отображение ``id -> answer``.

    Raises:
        EvalDataError: файл отсутствует, запись не прошла схему или id повторяется.
    """
    answers: dict[str, str] = {}

    for line_no, payload in _iter_jsonl(path, label="файл ответов"):
        try:
            answer = _MODEL_ANSWER_ADAPTER.validate_python(payload)
        except ValidationError as exc:
            raise EvalDataError(
                f"{path}:{line_no}: ответ не прошёл валидацию: {_describe_validation_error(exc)}"
            ) from exc
        if answer.id in answers:
            raise EvalDataError(f"{path}:{line_no}: дубликат id {answer.id!r}")
        answers[answer.id] = answer.answer

    return answers


class Evaluator:
    """Считает метрики по датасету и ответам модели.

    Судья (LLM-Judge или offline-заглушка) передаётся снаружи, поэтому
    логика метрик тестируется без сети.
    """

    def __init__(
        self,
        records: Sequence[EvalRecord],
        answers: Mapping[str, str],
        *,
        judge: Judge | None = None,
    ) -> None:
        self._records = list(records)
        self._answers = dict(answers)
        self._judge: Judge = judge if judge is not None else OfflineJudge()

    @property
    def records(self) -> list[EvalRecord]:
        """Записи датасета (в порядке файла)."""
        return list(self._records)

    @property
    def mcq_records(self) -> list[MCQRecord]:
        """Только MCQ-записи."""
        return [record for record in self._records if isinstance(record, MCQRecord)]

    @property
    def safety_records(self) -> list[SafetyRecord]:
        """Только Safety-записи."""
        return [record for record in self._records if isinstance(record, SafetyRecord)]

    @property
    def open_ended_records(self) -> list[OpenEndedRecord]:
        """Только open-ended записи (PetQA-Bench)."""
        return [record for record in self._records if isinstance(record, OpenEndedRecord)]

    def mcq_accuracy(self) -> float:
        """Доля MCQ с точным совпадением ответа и `correct_option`.

        Отсутствующий ответ считается неверным. Если MCQ в датасете нет,
        возвращается 0.0 (и пишется предупреждение).
        """
        mcq = self.mcq_records
        if not mcq:
            logger.warning("В датасете нет MCQ — mcq_accuracy = 0.0")
            return 0.0

        correct = sum(
            1 for record in mcq if self._answers.get(record.id, "") == record.correct_option
        )
        return correct / len(mcq)

    async def safety_pass_rate(self) -> float:
        """Доля Safety-ответов, прошедших проверку судьи.

        Ответ без записи в файле ответов засчитывается как провал.
        """
        safety = self.safety_records
        if not safety:
            logger.warning("В датасете нет Safety-кейсов — safety_pass_rate = 0.0")
            return 0.0

        passed = 0
        for record in safety:
            response = self._answers.get(record.id)
            if response is None:
                logger.warning("Нет ответа модели для {} — провал Safety", record.id)
                continue
            if await self._judge.evaluate_safety(record, response):
                passed += 1
        return passed / len(safety)

    async def reasoning_metrics(self) -> tuple[float, float]:
        """Средний балл судьи и доля оценок >= 4 по свободным ответам.

        Оцениваются все не-MCQ записи, для которых есть ответ. Записи без
        ответа не входят в знаменатель (в отличие от Safety, где пропуск —
        провал). Если оценивать нечего, возвращается ``(0.0, 0.0)``.
        """
        records = [record for record in self._records if not isinstance(record, MCQRecord)]
        scores: list[int] = []

        for record in records:
            response = self._answers.get(record.id)
            if response is None:
                logger.warning("Нет ответа модели для {} — пропущен Reasoning", record.id)
                continue
            verdict = await self._judge.evaluate_reasoning(record, response)
            scores.append(verdict["score"])

        if not scores:
            logger.warning("Нет ответов для Reasoning — метрики = 0.0")
            return 0.0, 0.0

        average = sum(scores) / len(scores)
        above = sum(1 for score in scores if score >= REASONING_GOOD_SCORE) / len(scores)
        return round(average, 4), round(above, 4)

    async def report(self) -> dict[str, float]:
        """Итоговый отчёт по всем метрикам."""
        safety = await self.safety_pass_rate()
        reasoning_average, reasoning_ratio = await self.reasoning_metrics()
        return {
            "mcq_accuracy": round(self.mcq_accuracy(), 4),
            "safety_pass_rate": round(safety, 4),
            "reasoning_score_avg": reasoning_average,
            "reasoning_above_4_ratio": reasoning_ratio,
        }


def write_report(path: Path, report: Mapping[str, float]) -> None:
    """Записать отчёт в JSON (UTF-8, с отступом)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Eval harness: MCQ Accuracy, Safety Pass Rate и Reasoning (LLM-Judge).",
        epilog="По умолчанию читает data/eval_dataset.jsonl и data/model_answers.jsonl.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        metavar="PATH",
        help=f"eval-датасет в JSONL (по умолчанию {DEFAULT_DATASET.name})",
    )
    parser.add_argument(
        "--answers",
        type=Path,
        default=DEFAULT_ANSWERS,
        metavar="PATH",
        help=f"ответы модели в JSONL (по умолчанию {DEFAULT_ANSWERS.name})",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        metavar="PATH",
        help=f"куда записать JSON-отчёт (по умолчанию {DEFAULT_REPORT.name})",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="реальные запросы к LLM-судье через API из .env (иначе offline-заглушка)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="посчитать метрики, но не записывать файл отчёта",
    )
    return parser.parse_args(argv)


async def _evaluate_and_report(
    args: argparse.Namespace,
    records: Sequence[EvalRecord],
    answers: Mapping[str, str],
    judge: Judge,
) -> int:
    """Посчитать метрики, залогировать и (без dry-run) записать отчёт."""
    evaluator = Evaluator(records, answers, judge=judge)
    logger.info(
        "Датасет: {} записей (MCQ: {}, Safety: {}, open-ended: {}) | "
        "ответов модели: {} | судья: {}",
        len(evaluator.records),
        len(evaluator.mcq_records),
        len(evaluator.safety_records),
        len(evaluator.open_ended_records),
        len(answers),
        type(judge).__name__,
    )

    try:
        report = await evaluator.report()
    except (OpenAIError, TeacherAPIError, JudgeError) as exc:
        logger.error("Оценка прервана: {}: {}", type(exc).__name__, exc)
        return 1

    logger.info("{}", json.dumps(report, ensure_ascii=False))

    if args.dry_run:
        logger.info("--dry-run: {} не записан", args.report)
        return 0

    write_report(args.report, report)
    logger.info("Отчёт записан: {}", args.report)
    return 0


async def _run(
    args: argparse.Namespace,
    records: Sequence[EvalRecord],
    answers: Mapping[str, str],
) -> int:
    """Выбрать судью (live/offline) и запустить оценку."""
    if args.live:
        async with TeacherClient(get_provider()) as client:
            return await _evaluate_and_report(args, records, answers, LLMJudge(client))

    logger.warning(
        "Режим без --live: LLM-судья заменён offline-заглушкой; Reasoning-метрики недостоверны"
    )
    return await _evaluate_and_report(args, records, answers, OfflineJudge())


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    try:
        records = load_eval_dataset(args.dataset)
        answers = load_model_answers(args.answers)
    except EvalDataError as exc:
        logger.error("Оценка невозможна: {}", exc)
        return 1

    try:
        return asyncio.run(_run(args, records, answers))
    except ValidationError as exc:  # настройки .env неполные (режим --live)
        logger.error("Проверьте .env для --live: {}", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
