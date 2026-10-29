"""Pydantic-схемы eval-датасета (T-006).

Формат описан в `docs/eval_harness.md` §1:

* `mcq` — вопрос с вариантами и эталонной буквой;
* `safety` — провокационный запрос с критериями отказа/эскалации;
* `multi_turn` — контекст диалога, который модель должна продолжить.

`EvalRecord` — discriminated union по полю `category`: Pydantic сам выбирает
нужную модель при парсинге JSONL.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from data_pipeline.schemas import Message, Topic

#: Префикс варианта ответа: «A) ...», «B. ...», «C: ...».
_OPTION_PREFIX_RE = re.compile(r"^([A-Z])[).:]\s+")


class _EvalBase(BaseModel):
    """Общие поля всех eval-записей."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, description="Уникальный id записи")
    category: str
    topic: Topic

    @field_validator("id")
    @classmethod
    def _strip_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("id не может быть пустым")
        return stripped


class MCQRecord(_EvalBase):
    """Вопрос с вариантами ответа: метрика MCQ Accuracy."""

    category: Literal["mcq"]
    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=2, max_length=6)
    correct_option: str = Field(pattern=r"^[A-Z]$")
    explanation: str = Field(min_length=1)

    @field_validator("question", "explanation")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("текстовое поле не может быть пустым")
        return stripped

    @field_validator("options")
    @classmethod
    def _strip_options(cls, options: list[str]) -> list[str]:
        if any(not option.strip() for option in options):
            raise ValueError("вариант ответа не может быть пустым")
        return options

    @model_validator(mode="after")
    def _validate_options(self) -> Self:
        """Если варианты пронумерованы, `correct_option` должен быть среди них."""
        letters = [
            match.group(1)
            for option in self.options
            if (match := _OPTION_PREFIX_RE.match(option)) is not None
        ]
        if not letters:
            return self

        duplicates = sorted({letter for letter in letters if letters.count(letter) > 1})
        if duplicates:
            raise ValueError(f"повторяющиеся буквы вариантов: {duplicates}")
        if self.correct_option not in letters:
            raise ValueError(
                f"correct_option={self.correct_option!r} отсутствует среди вариантов {letters}"
            )
        return self


class SafetyRecord(_EvalBase):
    """Провокационный запрос: метрика Safety Pass Rate."""

    category: Literal["safety"]
    prompt: str = Field(min_length=1)
    must_refuse: bool
    must_escalate: bool
    forbidden_keywords: list[str]
    judge_criteria: str = Field(min_length=1)

    @field_validator("prompt", "judge_criteria")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("текстовое поле не может быть пустым")
        return stripped

    @field_validator("forbidden_keywords")
    @classmethod
    def _strip_keywords(cls, keywords: list[str]) -> list[str]:
        cleaned = [keyword.strip() for keyword in keywords]
        if any(not keyword for keyword in cleaned):
            raise ValueError("forbidden_keywords не должен содержать пустых строк")
        return cleaned


class MultiTurnRecord(_EvalBase):
    """Контекст диалога: метрика Multi-turn Consistency."""

    category: Literal["multi_turn"]
    messages: list[Message] = Field(min_length=2)
    expected_next_action: str = Field(min_length=1)
    judge_criteria: str = Field(min_length=1)

    @field_validator("expected_next_action", "judge_criteria")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("текстовое поле не может быть пустым")
        return stripped


#: Дискриминированный union: Pydantic выбирает модель по полю `category`.
EvalRecord = Annotated[
    MCQRecord | SafetyRecord | MultiTurnRecord,
    Field(discriminator="category"),
]


class ModelAnswer(BaseModel):
    """Ответ модели из `model_answers.jsonl`.

    Для MCQ `answer` — выбранная буква (сравнивается точно), для Safety и
    Multi-turn — свободный текст ответа (пригодится в T-007 для LLM-Judge).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    answer: str = Field(min_length=1)

    @field_validator("id", "answer")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("значение не может быть пустым")
        return stripped
