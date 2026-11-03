"""Асинхронный клиент FastAPI для Telegram-бота (T-035)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger
from pydantic import ValidationError

from app.tools import ToolCall

API_DOWN_MESSAGE = (
    "Не удалось связаться с сервером ветеринара. "
    "Проверьте, что API запущен, и попробуйте позже."
)
API_TIMEOUT_MESSAGE = "Ветеринар отвечает слишком долго. Попробуйте ещё раз чуть позже."
MODEL_UNAVAILABLE_MESSAGE = "Модель временно недоступна. Попробуйте позже."
API_ERROR_MESSAGE = "Не удалось получить ответ ветеринара. Попробуйте позже."
EMPTY_RESPONSE_MESSAGE = "Модель не вернула ответ. Попробуйте переформулировать вопрос."


class VetApiError(RuntimeError):
    """Ошибка обращения к FastAPI с готовым сообщением для пользователя."""

    def __init__(self, message: str, *, user_message: str) -> None:
        super().__init__(message)
        self.user_message = user_message


@dataclass(frozen=True)
class ChatResult:
    """Ответ API: текст и уже выполненные вызовы инструментов."""

    content: str
    tool_calls: tuple[ToolCall, ...] = ()


def chat_endpoint(api_url: str) -> str:
    """Привести базовый URL или полный URL к ``/v1/chat/completions``."""
    normalized = api_url.rstrip("/")
    if normalized.endswith("/v1/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def build_payload(
    messages: Sequence[dict[str, str]],
    *,
    model_id: str,
    temperature: float,
    use_rag: bool,
    tools: Sequence[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Собрать тело запроса к OpenAI-совместимому API."""
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [dict(message) for message in messages],
        "temperature": temperature,
        "stream": False,
        "use_rag": use_rag,
    }
    if tools:
        payload["tools"] = [dict(tool) for tool in tools]
    return payload


def parse_chat_response(payload: dict[str, Any]) -> ChatResult:
    """Разобрать ответ API и проверить его структуру.

    Raises:
        VetApiError: ответ пустой или имеет неожиданный формат.
    """
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise VetApiError("API вернул ответ без choices", user_message=EMPTY_RESPONSE_MESSAGE)

    first = choices[0]
    if not isinstance(first, dict):
        raise VetApiError("API вернул некорректный choice", user_message=EMPTY_RESPONSE_MESSAGE)

    message = first.get("message")
    if not isinstance(message, dict):
        raise VetApiError("API вернул ответ без message", user_message=EMPTY_RESPONSE_MESSAGE)

    raw_content = message.get("content")
    content = raw_content.strip() if isinstance(raw_content, str) else ""

    tool_calls: list[ToolCall] = []
    raw_tool_calls = message.get("tool_calls")
    if isinstance(raw_tool_calls, list):
        for raw_call in raw_tool_calls:
            try:
                tool_calls.append(ToolCall.model_validate(raw_call))
            except ValidationError as exc:
                logger.warning("Bot: пропускаю некорректный tool_call — {}", exc)

    if not content and not tool_calls:
        raise VetApiError("API вернул пустой ответ", user_message=EMPTY_RESPONSE_MESSAGE)

    return ChatResult(content=content, tool_calls=tuple(tool_calls))


def _error_detail(response: httpx.Response) -> str:
    """Достать человекочитаемое ``detail`` из ошибки FastAPI."""
    try:
        payload: Any = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""

    detail = payload.get("detail")
    if isinstance(detail, str):
        return detail[:300]
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message[:300]
    return ""


class VetApiClient:
    """HTTP-клиент к ``POST /v1/chat/completions``."""

    def __init__(
        self,
        api_url: str,
        *,
        model_id: str,
        timeout_s: float = 300.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint = chat_endpoint(api_url)
        self._model_id = model_id
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._owns_client = client is None

    async def close(self) -> None:
        """Закрыть HTTP-соединения, если клиент создан внутри."""
        if self._owns_client:
            await self._client.aclose()

    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float,
        use_rag: bool,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> ChatResult:
        """Отправить историю в API и вернуть ответ ассистента.

        Raises:
            VetApiError: API недоступен, вернул HTTP-ошибку или пустой ответ.
        """
        payload = build_payload(
            messages,
            model_id=self._model_id,
            temperature=temperature,
            use_rag=use_rag,
            tools=tools,
        )

        try:
            response = await self._client.post(self._endpoint, json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.warning("Bot: таймаут API — {}", exc)
            raise VetApiError("таймаут API", user_message=API_TIMEOUT_MESSAGE) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = _error_detail(exc.response)
            logger.warning("Bot: API вернул HTTP {} — {}", status, detail)
            if status == 400:
                user_message = (
                    f"Запрос отклонён системой безопасности: {detail}"
                    if detail
                    else "Запрос отклонён системой безопасности."
                )
            elif status == 503:
                user_message = MODEL_UNAVAILABLE_MESSAGE
            else:
                user_message = API_ERROR_MESSAGE
            raise VetApiError(f"HTTP {status}: {detail}", user_message=user_message) from exc
        except httpx.RequestError as exc:
            logger.warning("Bot: API недоступен — {}", exc)
            raise VetApiError("API недоступен", user_message=API_DOWN_MESSAGE) from exc

        try:
            data: Any = response.json()
        except ValueError as exc:
            logger.warning("Bot: API вернул не-JSON — {}", exc)
            raise VetApiError("некорректный JSON API", user_message=API_ERROR_MESSAGE) from exc

        if not isinstance(data, dict):
            raise VetApiError("API вернул не объект", user_message=API_ERROR_MESSAGE)
        return parse_chat_response(data)
