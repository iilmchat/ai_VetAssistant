"""Тесты HTTP-клиента Streamlit-интерфейса (T-025)."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from app.settings import UISettings
from app.ui_client import build_payload, parse_sse_line, stream_chat


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


def test_parse_sse_line_returns_content() -> None:
    line = 'data: {"choices":[{"delta":{"content":"Привет"}}]}'

    assert parse_sse_line(line) == "Привет"


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
        stream: bool,
        timeout: float,
    ) -> _FakeResponse:
        captured.update(url=url, json=json, stream=stream, timeout=timeout)
        return _FakeResponse(lines)

    monkeypatch.setattr("app.ui_client.requests.post", fake_post)

    tokens = list(
        stream_chat(
            [{"role": "user", "content": "Кот не ест"}],
            temperature=0.3,
            use_rag=True,
            api_url="http://test/v1/chat/completions",
            model_id="test-model",
        )
    )

    assert tokens == ["При", "вет"]
    assert captured["url"] == "http://test/v1/chat/completions"
    assert captured["json"]["model"] == "test-model"
    assert captured["json"]["temperature"] == 0.3
    assert captured["json"]["use_rag"] is True
    assert captured["stream"] is True


def test_stream_chat_propagates_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*args: Any, **kwargs: Any) -> _FakeResponse:
        raise requests.ConnectionError("API выключен")

    monkeypatch.setattr("app.ui_client.requests.post", fake_post)

    with pytest.raises(requests.ConnectionError):
        list(stream_chat([{"role": "user", "content": "вопрос"}], temperature=0.7))
