"""Тесты сборки датасета: стратификация, фильтрация и CLI (T-010)."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from data_pipeline.dataset_io import read_jsonl, write_jsonl
from scripts.build_dataset import (
    build_dataset,
    main,
    prepare_safety_seeds,
    split_train_val,
    topic_distribution,
)
from scripts.generate_seeds import build_seeds

TOPICS = ("gastroenterology", "dermatology", "toxicology", "emergency")


def _dialogue(
    record_id: str,
    topic: str,
    first_user: str,
    *,
    email: bool = False,
) -> dict[str, Any]:
    user = first_user + (" Пишите на test@example.com" if email else "")
    return {
        "id": record_id,
        "topic": topic,
        "messages": [
            {"role": "user", "content": user},
            {"role": "assistant", "content": "Ответ ассистента."},
        ],
    }


def _grid(count_per_topic: int = 50) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for topic in TOPICS:
        for index in range(count_per_topic):
            records.append(_dialogue(f"{topic}-{index:03d}", topic, f"вопрос {topic} {index}"))
    return records


def _write_seeds_file(path: Path, count: int) -> Path:
    seeds = build_seeds(count, rng=random.Random(3))
    write_jsonl(path, [seed.model_dump(mode="json") for seed in seeds])
    return path


# --- Стратифицированное разбиение -------------------------------------------


def test_split_is_stratified_and_complete() -> None:
    records = _grid(count_per_topic=50)

    train, val = split_train_val(records, val_ratio=0.1, seed=42)

    assert len(train) + len(val) == len(records)
    assert len(val) == 20  # по 5 из каждой темы
    for topic in TOPICS:
        assert sum(1 for record in val if record["topic"] == topic) == 5
        assert sum(1 for record in train if record["topic"] == topic) == 45


def test_split_is_deterministic() -> None:
    records = _grid(count_per_topic=20)

    train_a, val_a = split_train_val(records, seed=7)
    train_b, val_b = split_train_val(records, seed=7)

    assert [record["id"] for record in train_a] == [record["id"] for record in train_b]
    assert [record["id"] for record in val_a] == [record["id"] for record in val_b]


def test_split_different_seeds_shuffle_differently() -> None:
    records = _grid(count_per_topic=20)

    _, val_a = split_train_val(records, seed=1)
    _, val_b = split_train_val(records, seed=2)

    assert [record["id"] for record in val_a] != [record["id"] for record in val_b]


def test_split_keeps_single_record_topic_in_train() -> None:
    records = [_dialogue("solo", "toxicology", "единственный вопрос")]

    train, val = split_train_val(records, val_ratio=0.1)

    assert [record["id"] for record in train] == ["solo"]
    assert val == []


def test_split_small_topic_gets_one_val_record() -> None:
    records = [
        _dialogue("a", "toxicology", "вопрос a"),
        _dialogue("b", "toxicology", "вопрос b"),
    ]

    train, val = split_train_val(records, val_ratio=0.1)

    assert len(train) == 1
    assert len(val) == 1


@pytest.mark.parametrize("ratio", [0.0, 1.0, -0.1, 1.5])
def test_split_rejects_invalid_ratio(ratio: float) -> None:
    with pytest.raises(ValueError, match="val_ratio"):
        split_train_val([_dialogue("a", "toxicology", "вопрос")], val_ratio=ratio)


def test_split_empty_input() -> None:
    assert split_train_val([]) == ([], [])


def test_topic_distribution_is_sorted() -> None:
    records = [
        _dialogue("a", "toxicology", "1"),
        _dialogue("b", "dermatology", "2"),
        _dialogue("c", "toxicology", "3"),
    ]

    assert topic_distribution(records) == {"dermatology": 1, "toxicology": 2}


# --- Сборка датасета --------------------------------------------------------


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    bulk = tmp_path / "bulk.jsonl"
    safety = tmp_path / "safety.jsonl"
    write_jsonl(
        bulk,
        [
            _dialogue("b1", "gastroenterology", "Кот не ест"),
            _dialogue("b2", "gastroenterology", "Собака чешется"),
            _dialogue("b3", "dermatology", "Ухо чешется"),
            _dialogue("b4", "dermatology", "Пятно на животе"),
            _dialogue("b5", "toxicology", "Парацетамол", email=True),
            _dialogue("b6", "toxicology", "Шоколад"),
            _dialogue("b7", "toxicology", "Шоколад"),
            _dialogue("b8", "emergency", "Судороги"),
        ],
    )
    write_jsonl(
        safety,
        [
            _dialogue("s1", "toxicology", "Сколько дать?", email=True),
            _dialogue("s2", "emergency", "Не поеду в клинику"),
        ],
    )
    return bulk, safety


def test_build_dataset_filters_and_splits(tmp_path: Path) -> None:
    bulk, safety = _write_inputs(tmp_path)
    clean = tmp_path / "clean.jsonl"
    train_path = tmp_path / "train.jsonl"
    val_path = tmp_path / "val.jsonl"
    report_path = tmp_path / "report.json"

    stats = build_dataset(
        bulk,
        safety,
        clean,
        train_path,
        val_path,
        report_path,
        val_ratio=0.2,
        split_seed=1,
    )

    assert stats.merged == 10
    assert stats.pii_dropped == 2
    assert stats.duplicates_dropped == 1
    assert stats.clean == 7
    assert stats.train + stats.val == 7

    clean_ids = {row["id"] for row in read_jsonl(clean)}
    assert clean_ids == {"b1", "b2", "b3", "b4", "b6", "b8", "s2"}

    train = list(read_jsonl(train_path))
    val = list(read_jsonl(val_path))
    assert len(train) == stats.train
    assert len(val) == stats.val
    assert {row["id"] for row in train} | {row["id"] for row in val} == clean_ids
    assert not ({row["id"] for row in train} & {row["id"] for row in val})

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["train"] == stats.train
    assert payload["val"] == stats.val
    assert payload["merged"] == 10
    assert payload["val_ratio"] == 0.2
    assert payload["topics_train"]
    assert payload["topics_val"]


def test_build_dataset_missing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="нет входного файла"):
        build_dataset(
            tmp_path / "absent_bulk.jsonl",
            tmp_path / "absent_safety.jsonl",
            tmp_path / "clean.jsonl",
            tmp_path / "train.jsonl",
            tmp_path / "val.jsonl",
            tmp_path / "report.json",
        )


def test_build_dataset_with_nothing_left_after_filter(tmp_path: Path) -> None:
    bulk = tmp_path / "bulk.jsonl"
    safety = tmp_path / "safety.jsonl"
    write_jsonl(bulk, [_dialogue("b1", "toxicology", "Почта", email=True)])
    write_jsonl(safety, [_dialogue("s1", "toxicology", "Ещё почта", email=True)])

    with pytest.raises(ValueError, match="после фильтрации"):
        build_dataset(
            bulk,
            safety,
            tmp_path / "clean.jsonl",
            tmp_path / "train.jsonl",
            tmp_path / "val.jsonl",
            tmp_path / "report.json",
        )


def test_prepare_safety_seeds_takes_first_n(tmp_path: Path) -> None:
    seeds_path = _write_seeds_file(tmp_path / "seeds.jsonl", count=5)
    subset_path = tmp_path / "safety_seeds.jsonl"

    ids = prepare_safety_seeds(seeds_path, subset_path, count=3)

    assert ids == ["bulk-0001", "bulk-0002", "bulk-0003"]
    assert [row["id"] for row in read_jsonl(subset_path)] == ids


def test_prepare_safety_seeds_rejects_zero(tmp_path: Path) -> None:
    seeds_path = _write_seeds_file(tmp_path / "seeds.jsonl", count=2)

    with pytest.raises(ValueError, match="safety_count"):
        prepare_safety_seeds(seeds_path, tmp_path / "subset.jsonl", count=0)


# --- CLI --------------------------------------------------------------------


def test_cli_dry_run_does_not_touch_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seeds_path = _write_seeds_file(tmp_path / "seeds.jsonl", count=3)
    train_path = tmp_path / "train.jsonl"

    exit_code = main(
        [
            "--dry-run",
            "--seeds",
            str(seeds_path),
            "--train-output",
            str(train_path),
            "--val-output",
            str(tmp_path / "val.jsonl"),
            "--clean-output",
            str(tmp_path / "clean.jsonl"),
            "--report",
            str(tmp_path / "report.json"),
        ]
    )

    assert exit_code == 0
    assert not train_path.exists()
    assert "сидов 3" in capsys.readouterr().out


def test_cli_skip_generation_builds_dataset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bulk, safety = _write_inputs(tmp_path)
    seeds_path = _write_seeds_file(tmp_path / "seeds.jsonl", count=2)
    train_path = tmp_path / "train.jsonl"
    val_path = tmp_path / "val.jsonl"
    clean_path = tmp_path / "clean.jsonl"
    report_path = tmp_path / "report.json"

    exit_code = main(
        [
            "--skip-generation",
            "--seeds",
            str(seeds_path),
            "--bulk-output",
            str(bulk),
            "--safety-output",
            str(safety),
            "--clean-output",
            str(clean_path),
            "--train-output",
            str(train_path),
            "--val-output",
            str(val_path),
            "--report",
            str(report_path),
            "--val-ratio",
            "0.2",
        ]
    )

    assert exit_code == 0
    assert clean_path.exists() and train_path.exists() and val_path.exists()
    assert report_path.exists()
    captured = capsys.readouterr().out
    assert "Итог сборки" in captured
    assert "train:" in captured and "val:" in captured


def test_cli_rejects_bad_val_ratio(tmp_path: Path) -> None:
    seeds_path = _write_seeds_file(tmp_path / "seeds.jsonl", count=2)

    exit_code = main(["--dry-run", "--seeds", str(seeds_path), "--val-ratio", "1.5"])

    assert exit_code == 1
