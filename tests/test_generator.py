"""Тесты Шага A: промпты, генератор, resume-логика (T-003).

Сеть не используется: `TeacherClient` замокан. Отдельно проверяем, что
репозиторный `data/seeds.jsonl` валиден и содержит ровно 5 пилотных сидов.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from configs.prompts import (
    PromptError,
    PromptRenderer,
    get_prompts,
    load_prompts,
)
from configs.settings import PROJECT_ROOT
from data_pipeline.dataset_io import (
    append_jsonl,
    collect_existing_ids,
    read_jsonl,
    read_seed_records,
    select_pending,
)
from data_pipeline.generator import GenerationError, StageAGenerator, clean_query
from data_pipeline.llm_client import ChatResult, TeacherClient
from data_pipeline.schemas import SeedRecord

SEEDS_PATH = PROJECT_ROOT / "data" / "seeds.jsonl"

SEED_TEXT = (
    "Парацетамол высокотоксичен для кошек даже в небольших дозах. "
    "Специфического домашнего антидота не существует."
)


def _seed(seed_id: str = "seed-test-001", topic: str = "toxicology") -> SeedRecord:
    return SeedRecord(id=seed_id, topic=topic, seed_text=SEED_TEXT)  # type: ignore[arg-type]


def _chat_result(content: str = "У кота рвота, что делать?") -> ChatResult:
    return ChatResult(
        content=content,
        model="teacher-test",
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        latency_s=0.42,
        attempts=1,
    )


@pytest.fixture
def mock_client() -> Iterator[MagicMock]:
    client = MagicMock(spec=TeacherClient)
    client.chat = AsyncMock(return_value=_chat_result())
    yield client


@pytest.fixture
def prompts() -> PromptRenderer:
    return get_prompts()


@pytest.fixture
def generator(mock_client: MagicMock, prompts: PromptRenderer) -> StageAGenerator:
    return StageAGenerator(mock_client, prompts=prompts)


# --- Библиотека промптов ----------------------------------------------------


def test_repo_prompts_are_valid(prompts: PromptRenderer) -> None:
    assert prompts.version >= 1
    template = prompts.stage_a.template
    assert "{topic}" in template
    assert "{seed_text}" in template


def test_prompt_rendering_substitutes_placeholders(prompts: PromptRenderer) -> None:
    rendered = prompts.render_stage_a(topic="toxicology", seed_text=SEED_TEXT)

    assert "toxicology" in rendered
    assert SEED_TEXT in rendered
    assert "{topic}" not in rendered
    assert "{seed_text}" not in rendered


def test_prompt_without_required_placeholder_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "version: 1\nstage_a:\n  template: 'Только тема: {topic}'\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptError, match="плейсхолдер"):
        load_prompts(path)


def test_prompt_with_unknown_placeholder_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "version: 1\nstage_a:\n  template: '{topic} {seed_text} {weigth}'\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptError, match="weigth"):
        load_prompts(path)


def test_missing_prompts_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="не найден"):
        load_prompts(tmp_path / "absent.yaml")


# --- Генератор --------------------------------------------------------------


@pytest.mark.asyncio
async def test_generator_sends_rendered_prompt(
    generator: StageAGenerator, mock_client: MagicMock
) -> None:
    await generator.generate_query("toxicology", SEED_TEXT, seed_id="seed-test-001")

    mock_client.chat.assert_awaited_once()
    call = mock_client.chat.await_args
    assert call is not None
    messages = call.args[0]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert "toxicology" in content
    assert SEED_TEXT in content
    assert "{topic}" not in content
    assert "{seed_text}" not in content
    assert call.kwargs["temperature"] == 0.9
    assert call.kwargs["max_tokens"] == 300


@pytest.mark.asyncio
async def test_generator_returns_structured_record(generator: StageAGenerator) -> None:
    record = await generator.generate_query("toxicology", SEED_TEXT, seed_id="seed-test-001")

    assert record.id == "seed-test-001"
    assert record.stage == "A"
    assert record.topic == "toxicology"
    assert record.seed_text == SEED_TEXT
    assert record.user_query == "У кота рвота, что делать?"
    assert record.model == "teacher-test"
    assert record.prompt_tokens == 100
    assert record.completion_tokens == 20
    assert record.total_tokens == 120
    assert record.attempts == 1
    assert record.prompts_version == get_prompts().version
    assert record.generated_at.tzinfo is not None


@pytest.mark.asyncio
async def test_generator_rejects_empty_answer(
    mock_client: MagicMock, prompts: PromptRenderer
) -> None:
    mock_client.chat = AsyncMock(return_value=_chat_result("   "))
    generator = StageAGenerator(mock_client, prompts=prompts)

    with pytest.raises(GenerationError, match="пустой"):
        await generator.generate_query("toxicology", SEED_TEXT, seed_id="seed-1")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"У кота рвота."', "У кота рвота."),
        ("«У кота рвота.»", "У кота рвота."),
        ("  У кота\nрвота.  ", "У кота рвота."),
        ("'У кота рвота.'", "У кота рвота."),
        ("У кота рвота.", "У кота рвота."),
    ],
)
def test_clean_query(raw: str, expected: str) -> None:
    assert clean_query(raw) == expected


# --- Сиды и resume ----------------------------------------------------------


def test_repo_seeds_are_valid() -> None:
    seeds = read_seed_records(SEEDS_PATH)

    assert len(seeds) == 5, "по T-003 в data/seeds.jsonl должно быть 5 сидов"
    assert len({seed.id for seed in seeds}) == 5
    assert all(len(seed.seed_text) >= 20 for seed in seeds)
    assert {"gastroenterology", "dermatology", "toxicology"} <= {seed.topic for seed in seeds}


def test_read_seed_records_rejects_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "seeds.jsonl"
    line = json.dumps(
        {"id": "dup", "topic": "toxicology", "seed_text": SEED_TEXT},
        ensure_ascii=False,
    )
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="дубликат"):
        read_seed_records(path)


def test_missing_seeds_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_seed_records(tmp_path / "absent.jsonl")


def test_collect_existing_ids_ignores_broken_lines(tmp_path: Path) -> None:
    path = tmp_path / "out.jsonl"
    path.write_text(
        '{"id": "a"}\n\n{"id": "b"}\n{broken json\n{"no_id": 1}\n',
        encoding="utf-8",
    )

    assert collect_existing_ids(path) == {"a", "b"}


def test_collect_existing_ids_on_missing_file(tmp_path: Path) -> None:
    assert collect_existing_ids(tmp_path / "absent.jsonl") == set()


def test_select_pending_skips_done_and_applies_limit() -> None:
    seeds = [_seed(f"seed-{index}") for index in range(1, 6)]

    assert [seed.id for seed in select_pending(seeds)] == [
        "seed-1",
        "seed-2",
        "seed-3",
        "seed-4",
        "seed-5",
    ]
    assert [seed.id for seed in select_pending(seeds, existing_ids={"seed-1", "seed-3"})] == [
        "seed-2",
        "seed-4",
        "seed-5",
    ]
    assert [seed.id for seed in select_pending(seeds, existing_ids={"seed-2"}, limit=2)] == [
        "seed-1",
        "seed-3",
    ]


def test_select_pending_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="limit"):
        select_pending([_seed()], limit=0)


def test_append_and_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "out.jsonl"
    append_jsonl(path, {"id": "a", "user_query": "У кота рвота."})
    append_jsonl(path, {"id": "b", "user_query": "Собака чешет ухо."})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(line.startswith("{") for line in lines)

    payloads = list(read_jsonl(path))
    assert [payload["id"] for payload in payloads] == ["a", "b"]
    assert payloads[0]["user_query"] == "У кота рвота."
