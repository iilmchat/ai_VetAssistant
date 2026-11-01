"""Типизированные настройки из `.env` (RULES §3: только pydantic-settings).

Провайдеры учителя описываются независимыми наборами переменных:
``TEACHER_PRIMARY_*`` (обязательный), ``TEACHER_FALLBACK_*`` (опциональный)
и ``GIGACHAT_*`` (опциональный, OAuth 2.0). `Settings.provider(name)`
собирает неизменяемую конфигурацию :class:`ProviderConfig` или
:class:`GigaChatConfig`, которая передаётся в `TeacherClient` через
dependency injection — сам клиент глобальные настройки не читает.

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
ProviderName = Literal["primary", "fallback", "gigachat"]
PROVIDER_NAMES: tuple[ProviderName, ...] = ("primary", "fallback", "gigachat")

#: Провайдеры с обычным Bearer-ключом (OpenAI-совместимый API).
OpenAIProviderName = Literal["primary", "fallback"]

#: Режим thinking: DeepSeek понимает extra_body.thinking, остальные — нет.
ThinkingMode = Literal["deepseek", "none"]

#: GigaChat: OAuth-эндпоинт, модель и scope по умолчанию (T-012).
GIGACHAT_BASE_URL = "https://api.giga.chat/v1"
GIGACHAT_MODEL = "GigaChat-2-Max"
GIGACHAT_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_SCOPE = "GIGACHAT_API_PERS"

#: Переменные GigaChat-провайдера; нужны только при `--provider gigachat`.
GIGACHAT_ENV_VARS: tuple[str, ...] = (
    "GIGACHAT_CLIENT_ID",
    "GIGACHAT_CLIENT_SECRET",
)

#: Бесплатный тариф GigaChat допускает только один одновременный запрос.
GIGACHAT_MAX_CONCURRENCY = 1


def thinking_mode_for_model(model: str) -> ThinkingMode:
    """Определить, можно ли передавать модели DeepSeek thinking-параметр.

    ``extra_body={"thinking": ...}`` — особенность DeepSeek. Для GigaChat и
    прочих OpenAI-совместимых провайдеров его отправлять нельзя.
    """
    return "deepseek" if model.strip().lower().startswith("deepseek") else "none"


#: Обязательные переменные primary-провайдера (см. `.env.example`).
#: Модель не входит в список: у неё есть дефолт `deepseek-chat`.
REQUIRED_ENV_VARS: tuple[str, ...] = (
    "TEACHER_PRIMARY_API_KEY",
    "TEACHER_PRIMARY_BASE_URL",
)

#: Модель primary-провайдера по умолчанию (thinking отключается на уровне клиента).
DEFAULT_PRIMARY_MODEL = "deepseek-flash"

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

    name: OpenAIProviderName
    api_key: SecretStr = Field(min_length=1, description="API-ключ (не попадает в repr)")
    base_url: str = Field(min_length=1, description="Базовый URL, обычно .../v1")
    model: str = Field(min_length=1, description="Идентификатор модели")
    thinking_mode: ThinkingMode = Field(
        default="none",
        description="Передавать ли DeepSeek-параметр extra_body.thinking",
    )


class GigaChatConfig(BaseModel):
    """Конфигурация GigaChat: OAuth-креды вместо статического API-ключа (T-012)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["gigachat"] = "gigachat"
    client_id: SecretStr = Field(min_length=1, description="GigaChat OAuth client_id")
    client_secret: SecretStr = Field(
        min_length=1, description="GigaChat OAuth client_secret (не попадает в repr)"
    )
    base_url: str = Field(default=GIGACHAT_BASE_URL, min_length=1)
    model: str = Field(default=GIGACHAT_MODEL, min_length=1)
    oauth_url: str = Field(default=GIGACHAT_OAUTH_URL, min_length=1)
    scope: str = Field(default=GIGACHAT_SCOPE, min_length=1)


