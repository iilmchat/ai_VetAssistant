"""Pydantic-схемы записей датасета (T-003).

Схемы — единый контракт между генератором, скриптами и фильтрами:
каждая запись, попадающая в JSONL, проходит валидацию (RULES §4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class StageARecord(BaseModel):
    """Результат Шага A: вопрос владельца + метаданные запроса к учителю."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, description="id исходного сида")
    stage: Literal["A"] = "A"
    topic: Topic
    seed_text: str
    user_query: str = Field(min_length=1, description="Сгенерированный вопрос владельца")
    model: str = Field(min_length=1, description="Модель, фактически отдавшая ответ")
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    latency_s: float = Field(ge=0.0)
    attempts: int = Field(ge=1)
    prompts_version: int = Field(ge=1)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("user_query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        """Вопрос должен быть одной строкой: JSONL не любит сырые переводы строк."""
        if "\n" in value or "\r" in value:
            raise ValueError("user_query должен быть одной строкой")
        return value
