#!/usr/bin/env python
"""Синхронизация данных с S3-хранилищем через DVC (T-014).

Обёртка нужна, чтобы одна команда работала из любого каталога и не зависела
от активированного virtualenv: DVC запускается текущим Python-интерпретатором.

Примеры::

    python scripts/sync_data.py push
    python scripts/sync_data.py pull
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from loguru import logger

from configs.settings import PROJECT_ROOT
from data_pipeline.cli import configure_logging

COMMANDS = ("push", "pull")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Загрузить (push) или скачать (pull) данные через DVC.",
        epilog="Используется remote selectel из .dvc/config; креды — в .dvc/config.local.",
    )
    parser.add_argument(
        "command",
        choices=COMMANDS,
        help="push — в S3, pull — из S3",
    )
    return parser.parse_args(argv)


def _dvc_command(command: str) -> list[str]:
    """Команда DVC через текущий интерпретатор (работает без активации venv)."""
    return [sys.executable, "-m", "dvc", command]


def sync(command: str, *, cwd: Path = PROJECT_ROOT) -> int:
    """Выполнить ``dvc push`` или ``dvc pull``; вернуть код возврата."""
    if command not in COMMANDS:
        raise ValueError(f"неизвестная команда DVC: {command!r}")

    cmd = _dvc_command(command)
    logger.info("DVC {}: {}", command, " ".join(cmd))
    completed = subprocess.run(cmd, cwd=cwd, check=False)
    if completed.returncode != 0:
        logger.error("DVC {} завершился с кодом {}", command, completed.returncode)
    else:
        logger.info("DVC {}: готово", command)
    return completed.returncode


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()
    return sync(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
