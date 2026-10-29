"""Тесты слоя абстракции учителя (T-002).

Все тесты офлайновые: `AsyncOpenAI` замокан, реальный API не вызывается и
ключи не нужны. Проверяем политику ретраев (429/5xx — да, 400/401/403 — нет),
парсинг ответа и логирование токенов.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from loguru import logger
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
)
from openai.types.chat import ChatCompletion
from pydantic import SecretStr
from tenacity import wait_none

from configs.settings import ProviderConfig
from data_pipeline import llm_client
from data_pipeline.llm_client import (
    ChatResult,
    TeacherAPIError,
    TeacherClient,
    is_retryable_error,
)

BASE_URL = "https://api.example.com/v1"
MODEL = "teacher-test"


def _provider(model: str = MODEL, base_url: str = BASE_URL) -> ProviderConfig:
    """Конфигурация провайдера без чтения реального `.env` (dependency injection)."""
    return ProviderConfig(
        name="primary",
        api_key=SecretStr("sk-test"),
        base_url=base_url,
        model=model,
    )


def _completion(
    content: str = "Привет, я ассистент",
    *,
    prompt_tokens: int = 11,
    completion_tokens: int = 7,
    finish_reason: str = "stop",
) -> ChatCompletion:
    """Собрать настоящий объект SDK без сети — так тесты не расходятся с типами."""
    return ChatCompletion.model_validate(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1_700_000_000,
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
    )


def _status_error(error_type: type[Exception], status_code: int) -> Exception:
    """Сконструировать ошибку SDK с нужным HTTP-статусом."""
    request = httpx2.Request("POST", f"{BASE_URL}/chat/completions")
    response = httpx2.Response(status_code, request=request)
    return error_type("error", response=response, body=None)  # type: ignore[call-arg]


@pytest.fixture
def mock_client() -> Iterator[MagicMock]:
    """`AsyncOpenAI` с замоканным `chat.completions.create`."""
    client = MagicMock(spec=AsyncOpenAI)
    client.chat.completions.create = AsyncMock()
    yield client


@pytest.fixture
def client(mock_client: MagicMock) -> TeacherClient:
    """`TeacherClient` на замоканном SDK, без пауз между ретраями."""
    return TeacherClient(
        _provider(),
        client=mock_client,
        max_attempts=3,
        wait_strategy=wait_none(),
    )


def _create_mock(mock_client: MagicMock) -> AsyncMock:
    create: AsyncMock = mock_client.chat.completions.create
    return create


@pytest.mark.asyncio
async def test_chat_returns_content_and_usage(
    client: TeacherClient, mock_client: MagicMock
) -> None:
    _create_mock(mock_client).return_value = _completion()

    result = await client.chat([{"role": "user", "content": "Привет"}])

    assert isinstance(result, ChatResult)
    assert result.content == "Привет, я ассистент"
    assert result.model == MODEL
    assert result.prompt_tokens == 11
    assert result.completion_tokens == 7
    assert result.total_tokens == 18
    assert result.attempts == 1
    assert result.latency_s >= 0.0
    assert result.finish_reason == "stop"

    _create_mock(mock_client).assert_awaited_once()
    call = _create_mock(mock_client).await_args
    assert call is not None
    kwargs: dict[str, Any] = dict(call.kwargs)
    assert kwargs["model"] == MODEL
    assert kwargs["messages"] == [{"role": "user", "content": "Привет"}]
    # Необязательные параметры не отправляются, если не заданы (SDK 3.x: omit).
    assert "temperature" not in kwargs
    assert "max_tokens" not in kwargs


@pytest.mark.asyncio
async def test_optional_params_are_forwarded(client: TeacherClient, mock_client: MagicMock) -> None:
    _create_mock(mock_client).return_value = _completion()

    await client.chat(
        [{"role": "user", "content": "Ответь JSON"}],
        temperature=0.2,
        max_tokens=128,
        response_format={"type": "json_object"},
    )

    call = _create_mock(mock_client).await_args
    assert call is not None
    kwargs: dict[str, Any] = dict(call.kwargs)
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 128
    assert kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_retries_on_rate_limit_then_succeeds(
    client: TeacherClient, mock_client: MagicMock
) -> None:
    create = _create_mock(mock_client)
    create.side_effect = [_status_error(RateLimitError, 429), _completion()]

    result = await client.chat([{"role": "user", "content": "Привет"}])

    assert result.content == "Привет, я ассистент"
    assert result.attempts == 2
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_retries_on_server_error_then_succeeds(
    client: TeacherClient, mock_client: MagicMock
) -> None:
    create = _create_mock(mock_client)
    create.side_effect = [_status_error(InternalServerError, 503), _completion()]

    result = await client.chat([{"role": "user", "content": "Привет"}])

    assert result.attempts == 2
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_retries_on_connection_error(client: TeacherClient, mock_client: MagicMock) -> None:
    create = _create_mock(mock_client)
    request = httpx2.Request("POST", f"{BASE_URL}/chat/completions")
    create.side_effect = [APIConnectionError(request=request), _completion()]

    result = await client.chat([{"role": "user", "content": "Привет"}])

    assert result.attempts == 2
    assert create.await_count == 2


@pytest.mark.parametrize(
    ("error_type", "status_code"),
    [
        (BadRequestError, 400),
        (AuthenticationError, 401),
        (PermissionDeniedError, 403),
    ],
)
@pytest.mark.asyncio
async def test_does_not_retry_client_errors(
    client: TeacherClient,
    mock_client: MagicMock,
    error_type: type[Exception],
    status_code: int,
) -> None:
    create = _create_mock(mock_client)
    create.side_effect = _status_error(error_type, status_code)

    with pytest.raises(error_type):
        await client.chat([{"role": "user", "content": "Привет"}])

    assert create.await_count == 1


@pytest.mark.asyncio
async def test_empty_content_after_length_raises_clear_error(
    client: TeacherClient, mock_client: MagicMock
) -> None:
    """Reasoning-модель потратила max_tokens на размышления — нужен понятный сигнал."""
    _create_mock(mock_client).return_value = _completion(
        content="", completion_tokens=2048, finish_reason="length"
    )

    with pytest.raises(TeacherAPIError, match="пустой ответ"):
        await client.chat([{"role": "user", "content": "Привет"}])


@pytest.mark.asyncio
async def test_empty_content_with_stop_is_allowed(
    client: TeacherClient, mock_client: MagicMock
) -> None:
    """Пустой content при finish_reason=stop — валидный ответ, решают генераторы."""
    _create_mock(mock_client).return_value = _completion(content="", finish_reason="stop")

    result = await client.chat([{"role": "user", "content": "Привет"}])

    assert result.content == ""
    assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_raises_after_attempts_exhausted(
    client: TeacherClient, mock_client: MagicMock
) -> None:
    create = _create_mock(mock_client)
    create.side_effect = [_status_error(InternalServerError, 500) for _ in range(3)]

    with pytest.raises(InternalServerError):
        await client.chat([{"role": "user", "content": "Привет"}])

    assert create.await_count == 3


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (APIConnectionError(request=httpx2.Request("POST", BASE_URL)), True),
        (APITimeoutError(request=httpx2.Request("POST", BASE_URL)), True),
        (_status_error(RateLimitError, 429), True),
        (_status_error(InternalServerError, 500), True),
        (_status_error(InternalServerError, 502), True),
        (_status_error(BadRequestError, 400), False),
        (_status_error(AuthenticationError, 401), False),
        (_status_error(PermissionDeniedError, 403), False),
        (ValueError("not an api error"), False),
    ],
)
def test_is_retryable_error(error: BaseException, expected: bool) -> None:
    assert is_retryable_error(error) is expected


@pytest.mark.asyncio
async def test_logs_token_usage(client: TeacherClient, mock_client: MagicMock) -> None:
    _create_mock(mock_client).return_value = _completion()
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(message), level="INFO", format="{message}")

    try:
        await client.chat([{"role": "user", "content": "Привет"}])
    finally:
        logger.remove(sink_id)

    assert any("total_tokens=18" in message for message in messages)


@pytest.mark.asyncio
async def test_empty_messages_rejected(client: TeacherClient, mock_client: MagicMock) -> None:
    with pytest.raises(ValueError, match="messages"):
        await client.chat([])

    _create_mock(mock_client).assert_not_awaited()


@pytest.mark.asyncio
async def test_response_without_choices_is_an_error(
    client: TeacherClient, mock_client: MagicMock
) -> None:
    completion = _completion()
    completion.choices = []
    _create_mock(mock_client).return_value = completion

    with pytest.raises(TeacherAPIError):
        await client.chat([{"role": "user", "content": "Привет"}])


@pytest.mark.asyncio
async def test_missing_usage_does_not_crash(client: TeacherClient, mock_client: MagicMock) -> None:
    completion = _completion()
    completion.usage = None
    _create_mock(mock_client).return_value = completion

    result = await client.chat([{"role": "user", "content": "Привет"}])

    assert result.total_tokens == 0


def test_sdk_client_is_built_without_builtin_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Дефолтный SDK пересоздаётся с max_retries=0, иначе ретраи дублируются."""
    factory = MagicMock()
    monkeypatch.setattr(llm_client, "AsyncOpenAI", factory)

    TeacherClient(_provider(), timeout_s=42.0)

    call = factory.call_args
    assert call is not None
    kwargs: dict[str, Any] = dict(call.kwargs)
    assert kwargs["api_key"] == "sk-test"
    assert kwargs["base_url"] == BASE_URL
    assert kwargs["max_retries"] == 0
    assert kwargs["timeout"] == 42.0


