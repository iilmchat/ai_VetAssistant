"""Типизированные настройки из `.env` (RULES §3: только pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень репозитория: конфиг не зависит от текущего каталога запуска скрипта.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Обязательные переменные окружения (см. `.env.example`).
REQUIRED_ENV_VARS: tuple[str, ...] = (
    "TEACHER_API_KEY",
    "TEACHER_BASE_URL",
    "TEACHER_MODEL",
)


class Settings(BaseSettings):
    """Настройки доступа к OpenAI-совместимому API учителя.

    Имена полей автоматически мапятся на переменные окружения в верхнем
    регистре (`teacher_api_key` <-> `TEACHER_API_KEY`), регистр не важен.
    """

    model_config = SettingsConfigDict(
        # Сначала `.env` в рабочем каталоге, затем `.env` в корне репозитория.
        env_file=(".env", str(PROJECT_ROOT / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    teacher_api_key: SecretStr = Field(description="API-ключ провайдера учителя")
    teacher_base_url: str = Field(description="Базовый URL OpenAI-совместимого API")
    teacher_model: str = Field(description="Идентификатор модели-учителя")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Вернуть настройки (кешируются на процесс).

    Падает с `ValidationError`, если `.env` не заполнен — это осознанный
    fail-fast: пайплайн не должен стартовать без ключей (RULES §6).
    """
    # Значения приходят из окружения, а не из аргументов конструктора —
    # mypy про это не знает (известное ограничение pydantic-settings).
    return Settings()  # type: ignore[call-arg]
