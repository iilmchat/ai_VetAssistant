"""Тесты генератора сидов и пилотного прогона (T-008)."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from configs.settings import ProviderConfig
from data_pipeline.dataset_io import read_jsonl, write_jsonl
from data_pipeline.llm_client import ChatResult
from data_pipeline.schemas import DialogueRecord, SeedRecord
from scripts.generate_seeds import TOPICS, build_seeds
from scripts.generate_seeds import main as generate_main
from scripts.run_pilot import main as pilot_main
from scripts.run_pilot import pilot_output_path

DIALOGUE = [
    {"role": "user", "content": "Кот не ест второй день, что делать?"},
    {"role": "assistant", "content": "Сколько коту лет и как давно он не ест?"},
    {"role": "user", "content": "Два года, второй день."},
    {"role": "assistant", "content": "Покажите кота ветеринару в ближайшие сутки."},
]


def _write_seeds(path: Path, count: int = 2) -> Path:
    seeds = build_seeds(count, rng=random.Random(5))
    write_jsonl(path, [seed.model_dump(mode="json") for seed in seeds])
    return path


def _read_seed_records(path: Path) -> list[SeedRecord]:
    return [SeedRecord.model_validate(payload) for payload in read_jsonl(path)]


class _FakeTeacher:
    """Минимальный двойник TeacherClient для пилота (без сети)."""

    def __init__(self, provider: ProviderConfig, **kwargs: Any) -> None:
        self.provider = provider

    async def __aenter__(self) -> _FakeTeacher:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def chat(self, messages: Any, **kwargs: Any) -> ChatResult:
        prompt = messages[0]["content"]
        if "Формат вывода: JSON-массив" in prompt:
            content = json.dumps(DIALOGUE, ensure_ascii=False)
        else:
            content = "Кот не ест второй день, что делать?"
        return ChatResult(
            content=content,
            model="fake-model",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            latency_s=0.01,
            attempts=1,
        )


# --- generate_seeds ---------------------------------------------------------


def test_build_seeds_count_topics_and_ids() -> None:
    seeds = build_seeds(100, rng=random.Random(1))

    assert len(seeds) == 100
    assert [seed.id for seed in seeds] == [f"bulk-{index:04d}" for index in range(1, 101)]
    assert all(seed.topic in TOPICS for seed in seeds)
    assert len({seed.topic for seed in seeds}) > 1
    assert all("MSD Vet Manual" in seed.seed_text for seed in seeds)


def test_build_seeds_is_deterministic() -> None:
    first = build_seeds(20, rng=random.Random(7))
    second = build_seeds(20, rng=random.Random(7))

    assert [seed.topic for seed in first] == [seed.topic for seed in second]
    assert [seed.seed_text for seed in first] == [seed.seed_text for seed in second]


def test_build_seeds_rejects_zero_count() -> None:
    with pytest.raises(ValueError, match="count"):
        build_seeds(0, rng=random.Random(1))


def test_generate_seeds_cli_writes_valid_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "seeds_bulk.jsonl"

    exit_code = generate_main(["--count", "5", "--output", str(output)])

    assert exit_code == 0
    records = _read_seed_records(output)
    assert len(records) == 5
    assert records[0].id == "bulk-0001"


def test_generate_seeds_dry_run_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "seeds_bulk.jsonl"

    exit_code = generate_main(["--count", "3", "--output", str(output), "--dry-run"])

    assert exit_code == 0
    assert not output.exists()
    assert "bulk-0001" in capsys.readouterr().out


# --- run_pilot --------------------------------------------------------------


def test_pilot_output_path_uses_provider_name() -> None:
    assert pilot_output_path("primary").name == "pilot_primary.jsonl"
    assert pilot_output_path("fallback").name == "pilot_fallback.jsonl"


def test_pilot_dry_run_does_not_call_api_or_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seeds = _write_seeds(tmp_path / "seeds.jsonl", count=3)
    output = tmp_path / "pilot_primary.jsonl"

    exit_code = pilot_main(
        [
            "--dry-run",
            "--seeds",
            str(seeds),
            "--output",
            str(output),
            "--limit",
            "2",
        ]
    )

    assert exit_code == 0
    assert not output.exists()
    captured = capsys.readouterr().out
    assert "bulk-0001" in captured
    assert "Шаг A" in captured
    assert "API не вызывается" in captured


def test_pilot_runs_two_stages_and_reports_stats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seeds = _write_seeds(tmp_path / "seeds.jsonl", count=2)
    output = tmp_path / "pilot_primary.jsonl"

    monkeypatch.setattr("scripts.run_pilot.TeacherClient", _FakeTeacher)
    monkeypatch.setattr(
        "scripts.run_pilot.get_provider",
        lambda name: ProviderConfig(
            name="primary",
            api_key=SecretStr("sk-fake"),
            base_url="http://127.0.0.1:1/v1",
            model="fake-model",
        ),
    )

    exit_code = pilot_main(
        [
            "--provider",
            "primary",
            "--seeds",
            str(seeds),
            "--output",
            str(output),
            "--limit",
            "2",
        ]
    )

    assert exit_code == 0
    records = [DialogueRecord.model_validate(payload) for payload in read_jsonl(output)]
    assert [record.id for record in records] == ["bulk-0001", "bulk-0002"]
    assert all(len(record.messages) == 4 for record in records)

    captured = capsys.readouterr().out
    assert "успешно 2" in captured
    assert "ошибок 0" in captured
    assert "токенов 120" in captured


def test_pilot_missing_seeds_returns_one(tmp_path: Path) -> None:
    exit_code = pilot_main(["--seeds", str(tmp_path / "absent.jsonl")])

    assert exit_code == 1
