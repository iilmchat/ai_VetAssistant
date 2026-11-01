"""Импорт и конвертация PetQA (T-011).

Официальный репозиторий ``ssu-humane/PetQA`` содержит код, а текстовые данные
опубликованы на Hugging Face (``humane-lab/PetQA``), ссылка на который есть в
README репозитория. Загружаем только текстовую часть: train/validation для
сидов и test (PetQA-Bench) для бенчмарка.

Модуль не вызывает учителя сам: перевод выполняют скрипты через
`TeacherClient`, а здесь собраны парсинг сырого формата, классификация темы и
преобразование в `SeedRecord`/`EvalRecord`. Это позволяет тестировать всю
логику без сети.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast, get_args

import httpx2
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from configs.prompts import PromptRenderer
from configs.settings import PROJECT_ROOT
from data_pipeline.dataset_io import write_jsonl
from data_pipeline.llm_client import TeacherClient
from data_pipeline.schemas import SeedRecord, Topic
from evaluation.schemas import MCQRecord, OpenEndedRecord

#: Официальный GitHub-репозиторий (данные лежат на Hugging Face).
PETQA_REPO_URL = "https://github.com/ssu-humane/PetQA"
#: Прямые ссылки на текстовую часть официального датасета.
PETQA_DATA_BASE_URL = "https://huggingface.co/datasets/humane-lab/PetQA/resolve/main/data/TEXT_ONLY"
PETQA_SPLITS: tuple[Literal["train", "validation", "test"], ...] = (
    "train",
    "validation",
    "test",
)
PETQA_TOPICS: tuple[str, ...] = get_args(Topic)

DEFAULT_RAW_PATH = PROJECT_ROOT / "data" / "petqa_raw.jsonl"
DEFAULT_SEEDS_PATH = PROJECT_ROOT / "data" / "petqa_ru_questions.jsonl"
DEFAULT_BENCHMARK_PATH = PROJECT_ROOT / "data" / "eval_dataset_petqa.jsonl"

#: Тематическая эвристика на случай, если учитель вернул неизвестную тему.
_TOPIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "emergency",
        (
            "судорог",
            "кровотеч",
            "не дыш",
            "задыха",
            "без сознания",
            "экстрен",
            "травм",
            "срочно",
        ),
    ),
    (
        "toxicology",
        (
            "отрав",
            "яд",
            "токси",
            "шоколад",
            "парацетамол",
            "ибупрофен",
            "лекарств",
            "съел",
            "проглотил",
        ),
    ),
    (
        "ophthalmology",
        ("глаз", "зрен", "конъюнктив", "век", "слез", "роговиц"),
    ),
    (
        "urology",
        ("моч", "почк", "цистит", "лоток", "писает", "моче"),
    ),
    (
        "dermatology",
        ("кож", "зуд", "чеш", "шерст", "сыпь", "лишай", "блох", "ухо", "отит"),
    ),
    (
        "gastroenterology",
        ("живот", "рвот", "понос", "аппетит", "корм", "желуд", "кишеч", "печен", "запор"),
    ),
    (
        "orthopedics",
        ("лап", "хром", "сустав", "кост", "спин", "позвон", "перелом", "движ"),
    ),
    (
        "cardiology",
        ("сердц", "кашел", "одыш", "аритм", "обморок", "давлен"),
    ),
    (
        "endocrinology",
        ("гормон", "щитовид", "диабет", "сахар", "жажд", "ожирен", "надпочеч"),
    ),
    (
        "behavior",
        ("поведен", "агресс", "куса", "лай", "тревог", "страх", "метит", "стресс"),
    ),
)


class PetQAError(ValueError):
    """Ошибка загрузки/парсинга/конвертации PetQA."""


class RawPetQARecord(BaseModel):
    """Сырая запись PetQA (поля, нужные пайплайну).

    Официальные текстовые файлы — JSON-массивы; локальная заглушка может быть
    JSONL. ``split`` добавляется при загрузке, у локальных записей его может не
    быть — тогда запись считается потенциальным сидом.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    q_id: int = Field(ge=0)
    a_id: int = 0
    question: str = Field(min_length=1)
    gold_answer: str = ""
    gold_question_type: str | None = None
    gold_disease: str | None = None
    animal_type: str | None = None
    split: Literal["train", "validation", "test"] | None = None
    options: list[str] = Field(default_factory=list)
    correct_option: str | None = None
    #: Необязательные поля локальной заглушки, позволяющие не звать API.
    question_ru: str | None = None
    gold_answer_ru: str | None = None
    topic: str | None = None


