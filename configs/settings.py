"""Типизированные настройки из `.env` (RULES §3: только pydantic-settings).

Провайдеры учителя описываются независимыми наборами переменных:
``TEACHER_PRIMARY_*`` (обязательный) и ``TEACHER_FALLBACK_*`` (опциональный).
`Settings.provider(name)` собирает неизменяемый :class:`ProviderConfig`,
который передаётся в `TeacherClient` через dependency injection — сам клиент
глобальные настройки не читает.

`os.getenv` в остальном коде запрещён: только `get_settings()`/`get_provider()`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень репозитория: конфиг не зависит от текущего каталога запуска скрипта.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Имена провайдеров, между которыми можно переключаться.
ProviderName = Literal["primary", "fallback"]
PROVIDER_NAMES: tuple[ProviderName, ...] = ("primary", "fallback")

#: Обязательные переменные primary-провайдера (см. `.env.example`).
#: Модель не входит в список: у неё есть дефолт `deepseek-chat`.
REQUIRED_ENV_VARS: tuple[str, ...] = (
    "TEACHER_PRIMARY_API_KEY",
    "TEACHER_PRIMARY_BASE_URL",
)

#: Модель primary-провайдера по умолчанию (без reasoning-режима — для bulk).
DEFAULT_PRIMARY_MODEL = "deepseek-chat"

#: Переменные fallback-провайдера; нужны только при `--provider fallback`.
FALLBACK_ENV_VARS: tuple[str, ...] = (
    "TEACHER_FALLBACK_API_KEY",
    "TEACHER_FALLBACK_BASE_URL",
    "TEACHER_FALLBACK_MODEL",
)


class ProviderNotConfiguredError(ValueError):
    """Запрошенный провайдер не сконфигурирован в `.env`."""


class ProviderConfig(BaseModel):
    """Неизменяемая конфигурация одного OpenAI-совместимого провайдера."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: ProviderName
    api_key: SecretStr = Field(min_length=1, description="API-ключ (не попадает в repr)")
    base_url: str = Field(min_length=1, description="Базовый URL, обычно .../v1")
    model: str = Field(min_length=1, description="Идентификатор модели")


class Settings(BaseSettings):
    """Настройки доступа к провайдерам учителя.

    Имена полей автоматически мапятся на переменные окружения в верхнем
    регистре (``teacher_primary_api_key`` <-> ``TEACHER_PRIMARY_API_KEY``).
    """

    model_config = SettingsConfigDict(
        # Сначала `.env` в рабочем каталоге, затем `.env` в корне репозитория.
        env_file=(".env", str(PROJECT_ROOT / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    teacher_primary_api_key: SecretStr = Field(
        min_length=1, description="API-ключ primary-провайдера"
    )
    teacher_primary_base_url: str = Field(
        min_length=1, description="Базовый URL primary-провайдера"
    )
    teacher_primary_model: str = Field(
        default=DEFAULT_PRIMARY_MODEL,
        min_length=1,
        description="Модель primary-провайдера (по умолчанию deepseek-chat)",
    )

    teacher_fallback_api_key: SecretStr | None = Field(
        default=None, description="API-ключ fallback-провайдера (опционально)"
    )
    teacher_fallback_base_url: str | None = Field(
        default=None, description="Базовый URL fallback-провайдера (опционально)"
    )
    teacher_fallback_model: str | None = Field(
        default=None, description="Модель fallback-провайдера (опционально)"
    )

    def provider(self, name: ProviderName = "primary") -> ProviderConfig:
        """Собрать конфигурацию провайдера по имени.

        Raises:
            ProviderNotConfiguredError: для fallback заданы не все переменные.
        """
        if name == "primary":
            return ProviderConfig(
                name="primary",
                api_key=self.teacher_primary_api_key,
                base_url=self.teacher_primary_base_url,
                model=self.teacher_primary_model,
            )

        if name != "fallback":  # pragma: no cover - защита от вызова из нетипизированного кода
            raise ValueError(f"неизвестный провайдер: {name!r}")

        api_key = self.teacher_fallback_api_key
        base_url = self.teacher_fallback_base_url
        model = self.teacher_fallback_model

        missing: list[str] = []
        if api_key is None or not api_key.get_secret_value().strip():
            missing.append("TEACHER_FALLBACK_API_KEY")
        if base_url is None or not base_url.strip():
            missing.append("TEACHER_FALLBACK_BASE_URL")
        if model is None or not model.strip():
            missing.append("TEACHER_FALLBACK_MODEL")

        if missing:
            raise ProviderNotConfiguredError(
                "fallback-провайдер не настроен: не хватает " + ", ".join(missing)
            )

        assert api_key is not None  # сужено проверкой выше, нужно для mypy
        assert base_url is not None
        assert model is not None
        return ProviderConfig(
            name="fallback",
            api_key=api_key,
            base_url=base_url,
            model=model,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Вернуть настройки (кешируются на процесс).

    Падает с `ValidationError`, если `.env` не заполнен — это осознанный
    fail-fast: пайплайн не должен стартовать без ключей (RULES §6).
    """
    # Значения приходят из окружения, а не из аргументов конструктора —
    # mypy про это не знает (известное ограничение pydantic-settings).
    return Settings()  # type: ignore[call-arg]


def get_provider(
    name: ProviderName = "primary",
    settings: Settings | None = None,
) -> ProviderConfig:
    """Вернуть конфигурацию провайдера (по умолчанию — primary из `.env`)."""
    config = settings if settings is not None else get_settings()
    return config.provider(name)
