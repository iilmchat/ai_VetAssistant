"""Проверки слоя конфигурации и провайдеров (T-001, T-008).

Гарантируем: `.env.example` содержит обязательные переменные, `Settings`
корректно собирает primary/fallback из окружения, а `ProviderConfig`
не светит API-ключ в repr.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from configs import ProviderNotConfiguredError, Settings
from configs.settings import (
    FALLBACK_ENV_VARS,
    GIGACHAT_BASE_URL,
    GIGACHAT_ENV_VARS,
    GIGACHAT_MODEL,
    GIGACHAT_OAUTH_URL,
    GIGACHAT_SCOPE,
    PROVIDER_NAMES,
    REQUIRED_ENV_VARS,
    GigaChatConfig,
    ProviderConfig,
    get_provider,
    resolve_concurrency,
    thinking_mode_for_model,
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
    for key in REQUIRED_ENV_VARS + FALLBACK_ENV_VARS + GIGACHAT_ENV_VARS:
        monkeypatch.delenv(key, raising=False)


def _set_primary_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEACHER_PRIMARY_API_KEY", "sk-test")
    monkeypatch.setenv("TEACHER_PRIMARY_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("TEACHER_PRIMARY_MODEL", "teacher-model")


def _set_fallback_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEACHER_FALLBACK_API_KEY", "sk-fallback")
    monkeypatch.setenv("TEACHER_FALLBACK_BASE_URL", "https://fallback.example.com/v1")
    monkeypatch.setenv("TEACHER_FALLBACK_MODEL", "fallback-model")


def _set_gigachat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIGACHAT_CLIENT_ID", "gc-client")
    monkeypatch.setenv("GIGACHAT_CLIENT_SECRET", "gc-secret")


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


def test_primary_model_defaults_to_deepseek_flash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Модель по умолчанию — deepseek-flash; задавать её в .env не обязательно."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("TEACHER_PRIMARY_API_KEY", "sk-test")
    monkeypatch.setenv("TEACHER_PRIMARY_BASE_URL", "https://api.example.com/v1")

    provider = _settings().provider("primary")

    assert provider.model == "deepseek-flash"


def test_env_example_uses_deepseek_flash() -> None:
    values = _read_env_example()

    assert values["TEACHER_PRIMARY_MODEL"] == "deepseek-flash"


def test_settings_reads_primary_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)

    provider = _settings().provider("primary")

    assert isinstance(provider, ProviderConfig)
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

    assert isinstance(provider, ProviderConfig)
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


# --- GigaChat и режим thinking (T-012) --------------------------------------


def test_provider_names_include_gigachat() -> None:
    assert "gigachat" in PROVIDER_NAMES


def test_env_example_documents_gigachat_vars() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    missing = [key for key in GIGACHAT_ENV_VARS if key not in text]
    assert not missing, f"В .env.example нет GigaChat-ключей: {missing}"
    assert GIGACHAT_BASE_URL in text
    assert GIGACHAT_MODEL in text
    assert GIGACHAT_OAUTH_URL in text
    assert GIGACHAT_SCOPE in text


def test_settings_reads_gigachat_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)
    _set_gigachat_env(monkeypatch)

    provider = _settings().provider("gigachat")

    assert isinstance(provider, GigaChatConfig)
    assert provider.name == "gigachat"
    assert provider.client_id.get_secret_value() == "gc-client"
    assert provider.client_secret.get_secret_value() == "gc-secret"
    assert provider.base_url == GIGACHAT_BASE_URL
    assert provider.model == GIGACHAT_MODEL
    assert provider.oauth_url == GIGACHAT_OAUTH_URL
    assert provider.scope == GIGACHAT_SCOPE


def test_gigachat_repr_hides_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)
    _set_gigachat_env(monkeypatch)

    provider = _settings().provider("gigachat")

    assert "gc-secret" not in repr(provider)


def test_gigachat_without_env_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)

    with pytest.raises(ProviderNotConfiguredError) as excinfo:
        _settings().provider("gigachat")

    message = str(excinfo.value)
    assert "GIGACHAT_CLIENT_ID" in message
    assert "GIGACHAT_CLIENT_SECRET" in message


def test_gigachat_partial_env_lists_missing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)
    monkeypatch.setenv("GIGACHAT_CLIENT_ID", "gc-client")

    with pytest.raises(ProviderNotConfiguredError, match="GIGACHAT_CLIENT_SECRET"):
        _settings().provider("gigachat")


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("deepseek-flash", "deepseek"),
        ("DeepSeek-Chat", "deepseek"),
        ("GigaChat-2-Max", "none"),
        ("teacher-model", "none"),
    ],
)
def test_thinking_mode_detection(model: str, expected: str) -> None:
    assert thinking_mode_for_model(model) == expected


def test_primary_deepseek_enables_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("TEACHER_PRIMARY_API_KEY", "sk-test")
    monkeypatch.setenv("TEACHER_PRIMARY_BASE_URL", "https://api.example.com/v1")

    provider = _settings().provider("primary")

    assert isinstance(provider, ProviderConfig)
    assert provider.model == "deepseek-flash"
    assert provider.thinking_mode == "deepseek"


def test_non_deepseek_provider_does_not_enable_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)

    provider = _settings().provider("primary")

    assert isinstance(provider, ProviderConfig)
    assert provider.thinking_mode == "none"


def test_resolve_concurrency_limits_gigachat(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _set_primary_env(monkeypatch)
    _set_gigachat_env(monkeypatch)
    settings = _settings()
    gigachat = settings.provider("gigachat")
    primary = settings.provider("primary")

    assert resolve_concurrency(gigachat, 10) == 1
    assert resolve_concurrency(primary, 10) == 10
    with pytest.raises(ValueError, match="concurrency"):
        resolve_concurrency(primary, 0)


def test_gigachat_config_can_be_built_directly() -> None:
    provider = GigaChatConfig(
        client_id=SecretStr("gc-client"),
        client_secret=SecretStr("gc-secret"),
    )

    assert provider.name == "gigachat"
    assert provider.base_url == GIGACHAT_BASE_URL
    assert provider.model == GIGACHAT_MODEL
