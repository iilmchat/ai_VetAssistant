"""Тесты HTTP-клиента Streamlit-интерфейса (T-025)."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from app.settings import UISettings
from app.tools import SET_REMINDER_TOOL
from app.ui_client import (
    api_base_url,
    auth_headers,
    build_payload,
    fetch_appointments,
    fetch_reminders,
    login,
    parse_sse_event,
    parse_sse_line,
    register,
    stream_chat,
    stream_chat_events,
)


class _FakeResponse:
    """Минимальная заглушка requests.Response для SSE."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self) -> Any:
        return iter(self._lines)


class _FakeJsonResponse:
    """Заглушка requests.Response для GET-эндпоинтов."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


def test_api_base_url_strips_chat_suffix() -> None:
    assert api_base_url("http://api:8000/v1/chat/completions") == "http://api:8000"
    assert api_base_url("http://api:8000") == "http://api:8000"
    assert api_base_url("http://api:8000/v1/chat/completions/") == "http://api:8000"


def test_fetch_appointments_and_reminders(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    def fake_get(
        url: str,
        *,
        timeout: float,
        headers: dict[str, str],
    ) -> _FakeJsonResponse:
        urls.append(url)
        captured_headers.append(headers)
        if url.endswith("/appointments"):
            return _FakeJsonResponse(
                [{"id": 1, "pet_name": "Барсик", "date": "2026-11-04", "time": "15:00"}]
            )
        return _FakeJsonResponse([{"id": 1, "text": "Дать таблетку", "time": "20:00"}])

    captured_headers: list[dict[str, str]] = []
    monkeypatch.setattr("app.ui_client.requests.get", fake_get)

    appointments = fetch_appointments(
        "http://api:8000/v1/chat/completions",
        token="jwt-token",
    )
    reminders = fetch_reminders(
        "http://api:8000/v1/chat/completions",
        token="jwt-token",
    )

    assert appointments[0]["pet_name"] == "Барсик"
    assert reminders[0]["text"] == "Дать таблетку"
    assert urls == [
        "http://api:8000/v1/appointments",
        "http://api:8000/v1/reminders",
    ]
    assert captured_headers == [
        {"Authorization": "Bearer jwt-token"},
        {"Authorization": "Bearer jwt-token"},
    ]


def test_auth_headers_are_optional() -> None:
    assert auth_headers() == {}
    assert auth_headers("token") == {"Authorization": "Bearer token"}


def test_login_and_register_request_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_post(
        url: str,
        *,
        json: dict[str, str],
        timeout: float,
    ) -> _FakeJsonResponse:
        calls.append((url, json))
        return _FakeJsonResponse({"access_token": "jwt", "token_type": "bearer"})

    monkeypatch.setattr("app.ui_client.requests.post", fake_post)

    login_data = login(
        "http://api:8000/v1/chat/completions",
        email="owner@example.com",
        password="secret-pass-1",
    )
    register_data = register(
        "http://api:8000/v1/chat/completions",
        email="new@example.com",
        password="secret-pass-2",
    )

    assert login_data["access_token"] == "jwt"
    assert register_data["access_token"] == "jwt"
    assert calls == [
        (
            "http://api:8000/v1/auth/login",
            {"email": "owner@example.com", "password": "secret-pass-1"},
        ),
        (
            "http://api:8000/v1/auth/register",
            {"email": "new@example.com", "password": "secret-pass-2"},
        ),
    ]


def test_login_rejects_response_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(
        url: str,
        *,
        json: dict[str, str],
        timeout: float,
    ) -> _FakeJsonResponse:
        return _FakeJsonResponse({"detail": "Неверный email или пароль"})

    monkeypatch.setattr("app.ui_client.requests.post", fake_post)

    with pytest.raises(ValueError, match="access_token"):
        login("http://api:8000", email="owner@example.com", password="wrong")


def test_ui_settings_read_api_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VET_UI_API_URL", "http://api:8000/v1/chat/completions")
    monkeypatch.setenv("VET_UI_MODEL_ID", "docker-model")
    monkeypatch.setenv("VET_UI_TIMEOUT_S", "42")

    settings = UISettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.api_url == "http://api:8000/v1/chat/completions"
    assert settings.model_id == "docker-model"
    assert settings.timeout_s == 42.0


def test_build_payload_contains_stream_and_settings() -> None:
    payload = build_payload(
        [{"role": "user", "content": "Кот не ест"}],
        model_id="qwen3-8b-vet",
        temperature=0.7,
        use_rag=True,
    )

    assert payload["model"] == "qwen3-8b-vet"
    assert payload["temperature"] == 0.7
    assert payload["stream"] is True
    assert payload["use_rag"] is True
    assert payload["messages"] == [{"role": "user", "content": "Кот не ест"}]


def test_build_payload_includes_tools() -> None:
    payload = build_payload(
        [{"role": "user", "content": "Напомни дать таблетку"}],
        model_id="qwen3-8b-vet",
        temperature=0.2,
        tools=[SET_REMINDER_TOOL],
    )

    assert payload["tools"] == [SET_REMINDER_TOOL]


def test_parse_sse_line_returns_content() -> None:
    line = 'data: {"choices":[{"delta":{"content":"Привет"}}]}'

    assert parse_sse_line(line) == "Привет"


def test_parse_sse_event_returns_tool_calls() -> None:
    line = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        '"type":"function","function":{"name":"set_reminder",'
        '"arguments":"{\\"time\\":\\"20:00\\",\\"text\\":\\"Дать таблетку\\"}"}}]}}]}'
    )

    event = parse_sse_event(line)

    assert event is not None
    assert event.content is None
    assert len(event.tool_calls) == 1
    assert event.tool_calls[0].id == "call_1"
    assert event.tool_calls[0].function.name == "set_reminder"
    assert "Дать таблетку" in event.tool_calls[0].function.arguments


@pytest.mark.parametrize(
    "line",
    [
        "",
        "event: ping",
        "data: [DONE]",
        "data: not-json",
        'data: {"choices":[]}',
        'data: {"choices":[{"delta":{}}]}',
        'data: {"choices":[{"delta":{"content":""}}]}',
    ],
)
def test_parse_sse_line_ignores_non_content(line: str) -> None:
    assert parse_sse_line(line) is None


def test_stream_chat_yields_deltas_and_sends_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    lines = [
        'data: {"choices":[{"delta":{"content":"При"}}]}'.encode(),
        b"",
        'data: {"choices":[{"delta":{"content":"вет"}}]}'.encode(),
        b"data: [DONE]",
    ]

    def fake_post(
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        stream: bool,
        timeout: float,
    ) -> _FakeResponse:
        captured.update(
            url=url,
            json=json,
            headers=headers,
            stream=stream,
            timeout=timeout,
        )
        return _FakeResponse(lines)

    monkeypatch.setattr("app.ui_client.requests.post", fake_post)

    tokens = list(
        stream_chat(
            [{"role": "user", "content": "Кот не ест"}],
            temperature=0.3,
            use_rag=True,
            api_url="http://test/v1/chat/completions",
            model_id="test-model",
            token="jwt-token",
        )
    )

    assert tokens == ["При", "вет"]
    assert captured["url"] == "http://test/v1/chat/completions"
    assert captured["json"]["model"] == "test-model"
    assert captured["json"]["temperature"] == 0.3
    assert captured["json"]["use_rag"] is True
    assert captured["stream"] is True
    assert captured["headers"] == {"Authorization": "Bearer jwt-token"}


def test_stream_chat_events_yields_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    lines = [
        (
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
            '"type":"function","function":{"name":"set_reminder",'
            '"arguments":"{\\"time\\":\\"20:00\\",\\"text\\":\\"Дать таблетку\\"}"}}]}}]}'
        ).encode(),
        b"data: [DONE]",
    ]

    def fake_post(
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        stream: bool,
        timeout: float,
    ) -> _FakeResponse:
        captured.update(
            url=url,
            json=json,
            headers=headers,
            stream=stream,
            timeout=timeout,
        )
        return _FakeResponse(lines)

    monkeypatch.setattr("app.ui_client.requests.post", fake_post)

    events = list(
        stream_chat_events(
            [{"role": "user", "content": "Напомни в 20:00"}],
            temperature=0.2,
            tools=[SET_REMINDER_TOOL],
            token="jwt-token",
        )
    )

    assert len(events) == 1
    assert events[0].tool_calls[0].function.name == "set_reminder"
    assert captured["json"]["tools"] == [SET_REMINDER_TOOL]
    assert captured["headers"] == {"Authorization": "Bearer jwt-token"}


def test_stream_chat_propagates_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*args: Any, **kwargs: Any) -> _FakeResponse:
        raise requests.ConnectionError("API выключен")

    monkeypatch.setattr("app.ui_client.requests.post", fake_post)

    with pytest.raises(requests.ConnectionError):
        list(stream_chat([{"role": "user", "content": "вопрос"}], temperature=0.7))