@dataclass(frozen=True, slots=True)
class Translation:
    """Результат перевода одной записи PetQA."""

    question: str
    answer: str
    topic: Topic


def _as_record(payload: object, *, split: str | None = None) -> RawPetQARecord:
    if not isinstance(payload, Mapping):
        raise PetQAError("запись PetQA должна быть JSON-объектом")
    data = dict(payload)
    if split is not None and not data.get("split"):
        data["split"] = split
    try:
        return RawPetQARecord.model_validate(data)
    except ValidationError as exc:
        raise PetQAError(f"запись PetQA не прошла валидацию: {exc}") from exc


def parse_petqa_payload(
    payload: object,
    *,
    split: Literal["train", "validation", "test"] | None = None,
) -> list[RawPetQARecord]:
    """Разобрать JSON-массив, одиночный объект или список объектов PetQA."""
    if isinstance(payload, Mapping):
        return [_as_record(payload, split=split)]
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [_as_record(item, split=split) for item in payload]
    raise PetQAError("PetQA: ожидался JSON-массив объектов")


def load_petqa_raw(path: Path = DEFAULT_RAW_PATH) -> list[RawPetQARecord]:
    """Прочитать локальный ``petqa_raw.jsonl`` или JSON-массив."""
    if not path.exists():
        raise PetQAError(f"файл PetQA не найден: {path}")

    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise PetQAError(f"файл PetQA пуст: {path}")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Локальная заглушка обычно JSONL: по одному объекту на строку.
        records: list[RawPetQARecord] = []
        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PetQAError(f"{path}:{line_no}: битый JSON ({exc.msg})") from exc
            records.append(_as_record(item))
        if not records:
            raise PetQAError(f"файл PetQA пуст: {path}") from None
        return records

    return parse_petqa_payload(parsed)


def download_petqa_text(
    destination: Path = DEFAULT_RAW_PATH,
    *,
    timeout_s: float = 60.0,
    client: httpx2.Client | None = None,
) -> list[RawPetQARecord]:
    """Скачать текстовую часть PetQA и сохранить единый JSONL.

    GitHub-репозиторий PetQA не хранит датасет; данные опубликованы на
    Hugging Face и связаны из официального README. При сетевой ошибке, если
    ``destination`` уже существует, используется локальная заглушка.

    Raises:
        PetQAError: скачивание не удалось и локального файла нет.
    """
    owns_client = client is None
    http = client if client is not None else httpx2.Client(timeout=timeout_s, follow_redirects=True)
    records: list[RawPetQARecord] = []

    try:
        for split in PETQA_SPLITS:
            url = f"{PETQA_DATA_BASE_URL}/{split}.json"
            response = http.get(url)
            response.raise_for_status()
            records.extend(parse_petqa_payload(response.json(), split=split))
    except (httpx2.HTTPError, ValueError, PetQAError) as exc:
        if destination.exists():
            logger.warning(
                "PetQA: скачивание не удалось ({}); читаю локальный {}",
                exc,
                destination,
            )
            return load_petqa_raw(destination)
        raise PetQAError(
            f"не удалось скачать PetQA ({exc}); "
            f"положите текстовый JSONL в {destination} и запустите с --no-download"
        ) from exc
    finally:
        if owns_client:
            http.close()

    write_jsonl(destination, [record.model_dump(mode="json") for record in records])
    logger.info(
        "PetQA: скачано {} записей ({}); источник: {}",
        len(records),
        ", ".join(PETQA_SPLITS),
        PETQA_DATA_BASE_URL,
    )
    return records


def classify_topic(text: str, *, default: Topic = "behavior") -> Topic:
    """Определить тему по русским ключевым словам (fallback после учителя)."""
    lowered = text.lower()
    for topic, keywords in _TOPIC_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return cast(Topic, topic)
    return default


def _extract_json_object(content: str) -> Mapping[str, Any]:
    """Вытащить JSON-объект из ответа модели, допуская markdown-обёртку."""
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match is None:
            raise PetQAError("ответ переводчика не содержит JSON-объекта") from None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise PetQAError(f"ответ переводчика содержит битый JSON: {exc.msg}") from exc
    if not isinstance(payload, Mapping):
        raise PetQAError("ответ переводчика должен быть JSON-объектом")
    return payload


