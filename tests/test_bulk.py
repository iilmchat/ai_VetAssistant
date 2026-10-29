"""Тесты bulk-генерации: семафор, resume и устойчивость к ошибкам (T-009)."""

from __future__ import annotations

import asyncio
import json
import random
import re
from pathlib import Path
from typing import Any

import httpx2
import pytest
from openai import APIConnectionError, APIStatusError
from pydantic import SecretStr

from configs.settings import ProviderConfig
from data_pipeline.dataset_io import read_jsonl, write_jsonl
from data_pipeline.llm_client import ChatResult
from data_pipeline.schemas import DialogueRecord
from scripts.generate_seeds import build_seeds
from scripts.run_bulk import FatalProviderError, bulk_output_path, generate_bulk, main

DIALOGUE = [
    {"role": "user", "content": "Кот не ест второй день, что делать?"},
    {"role": "assistant", "content": "Сколько коту лет и как давно он не ест?"},
    {"role": "user", "content": "Два года, второй день."},
    {"role": "assistant", "content": "Покажите кота ветеринару в ближайшие сутки."},
]

SEED_NUMBER_RE = re.compile(r"номер (\d+)")


def _provider() -> ProviderConfig:
    return ProviderConfig(
        name="primary",
        api_key=SecretStr("sk-fake"),
        base_url="http://127.0.0.1:1/v1",
        model="fake-model",
    )


def _write_seeds(path: Path, count: int) -> Path:
    seeds = build_seeds(count, rng=random.Random(5))
    write_jsonl(path, [seed.model_dump(mode="json") for seed in seeds])
    return path


def _dialogue_payload(seed_id: str) -> dict[str, Any]:
    return {
        "id": seed_id,
        "stage": "B",
        "topic": "toxicology",
        "messages": DIALOGUE,
        "model": "fake-model",
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
        "latency_s": 0.01,
        "attempts": 1,
        "prompts_version": 4,
        "generated_at": "2026-01-01T00:00:00Z",
    }


class _FakeClient:
    """Двойник TeacherClient: считает одновременные вызовы и умеет падать."""

    def __init__(
        self,
        *,
        delay: float = 0.0,
        fail_on_numbers: set[int] | None = None,
        fatal_status: int | None = None,
    ) -> None:
        self.delay = delay
        self.fail_on_numbers = fail_on_numbers or set()
        self.fatal_status = fatal_status
        self.active = 0
        self.max_active = 0
        self.stage_a_numbers: list[int] = []
        self.calls = 0

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def chat(self, messages: Any, **kwargs: Any) -> ChatResult:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            prompt = messages[0]["content"]
            is_stage_b = "Формат вывода: JSON-массив" in prompt
            match = SEED_NUMBER_RE.search(prompt)
            number = int(match.group(1)) if match else None

            if not is_stage_b and self.fatal_status is not None:
                request = httpx2.Request("POST", "http://test")
                response = httpx2.Response(self.fatal_status, request=request)
                raise APIStatusError("Insufficient Balance", response=response, body=None)

            if not is_stage_b and number in self.fail_on_numbers:
                raise APIConnectionError(request=httpx2.Request("POST", "http://test"))

            if is_stage_b:
                content = json.dumps(DIALOGUE, ensure_ascii=False)
            else:
                if number is not None:
                    self.stage_a_numbers.append(number)
                content = f"Вопрос по сиду {number}: кот не ест, что делать?"
            return ChatResult(
                content=content,
                model="fake-model",
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                latency_s=0.01,
                attempts=1,
            )
        finally:
            self.active -= 1


def test_bulk_output_path_uses_provider_name() -> None:
    assert bulk_output_path("primary").name == "dialogues_bulk_primary.jsonl"
    assert bulk_output_path("fallback").name == "dialogues_bulk_fallback.jsonl"


@pytest.mark.asyncio
async def test_semaphore_limits_parallel_chains(tmp_path: Path) -> None:
    seeds = build_seeds(6, rng=random.Random(1))
    client: Any = _FakeClient(delay=0.01)

    stats = await generate_bulk(seeds, tmp_path / "out.jsonl", client, concurrency=2)

    assert stats.success == 6
    assert stats.errors == 0
    assert client.max_active == 2  # ровно лимит, не больше
    records = [DialogueRecord.model_validate(row) for row in read_jsonl(tmp_path / "out.jsonl")]
    assert len(records) == 6


