"""Генераторы Шагов A, B и Safety-блока (T-003, T-004, T-005)."""

from __future__ import annotations

import json
from typing import Any, Literal

from loguru import logger
from pydantic import ValidationError

from configs.prompts import PromptRenderer, get_prompts
from data_pipeline.llm_client import ChatResult, TeacherClient
from data_pipeline.schemas import (
    DialogueRecord,
    Message,
    StageARecord,
    Topic,
)

#: Пары кавычек, которые модель иногда добавляет вопреки промпту.
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ('"', '"'),
    ("«", "»"),
    ("'", "'"),
    ("“", "”"),
)


class GenerationError(RuntimeError):
    """Учитель вернул пустой, битый или структурно невалидный результат."""


def _normalize(text: str) -> str:
    """Нормализовать текст для сравнения (пробелы, регистр)."""
    return " ".join(text.split()).casefold()


def _describe_validation_error(exc: ValidationError) -> str:
    """Коротко перечислить, какие поля не прошли валидацию."""
    details = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "?"
        details.append(f"{location}: {error['msg']}")
    return "; ".join(details)


def clean_query(text: str) -> str:
    """Нормализовать ответ модели: одна строка, без внешних кавычек."""
    collapsed = " ".join(text.split())
    for left, right in _QUOTE_PAIRS:
        if len(collapsed) >= 2 and collapsed.startswith(left) and collapsed.endswith(right):
            return collapsed[1:-1].strip()
    return collapsed


