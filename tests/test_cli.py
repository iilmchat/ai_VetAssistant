"""Тесты общих CLI-утилит (T-003)."""

from __future__ import annotations

import pytest
from loguru import logger

from data_pipeline.cli import configure_logging


def test_configure_logging_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    logger.info("проверка логов")

    captured = capsys.readouterr()
    assert "проверка логов" in captured.out
