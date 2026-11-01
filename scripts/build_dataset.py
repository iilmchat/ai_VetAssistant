#!/usr/bin/env python
"""Сборка финального датасета v1 «под ключ» (T-010).

Шаги:

1. ``run_bulk.py`` — 8000 диалогов Шагов A+B (thinking отключён, конкурентность 20).
2. ``run_safety.py`` — 500 safety-кейсов на подмножестве тех же сидов.
3. Объединение и фильтрация (`filter_dataset`: PII + дедупликация).
4. Стратифицированное по `topic` разбиение 90/10 на `train.jsonl`/`val.jsonl`.
5. JSON-отчёт со статистикой и распределением тем.

Генерация идемпотентна: ``run_bulk``/``run_safety`` вызываются с ``--resume``,
поэтому повторный запуск продолжает с места остановки.

Примеры::

    python scripts/build_dataset.py --dry-run
    python scripts/build_dataset.py --concurrency 20
    python scripts/build_dataset.py --skip-generation   # только фильтр и split
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from configs.settings import (
    PROJECT_ROOT,
    PROVIDER_NAMES,
    get_provider,
    resolve_concurrency,
)
from data_pipeline.cli import configure_logging
from data_pipeline.dataset_io import read_jsonl, read_seed_records, write_jsonl
from data_pipeline.filter import filter_dataset

DATA_DIR = PROJECT_ROOT / "data"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

DEFAULT_SEEDS = DATA_DIR / "seeds_bulk_8000.jsonl"
DEFAULT_SAFETY_SEEDS = DATA_DIR / "safety_seeds_500.jsonl"
DEFAULT_BULK = DATA_DIR / "dialogues_bulk.jsonl"
DEFAULT_SAFETY = DATA_DIR / "safety_dialogues.jsonl"
DEFAULT_CLEAN = DATA_DIR / "dataset_v1_clean.jsonl"
DEFAULT_TRAIN = DATA_DIR / "train.jsonl"
DEFAULT_VAL = DATA_DIR / "val.jsonl"
DEFAULT_REPORT = DATA_DIR / "dataset_v1_report.json"

DEFAULT_CONCURRENCY = 20
DEFAULT_SAFETY_COUNT = 500
DEFAULT_VAL_RATIO = 0.1
DEFAULT_SPLIT_SEED = 42


@dataclass(frozen=True, slots=True)
class DatasetStats:
    """Итоги сборки датасета."""

    merged: int
    pii_dropped: int
    duplicates_dropped: int
    clean: int
    train: int
    val: int
    topics_train: Mapping[str, int]
    topics_val: Mapping[str, int]
    pii_by_kind: Mapping[str, int]

    def as_dict(self) -> dict[str, Any]:
        """Сериализуемое представление для JSON-отчёта."""
        return {
            "merged": self.merged,
            "pii_dropped": self.pii_dropped,
            "duplicates_dropped": self.duplicates_dropped,
            "clean": self.clean,
            "train": self.train,
            "val": self.val,
            "topics_train": dict(self.topics_train),
            "topics_val": dict(self.topics_val),
            "pii_by_kind": dict(self.pii_by_kind),
        }


def topic_distribution(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Распределение записей по темам (отсортировано по названию темы)."""
    counter = Counter(str(record.get("topic", "unknown")) for record in records)
    return dict(sorted(counter.items()))


