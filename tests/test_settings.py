"""Проверки слоя конфигурации и провайдеров (T-001, T-008).

Гарантируем: `.env.example` содержит обязательные переменные, `Settings`
корректно собирает primary/fallback из окружения, а `ProviderConfig`
не светит API-ключ в repr.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from configs import ProviderNotConfiguredError, Settings
from configs.settings import (
    FALLBACK_ENV_VARS,
    REQUIRED_ENV_VARS,
    get_provider,
)

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


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in REQUIRED_ENV_VARS + FALLBACK_ENV_VARS:
        monkeypatch.delenv(key, raising=False)


def _set_primary_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEACHER_PRIMARY_API_KEY", "sk-test")
    monkeypatch.setenv("TEACHER_PRIMARY_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("TEACHER_PRIMARY_MODEL", "teacher-model")


def _set_fallback_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEACHER_FALLBACK_API_KEY", "sk-fallback")
    monkeypatch.setenv("TEACHER_FALLBACK_BASE_URL", "https://fallback.example.com/v1")
    monkeypatch.setenv("TEACHER_FALLBACK_MODEL", "fallback-model")


def _settings() -> Settings:
    """Настройки только из env, без чтения реального `.env`."""
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_env_example_contains_required_vars() -> None:
    values = _read_env_example()
    missing = [key for key in REQUIRED_ENV_VARS if key not in values]
    assert not missing, f"В .env.example нет обязательных ключей: {missing}"


def test_env_example_documents_fallback_vars() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    missing = [key for key in FALLBACK_ENV_VARS if key not in text]
    assert not missing, f"В .env.example нет fallback-ключей: {missing}"


def test_primary_model_defaults_to_non_reasoning_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Модель по умолчанию — deepseek-chat; задавать её в .env не обязательно."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("TEACHER_PRIMARY_API_KEY", "sk-test")
    monkeypatch.setenv("TEACHER_PRIMARY_BASE_URL", "https://api.example.com/v1")

    provider = _settings().provider("primary")

    assert provider.model == "deepseek-chat"


def test_env_example_uses_non_reasoning_model() -> None:
    values = _read_env_example()

    assert values["TEACHER_PRIMARY_MODEL"] == "deepseek-chat"


def test_settings_reads_primary_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)

    provider = _settings().provider("primary")

    assert provider.name == "primary"
    assert provider.api_key.get_secret_value() == "sk-test"
    assert provider.base_url == "https://api.example.com/v1"
    assert provider.model == "teacher-model"


def test_provider_repr_hides_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)

    provider = _settings().provider("primary")

    assert "sk-test" not in repr(provider)


def test_settings_reads_fallback_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)
    _set_fallback_env(monkeypatch)

    provider = _settings().provider("fallback")

    assert provider.name == "fallback"
    assert provider.api_key.get_secret_value() == "sk-fallback"
    assert provider.base_url == "https://fallback.example.com/v1"
    assert provider.model == "fallback-model"


def test_fallback_without_env_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)

    with pytest.raises(ProviderNotConfiguredError, match="TEACHER_FALLBACK_API_KEY"):
        _settings().provider("fallback")


def test_partial_fallback_lists_all_missing_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)
    monkeypatch.setenv("TEACHER_FALLBACK_API_KEY", "sk-fallback")

    with pytest.raises(ProviderNotConfiguredError) as excinfo:
        _settings().provider("fallback")

    message = str(excinfo.value)
    assert "TEACHER_FALLBACK_BASE_URL" in message
    assert "TEACHER_FALLBACK_MODEL" in message


def test_get_provider_uses_explicit_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)
    settings = _settings()

    provider = get_provider("primary", settings)

    assert provider.model == "teacher-model"
    assert provider.base_url == "https://api.example.com/v1"


def test_settings_ignores_unknown_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)
    monkeypatch.setenv("JUDGE_MODEL", "judge-model")

    settings = _settings()

    assert settings.provider("primary").model == "teacher-model"


def test_settings_fail_fast_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)

    with pytest.raises(ValidationError):
        _settings()
