"""Конфигурация проекта.

Единственная точка чтения переменных окружения (RULES §3): никакого
`os.getenv` в остальном коде — только `get_settings()`.
"""

from configs.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
