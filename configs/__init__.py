"""Конфигурация проекта.

Единственная точка чтения переменных окружения (RULES §3): никакого
`os.getenv` в остальном коде — только `get_settings()`/`get_provider()`.
"""

from configs.settings import (
    DEFAULT_PRIMARY_MODEL,
    GIGACHAT_BASE_URL,
    GIGACHAT_MODEL,
    GIGACHAT_OAUTH_URL,
    GIGACHAT_SCOPE,
    PROVIDER_NAMES,
    GigaChatConfig,
    ProviderConfig,
    ProviderName,
    ProviderNotConfiguredError,
    ProviderSpec,
    Settings,
    get_provider,
    get_settings,
    resolve_concurrency,
)

__all__ = [
    "DEFAULT_PRIMARY_MODEL",
    "GIGACHAT_BASE_URL",
    "GIGACHAT_MODEL",
    "GIGACHAT_OAUTH_URL",
    "GIGACHAT_SCOPE",
    "PROVIDER_NAMES",
    "GigaChatConfig",
    "ProviderConfig",
    "ProviderName",
    "ProviderNotConfiguredError",
    "ProviderSpec",
    "Settings",
    "get_provider",
    "get_settings",
    "resolve_concurrency",
]