@pytest.mark.asyncio
async def test_one_error_does_not_stop_the_run(tmp_path: Path) -> None:
    seeds = build_seeds(3, rng=random.Random(2))
    client: Any = _FakeClient(fail_on_numbers={2})
    output = tmp_path / "out.jsonl"

    stats = await generate_bulk(seeds, output, client, concurrency=3)

    assert stats.processed == 3
    assert stats.success == 2
    assert stats.errors == 1
    assert stats.tokens == 120  # 2 успешных кейса × (30 + 30)
    records = [DialogueRecord.model_validate(row) for row in read_jsonl(output)]
    assert {record.id for record in records} == {"bulk-0001", "bulk-0003"}


@pytest.mark.asyncio
async def test_fatal_balance_error_aborts_bulk(tmp_path: Path) -> None:
    """402/401/403 — не транзиентные: прогон должен остановиться сразу."""
    seeds = build_seeds(5, rng=random.Random(3))
    client: Any = _FakeClient(fatal_status=402)
    output = tmp_path / "out.jsonl"

    with pytest.raises(FatalProviderError, match="402"):
        await generate_bulk(seeds, output, client, concurrency=1)

    assert client.calls == 1
    assert list(read_jsonl(output)) == []


def test_resume_skips_ids_already_in_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seeds = _write_seeds(tmp_path / "seeds.jsonl", count=3)
    output = tmp_path / "bulk.jsonl"
    write_jsonl(output, [_dialogue_payload("bulk-0001")])
    client: Any = _FakeClient()

    monkeypatch.setattr("scripts.run_bulk.TeacherClient", lambda provider, **kwargs: client)
    monkeypatch.setattr("scripts.run_bulk.get_provider", lambda name: _provider())

    exit_code = main(
        [
            "--resume",
            "--seeds",
            str(seeds),
            "--output",
            str(output),
            "--concurrency",
            "2",
        ]
    )

    assert exit_code == 0
    assert sorted(client.stage_a_numbers) == [2, 3]
    records = [DialogueRecord.model_validate(row) for row in read_jsonl(output)]
    assert {record.id for record in records} == {"bulk-0001", "bulk-0002", "bulk-0003"}

    captured = capsys.readouterr().out
    assert "уже готово: 1" in captured
    assert "Итог bulk: обработано 2, успешно 2, ошибок 0" in captured


def test_resume_with_everything_done_does_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seeds = _write_seeds(tmp_path / "seeds.jsonl", count=2)
    output = tmp_path / "bulk.jsonl"
    write_jsonl(
        output,
        [_dialogue_payload("bulk-0001"), _dialogue_payload("bulk-0002")],
    )
    client: Any = _FakeClient()
    monkeypatch.setattr("scripts.run_bulk.TeacherClient", lambda provider, **kwargs: client)
    monkeypatch.setattr("scripts.run_bulk.get_provider", lambda name: _provider())

    exit_code = main(["--resume", "--seeds", str(seeds), "--output", str(output)])

    assert exit_code == 0
    assert client.stage_a_numbers == []
    assert "Нечего обрабатывать" in capsys.readouterr().out


def test_limit_caps_new_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seeds = _write_seeds(tmp_path / "seeds.jsonl", count=4)
    output = tmp_path / "bulk.jsonl"
    client: Any = _FakeClient()
    monkeypatch.setattr("scripts.run_bulk.TeacherClient", lambda provider, **kwargs: client)
    monkeypatch.setattr("scripts.run_bulk.get_provider", lambda name: _provider())

    exit_code = main(
        [
            "--seeds",
            str(seeds),
            "--output",
            str(output),
            "--limit",
            "2",
            "--concurrency",
            "1",
        ]
    )

    assert exit_code == 0
    records = [DialogueRecord.model_validate(row) for row in read_jsonl(output)]
    assert [record.id for record in records] == ["bulk-0001", "bulk-0002"]


def test_dry_run_does_not_call_api_or_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seeds = _write_seeds(tmp_path / "seeds.jsonl", count=2)
    output = tmp_path / "bulk.jsonl"
    client: Any = _FakeClient()
    monkeypatch.setattr("scripts.run_bulk.TeacherClient", lambda provider, **kwargs: client)
    monkeypatch.setattr("scripts.run_bulk.get_provider", lambda name: _provider())

    exit_code = main(["--dry-run", "--seeds", str(seeds), "--output", str(output), "--limit", "2"])

    assert exit_code == 0
    assert not output.exists()
    assert client.stage_a_numbers == []
    assert "bulk-0001" in capsys.readouterr().out


def test_missing_seeds_returns_one(tmp_path: Path) -> None:
    exit_code = main(["--seeds", str(tmp_path / "absent.jsonl")])

    assert exit_code == 1


def test_generate_bulk_rejects_zero_concurrency(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="concurrency"):
        asyncio.run(
            generate_bulk([], tmp_path / "out.jsonl", object(), concurrency=0)  # type: ignore[arg-type]
        )
