"""Загрузчик библиотеки промптов (T-003, T-004, T-005).

Промпты живут в `configs/prompts.yaml`, чтобы менять их без правки кода.
Подстановка значений — через :class:`string.Template` (`$name`), а не
`str.format`: шаблоны Шага B и Safety содержат JSON-пример с фигурными
скобками, который `format` попытался бы интерпретировать.

Загрузчик валидирует структуру через Pydantic и проверяет, что в шаблоне
есть все обязательные плейсхолдеры и нет опечаток в них.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template
from typing import ClassVar, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Плейсхолдеры, которые обязаны присутствовать в шаблоне Шага A.
STAGE_A_PLACEHOLDERS: tuple[str, ...] = ("topic", "seed_text")

#: Плейсхолдеры, которые обязаны присутствовать в шаблоне Шага B.
STAGE_B_PLACEHOLDERS: tuple[str, ...] = ("topic", "user_query")

#: Плейсхолдеры, которые обязаны присутствовать в Safety-шаблоне.
STAGE_SAFETY_PLACEHOLDERS: tuple[str, ...] = ("topic",)

#: Плейсхолдеры, которые обязаны присутствовать в шаблоне судьи.
JUDGE_PLACEHOLDERS: tuple[str, ...] = ("criteria", "response")

DEFAULT_PROMPTS_PATH = Path(__file__).resolve().parent / "prompts.yaml"


class PromptError(ValueError):
    """Файл промптов отсутствует или не соответствует схеме."""


def _validate_template(step: str, template: str, required: tuple[str, ...]) -> None:
    """Проверить синтаксис `string.Template` и набор плейсхолдеров."""
    parsed = Template(template)
    used = set(parsed.get_identifiers())

    missing = [name for name in required if name not in used]
    if missing:
        raise ValueError(f"в шаблоне {step} нет плейсхолдеров: {missing}")

    unknown = sorted(used - set(required))
    if unknown:
        raise ValueError(f"неизвестные плейсхолдеры в шаблоне {step}: {unknown}")

    # Ловит синтаксические ошибки вроде одиночного '$' в конце строки.
    try:
        parsed.substitute(dict.fromkeys(required, ""))
    except (KeyError, ValueError) as exc:
        raise ValueError(f"некорректный синтаксис шаблона {step}: {exc}") from exc


class StagePrompt(BaseModel):
    """Базовый шаблон одного шага генерации."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    template: str = Field(min_length=1)

    required_placeholders: ClassVar[tuple[str, ...]] = ()
    step_name: ClassVar[str] = "?"

    @model_validator(mode="after")
    def _validate_placeholders(self) -> Self:
        _validate_template(self.step_name, self.template, self.required_placeholders)
        return self


class StageAPrompt(StagePrompt):
    """Шаблон Шага A: из seed-факта делает вопрос владельца животного."""

    required_placeholders: ClassVar[tuple[str, ...]] = STAGE_A_PLACEHOLDERS
    step_name: ClassVar[str] = "Шага A"

    def render(self, *, topic: str, seed_text: str) -> str:
        """Подставить данные сида в шаблон."""
        return Template(self.template).substitute(topic=topic, seed_text=seed_text)


class StageBPrompt(StagePrompt):
    """Шаблон Шага B: из вопроса владельца делает многотурный диалог."""

    required_placeholders: ClassVar[tuple[str, ...]] = STAGE_B_PLACEHOLDERS
    step_name: ClassVar[str] = "Шага B"

    def render(self, *, topic: str, user_query: str) -> str:
        """Подставить стартовый вопрос и тему в шаблон."""
        return Template(self.template).substitute(topic=topic, user_query=user_query)


class StageSafetyPrompt(StagePrompt):
    """Шаблон Safety-блока: провокационный диалог про нарушение правил."""

    required_placeholders: ClassVar[tuple[str, ...]] = STAGE_SAFETY_PLACEHOLDERS
    step_name: ClassVar[str] = "Safety"

    def render(self, *, topic: str) -> str:
        """Подставить тему кейса в шаблон."""
        return Template(self.template).substitute(topic=topic)


class StageJudgePrompt(StagePrompt):
    """Шаблон LLM-Judge: рубрика + ответ ассистента -> JSON с оценкой."""

    required_placeholders: ClassVar[tuple[str, ...]] = JUDGE_PLACEHOLDERS
    step_name: ClassVar[str] = "судьи"

    def render(self, *, criteria: str, response: str) -> str:
        """Подставить критерий и ответ ассистента в шаблон судьи."""
        return Template(self.template).substitute(criteria=criteria, response=response)


class PromptLibrary(BaseModel):
    """Корневой документ `prompts.yaml`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    stage_a: StageAPrompt
    stage_b: StageBPrompt
    stage_safety: StageSafetyPrompt
    stage_judge: StageJudgePrompt


class PromptRenderer:
    """Удобный фасад: доступ к шаблонам и их рендеринг."""

    def __init__(self, library: PromptLibrary) -> None:
        self._library = library

    @property
    def version(self) -> int:
        """Версия библиотеки промптов (пишется в метаданные датасета)."""
        return self._library.version

    @property
    def stage_a(self) -> StageAPrompt:
        """Шаблон Шага A."""
        return self._library.stage_a

    @property
    def stage_b(self) -> StageBPrompt:
        """Шаблон Шага B."""
        return self._library.stage_b

    @property
    def stage_safety(self) -> StageSafetyPrompt:
        """Шаблон Safety-блока."""
        return self._library.stage_safety

    @property
    def stage_judge(self) -> StageJudgePrompt:
        """Шаблон LLM-Judge."""
        return self._library.stage_judge

    def render_stage_a(self, *, topic: str, seed_text: str) -> str:
        """Собрать готовый промпт Шага A."""
        return self._library.stage_a.render(topic=topic, seed_text=seed_text)

    def render_stage_b(self, *, topic: str, user_query: str) -> str:
        """Собрать готовый промпт Шага B."""
        return self._library.stage_b.render(topic=topic, user_query=user_query)

    def render_safety(self, *, topic: str) -> str:
        """Собрать готовый промпт Safety-блока."""
        return self._library.stage_safety.render(topic=topic)

    def render_judge(self, *, criteria: str, response: str) -> str:
        """Собрать готовый промпт судьи."""
        return self._library.stage_judge.render(criteria=criteria, response=response)


def load_prompts(path: Path | None = None) -> PromptRenderer:
    """Прочитать и провалидировать библиотеку промптов.

    Raises:
        PromptError: файл не найден, не является YAML-объектом или не проходит схему.
    """
    prompts_path = path if path is not None else DEFAULT_PROMPTS_PATH
    try:
        raw_text = prompts_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PromptError(f"файл промптов не найден: {prompts_path}") from exc

    try:
        raw: object = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise PromptError(f"некорректный YAML в {prompts_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise PromptError(f"{prompts_path}: ожидался YAML-объект на верхнем уровне")

    try:
        library = PromptLibrary.model_validate(raw)
    except ValueError as exc:
        raise PromptError(f"{prompts_path}: {exc}") from exc

    return PromptRenderer(library)


@lru_cache(maxsize=4)
def get_prompts(path: Path | None = None) -> PromptRenderer:
    """Кешированный доступ к промптам (файл читается один раз на процесс)."""
    return load_prompts(path)
