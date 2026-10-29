"""Pydantic-схемы записей датасета (T-003, T-004).

Схемы — единый контракт между генераторами, скриптами и фильтрами:
каждая запись, попадающая в JSONL, проходит валидацию (RULES §4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Тематическая таксономия v1 (Design §3.2). Расширяется по мере роста сидов.
Topic = Literal[
    "gastroenterology",
    "dermatology",
    "toxicology",
    "urology",
    "ophthalmology",
    "emergency",
    "behavior",
    "orthopedics",
    "cardiology",
    "endocrinology",
]

#: Границы длины диалога Шага B (synthetic_prompts.md: «от 4 до 8 сообщений»).
MIN_DIALOGUE_MESSAGES = 4
MAX_DIALOGUE_MESSAGES = 8


class SeedRecord(BaseModel):
    """Сид: факт из справочника, из которого генерируется вопрос владельца."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, description="Уникальный идентификатор сида")
    topic: Topic = Field(description="Тема из таксономии")
    seed_text: str = Field(min_length=20, description="Факт из MSD Vet Manual, 1–2 предложения")

    @field_validator("id", "seed_text")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("значение не может быть пустым")
        return stripped


class LLMMetadata(BaseModel):
    """Метаданные запроса к учителю — общие для всех шагов."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1, description="Модель, фактически отдавшая ответ")
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    latency_s: float = Field(ge=0.0)
    attempts: int = Field(ge=1)
    prompts_version: int = Field(ge=1, description="Версия configs/prompts.yaml")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StageARecord(LLMMetadata):
    """Результат Шага A: вопрос владельца + метаданные запроса к учителю."""

    id: str = Field(min_length=1, description="id исходного сида")
    stage: Literal["A"] = "A"
    topic: Topic
    seed_text: str
    user_query: str = Field(min_length=1, description="Сгенерированный вопрос владельца")

    @field_validator("user_query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        """Вопрос должен быть одной строкой: JSONL не любит сырые переводы строк."""
        if "\n" in value or "\r" in value:
            raise ValueError("user_query должен быть одной строкой")
        return value


class Message(BaseModel):
    """Реплика диалога. Системные сообщения в датасет не попадают."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content не может быть пустым")
        return stripped


class DialogueRecord(LLMMetadata):
    """Многотурный диалог владельца и ассистента.

    ``stage`` различает источник: ``"B"`` — обычный кейс из сидов,
    ``"safety"`` — провокационный кейс Safety-блока.
    """

    id: str = Field(min_length=1, description="id исходного сида (совпадает с Шагом A)")
    stage: Literal["B", "safety"] = "B"
    topic: Topic
    messages: list[Message] = Field(
        min_length=MIN_DIALOGUE_MESSAGES, max_length=MAX_DIALOGUE_MESSAGES
    )

    @model_validator(mode="after")
    def _validate_dialogue(self) -> Self:
        """Проверить структуру диалога: старт, финал и чередование ролей."""
        if not MIN_DIALOGUE_MESSAGES <= len(self.messages) <= MAX_DIALOGUE_MESSAGES:
            raise ValueError(
                f"диалог должен содержать {MIN_DIALOGUE_MESSAGES}–{MAX_DIALOGUE_MESSAGES} "
                f"сообщений, а не {len(self.messages)}"
            )
        if self.messages[0].role != "user":
            raise ValueError("первое сообщение диалога должно быть от user")
        if self.messages[-1].role != "assistant":
            raise ValueError("последнее сообщение диалога должно быть от assistant")

        for index, (current, following) in enumerate(
            zip(self.messages, self.messages[1:], strict=False), start=1
        ):
            if current.role == following.role:
                raise ValueError(
                    f"роли не чередуются: сообщения {index} и {index + 1} обе от {current.role}"
                )
        return self

    @property
    def turns(self) -> int:
        """Количество полных пар «вопрос владельца — ответ ассистента»."""
        return len(self.messages) // 2
