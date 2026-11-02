#!/usr/bin/env python
"""Оценка Router & Triage на эталонном бенчмарке (T-013).

Скрипт читает JSONL с размеченными фразами, прогоняет каждую через
:func:`app.router.triage_message` и считает Precision, Recall и F1
отдельно для детекции экстренности и prompt injection.

Примеры::

    python scripts/evaluate_router.py --help
    python scripts/evaluate_router.py --dry-run
    python scripts/evaluate_router.py
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Self

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.router import triage_message
from configs.settings import PROJECT_ROOT
from data_pipeline.cli import configure_logging

DEFAULT_BENCHMARK_PATH = PROJECT_ROOT / "data" / "router_benchmark.jsonl"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "docs" / "development" / "reports" / "EVAL_ROUTER.md"

Category = Literal["emergency", "normal", "injection"]
Target = Literal["emergency", "injection"]

#: Ожидаемые метки для каждой категории бенчмарка.
_CATEGORY_LABELS: dict[Category, tuple[bool, bool]] = {
    "emergency": (True, False),
    "normal": (False, False),
    "injection": (False, True),
}


class RouterBenchmarkCase(BaseModel):
    """Одна размеченная фраза бенчмарка."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, description="Уникальный идентификатор кейса")
    text: str = Field(min_length=1, description="Сообщение пользователя")
    category: Category
    expected_emergency: bool
    expected_injection: bool

    @model_validator(mode="after")
    def _validate_category(self) -> Self:
        """Проверить, что метки соответствуют категории."""
        expected = _CATEGORY_LABELS[self.category]
        actual = (self.expected_emergency, self.expected_injection)
        if actual != expected:
            raise ValueError(
                f"для категории {self.category!r} ожидались метки {expected}, а не {actual}"
            )
        return self


@dataclass(frozen=True)
class CaseResult:
    """Предсказание роутера для одного кейса."""

    case: RouterBenchmarkCase
    predicted_emergency: bool
    predicted_injection: bool
    reason: str


@dataclass(frozen=True)
class BinaryMetrics:
    """Матрица ошибок и производные метрики для одного признака."""

    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def total(self) -> int:
        """Всего кейсов."""
        return self.tp + self.fp + self.fn + self.tn

    @property
    def precision(self) -> float:
        """Точность: доля верных срабатываний среди предсказанных."""
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float:
        """Полнота: доля найденных положительных кейсов."""
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> float:
        """Гармоническое среднее Precision и Recall."""
        return _ratio(2 * self.precision * self.recall, self.precision + self.recall)

    @property
    def accuracy(self) -> float:
        """Доля верных предсказаний среди всех кейсов."""
        return _ratio(self.tp + self.tn, self.total)


def _ratio(numerator: float, denominator: float) -> float:
    """Безопасное деление: при пустом знаменателе возвращает 0.0."""
    return numerator / denominator if denominator else 0.0


def load_benchmark(path: Path) -> list[RouterBenchmarkCase]:
    """Прочитать и провалидировать JSONL-бенчмарк.

    Raises:
        ValueError: файл пуст, содержит некорректный JSON, повторяющиеся id
            или запись не проходит схему.
    """
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"не удалось прочитать бенчмарк {path}: {exc}") from exc

    cases: list[RouterBenchmarkCase] = []
    for line_number, line in enumerate(raw_lines, start=1):
        if not line.strip():
            continue
        try:
            payload: object = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: некорректный JSON: {exc}") from exc
        try:
            cases.append(RouterBenchmarkCase.model_validate(payload))
        except ValidationError as exc:
            raise ValueError(f"{path}:{line_number}: некорректная запись: {exc}") from exc

    if not cases:
        raise ValueError(f"бенчмарк пуст: {path}")

    ids = [case.id for case in cases]
    duplicates = sorted(case_id for case_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"в бенчмарке повторяются id: {', '.join(duplicates)}")

    return cases


def run_benchmark(cases: Sequence[RouterBenchmarkCase]) -> list[CaseResult]:
    """Прогнать все кейсы через роутер."""
    results: list[CaseResult] = []
    for case in cases:
        triage = triage_message(case.text)
        results.append(
            CaseResult(
                case=case,
                predicted_emergency=triage["is_emergency"],
                predicted_injection=triage["injection_detected"],
                reason=triage["reason"],
            )
        )
    return results


def binary_metrics(results: Sequence[CaseResult], target: Target) -> BinaryMetrics:
    """Посчитать матрицу ошибок для выбранного признака."""
    tp = fp = fn = tn = 0
    for result in results:
        expected = (
            result.case.expected_emergency
            if target == "emergency"
            else result.case.expected_injection
        )
        predicted = (
            result.predicted_emergency if target == "emergency" else result.predicted_injection
        )
        if expected and predicted:
            tp += 1
        elif predicted:
            fp += 1
        elif expected:
            fn += 1
        else:
            tn += 1
    return BinaryMetrics(tp=tp, fp=fp, fn=fn, tn=tn)


