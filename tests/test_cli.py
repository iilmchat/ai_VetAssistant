"""Тесты общих CLI-утилит (T-003, T-004)."""

from __future__ import annotations

import argparse

import pytest
from loguru import logger

from data_pipeline.cli import configure_logging, positive_int


def test_configure_logging_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    logger.info("проверка логов")

    captured = capsys.readouterr()
    assert "проверка логов" in captured.out


@pytest.mark.parametrize("value", ["1", "5", "100"])
def test_positive_int_accepts_positive(value: str) -> None:
    assert positive_int(value) == int(value)


@pytest.mark.parametrize("value", ["0", "-1"])
def test_positive_int_rejects_non_positive(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match=">= 1"):
        positive_int(value)


def test_positive_int_rejects_text() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="целое"):
        positive_int("два")
