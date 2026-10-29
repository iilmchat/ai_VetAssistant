"""Загрузчик библиотеки промптов (T-003).

Промпты живут в `configs/prompts.yaml`, чтобы менять их без правки кода.
Загрузчик валидирует структуру через Pydantic и проверяет, что в шаблоне
есть все обязательные плейсхолдеры и нет опечаток в них.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Плейсхолдеры, которые обязаны присутствовать в шаблоне Шага A.
STAGE_A_PLACEHOLDERS: tuple[str, ...] = ("topic", "seed_text")

DEFAULT_PROMPTS_PATH = Path(__file__).resolve().parent / "prompts.yaml"

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class PromptError(ValueError):
    """Файл промптов отсутствует или не соответствует схеме."""


class StageAPrompt(BaseModel):
    """Шаблон Шага A: из seed-факта делает вопрос владельца животного."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    template: str = Field(min_length=1, description="Шаблон с {topic} и {seed_text}")

    @model_validator(mode="after")
    def _validate_placeholders(self) -> Self:
        used = set(_PLACEHOLDER_RE.findall(self.template))
        missing = [name for name in STAGE_A_PLACEHOLDERS if name not in used]
        if missing:
            raise ValueError(f"в шаблоне Шага A нет плейсхолдеров: {sorted(missing)}")
        unknown = sorted(used - set(STAGE_A_PLACEHOLDERS))
        if unknown:
            raise ValueError(f"неизвестные плейсхолдеры в шаблоне Шага A: {unknown}")
        return self

    def render(self, *, topic: str, seed_text: str) -> str:
        """Подставить данные сида в шаблон."""
        return self.template.format(topic=topic, seed_text=seed_text)


class PromptLibrary(BaseModel):
    """Корневой документ `prompts.yaml`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    stage_a: StageAPrompt


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

    def render_stage_a(self, *, topic: str, seed_text: str) -> str:
        """Собрать готовый промпт Шага A."""
        return self._library.stage_a.render(topic=topic, seed_text=seed_text)


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
