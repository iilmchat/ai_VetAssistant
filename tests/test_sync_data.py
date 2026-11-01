"""Тесты обёртки DVC-синхронизации (T-014)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from configs.settings import PROJECT_ROOT
from scripts.sync_data import main, parse_args, sync


def test_parse_args_accepts_push_and_pull() -> None:
    assert parse_args(["push"]).command == "push"
    assert parse_args(["pull"]).command == "pull"


def test_parse_args_rejects_unknown_command() -> None:
    with pytest.raises(SystemExit):
        parse_args(["delete"])


def test_sync_invokes_dvc_push_via_current_python(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], Path, bool]] = []

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path,
        check: bool,
    ) -> SimpleNamespace:
        calls.append((cmd, cwd, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("scripts.sync_data.subprocess.run", fake_run)

    assert main(["push"]) == 0
    assert calls == [
        ([sys.executable, "-m", "dvc", "push"], PROJECT_ROOT, False),
    ]


def test_sync_propagates_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.sync_data.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=2),
    )

    assert sync("pull") == 2


def test_sync_rejects_unknown_command() -> None:
    with pytest.raises(ValueError, match="DVC"):
        sync("delete")
