"""Тесты генераторов Шагов A и B, resume-логики и JSONL-утилит (T-003, T-004).

Сеть не используется: `TeacherClient` замокан. Отдельно проверяем, что
репозиторный `data/seeds.jsonl` валиден и содержит ровно 5 пилотных сидов.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from configs.prompts import PromptRenderer, get_prompts
from configs.settings import PROJECT_ROOT
from data_pipeline.dataset_io import (
    append_jsonl,
    collect_existing_ids,
    read_jsonl,
    read_seed_records,
    read_stage_a_records,
    select_pending,
    write_jsonl,
)
from data_pipeline.generator import (
    GenerationError,
    StageAGenerator,
    StageBGenerator,
    StageSafetyGenerator,
    clean_query,
    parse_dialogue_json,
)
from data_pipeline.llm_client import ChatResult, TeacherClient
from data_pipeline.schemas import DialogueRecord, SeedRecord, StageARecord

SEEDS_PATH = PROJECT_ROOT / "data" / "seeds.jsonl"

SEED_TEXT = (
    "Парацетамол высокотоксичен для кошек даже в небольших дозах. "
    "Специфического домашнего антидота не существует."
)
USER_QUERY = "Кот наелся таблеток, что делать?"

VALID_DIALOGUE: list[dict[str, str]] = [
    {"role": "user", "content": USER_QUERY},
    {"role": "assistant", "content": "Сколько коту лет и когда он съел таблетку?"},
    {"role": "user", "content": "Два года, примерно час назад."},
    {
        "role": "assistant",
        "content": "Это экстренная ситуация: срочно везите кота в клинику, не ждите симптомов.",
    },
]


def _seed(seed_id: str = "seed-test-001", topic: str = "toxicology") -> SeedRecord:
    return SeedRecord(id=seed_id, topic=topic, seed_text=SEED_TEXT)  # type: ignore[arg-type]


def _stage_a_payload(record_id: str = "seed-test-001") -> dict[str, object]:
    return {
        "id": record_id,
        "stage": "A",
        "topic": "toxicology",
        "seed_text": SEED_TEXT,
        "user_query": USER_QUERY,
        "model": "teacher-test",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "latency_s": 0.1,
        "attempts": 1,
        "prompts_version": 2,
        "generated_at": "2026-01-01T00:00:00Z",
    }


def _chat_result(content: str) -> ChatResult:
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
    client.chat = AsyncMock(return_value=_chat_result("У кота рвота, что делать?"))
    yield client


@pytest.fixture
def prompts() -> PromptRenderer:
    return get_prompts()


@pytest.fixture
def stage_a(mock_client: MagicMock, prompts: PromptRenderer) -> StageAGenerator:
    return StageAGenerator(mock_client, prompts=prompts)


@pytest.fixture
def stage_b(mock_client: MagicMock, prompts: PromptRenderer) -> StageBGenerator:
    return StageBGenerator(mock_client, prompts=prompts)


@pytest.fixture
def safety(mock_client: MagicMock, prompts: PromptRenderer) -> StageSafetyGenerator:
    return StageSafetyGenerator(mock_client, prompts=prompts)


def _reply(mock_client: MagicMock, content: str) -> None:
    mock_client.chat = AsyncMock(return_value=_chat_result(content))


# --- Шаг A ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_a_sends_rendered_prompt(
    stage_a: StageAGenerator, mock_client: MagicMock
) -> None:
    await stage_a.generate_query("toxicology", SEED_TEXT, seed_id="seed-test-001")

    mock_client.chat.assert_awaited_once()
    call = mock_client.chat.await_args
    assert call is not None
    messages = call.args[0]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    assert "toxicology" in content
    assert SEED_TEXT in content
    assert "$topic" not in content
    assert "$seed_text" not in content
    assert call.kwargs["temperature"] == 0.9
    assert call.kwargs["max_tokens"] == 300


@pytest.mark.asyncio
async def test_stage_a_returns_structured_record(stage_a: StageAGenerator) -> None:
    record = await stage_a.generate_query("toxicology", SEED_TEXT, seed_id="seed-test-001")

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
async def test_stage_a_rejects_empty_answer(
    mock_client: MagicMock, prompts: PromptRenderer
) -> None:
    _reply(mock_client, "   ")
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


# --- Шаг B ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_b_sends_prompt_with_json_example(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    _reply(mock_client, json.dumps(VALID_DIALOGUE, ensure_ascii=False))

    await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-test-001")

    call = mock_client.chat.await_args
    assert call is not None
    content = call.args[0][0]["content"]
    assert USER_QUERY in content
    assert "toxicology" in content
    assert '{"role": "user", "content": "..."}' in content
    assert "$user_query" not in content


@pytest.mark.asyncio
async def test_stage_b_parses_valid_dialogue(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    _reply(mock_client, json.dumps(VALID_DIALOGUE, ensure_ascii=False))

    dialogue = await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-test-001")

    assert isinstance(dialogue, DialogueRecord)
    assert dialogue.id == "seed-test-001"
    assert dialogue.stage == "B"
    assert dialogue.topic == "toxicology"
    assert len(dialogue.messages) == 4
    assert dialogue.turns == 2
    assert dialogue.messages[0].role == "user"
    assert dialogue.messages[-1].role == "assistant"
    assert dialogue.messages[0].content == USER_QUERY
    assert dialogue.model == "teacher-test"
    assert dialogue.total_tokens == 120
    assert dialogue.prompts_version == get_prompts().version


@pytest.mark.asyncio
async def test_stage_b_accepts_markdown_fence(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    fenced = "```json\n" + json.dumps(VALID_DIALOGUE, ensure_ascii=False) + "\n```"
    _reply(mock_client, fenced)

    dialogue = await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-1")

    assert len(dialogue.messages) == 4


@pytest.mark.asyncio
async def test_stage_b_accepts_surrounding_prose(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    payload = json.dumps(VALID_DIALOGUE, ensure_ascii=False)
    _reply(mock_client, f"Вот диалог:\n{payload}\nНадеюсь, подойдёт.")

    dialogue = await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-1")

    assert len(dialogue.messages) == 4


@pytest.mark.asyncio
async def test_stage_b_accepts_messages_wrapper(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    payload = json.dumps({"messages": VALID_DIALOGUE}, ensure_ascii=False)
    _reply(mock_client, payload)

    dialogue = await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-1")

    assert len(dialogue.messages) == 4


@pytest.mark.asyncio
async def test_stage_b_drops_extra_message_fields(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    """Модель иногда добавляет `turn`/`emotion` — лишние поля не ломают диалог."""
    noisy = [
        dict(message, turn=index, emotion="neutral") for index, message in enumerate(VALID_DIALOGUE)
    ]
    _reply(mock_client, json.dumps(noisy, ensure_ascii=False))

    dialogue = await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-1")

    assert len(dialogue.messages) == 4
    assert dialogue.messages[0].model_dump() == {"role": "user", "content": USER_QUERY}


@pytest.mark.asyncio
async def test_stage_b_rejects_invalid_json(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    _reply(mock_client, "Извините, не могу сгенерировать диалог.")

    with pytest.raises(GenerationError, match="JSON"):
        await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-1")


@pytest.mark.asyncio
async def test_stage_b_rejects_two_users_in_a_row(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    broken = [
        {"role": "user", "content": "Раз"},
        {"role": "user", "content": "Два"},
        {"role": "assistant", "content": "Три"},
        {"role": "assistant", "content": "Четыре"},
    ]
    _reply(mock_client, json.dumps(broken, ensure_ascii=False))

    with pytest.raises(GenerationError, match="не прошёл валидацию"):
        await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-1")


@pytest.mark.asyncio
async def test_stage_b_rejects_too_short_dialogue(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    _reply(mock_client, json.dumps(VALID_DIALOGUE[:2], ensure_ascii=False))

    with pytest.raises(GenerationError, match="не прошёл валидацию"):
        await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-1")


@pytest.mark.asyncio
async def test_stage_b_rejects_too_long_dialogue(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    long_dialogue = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"Реплика {index}"}
        for index in range(10)
    ]
    _reply(mock_client, json.dumps(long_dialogue, ensure_ascii=False))

    with pytest.raises(GenerationError, match="не прошёл валидацию"):
        await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-1")


@pytest.mark.asyncio
async def test_stage_b_rejects_starting_with_assistant(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    broken = [VALID_DIALOGUE[1], VALID_DIALOGUE[0], VALID_DIALOGUE[1], VALID_DIALOGUE[0]]
    _reply(mock_client, json.dumps(broken, ensure_ascii=False))

    with pytest.raises(GenerationError, match="не прошёл валидацию"):
        await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-1")


@pytest.mark.asyncio
async def test_stage_b_rejects_non_object_messages(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    _reply(mock_client, json.dumps(["user", "assistant", "user", "assistant"]))

    with pytest.raises(GenerationError, match="не прошёл валидацию"):
        await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-1")


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        '"строка"',
        '{"messages": "не массив"}',
    ],
)
def test_parse_dialogue_json_rejects_wrong_shapes(payload: str) -> None:
    with pytest.raises(GenerationError):
        parse_dialogue_json(payload)


def test_parse_dialogue_json_returns_array_as_is() -> None:
    """Пустой массив — валидный JSON; его отбраковывает уже схема диалога."""
    assert parse_dialogue_json("[]") == []


@pytest.mark.asyncio
async def test_stage_b_rejects_empty_array(
    stage_b: StageBGenerator, mock_client: MagicMock
) -> None:
    _reply(mock_client, "[]")

    with pytest.raises(GenerationError, match="не прошёл валидацию"):
        await stage_b.generate_dialogue(USER_QUERY, "toxicology", seed_id="seed-1")


# --- Safety -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_safety_sends_prompt_with_topic(
    safety: StageSafetyGenerator, mock_client: MagicMock
) -> None:
    _reply(mock_client, json.dumps(VALID_DIALOGUE, ensure_ascii=False))

    await safety.generate_case("toxicology", case_id="safety-seed-1")

    call = mock_client.chat.await_args
    assert call is not None
    content = call.args[0][0]["content"]
    assert "toxicology" in content
    assert "Ты — специалист по безопасности в медицинских ИИ-ассистентах." in content
    assert "Категорический отказ от назначения дозировок без ветеринара." in content
    assert "$topic" not in content
    assert call.kwargs["temperature"] == 0.8


@pytest.mark.asyncio
async def test_safety_returns_safety_record(
    safety: StageSafetyGenerator, mock_client: MagicMock
) -> None:
    _reply(mock_client, json.dumps(VALID_DIALOGUE, ensure_ascii=False))

    record = await safety.generate_case("toxicology", case_id="safety-seed-1")

    assert record.stage == "safety"
    assert record.id == "safety-seed-1"
    assert record.topic == "toxicology"
    assert len(record.messages) == 4
    assert record.turns == 2
    assert record.messages[0].role == "user"
    assert record.messages[-1].role == "assistant"
    assert record.prompts_version == get_prompts().version


@pytest.mark.asyncio
async def test_safety_rejects_invalid_json(
    safety: StageSafetyGenerator, mock_client: MagicMock
) -> None:
    _reply(mock_client, "Не могу выполнить эту просьбу.")

    with pytest.raises(GenerationError, match="JSON"):
        await safety.generate_case("toxicology", case_id="safety-seed-1")


@pytest.mark.asyncio
async def test_safety_rejects_broken_roles(
    safety: StageSafetyGenerator, mock_client: MagicMock
) -> None:
    broken = [VALID_DIALOGUE[1], VALID_DIALOGUE[0], VALID_DIALOGUE[1], VALID_DIALOGUE[0]]
    _reply(mock_client, json.dumps(broken, ensure_ascii=False))

    with pytest.raises(GenerationError, match="не прошёл валидацию"):
        await safety.generate_case("toxicology", case_id="safety-seed-1")


@pytest.mark.asyncio
async def test_safety_rejects_too_short_dialogue(
    safety: StageSafetyGenerator, mock_client: MagicMock
) -> None:
    _reply(mock_client, json.dumps(VALID_DIALOGUE[:2], ensure_ascii=False))

    with pytest.raises(GenerationError, match="не прошёл валидацию"):
        await safety.generate_case("toxicology", case_id="safety-seed-1")


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


def test_read_stage_a_records_validates(tmp_path: Path) -> None:
    path = tmp_path / "stage_a.jsonl"
    path.write_text(
        json.dumps(_stage_a_payload(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    records = read_stage_a_records(path)

    assert len(records) == 1
    assert isinstance(records[0], StageARecord)
    assert records[0].user_query == USER_QUERY


def test_read_stage_a_records_rejects_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "stage_a.jsonl"
    line = json.dumps(_stage_a_payload(), ensure_ascii=False)
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="дубликат"):
        read_stage_a_records(path)


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


def test_select_pending_works_with_stage_a_records() -> None:
    records = [
        StageARecord.model_validate(_stage_a_payload(f"seed-{index}")) for index in range(1, 4)
    ]

    pending = select_pending(records, existing_ids={"seed-2"})

    assert [record.id for record in pending] == ["seed-1", "seed-3"]


def test_select_pending_uses_custom_key() -> None:
    """Safety-блок хранит id как `safety-<seed.id>` — resume должен это учитывать."""
    seeds = [_seed("seed-1"), _seed("seed-2")]

    pending = select_pending(
        seeds,
        existing_ids={"safety-seed-1"},
        key=lambda seed: f"safety-{seed.id}",
    )

    assert [seed.id for seed in pending] == ["seed-2"]


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


def test_write_jsonl_overwrites_file(tmp_path: Path) -> None:
    path = tmp_path / "clean" / "dataset.jsonl"

    assert write_jsonl(path, [{"id": "a"}, {"id": "b"}]) == 2
    assert write_jsonl(path, [{"id": "c"}]) == 1

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines == ['{"id": "c"}']
    assert path.read_text(encoding="utf-8").endswith("\n")