def split_train_val(
    records: Sequence[Mapping[str, Any]],
    *,
    val_ratio: float = DEFAULT_VAL_RATIO,
    seed: int = DEFAULT_SPLIT_SEED,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Стратифицированное по `topic` разбиение на train/val.

    Внутри каждой темы записи перемешиваются детерминированным `random.Random`;
    в val уходит ``round(n * val_ratio)`` записей, но хотя бы одна, если в теме
    есть 2+ записи. Записи с одной темой не теряются: train + val = все входы.

    Raises:
        ValueError: `val_ratio` вне интервала (0, 1).
    """
    if not 0.0 < val_ratio < 1.0:
        raise ValueError("val_ratio должен быть в диапазоне (0, 1)")
    if not records:
        return [], []

    rng = random.Random(seed)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        topic = str(record.get("topic", "unknown"))
        buckets[topic].append(dict(record))

    train: list[dict[str, Any]] = []
    val: list[dict[str, Any]] = []

    for topic in sorted(buckets):
        items = buckets[topic]
        rng.shuffle(items)
        total = len(items)
        n_val = round(total * val_ratio)
        if total >= 2 and n_val == 0:
            n_val = 1
        n_val = min(n_val, total - 1) if total > 1 else 0
        val.extend(items[:n_val])
        train.extend(items[n_val:])

    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def prepare_safety_seeds(
    seeds_path: Path,
    output_path: Path,
    count: int = DEFAULT_SAFETY_COUNT,
) -> list[str]:
    """Записать первые `count` сидов в отдельный файл для Safety-блока.

    Возвращает список id, чтобы отчёт мог показать, сколько кейсов ожидается.
    """
    if count < 1:
        raise ValueError("safety_count должен быть >= 1")
    seeds = read_seed_records(seeds_path)
    if not seeds:
        raise ValueError(f"файл сидов пуст: {seeds_path}")

    subset = seeds[:count]
    write_jsonl(output_path, [seed.model_dump(mode="json") for seed in subset])
    logger.info("Safety-сиды: {} из {} → {}", len(subset), len(seeds), output_path)
    return [seed.id for seed in subset]


def build_dataset(
    bulk_path: Path,
    safety_path: Path,
    clean_path: Path,
    train_path: Path,
    val_path: Path,
    report_path: Path,
    *,
    val_ratio: float = DEFAULT_VAL_RATIO,
    split_seed: int = DEFAULT_SPLIT_SEED,
) -> DatasetStats:
    """Объединить, отфильтровать и разбить датасет; записать файлы и отчёт."""
    for path in (bulk_path, safety_path):
        if not path.exists():
            raise FileNotFoundError(f"нет входного файла: {path}")

    merged = list(read_jsonl(bulk_path)) + list(read_jsonl(safety_path))
    if not merged:
        raise ValueError("входные файлы пусты — нечего собирать")

    cleaned, filter_report = filter_dataset(merged)
    if not cleaned:
        raise ValueError("после фильтрации не осталось записей")

    train, val = split_train_val(cleaned, val_ratio=val_ratio, seed=split_seed)

    write_jsonl(clean_path, cleaned)
    write_jsonl(train_path, train)
    write_jsonl(val_path, val)

    stats = DatasetStats(
        merged=filter_report.total,
        pii_dropped=filter_report.pii_dropped,
        duplicates_dropped=filter_report.duplicates_dropped,
        clean=len(cleaned),
        train=len(train),
        val=len(val),
        topics_train=topic_distribution(train),
        topics_val=topic_distribution(val),
        pii_by_kind=dict(filter_report.pii_by_kind),
    )

    payload = {
        **stats.as_dict(),
        "val_ratio": val_ratio,
        "split_seed": split_seed,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return stats


def _run_script(script: str, args: Sequence[str]) -> None:
    """Запустить дочерний CLI-скрипт и упасть при ненулевом коде возврата."""
    command = [sys.executable, str(SCRIPTS_DIR / script), *args]
    logger.info("Запуск: {}", " ".join(command))
    completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{script} завершился с кодом {completed.returncode}")


def _generate(args: argparse.Namespace) -> None:
    """Сгенерировать bulk- и safety-диалоги через дочерние скрипты."""
    provider = get_provider(args.provider)
    concurrency = resolve_concurrency(provider, args.concurrency)
    if concurrency != args.concurrency:
        logger.warning(
            "GigaChat: concurrency принудительно ограничена до {} (запрошено {})",
            concurrency,
            args.concurrency,
        )
    prepare_safety_seeds(args.seeds, args.safety_seeds, args.safety_count)

    _run_script(
        "run_bulk.py",
        [
            "--provider",
            args.provider,
            "--seeds",
            str(args.seeds),
            "--output",
            str(args.bulk_output),
            "--concurrency",
            str(concurrency),
            "--resume",
        ],
    )
    _run_script(
        "run_safety.py",
        [
            "--provider",
            args.provider,
            "--seeds",
            str(args.safety_seeds),
            "--output",
            str(args.safety_output),
            "--resume",
        ],
    )
    # Второй проход добирает кейсы, упавшие на генерации/валидации: успешные
    # id пропускаются, повторный вызов для готового набора почти бесплатен.
    _run_script(
        "run_safety.py",
        [
            "--provider",
            args.provider,
            "--seeds",
            str(args.safety_seeds),
            "--output",
            str(args.safety_output),
            "--resume",
        ],
    )


def _log_stats(stats: DatasetStats, report_path: Path) -> None:
    """Напечатать финальный отчёт в лог."""
    logger.info(
        "Итог сборки: объединено {}, PII {}, дубликаты {}, осталось {}",
        stats.merged,
        stats.pii_dropped,
        stats.duplicates_dropped,
        stats.clean,
    )
    logger.info("train: {} | val: {}", stats.train, stats.val)
    logger.info("темы train: {}", dict(stats.topics_train))
    logger.info("темы val: {}", dict(stats.topics_val))
    logger.info("PII по типам: {}", dict(stats.pii_by_kind))
    logger.info("Отчёт: {}", report_path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Сборка датасета v1: bulk + safety → фильтр → train/val.",
        epilog="Генерация идемпотентна: run_bulk/run_safety вызываются с --resume.",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDER_NAMES,
        default="primary",
        help="провайдер генерации (по умолчанию primary)",
    )
    parser.add_argument(
        "--seeds",
        type=Path,
        default=DEFAULT_SEEDS,
        metavar="PATH",
        help=f"8000 сидов для bulk (по умолчанию {DEFAULT_SEEDS.name})",
    )
    parser.add_argument(
        "--safety-seeds",
        type=Path,
        default=DEFAULT_SAFETY_SEEDS,
        metavar="PATH",
        help=f"файл подмножества сидов для Safety (по умолчанию {DEFAULT_SAFETY_SEEDS.name})",
    )
    parser.add_argument(
        "--safety-count",
        type=int,
        default=DEFAULT_SAFETY_COUNT,
        metavar="N",
        help=f"сколько safety-кейсов сгенерировать (по умолчанию {DEFAULT_SAFETY_COUNT})",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        metavar="N",
        help=f"параллельных цепочек A+B (по умолчанию {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "--bulk-output",
        type=Path,
        default=DEFAULT_BULK,
        metavar="PATH",
        help=f"bulk-диалоги (по умолчанию {DEFAULT_BULK.name})",
    )
    parser.add_argument(
        "--safety-output",
        type=Path,
        default=DEFAULT_SAFETY,
        metavar="PATH",
        help=f"safety-диалоги (по умолчанию {DEFAULT_SAFETY.name})",
    )
    parser.add_argument(
        "--clean-output",
        type=Path,
        default=DEFAULT_CLEAN,
        metavar="PATH",
        help=f"очищенный объединённый датасет (по умолчанию {DEFAULT_CLEAN.name})",
    )
    parser.add_argument(
        "--train-output",
        type=Path,
        default=DEFAULT_TRAIN,
        metavar="PATH",
        help=f"train JSONL (по умолчанию {DEFAULT_TRAIN.name})",
    )
    parser.add_argument(
        "--val-output",
        type=Path,
        default=DEFAULT_VAL,
        metavar="PATH",
        help=f"val JSONL (по умолчанию {DEFAULT_VAL.name})",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        metavar="PATH",
        help=f"JSON-отчёт (по умолчанию {DEFAULT_REPORT.name})",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=DEFAULT_VAL_RATIO,
        metavar="R",
        help=f"доля val (по умолчанию {DEFAULT_VAL_RATIO})",
    )
    parser.add_argument(
        "--split-seed",
        type=int,
        default=DEFAULT_SPLIT_SEED,
        metavar="N",
        help=f"зерно разбиения (по умолчанию {DEFAULT_SPLIT_SEED})",
    )
    parser.add_argument(
        "--skip-generation",
        action="store_true",
        help="не запускать bulk/safety, использовать готовые файлы",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать план и проверить входные файлы, ничего не генерируя",
    )
    return parser.parse_args(argv)


def _check_safety_count(value: int) -> None:
    if value < 1:
        raise ValueError("safety-count должен быть >= 1")


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    try:
        _check_safety_count(args.safety_count)
        if not 0.0 < args.val_ratio < 1.0:
            raise ValueError("val-ratio должен быть в диапазоне (0, 1)")
        if args.concurrency < 1:
            raise ValueError("concurrency должен быть >= 1")
        seeds = read_seed_records(args.seeds)
        if not seeds:
            raise ValueError(f"файл сидов пуст: {args.seeds}")
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Не удалось подготовить сборку: {}", exc)
        return 1

    logger.info(
        "План: сидов {}, safety {}, concurrency {}, val {:.0%}",
        len(seeds),
        args.safety_count,
        args.concurrency,
        args.val_ratio,
    )
    logger.info(
        "bulk → {} | safety → {} | clean → {}",
        args.bulk_output,
        args.safety_output,
        args.clean_output,
    )

    if args.dry_run:
        logger.info("--dry-run: генерация и запись файлов не выполняются")
        return 0

    try:
        if not args.skip_generation:
            _generate(args)
        stats = build_dataset(
            args.bulk_output,
            args.safety_output,
            args.clean_output,
            args.train_output,
            args.val_output,
            args.report,
            val_ratio=args.val_ratio,
            split_seed=args.split_seed,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        logger.error("Сборка прервана: {}", exc)
        return 1

    _log_stats(stats, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
