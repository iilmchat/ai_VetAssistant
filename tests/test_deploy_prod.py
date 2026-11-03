"""Тесты оркестратора деплоя и smoke-теста (T-042)."""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from scripts.deploy_prod import (
    parse_env,
    render_env,
    resolve_telegram_token,
)
from scripts.smoke_test import (
    CheckResult,
    api_base_url,
    check_chat,
    check_site,
    normalize_base_url,
    print_report,
    register_user,
    response_detail,
)


class FakeSession:
    """Минимальная заглушка requests.Session."""

    def __init__(self, responses: list[requests.Response]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self.responses.pop(0)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self.responses.pop(0)


def make_response(
    status: int,
    payload: Any = None,
    *,
    text: str = "",
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = "application/json"
    if payload is None:
        response._content = text.encode("utf-8")
    else:
        response._content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return response


def test_render_env_replaces_values_and_preserves_comments() -> None:
    template = (
        "# production env\n"
        "POSTGRES_PASSWORD=\n"
        "VET_API_JWT_SECRET=old\n"
        "VET_DOMAIN=example.com\n"
    )

    rendered = render_env(
        template,
        {
            "POSTGRES_PASSWORD": "postgres-secret",
            "VET_API_JWT_SECRET": "jwt-secret",
            "VET_DOMAIN": "ai-pets.ru",
            "EXTRA": "value",
        },
    )

    assert "# production env" in rendered
    assert "POSTGRES_PASSWORD=postgres-secret" in rendered
    assert "VET_API_JWT_SECRET=jwt-secret" in rendered
    assert "VET_DOMAIN=ai-pets.ru" in rendered
    assert "EXTRA=value" in rendered


def test_parse_env_ignores_comments_and_empty_lines() -> None:
    values = parse_env("# comment\nA=1\n\nB=two=three\n")

    assert values == {"A": "1", "B": "two=three"}


def test_resolve_telegram_token_prefers_explicit_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")

    assert resolve_telegram_token("explicit-token") == "explicit-token"
    assert resolve_telegram_token(None) == "env-token"


def test_normalize_and_api_base_url() -> None:
    assert normalize_base_url("https://ai-pets.ru/") == "https://ai-pets.ru"
    assert api_base_url("https://ai-pets.ru") == "https://ai-pets.ru/api"
    assert api_base_url("https://ai-pets.ru/api/") == "https://ai-pets.ru/api"
    with pytest.raises(ValueError):
        normalize_base_url("   ")


def test_response_detail_extracts_api_detail() -> None:
    response = make_response(400, {"detail": "Запрос отклонён"})

    assert response_detail(response) == "Запрос отклонён"


def test_check_site_accepts_200() -> None:
    session = FakeSession([make_response(200, text="<html></html>")])

    result = check_site(session, "https://ai-pets.ru", timeout=5)

    assert result.ok is True
    assert "HTTP 200" in result.detail
    assert session.calls[0]["url"] == "https://ai-pets.ru"


def test_check_site_reports_http_error() -> None:
    session = FakeSession([make_response(502, {"detail": "Bad Gateway"})])

    result = check_site(session, "https://ai-pets.ru", timeout=5)

    assert result.ok is False
    assert "HTTP 502" in result.detail


def test_register_user_returns_token_and_uses_api_prefix() -> None:
    session = FakeSession(
        [
            make_response(
                201,
                {
                    "access_token": "jwt-token",
                    "user": {"id": 42, "email": "smoke@example.com"},
                },
            )
        ]
    )

    result, token = register_user(session, "https://ai-pets.ru", timeout=5)

    assert result.ok is True
    assert token == "jwt-token"
    assert session.calls[0]["url"] == "https://ai-pets.ru/api/v1/auth/register"
    assert "smoke-" in session.calls[0]["json"]["email"]


def test_check_chat_requires_non_empty_answer() -> None:
    session = FakeSession(
        [
            make_response(
                200,
                {"choices": [{"message": {"role": "assistant", "content": "Срочно."}}]},
            )
        ]
    )

    result = check_chat(session, "https://ai-pets.ru", "jwt-token", timeout=5)

    assert result.ok is True
    assert "Срочно" in result.detail
    assert session.calls[0]["headers"] == {"Authorization": "Bearer jwt-token"}


def test_check_chat_fails_without_token() -> None:
    result = check_chat(
        FakeSession([]),
        "https://ai-pets.ru",
        None,
        timeout=5,
    )

    assert result.ok is False
    assert "нет JWT" in result.detail


def test_print_report_returns_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    success = [CheckResult("Сайт", True, "HTTP 200", 0.1)]

    assert print_report("https://ai-pets.ru", success) == 0
    output = capsys.readouterr().out
    assert "✅" in output
    assert "1/1" in output

    failure = [CheckResult("Чат", False, "HTTP 503", 0.2)]
    assert print_report("https://ai-pets.ru", failure) == 1
    assert "❌" in capsys.readouterr().out
