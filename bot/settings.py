"""Настройки Telegram-бота (T-035).

Токен читается из ``TELEGRAM_BOT_TOKEN`` (стандартное имя для BotFather),
остальные параметры — из переменных с префиксом ``VET_BOT_``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.settings import DEFAULT_MODEL_ID
from configs.settings import PROJECT_ROOT

#: Полный URL OpenAI-совместимого эндпоинта для локального запуска.
DEFAULT_BOT_API_URL = "http://127.0.0.1:8000/v1/chat/completions"

#: Таймаут запроса к API: CPU-генерация может занимать несколько минут.
DEFAULT_BOT_TIMEOUT_S = 300.0

#: Температура генерации по умолчанию.
DEFAULT_BOT_TEMPERATURE = 0.7

#: Сколько последних сообщений хранить в истории одного пользователя.
DEFAULT_BOT_HISTORY_MESSAGES = 20


class BotSettings(BaseSettings):
    """Параметры Telegram-бота и его клиента к FastAPI."""

    model_config = SettingsConfigDict(
        env_prefix="VET_BOT_",
        env_file=(".env", str(PROJECT_ROOT / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    telegram_bot_token: str = Field(
        default="",
        validation_alias="TELEGRAM_BOT_TOKEN",
        description="Токен Telegram-бота от @BotFather",
    )
    api_url: str = Field(
        default=DEFAULT_BOT_API_URL,
        validation_alias="VET_BOT_API_URL",
        min_length=1,
        description="URL /v1/chat/completions локального FastAPI",
    )
    auth_secret: str = Field(
        default="",
        validation_alias="VET_BOT_AUTH_SECRET",
        description=(
            "Секрет для синтетических аккаунтов Telegram; "
            "по умолчанию используется TELEGRAM_BOT_TOKEN"
        ),
    )
    model_id: str = Field(
        default=DEFAULT_MODEL_ID,
        validation_alias="VET_BOT_MODEL_ID",
        min_length=1,
        description="Имя модели в запросах к API",
    )
    timeout_s: float = Field(
        default=DEFAULT_BOT_TIMEOUT_S,
        validation_alias="VET_BOT_TIMEOUT_S",
        gt=0,
        description="Таймаут запроса к API, секунды",
    )
    temperature: float = Field(
        default=DEFAULT_BOT_TEMPERATURE,
        validation_alias="VET_BOT_TEMPERATURE",
        ge=0.0,
        le=2.0,
        description="Температура генерации",
    )
    use_rag: bool = Field(
        default=True,
        validation_alias="VET_BOT_USE_RAG",
        description="Использовать локальную базу знаний",
    )
    use_tools: bool = Field(
        default=True,
        validation_alias="VET_BOT_USE_TOOLS",
        description="Разрешить Function Calling",
    )
    max_history_messages: int = Field(
        default=DEFAULT_BOT_HISTORY_MESSAGES,
        validation_alias="VET_BOT_MAX_HISTORY_MESSAGES",
        ge=2,
        le=100,
        description="Сколько последних сообщений хранить в истории",
    )

    @property
    def resolved_auth_secret(self) -> str:
        """Секрет HMAC для аккаунтов Telegram (не хранит пароли в БД)."""
        return (
            self.auth_secret.strip()
            or self.telegram_bot_token.strip()
            or "vetassistant-bot-dev-secret"
        )


@lru_cache(maxsize=1)
def get_bot_settings() -> BotSettings:
    """Вернуть настройки бота (кеш на процесс)."""
    return BotSettings()
