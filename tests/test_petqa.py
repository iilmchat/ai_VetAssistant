"""Тесты импорта PetQA и конвертации в схемы (T-011).

Все тесты офлайновые: сеть подменяется `httpx2.MockTransport`, перевод —
двойником `TeacherClient`. Проверяем JSON-массив/JSONL, fallback на локальный
файл, перевод+классификацию, SeedRecord и EvalRecord (open-ended/MCQ).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from configs.prompts import get_prompts
from configs.settings import ProviderConfig
from data_pipeline.dataset_io import read_jsonl, write_jsonl
from data_pipeline.llm_client import ChatResult
from data_pipeline.petqa import (
    PETQA_TOPICS,
    PetQAError,
    RawPetQARecord,
    classify_topic,
    download_petqa_text,
    load_petqa_raw,
    parse_petqa_payload,
    parse_translation_content,
    petqa_benchmark_id,
    petqa_seed_id,
    to_benchmark_record,
    to_mcq_record,
    to_open_ended_record,
    to_seed_record,
)
from data_pipeline.schemas import SeedRecord
from evaluation.evaluate import load_eval_dataset
from evaluation.judge import build_criteria
from evaluation.schemas import MCQRecord, OpenEndedRecord
from scripts.generate_seeds import main as generate_main
from scripts.prepare_benchmark import main as benchmark_main
from scripts.prepare_petqa import main as petqa_main

TRANSLATED_QUESTION = "У кошки уже второй день сильно болит живот, что делать?"
TRANSLATED_ANSWER = (
    "Необходимо срочно показать кошку ветеринарному врачу: боль в животе может быть "
    "признаком опасного состояния."
)


def _raw_payload(q_id: int = 1, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "q_id": q_id,
        "a_id": 0,
        "question": "고양이의 배가 아파 보입니다. 어떻게 해야 하나요?",
        "gold_answer": "동물병원에 데려가세요.",
        "gold_question_type": None,
        "gold_disease": None,
        "animal_type": "cat",
    }
    payload.update(overrides)
    return payload


def _write_json_array(path: Path, payloads: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps(payloads, ensure_ascii=False), encoding="utf-8")
    return path


def _provider() -> ProviderConfig:
    return ProviderConfig(
        name="primary",
        api_key=SecretStr("sk-test"),
        base_url="http://127.0.0.1:1/v1",
        model="deepseek-flash",
        thinking_mode="deepseek",
    )


class _FakeTeacher:
    """Двойник TeacherClient: возвращает заранее заданный перевод."""

    def __init__(self, provider: ProviderConfig, **kwargs: Any) -> None:
        self.provider = provider
        self.kwargs = kwargs

    async def __aenter__(self) -> _FakeTeacher:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def chat(self, messages: Any, **kwargs: Any) -> ChatResult:
        return ChatResult(
            content=json.dumps(
                {
                    "question": TRANSLATED_QUESTION,
                    "answer": TRANSLATED_ANSWER,
                    "topic": "gastroenterology",
                },
                ensure_ascii=False,
            ),
            model="fake-translator",
            prompt_tokens=100,
            completion_tokens=80,
            total_tokens=180,
            latency_s=0.01,
            attempts=1,
        )


def test_parse_json_array_adds_split_and_validates() -> None:
    records = parse_petqa_payload([_raw_payload(1), _raw_payload(2)], split="train")

    assert [record.q_id for record in records] == [1, 2]
    assert all(record.split == "train" for record in records)
    assert records[0].animal_type == "cat"


def test_parse_single_object() -> None:
    record = parse_petqa_payload(_raw_payload(7))[0]

    assert isinstance(record, RawPetQARecord)
    assert record.q_id == 7


def test_parse_rejects_non_object() -> None:
    with pytest.raises(PetQAError, match="JSON-объектом"):
        parse_petqa_payload([["not", "a", "record"]])


def test_load_petqa_raw_supports_json_array_and_jsonl(tmp_path: Path) -> None:
    json_path = _write_json_array(tmp_path / "petqa.json", [_raw_payload(3)])
    jsonl_path = tmp_path / "petqa.jsonl"
    write_jsonl(jsonl_path, [dict(_raw_payload(4), split="test")])

    assert load_petqa_raw(json_path)[0].q_id == 3
    loaded = load_petqa_raw(jsonl_path)
    assert loaded[0].q_id == 4
    assert loaded[0].split == "test"


def test_download_falls_back_to_local_file(tmp_path: Path) -> None:
    local = tmp_path / "petqa_raw.jsonl"
    write_jsonl(local, [dict(_raw_payload(9), split="train")])

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, request=request)

    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    try:
        records = download_petqa_text(local, client=client)
    finally:
        client.close()

    assert [record.q_id for record in records] == [9]
    assert load_petqa_raw(local)[0].q_id == 9


def test_download_writes_all_splits(tmp_path: Path) -> None:
    destination = tmp_path / "petqa_raw.jsonl"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, request=request, json=[_raw_payload(42)])

    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    try:
        records = download_petqa_text(destination, client=client)
    finally:
        client.close()

    assert len(records) == 3
    assert {record.split for record in records} == {"train", "validation", "test"}
    assert len(load_petqa_raw(destination)) == 3


def test_download_without_local_file_reports_error(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, request=request)

    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    try:
        with pytest.raises(PetQAError, match="положите"):
            download_petqa_text(tmp_path / "absent.jsonl", client=client)
    finally:
        client.close()


def test_parse_translation_extracts_json_and_topic() -> None:
    translation = parse_translation_content(
        "```json\n"
        + json.dumps(
            {
                "question": TRANSLATED_QUESTION,
                "answer": TRANSLATED_ANSWER,
                "topic": "gastroenterology",
            },
            ensure_ascii=False,
        )
        + "\n```"
    )

    assert translation.question == TRANSLATED_QUESTION
    assert translation.answer == TRANSLATED_ANSWER
    assert translation.topic == "gastroenterology"


def test_parse_translation_falls_back_to_keyword_topic() -> None:
    translation = parse_translation_content(
        json.dumps(
            {
                "question": "У собаки начались судороги, нужна срочная помощь.",
                "answer": "",
                "topic": "unknown-topic",
            },
            ensure_ascii=False,
        )
    )

    assert translation.topic == "emergency"


def test_parse_translation_rejects_garbage() -> None:
    with pytest.raises(PetQAError, match="JSON"):
        parse_translation_content("это не JSON")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Кошка не ест, началась рвота", "gastroenterology"),
        ("У собаки зуд и сыпь на коже", "dermatology"),
        ("Кот выпил парацетамол", "toxicology"),
        ("Собака хромает на правую лапу", "orthopedics"),
        ("Кошка писает мимо лотка", "urology"),
        ("Начались судороги", "emergency"),
    ],
)
def test_classify_topic_keywords(text: str, expected: str) -> None:
    assert classify_topic(text) == expected


def test_translation_prompt_is_rendered() -> None:
    prompt = get_prompts().render_petqa_translate(
        question="질문",
        answer="ответ",
        topics=", ".join(PETQA_TOPICS),
    )

    assert "질문" in prompt
    assert "gastroenterology" in prompt
    assert "{" in prompt and "}" in prompt


def test_to_seed_record_and_ids() -> None:
    raw = RawPetQARecord.model_validate(_raw_payload(12, split="train"))
    translation = parse_translation_content(
        json.dumps(
            {
                "question": TRANSLATED_QUESTION,
                "answer": TRANSLATED_ANSWER,
                "topic": "gastroenterology",
            },
            ensure_ascii=False,
        )
    )

    seed = to_seed_record(raw, translation)

    assert isinstance(seed, SeedRecord)
    assert seed.id == petqa_seed_id(raw) == "petqa-00012"
    assert seed.topic == "gastroenterology"
    assert seed.seed_text == TRANSLATED_QUESTION


def test_to_open_ended_and_mcq_records() -> None:
    translation = parse_translation_content(
        json.dumps(
            {
                "question": TRANSLATED_QUESTION,
                "answer": TRANSLATED_ANSWER,
                "topic": "gastroenterology",
            },
            ensure_ascii=False,
        )
    )
    raw = RawPetQARecord.model_validate(
        {
            **_raw_payload(13, split="test", gold_question_type="diagnosis"),
            "gold_disease": "гастрит",
        }
    )
    raw_mcq = RawPetQARecord.model_validate(
        {
            **_raw_payload(14, split="test"),
            "options": ["A) Наблюдать", "B) К врачу", "C) Дать лекарство"],
            "correct_option": "B",
        }
    )

    open_ended = to_open_ended_record(raw, translation)
    mcq = to_mcq_record(raw_mcq, translation)

    assert isinstance(open_ended, OpenEndedRecord)
    assert open_ended.category == "open-ended"
    assert open_ended.id == petqa_benchmark_id(raw) == "petqa-bench-00013"
    assert open_ended.reference_answer == TRANSLATED_ANSWER
    assert open_ended.source_question_type == "diagnosis"
    assert open_ended.gold_disease == "гастрит"

    assert isinstance(mcq, MCQRecord)
    assert mcq.category == "mcq"
    assert mcq.correct_option == "B"
    assert isinstance(to_benchmark_record(raw_mcq, translation), MCQRecord)


def test_open_ended_record_can_be_loaded_and_judged() -> None:
    record = OpenEndedRecord(
        id="petqa-bench-00001",
        category="open-ended",
        topic="gastroenterology",
        question=TRANSLATED_QUESTION,
        reference_answer=TRANSLATED_ANSWER,
        animal_type="cat",
    )

    criteria = build_criteria(record)

    assert "Эталонный ответ" in criteria
    assert TRANSLATED_ANSWER in criteria


def test_open_ended_record_rejects_empty_answer() -> None:
    with pytest.raises(ValidationError):
        OpenEndedRecord(
            id="petqa-bench-00001",
            category="open-ended",
            topic="gastroenterology",
            question=TRANSLATED_QUESTION,
            reference_answer="",
        )


def test_prepare_petqa_script_mocks_teacher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_path = tmp_path / "petqa_raw.jsonl"
    write_jsonl(
        raw_path,
        [
            dict(_raw_payload(1), split="train"),
            dict(_raw_payload(2), split="validation"),
            dict(_raw_payload(3), split="test"),
        ],
    )
    output = tmp_path / "petqa_ru_questions.jsonl"
    monkeypatch.setattr("scripts.prepare_petqa.TeacherClient", _FakeTeacher)
    monkeypatch.setattr("scripts.prepare_petqa.get_provider", lambda name: _provider())

    exit_code = petqa_main(
        [
            "--no-download",
            "--raw-path",
            str(raw_path),
            "--output",
            str(output),
            "--concurrency",
            "2",
        ]
    )

    assert exit_code == 0
    records = [SeedRecord.model_validate(row) for row in read_jsonl(output)]
    assert sorted(record.id for record in records) == ["petqa-00001", "petqa-00002"]
    assert all(record.seed_text == TRANSLATED_QUESTION for record in records)


def test_prepare_benchmark_script_mocks_teacher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_path = tmp_path / "petqa_raw.jsonl"
    write_jsonl(
        raw_path,
        [
            dict(_raw_payload(1), split="test"),
            dict(
                _raw_payload(2),
                split="test",
                options=["A) Наблюдать", "B) К врачу", "C) Дать лекарство"],
                correct_option="B",
            ),
            dict(_raw_payload(3), split="train"),
        ],
    )
    output = tmp_path / "eval_dataset_petqa.jsonl"
    monkeypatch.setattr("scripts.prepare_benchmark.TeacherClient", _FakeTeacher)
    monkeypatch.setattr("scripts.prepare_benchmark.get_provider", lambda name: _provider())

    exit_code = benchmark_main(
        [
            "--no-download",
            "--raw-path",
            str(raw_path),
            "--output",
            str(output),
            "--concurrency",
            "2",
        ]
    )

    assert exit_code == 0
    records = load_eval_dataset(output)
    assert sorted(record.category for record in records) == ["mcq", "open-ended"]
    assert all(record.topic == "gastroenterology" for record in records)


def test_generate_seeds_source_petqa(tmp_path: Path) -> None:
    petqa_path = tmp_path / "petqa_ru_questions.jsonl"
    write_jsonl(
        petqa_path,
        [
            {
                "id": "petqa-00001",
                "topic": "gastroenterology",
                "seed_text": TRANSLATED_QUESTION,
            },
            {
                "id": "petqa-00002",
                "topic": "dermatology",
                "seed_text": "У собаки сильно чешется кожа, появилась сыпь и покраснение.",
            },
        ],
    )
    output = tmp_path / "seeds_petqa.jsonl"

    exit_code = generate_main(
        [
            "--source",
            "petqa",
            "--petqa-path",
            str(petqa_path),
            "--count",
            "1",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    records = [SeedRecord.model_validate(row) for row in read_jsonl(output)]
    assert [record.id for record in records] == ["petqa-00001"]


def test_generate_seeds_source_petqa_missing_file(tmp_path: Path) -> None:
    exit_code = generate_main(
        [
            "--source",
            "petqa",
            "--petqa-path",
            str(tmp_path / "absent.jsonl"),
            "--output",
            str(tmp_path / "out.jsonl"),
        ]
    )

    assert exit_code == 1
