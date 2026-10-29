#!/usr/bin/env python
"""Скелет eval harness (T-006).

Читает `data/eval_dataset.jsonl`, валидирует записи через `EvalRecord`
и считает MCQ Accuracy по ответам модели из `data/model_answers.jsonl`.
Safety и Reasoning пока заглушки — они появятся в T-007 (LLM-Judge).

Примеры::

    python evaluation/evaluate.py --help
    python evaluation/evaluate.py --dry-run
    python evaluation/evaluate.py --dataset data/eval_dataset.jsonl \\
        --answers data/model_answers.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import TypeAdapter, ValidationError

from configs.settings import PROJECT_ROOT
from data_pipeline.cli import configure_logging
from evaluation.schemas import EvalRecord, MCQRecord, ModelAnswer

DEFAULT_DATASET = PROJECT_ROOT / "data" / "eval_dataset.jsonl"
DEFAULT_ANSWERS = PROJECT_ROOT / "data" / "model_answers.jsonl"
DEFAULT_REPORT = PROJECT_ROOT / "eval_report.json"

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

    В T-006 реализована только MCQ Accuracy; Safety, Reasoning и Multi-turn —
    заглушки, которые будут заменены LLM-Judge в T-007.
    """

    def __init__(self, records: Sequence[EvalRecord], answers: Mapping[str, str]) -> None:
        self._records = list(records)
        self._answers = dict(answers)

    @property
    def records(self) -> list[EvalRecord]:
        """Записи датасета (в порядке файла)."""
        return list(self._records)

    @property
    def mcq_records(self) -> list[MCQRecord]:
        """Только MCQ-записи."""
        return [record for record in self._records if isinstance(record, MCQRecord)]

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

    def safety_pass_rate(self) -> float:
        """Заглушка Safety Pass Rate: проверки появятся в T-007."""
        return 0.0

    def reasoning_score(self) -> float:
        """Заглушка Reasoning Score: LLM-Judge появится в T-007."""
        return 0.0

    def multi_turn_consistency(self) -> float:
        """Заглушка Multi-turn Consistency: проверка появится в T-007."""
        return 0.0

    def report(self) -> dict[str, float]:
        """Итоговый отчёт. В T-006 — только MCQ Accuracy."""
        return {"mcq_accuracy": self.mcq_accuracy()}


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
        description="Eval harness: MCQ Accuracy по ответам модели (Safety/Reasoning — T-007).",
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
        "--dry-run",
        action="store_true",
        help="посчитать метрики, но не записывать файл отчёта",
    )
    return parser.parse_args(argv)


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

    evaluator = Evaluator(records, answers)
    report = evaluator.report()

    logger.info(
        "Датасет: {} записей (MCQ: {}) | ответов модели: {}",
        len(evaluator.records),
        len(evaluator.mcq_records),
        len(answers),
    )
    logger.info("{}", json.dumps(report, ensure_ascii=False))

    if args.dry_run:
        logger.info("--dry-run: {} не записан", args.report)
        return 0

    write_report(args.report, report)
    logger.info("Отчёт записан: {}", args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