def _strip_code_fence(text: str) -> str:
    """Убрать обёртку ```json ... ```, которую модели добавляют вопреки промпту."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_dialogue_json(text: str) -> list[Any]:
    """Извлечь JSON-массив сообщений из ответа учителя.

    Терпим к типичным вольностям модели: markdown-обёртке, пояснениям до/после
    JSON и обёртке вида ``{"messages": [...]}``.

    Raises:
        GenerationError: JSON не найден или не является массивом сообщений.
    """
    cleaned = _strip_code_fence(text)
    candidates: list[str] = [cleaned]

    start, end = cleaned.find("["), cleaned.rfind("]")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])

    for candidate in candidates:
        try:
            payload: Any = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            return list(payload)
        if isinstance(payload, dict):
            wrapped = payload.get("messages")
            if isinstance(wrapped, list):
                return list(wrapped)

    snippet = " ".join(cleaned.split())[:200]
    raise GenerationError(f"ответ учителя не содержит JSON-массива сообщений: {snippet!r}")


def _build_dialogue_record(
    raw_messages: list[Any],
    *,
    record_id: str,
    topic: Topic,
    stage: Literal["B", "safety"],
    result: ChatResult,
    prompts_version: int,
) -> DialogueRecord:
    """Собрать и провалидировать `DialogueRecord` из сырых реплик.

    Raises:
        GenerationError: реплики или структура диалога не прошли схему.
    """
    try:
        messages = [Message.model_validate(item) for item in raw_messages]
        return DialogueRecord(
            id=record_id,
            stage=stage,
            topic=topic,
            messages=messages,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            latency_s=result.latency_s,
            attempts=result.attempts,
            prompts_version=prompts_version,
        )
    except ValidationError as exc:
        raise GenerationError(
            f"диалог для {record_id!r} не прошёл валидацию: {_describe_validation_error(exc)}"
        ) from exc


class StageAGenerator:
    """Генерирует «сырые» вопросы владельцев из фактов справочника.

    Пример::

        generator = StageAGenerator(client)
        record = await generator.generate_query(topic, seed_text, seed_id="seed-msd-001")
    """

    def __init__(
        self,
        client: TeacherClient,
        *,
        prompts: PromptRenderer | None = None,
        temperature: float = 0.9,
        max_tokens: int = 2048,
    ) -> None:
        """Создать генератор.

        Args:
            client: клиент учителя (T-002).
            prompts: библиотека промптов; по умолчанию — `configs/prompts.yaml`.
            temperature: высокая температура нужна для разнообразия формулировок.
            max_tokens: вопрос короткий, но reasoning-модели тратят токены на
                скрытые рассуждения — 2048 даёт запас.
        """
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature должна быть в диапазоне 0..2")
        if max_tokens < 1:
            raise ValueError("max_tokens должен быть >= 1")

        self._client = client
        self._prompts = prompts if prompts is not None else get_prompts()
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def prompts_version(self) -> int:
        """Версия библиотеки промптов (попадает в метаданные записи)."""
        return self._prompts.version

    async def generate_query(
        self,
        topic: Topic,
        seed_text: str,
        *,
        seed_id: str,
    ) -> StageARecord:
        """Сгенерировать вопрос владельца по факту из справочника.

        Args:
            topic: тема из таксономии.
            seed_text: факт из MSD Vet Manual.
            seed_id: id сида — попадает в запись и используется `--resume`.

        Raises:
            GenerationError: модель вернула пустой ответ.
            openai.OpenAIError: ошибка API (после исчерпания ретраев).
        """
        prompt = self._prompts.render_stage_a(topic=topic, seed_text=seed_text)
        logger.debug("Шаг A: seed={} topic={} промпт={} символов", seed_id, topic, len(prompt))

        result = await self._client.chat(
            [{"role": "user", "content": prompt}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )

        query = clean_query(result.content)
        if not query:
            raise GenerationError(f"пустой вопрос владельца для сида {seed_id!r}")

        return StageARecord(
            id=seed_id,
            topic=topic,
            seed_text=seed_text,
            user_query=query,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            latency_s=result.latency_s,
            attempts=result.attempts,
            prompts_version=self.prompts_version,
        )


class StageBGenerator:
    """Разворачивает вопрос владельца в многотурный диалог с ассистентом.

    Пример::

        generator = StageBGenerator(client)
        record = await generator.generate_dialogue(query, topic, seed_id="seed-msd-001")
    """

    def __init__(
        self,
        client: TeacherClient,
        *,
        prompts: PromptRenderer | None = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> None:
        """Создать генератор.

        Args:
            client: клиент учителя (T-002).
            prompts: библиотека промптов; по умолчанию — `configs/prompts.yaml`.
            temperature: диалог должен быть реалистичным, но не хаотичным.
            max_tokens: 4–8 реплик + запас на reasoning-токены модели.
        """
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature должна быть в диапазоне 0..2")
        if max_tokens < 1:
            raise ValueError("max_tokens должен быть >= 1")

        self._client = client
        self._prompts = prompts if prompts is not None else get_prompts()
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def prompts_version(self) -> int:
        """Версия библиотеки промптов (попадает в метаданные записи)."""
        return self._prompts.version

    async def generate_dialogue(
        self,
        user_query: str,
        topic: Topic,
        *,
        seed_id: str,
    ) -> DialogueRecord:
        """Сгенерировать многотурный диалог по стартовому вопросу.

        Args:
            user_query: вопрос владельца из Шага A.
            topic: тема из таксономии.
            seed_id: id исходного сида.

        Raises:
            GenerationError: ответ не является JSON-массивом, реплики не прошли
                схему или нарушена структура диалога (роли, длина).
            openai.OpenAIError: ошибка API (после исчерпания ретраев).
        """
        prompt = self._prompts.render_stage_b(topic=topic, user_query=user_query)
        logger.debug("Шаг B: seed={} topic={} промпт={} символов", seed_id, topic, len(prompt))

        result = await self._client.chat(
            [{"role": "user", "content": prompt}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )

        raw_messages = parse_dialogue_json(result.content)
        record = _build_dialogue_record(
            raw_messages,
            record_id=seed_id,
            topic=topic,
            stage="B",
            result=result,
            prompts_version=self.prompts_version,
        )

        if _normalize(record.messages[0].content) != _normalize(user_query):
            logger.debug(
                "Шаг B: первый вопрос диалога отличается от вопроса Шага A (seed={})", seed_id
            )

        return record


class StageSafetyGenerator:
    """Генерирует провокационные диалоги для проверки Safety-правил.

    Владелец пытается вынудить ассистента нарушить правила (дозировка
    человеческого препарата, диагноз без осмотра, «домашнее средство»
    вместо неотложной помощи), а ассистент должен отказать и эскалировать.

    Пример::

        generator = StageSafetyGenerator(client)
        record = await generator.generate_case("toxicology", case_id="safety-seed-msd-003")
    """

    def __init__(
        self,
        client: TeacherClient,
        *,
        prompts: PromptRenderer | None = None,
        temperature: float = 0.8,
        max_tokens: int = 8192,
    ) -> None:
        """Создать генератор.

        Args:
            client: клиент учителя (T-002).
            prompts: библиотека промптов; по умолчанию — `configs/prompts.yaml`.
            temperature: провокации должны быть разнообразными, но связными.
            max_tokens: 4–8 реплик + запас на reasoning-токены модели.
        """
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature должна быть в диапазоне 0..2")
        if max_tokens < 1:
            raise ValueError("max_tokens должен быть >= 1")

        self._client = client
        self._prompts = prompts if prompts is not None else get_prompts()
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def prompts_version(self) -> int:
        """Версия библиотеки промптов (попадает в метаданные записи)."""
        return self._prompts.version

    async def generate_case(self, topic: Topic, *, case_id: str) -> DialogueRecord:
        """Сгенерировать Safety-кейс по теме.

        Args:
            topic: тема из таксономии.
            case_id: id кейса (используется `--resume` и попадает в запись).

        Raises:
            GenerationError: ответ не является JSON-массивом, реплики не прошли
                схему или нарушена структура диалога (роли, длина).
            openai.OpenAIError: ошибка API (после исчерпания ретраев).
        """
        prompt = self._prompts.render_safety(topic=topic)
        logger.debug("Safety: id={} topic={} промпт={} символов", case_id, topic, len(prompt))

        result = await self._client.chat(
            [{"role": "user", "content": prompt}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )

        raw_messages = parse_dialogue_json(result.content)
        return _build_dialogue_record(
            raw_messages,
            record_id=case_id,
            topic=topic,
            stage="safety",
            result=result,
            prompts_version=self.prompts_version,
        )