def render_markdown(
    *,
    benchmark_path: Path,
    cases: Sequence[RouterBenchmarkCase],
    results: Sequence[CaseResult],
    emergency: BinaryMetrics,
    injection: BinaryMetrics,
    generated_on: date,
) -> str:
    """Собрать Markdown-отчёт с метриками и списком ошибок."""
    category_counts = Counter(case.category for case in cases)
    errors = [
        result
        for result in results
        if result.predicted_emergency != result.case.expected_emergency
        or result.predicted_injection != result.case.expected_injection
    ]

    lines = [
        "# EVAL_ROUTER — оценка Router & Triage (T-013)",
        "",
        f"**Дата:** {generated_on.isoformat()}  ",
        f"**Бенчмарк:** `{_display_path(benchmark_path)}` — {len(cases)} кейсов  ",
        "**Роутер:** `app/router.py`, regex-эвристики без вызова LLM",
        "",
        "## 1. Метрики",
        "",
        "| Задача | Precision | Recall | F1 | Accuracy | TP | FP | FN | TN |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for title, metrics in (("Экстренность", emergency), ("Prompt injection", injection)):
        lines.append(
            f"| {title} | {metrics.precision:.4f} | {metrics.recall:.4f} | "
            f"{metrics.f1:.4f} | {metrics.accuracy:.4f} | "
            f"{metrics.tp} | {metrics.fp} | {metrics.fn} | {metrics.tn} |"
        )

    lines.extend(
        [
            "",
            "## 2. Состав бенчмарка",
            "",
            "| Категория | Кейсов |",
            "|---|---:|",
            f"| Экстренные | {category_counts['emergency']} |",
            f"| Обычные | {category_counts['normal']} |",
            f"| Prompt injection | {category_counts['injection']} |",
            f"| **Итого** | **{len(cases)}** |",
            "",
            "## 3. Ошибки",
            "",
        ]
    )

    if not errors:
        lines.append(
            f"Ошибок нет: все {len(cases)} кейсов классифицированы верно по обоим признакам."
        )
    else:
        lines.extend(
            [
                "| ID | Категория | Текст | Ожидалось | Получено |",
                "|---|---|---|---|---|",
            ]
        )
        for result in errors:
            case = result.case
            text = case.text.replace("|", "\\|")
            lines.append(
                f"| `{case.id}` | {case.category} | {text} | "
                f"{_labels(case.expected_emergency, case.expected_injection)} | "
                f"{_labels(result.predicted_emergency, result.predicted_injection)} |"
            )

    lines.extend(
        [
            "",
            "## 4. Вывод",
            "",
            (
                f"На бенчмарке из {len(cases)} кейсов роутер показал "
                f"F1={emergency.f1:.4f} для экстренности и "
                f"F1={injection.f1:.4f} для prompt injection."
            ),
            (
                "Проверка выполняется детерминированными regex-эвристиками "
                "до вызова LLM; результаты воспроизводятся командой "
                "`python scripts/evaluate_router.py`."
            ),
            "",
            "> Бенчмарк небольшой и курируемый: метрики отражают покрытие "
            "типовых формулировок, а не всех возможных перефразирований.",
            "",
        ]
    )
    return "\n".join(lines)


def _labels(emergency: bool, injection: bool) -> str:
    """Человекочитаемое описание меток кейса."""
    labels: list[str] = []
    if emergency:
        labels.append("экстренность")
    if injection:
        labels.append("инъекция")
    return " + ".join(labels) if labels else "обычный"


def _display_path(path: Path) -> str:
    """Показать путь относительно корня проекта, если это возможно."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Оценить Router & Triage и записать Markdown-отчёт.",
    )
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=DEFAULT_BENCHMARK_PATH,
        metavar="PATH",
        help=f"JSONL-бенчмарк (по умолчанию {DEFAULT_BENCHMARK_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        metavar="PATH",
        help=f"Markdown-отчёт (по умолчанию {DEFAULT_REPORT_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Посчитать метрики, но не записывать отчёт",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа скрипта."""
    args = parse_args(argv)
    configure_logging()

    try:
        cases = load_benchmark(args.benchmark)
    except ValueError as exc:
        logger.error("Бенчмарк не загружен: {}", exc)
        return 1

    results = run_benchmark(cases)
    emergency = binary_metrics(results, "emergency")
    injection = binary_metrics(results, "injection")

    logger.info("Кейсов: {}", len(cases))
    logger.info(
        "Экстренность: precision={:.4f}, recall={:.4f}, f1={:.4f}",
        emergency.precision,
        emergency.recall,
        emergency.f1,
    )
    logger.info(
        "Prompt injection: precision={:.4f}, recall={:.4f}, f1={:.4f}",
        injection.precision,
        injection.recall,
        injection.f1,
    )

    if args.dry_run:
        logger.info("Dry-run: отчёт не записан ({})", args.output)
        return 0

    report = render_markdown(
        benchmark_path=args.benchmark,
        cases=cases,
        results=results,
        emergency=emergency,
        injection=injection,
        generated_on=date.today(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    logger.info("Отчёт записан: {}", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
