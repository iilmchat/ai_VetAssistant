"""Тесты production smoke-теста (T-042/T-045)."""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from scripts.smoke_test import (
    CheckResult,
    api_base_url,
    check_appointments,
    check_chat,
    check_site,
    login_user,
    normalize_base_url,
    print_report,
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


def make_response(status: int, payload: Any = None, *, text: str = "") -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = "application/json"
    response._content = (
        text.encode("utf-8")
        if payload is None
        else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    return response


def test_normalize_and_api_base_url() -> None:
    assert normalize_base_url("https://ai-pets.ru/") == "https://ai-pets.ru"
    assert api_base_url("https://ai-pets.ru") == "https://ai-pets.ru/api"
    assert api_base_url("https://ai-pets.ru/api/") == "https://ai-pets.ru/api"
    with pytest.raises(ValueError):
        normalize_base_url("   ")


def test_response_detail_extracts_api_detail() -> None:
    assert response_detail(make_response(400, {"detail": "Запрос отклонён"})) == ("Запрос отклонён")


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


def test_login_user_uses_existing_credentials() -> None:
    session = FakeSession([make_response(200, {"access_token": "jwt-login"})])

    result, token = login_user(
        session,
        "https://ai-pets.ru",
        email="owner@example.com",
        password="secret-pass-1",
        timeout=5,
    )

    assert result.ok is True
    assert token == "jwt-login"
    assert session.calls[0]["url"] == "https://ai-pets.ru/api/v1/auth/login"
    assert session.calls[0]["json"] == {
        "email": "owner@example.com",
        "password": "secret-pass-1",
    }


def test_login_user_reports_closed_or_bad_credentials() -> None:
    session = FakeSession([make_response(401, {"detail": "Неверный email или пароль"})])

    result, token = login_user(
        session,
        "https://ai-pets.ru",
        email="owner@example.com",
        password="wrong",
        timeout=5,
    )

    assert result.ok is False
    assert token is None
    assert "401" in result.detail
    assert "Неверный email" in result.detail


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
    result = check_chat(FakeSession([]), "https://ai-pets.ru", None, timeout=5)

    assert result.ok is False
    assert "нет JWT" in result.detail


def test_check_appointments_accepts_empty_list() -> None:
    session = FakeSession([make_response(200, [])])

    result = check_appointments(
        session,
        "https://ai-pets.ru",
        "jwt-token",
        timeout=5,
    )

    assert result.ok is True
    assert "записей: 0" in result.detail
    assert session.calls[0]["url"] == "https://ai-pets.ru/api/v1/appointments"
    assert session.calls[0]["headers"] == {"Authorization": "Bearer jwt-token"}


def test_check_appointments_accepts_user_records() -> None:
    session = FakeSession(
        [
            make_response(
                200,
                [
                    {
                        "id": 1,
                        "pet_name": "Мурзик",
                        "date": "2026-11-04",
                        "time": "10:00",
                    }
                ],
            )
        ]
    )

    result = check_appointments(
        session,
        "https://ai-pets.ru",
        "jwt-token",
        timeout=5,
    )

    assert result.ok is True
    assert "записей: 1" in result.detail


def test_check_appointments_requires_token() -> None:
    result = check_appointments(
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