def parse_translation_content(content: str) -> Translation:
    """Разобрать ответ ``petqa_translate`` с переводом и темой."""
    payload = _extract_json_object(content)
    question = payload.get("question") or payload.get("translation")
    if not isinstance(question, str) or not question.strip():
        raise PetQAError("переводчик не вернул поле question")

    answer = payload.get("answer") or payload.get("gold_answer") or ""
    if not isinstance(answer, str):
        raise PetQAError("поле answer перевода должно быть строкой")

    raw_topic = payload.get("topic")
    topic: Topic = (
        cast(Topic, raw_topic)
        if isinstance(raw_topic, str) and raw_topic in PETQA_TOPICS
        else classify_topic(question)
    )
    return Translation(question=question.strip(), answer=answer.strip(), topic=topic)


async def translate_raw_record(
    client: TeacherClient,
    prompts: PromptRenderer,
    raw: RawPetQARecord,
    *,
    max_tokens: int = 1024,
) -> Translation:
    """Перевести одну запись через учителя; сеть/парсинг — на вызывающем."""
    if raw.question_ru is not None and raw.question_ru.strip():
        answer = raw.gold_answer_ru or ""
        topic = (
            cast(Topic, raw.topic) if raw.topic in PETQA_TOPICS else classify_topic(raw.question_ru)
        )
        return Translation(question=raw.question_ru.strip(), answer=answer.strip(), topic=topic)

    prompt = prompts.render_petqa_translate(
        question=raw.question,
        answer=raw.gold_answer,
        topics=", ".join(PETQA_TOPICS),
    )
    result = await client.chat(
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    return parse_translation_content(result.content)


def petqa_seed_id(raw: RawPetQARecord) -> str:
    """Стабильный id сида, совместимый с префиксами пайплайна."""
    return f"petqa-{raw.q_id:05d}"


def petqa_benchmark_id(raw: RawPetQARecord) -> str:
    """Стабильный id benchmark-записи."""
    return f"petqa-bench-{raw.q_id:05d}"


def to_seed_record(raw: RawPetQARecord, translation: Translation) -> SeedRecord:
    """Преобразовать переведённый вопрос в `SeedRecord`."""
    return SeedRecord(
        id=petqa_seed_id(raw),
        topic=translation.topic,
        seed_text=translation.question,
    )


def to_open_ended_record(raw: RawPetQARecord, translation: Translation) -> OpenEndedRecord:
    """Преобразовать запись PetQA-Bench в `OpenEndedRecord`."""
    answer = translation.answer.strip() or raw.gold_answer.strip()
    if not answer:
        raise PetQAError(f"PetQA q_id={raw.q_id}: отсутствует эталонный ответ")

    animal: Literal["dog", "cat"] | None = None
    if raw.animal_type in ("dog", "cat"):
        animal = cast(Literal["dog", "cat"], raw.animal_type)

    return OpenEndedRecord(
        id=petqa_benchmark_id(raw),
        category="open-ended",
        topic=translation.topic,
        question=translation.question,
        reference_answer=answer,
        animal_type=animal,
        source_question_type=raw.gold_question_type,
        gold_disease=raw.gold_disease,
    )


def to_mcq_record(raw: RawPetQARecord, translation: Translation) -> MCQRecord:
    """Преобразовать запись с готовыми options/correct_option в MCQ.

    Официальный PetQA-Bench не содержит вариантов ответа, поэтому для него
    используется ветка ``open-ended``. Ветка MCQ нужна для локальных
    расширений/заглушек, где варианты уже добавлены в исходный JSONL.
    """
    if not raw.options or not raw.correct_option:
        raise PetQAError(f"PetQA q_id={raw.q_id}: нет options/correct_option для MCQ")

    explanation = translation.answer.strip() or raw.gold_answer.strip()
    if not explanation:
        raise PetQAError(f"PetQA q_id={raw.q_id}: нет объяснения для MCQ")
    return MCQRecord(
        id=petqa_benchmark_id(raw),
        category="mcq",
        topic=translation.topic,
        question=translation.question,
        options=list(raw.options),
        correct_option=raw.correct_option,
        explanation=explanation,
    )


def to_benchmark_record(
    raw: RawPetQARecord,
    translation: Translation,
) -> MCQRecord | OpenEndedRecord:
    """Выбрать формат benchmark-записи по наличию вариантов ответа."""
    if raw.options and raw.correct_option:
        return to_mcq_record(raw, translation)
    return to_open_ended_record(raw, translation)