#: Любой поддерживаемый провайдер учителя.
ProviderSpec = ProviderConfig | GigaChatConfig


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
        description="Модель primary-провайдера (по умолчанию deepseek-flash)",
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

    gigachat_client_id: SecretStr | None = Field(
        default=None, description="GigaChat OAuth client_id (опционально)"
    )
    gigachat_client_secret: SecretStr | None = Field(
        default=None, description="GigaChat OAuth client_secret (опционально)"
    )
    gigachat_base_url: str = Field(
        default=GIGACHAT_BASE_URL,
        min_length=1,
        description="Базовый URL GigaChat API",
    )
    gigachat_model: str = Field(
        default=GIGACHAT_MODEL,
        min_length=1,
        description="Модель GigaChat",
    )
    gigachat_oauth_url: str = Field(
        default=GIGACHAT_OAUTH_URL,
        min_length=1,
        description="OAuth-эндпоинт GigaChat",
    )
    gigachat_scope: str = Field(
        default=GIGACHAT_SCOPE,
        min_length=1,
        description="OAuth scope GigaChat",
    )

    def provider(self, name: ProviderName = "primary") -> ProviderSpec:
        """Собрать конфигурацию провайдера по имени.

        Raises:
            ProviderNotConfiguredError: для fallback или GigaChat заданы не все
                обязательные переменные.
        """
        if name == "primary":
            return self._openai_provider(
                "primary",
                self.teacher_primary_api_key,
                self.teacher_primary_base_url,
                self.teacher_primary_model,
            )

        if name == "fallback":
            return self._fallback_provider()

        if name == "gigachat":
            return self._gigachat_provider()

        raise ValueError(f"неизвестный провайдер: {name!r}")  # pragma: no cover

    def _openai_provider(
        self,
        name: OpenAIProviderName,
        api_key: SecretStr,
        base_url: str,
        model: str,
    ) -> ProviderConfig:
        """Собрать провайдера с Bearer-ключом и определить режим thinking."""
        return ProviderConfig(
            name=name,
            api_key=api_key,
            base_url=base_url,
            model=model,
            thinking_mode=thinking_mode_for_model(model),
        )

    def _fallback_provider(self) -> ProviderConfig:
        """Собрать fallback-провайдера или сообщить обо всех пропущенных ключах."""
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
        return self._openai_provider("fallback", api_key, base_url, model)

    def _gigachat_provider(self) -> GigaChatConfig:
        """Собрать GigaChat-провайдера или сообщить о пропущенных OAuth-кредах."""
        client_id = self.gigachat_client_id
        client_secret = self.gigachat_client_secret

        missing: list[str] = []
        if client_id is None or not client_id.get_secret_value().strip():
            missing.append("GIGACHAT_CLIENT_ID")
        if client_secret is None or not client_secret.get_secret_value().strip():
            missing.append("GIGACHAT_CLIENT_SECRET")

        if missing:
            raise ProviderNotConfiguredError(
                "gigachat-провайдер не настроен: не хватает " + ", ".join(missing)
            )

        assert client_id is not None  # сужено проверкой выше, нужно для mypy
        assert client_secret is not None
        return GigaChatConfig(
            client_id=client_id,
            client_secret=client_secret,
            base_url=self.gigachat_base_url,
            model=self.gigachat_model,
            oauth_url=self.gigachat_oauth_url,
            scope=self.gigachat_scope,
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
) -> ProviderSpec:
    """Вернуть конфигурацию провайдера (по умолчанию — primary из `.env`)."""
    config = settings if settings is not None else get_settings()
    return config.provider(name)


def resolve_concurrency(provider: ProviderSpec, requested: int) -> int:
    """Ограничить конкурентность с учётом лимитов провайдера.

    GigaChat на бесплатном тарифе принимает только один одновременный запрос,
    поэтому для него ``concurrency`` принудительно равна 1.

    Raises:
        ValueError: запрошено меньше одной цепочки.
    """
    if requested < 1:
        raise ValueError("concurrency должен быть >= 1")
    if provider.name == "gigachat":
        return GIGACHAT_MAX_CONCURRENCY
    return requested
