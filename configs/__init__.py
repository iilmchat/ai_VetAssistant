"""Конфигурация проекта.

Единственная точка чтения переменных окружения (RULES §3): никакого
`os.getenv` в остальном коде — только `get_settings()`/`get_provider()`.
"""

from configs.settings import (
    PROVIDER_NAMES,
    ProviderConfig,
    ProviderName,
    ProviderNotConfiguredError,
    Settings,
    get_provider,
    get_settings,
)

__all__ = [
    "PROVIDER_NAMES",
    "ProviderConfig",
    "ProviderName",
    "ProviderNotConfiguredError",
    "Settings",
    "get_provider",
    "get_settings",
]