@pytest.mark.asyncio
async def test_thinking_is_enabled_by_default(
    client: TeacherClient, mock_client: MagicMock
) -> None:
    """Судья и обычные вызовы не отключают thinking."""
    _create_mock(mock_client).return_value = _completion()

    await client.chat([{"role": "user", "content": "Привет"}])

    call = _create_mock(mock_client).await_args
    assert call is not None
    assert "extra_body" not in call.kwargs


@pytest.mark.asyncio
async def test_disable_thinking_sends_extra_body(mock_client: MagicMock) -> None:
    """Генерация данных передаёт thinking=disabled в тело запроса."""
    client = TeacherClient(
        _provider(),
        client=mock_client,
        max_attempts=1,
        wait_strategy=wait_none(),
        disable_thinking=True,
    )
    _create_mock(mock_client).return_value = _completion()

    await client.chat([{"role": "user", "content": "Привет"}])

    call = _create_mock(mock_client).await_args
    assert call is not None
    assert call.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


@pytest.mark.asyncio
async def test_custom_provider_model_is_forwarded(mock_client: MagicMock) -> None:
    """Клиент использует модель переданного провайдера, а не глобальный конфиг."""
    client = TeacherClient(
        _provider(model="another-model"),
        client=mock_client,
        max_attempts=1,
        wait_strategy=wait_none(),
    )
    create = _create_mock(mock_client)
    create.return_value = _completion()

    await client.chat([{"role": "user", "content": "Привет"}])

    call = create.await_args
    assert call is not None
    assert call.kwargs["model"] == "another-model"


def test_client_exposes_provider_config(mock_client: MagicMock) -> None:
    provider = _provider()

    client = TeacherClient(provider, client=mock_client, max_attempts=1)

    assert client.provider is provider
    assert client.model == MODEL


def test_max_attempts_must_be_positive(mock_client: MagicMock) -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        TeacherClient(_provider(), client=mock_client, max_attempts=0)
