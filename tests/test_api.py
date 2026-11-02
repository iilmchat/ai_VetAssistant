"""Тесты OpenAI-совместимого API с замоканной GGUF-моделью (T-022)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import VET_SYSTEM_PROMPT, app, get_model
from app.settings import DEFAULT_MODEL_ID


class FakeModel:
    """Заглушка llama-cpp-python: записывает вызовы и возвращает фикстуры."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_chat_completion(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return iter(
                [
                    {
                        "id": "chatcmpl-fake",
                        "object": "chat.completion.chunk",
                        "created": 123,
                        "model": "fake",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": "Обратитесь "},
                                "finish_reason": None,
                            }
                        ],
                    },
                    {
                        "id": "chatcmpl-fake",
                        "object": "chat.completion.chunk",
                        "created": 123,
                        "model": "fake",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "к ветеринару."},
                                "finish_reason": None,
                            }
                        ],
                    },
                    {
                        "id": "chatcmpl-fake",
                        "object": "chat.completion.chunk",
                        "created": 123,
                        "model": "fake",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    },
                ]
            )

        return {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": 123,
            "model": "fake",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Обратитесь к ветеринару."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }


@pytest.fixture
def fake_model() -> FakeModel:
    return FakeModel()


@pytest.fixture
def client(fake_model: FakeModel) -> Iterator[TestClient]:
    app.dependency_overrides[get_model] = lambda: fake_model
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_chat_completion_returns_openai_shape(client: TestClient, fake_model: FakeModel) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Кот не ест сутки. Что делать?"}]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion"
    assert data["model"] == DEFAULT_MODEL_ID
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["message"]["content"] == "Обратитесь к ветеринару."
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }


def test_vet_system_prompt_is_added_when_missing(
    client: TestClient, fake_model: FakeModel
) -> None:
    client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "У собаки понос."}]},
    )

    call = fake_model.calls[0]
    assert call["messages"][0] == {"role": "system", "content": VET_SYSTEM_PROMPT}
    assert call["messages"][1] == {"role": "user", "content": "У собаки понос."}
    assert call["temperature"] == 0.2
    assert call["top_p"] == 0.95
    assert call["max_tokens"] == 1024


def test_custom_system_prompt_is_preserved(client: TestClient, fake_model: FakeModel) -> None:
    client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": "Отвечай очень кратко."},
                {"role": "user", "content": "Кошка чихает."},
            ]
        },
    )

    messages = fake_model.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "Отвечай очень кратко."}
    assert sum(1 for message in messages if message["role"] == "system") == 1


def test_custom_model_name_is_returned(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "my-custom-model",
            "messages": [{"role": "user", "content": "Вопрос"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["model"] == "my-custom-model"


def test_streaming_returns_sse_chunks(client: TestClient) -> None:
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Кот не ест."}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    lines = [
        line.removeprefix("data: ")
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert lines[-1] == "[DONE]"

    chunks = [json.loads(line) for line in lines[:-1]]
    assert chunks[0]["model"] == DEFAULT_MODEL_ID
    content = "".join(
        chunk["choices"][0]["delta"].get("content", "")
        for chunk in chunks
        if chunk.get("choices")
    )
    assert content == "Обратитесь к ветеринару."


def test_empty_messages_are_rejected(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json={"messages": []})

    assert response.status_code == 422


def test_health_reports_model(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["model"] == DEFAULT_MODEL_ID
    assert "model_path_exists" in data
