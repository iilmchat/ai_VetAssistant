"""Конфигурация проекта.

Единственная точка чтения переменных окружения (RULES §3): никакого
`os.getenv` в остальном коде — только `get_settings()`/`get_provider()`.
"""

from configs.settings import (
    DEFAULT_PRIMARY_MODEL,
    PROVIDER_NAMES,
    ProviderConfig,
    ProviderName,
    ProviderNotConfiguredError,
    Settings,
    get_provider,
    get_settings,
)

__all__ = [
    "DEFAULT_PRIMARY_MODEL",
    "PROVIDER_NAMES",
    "ProviderConfig",
    "ProviderName",
    "ProviderNotConfiguredError",
    "Settings",
    "get_provider",
    "get_settings",
]
