"""Тесты смоук-теста GGUF через OpenAI-совместимый API (T-020)."""

from __future__ import annotations

from typing import Any

import httpx2
import pytest
from openai import APIConnectionError

from configs.settings import ProviderConfig
from data_pipeline.llm_client import ChatResult
from scripts.test_gguf import DEFAULT_BASE_URL, DEFAULT_MODEL_ID, main, parse_args


def _chat_result(content: str) -> ChatResult:
    return ChatResult(
        content=content,
        model="gguf-test",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        latency_s=0.1,
        attempts=1,
    )


def _fake_teacher(content: str, calls: list[Any]) -> type[Any]:
    class _FakeTeacher:
        def __init__(self, provider: ProviderConfig, **kwargs: Any) -> None:
            self.provider = provider
            self.kwargs = kwargs

        async def __aenter__(self) -> _FakeTeacher:
            return self

        async def __aexit__(self, *exc_info: object) -> None:
            return None

        async def chat(self, messages: Any, **kwargs: Any) -> ChatResult:
            calls.append((messages, kwargs))
            return _chat_result(content)

    return _FakeTeacher


def test_parse_args_defaults() -> None:
    args = parse_args([])

    assert args.base_url == DEFAULT_BASE_URL
    assert args.model_id == DEFAULT_MODEL_ID
    assert args.plain is False
    assert args.dry_run is False


def test_dry_run_does_not_call_api(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr("scripts.test_gguf.TeacherClient", _fake_teacher("", calls))

    exit_code = main(["--dry-run"])

    assert exit_code == 0
    assert calls == []
    output = capsys.readouterr().out
    assert "base_url=" in output
    assert "model=" in output
    assert "API не вызывается" in output


def test_json_response_is_validated(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(
        "scripts.test_gguf.TeacherClient",
        _fake_teacher('{"status": "ok", "role": "veterinary_assistant"}', calls),
    )

    exit_code = main([])

    assert exit_code == 0
    assert len(calls) == 1
    output = capsys.readouterr().out
    assert "JSON OK" in output
    assert "OK" in output


def test_invalid_json_returns_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(
        "scripts.test_gguf.TeacherClient",
        _fake_teacher("Извините, не могу", calls),
    )

    exit_code = main([])

    assert exit_code == 1
    assert "не содержит JSON" in capsys.readouterr().out


def test_plain_mode_accepts_non_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(
        "scripts.test_gguf.TeacherClient",
        _fake_teacher("OK", calls),
    )

    exit_code = main(["--plain"])

    assert exit_code == 0
    assert "OK" in capsys.readouterr().out


def test_api_error_returns_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _FailingTeacher:
        def __init__(self, provider: ProviderConfig, **kwargs: Any) -> None:
            self.provider = provider

        async def __aenter__(self) -> _FailingTeacher:
            return self

        async def __aexit__(self, *exc_info: object) -> None:
            return None

        async def chat(self, messages: Any, **kwargs: Any) -> ChatResult:
            raise APIConnectionError(
                request=httpx2.Request("POST", "http://test/v1/chat/completions")
            )

    monkeypatch.setattr("scripts.test_gguf.TeacherClient", _FailingTeacher)

    exit_code = main([])

    assert exit_code == 1
    assert "Ошибка API" in capsys.readouterr().out
