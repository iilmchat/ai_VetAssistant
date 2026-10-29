"""Проверки слоя конфигурации (T-001).

Гарантируем: `.env.example` содержит все обязательные переменные, а
`Settings` корректно собирает их из окружения и не падает на лишних ключах.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from configs import Settings
from configs.settings import REQUIRED_ENV_VARS

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def _read_env_example() -> dict[str, str]:
    """Разобрать `.env.example` в словарь, пропуская комментарии и пустые строки."""
    values: dict[str, str] = {}
    for raw_line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def test_env_example_contains_required_vars() -> None:
    values = _read_env_example()
    missing = [key for key in REQUIRED_ENV_VARS if key not in values]
    assert not missing, f"В .env.example нет обязательных ключей: {missing}"


def test_settings_reads_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEACHER_API_KEY", "sk-test")
    monkeypatch.setenv("TEACHER_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("TEACHER_MODEL", "teacher-model")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.teacher_api_key.get_secret_value() == "sk-test"
    assert settings.teacher_base_url == "https://api.example.com/v1"
    assert settings.teacher_model == "teacher-model"


def test_settings_ignores_unknown_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEACHER_API_KEY", "sk-test")
    monkeypatch.setenv("TEACHER_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("TEACHER_MODEL", "teacher-model")
    monkeypatch.setenv("JUDGE_MODEL", "judge-model")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.teacher_model == "teacher-model"


def test_settings_fail_fast_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in REQUIRED_ENV_VARS:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
