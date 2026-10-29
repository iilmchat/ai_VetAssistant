"""Общие утилиты CLI-скриптов (RULES §3: логи только через loguru)."""

from __future__ import annotations

import sys

from loguru import logger


def configure_logging(level: str = "INFO") -> None:
    """Настроить loguru на stdout с учётом кодировки консоли Windows."""
    logger.remove()
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="backslashreplace")
    logger.add(
        stream,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    )
