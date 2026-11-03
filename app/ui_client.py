"""HTTP-клиент Streamlit-интерфейса VetAssistant (T-025).

Вынесен отдельно от `app/ui.py`, чтобы парсинг SSE и сборку запроса можно
было тестировать без запуска Streamlit.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import requests

from app.settings import DEFAULT_MODEL_ID, DEFAULT_UI_API_URL, DEFAULT_UI_TIMEOUT_S
from app.tools import ToolCall, ToolCallFunction

DEFAULT_API_URL = DEFAULT_UI_API_URL
DEFAULT_TIMEOUT_S = DEFAULT_UI_TIMEOUT_S


def api_base_url(api_url: str = DEFAULT_API_URL) -> str:
    """Получить базовый URL API из полного URL chat/completions."""
    normalized = api_url.rstrip("/")
    suffix = "/v1/chat/completions"
    if normalized.endswith(suffix):
        return normalized[: -len(suffix)]
    return normalized


def auth_headers(token: str | None = None) -> dict[str, str]:
    """Заголовок Authorization для защищённых запросов."""
    return {"Authorization": f"Bearer {token}"} if token else {}


def _auth_request(
    api_url: str,
    path: str,
    *,
    email: str,
    password: str,
    timeout: float,
) -> dict[str, Any]:
    """Выполнить register/login и проверить наличие токена."""
    response = requests.post(
        f"{api_base_url(api_url)}{path}",
        json={"email": email, "password": password},
        timeout=timeout,
    )
    response.raise_for_status()
    payload: Any = response.json()
    if not isinstance(payload, dict) or not isinstance(
        payload.get("access_token"), str
    ):
        raise ValueError("API не вернул access_token")
    return payload


def login(
    api_url: str = DEFAULT_API_URL,
    *,
    email: str,
    password: str,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Войти и получить JWT для Streamlit-сессии."""
    return _auth_request(
        api_url,
        "/v1/auth/login",
        email=email,
        password=password,
        timeout=timeout,
    )


def register(
    api_url: str = DEFAULT_API_URL,
    *,
    email: str,
    password: str,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Зарегистрироваться и получить JWT для Streamlit-сессии."""
    return _auth_request(
        api_url,
        "/v1/auth/register",
        email=email,
        password=password,
        timeout=timeout,
    )


@dataclass(frozen=True)
class ChatStreamEvent:
    """Событие SSE: текст и/или вызов инструмента."""

    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


def build_payload(
    messages: Sequence[dict[str, str]],
    *,
    model_id: str,
    temperature: float,
    use_rag: bool = False,
    tools: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Собрать тело запроса к OpenAI-совместимому API."""
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [dict(message) for message in messages],
        "temperature": temperature,
        "stream": True,
        "use_rag": use_rag,
    }
    if tools:
        payload["tools"] = [dict(tool) for tool in tools]
    return payload


def parse_sse_event(line: str) -> ChatStreamEvent | None:
    """Разобрать строку SSE в текст и/или вызовы инструментов."""
    prefix = "data: "
    if not line.startswith(prefix):
        return None

    data = line[len(prefix) :].strip()
    if not data or data == "[DONE]":
        return None

    try:
        payload: Any = json.loads(data)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None

    delta = first.get("delta")
    if not isinstance(delta, dict):
        return None

    content = delta.get("content")
    if not isinstance(content, str) or not content:
        content = None

    tool_calls: list[ToolCall] = []
    raw_calls = delta.get("tool_calls")
    if isinstance(raw_calls, list):
        for index, raw_call in enumerate(raw_calls):
            if not isinstance(raw_call, dict):
                continue
            function = raw_call.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            call_id = raw_call.get("id")
            if not isinstance(call_id, str) or not call_id:
                call_id = f"call_{index}"
            arguments = function.get("arguments")
            if not isinstance(arguments, str):
                arguments = json.dumps(
                    arguments if arguments is not None else {},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    function=ToolCallFunction(name=name, arguments=arguments),
                )
            )

    if content is None and not tool_calls:
        return None
    return ChatStreamEvent(content=content, tool_calls=tuple(tool_calls))


def parse_sse_line(line: str) -> str | None:
    """Вернуть текстовую дельту из строки SSE или ``None``."""
    event = parse_sse_event(line)
    return event.content if event is not None else None


def stream_chat_events(
    messages: Sequence[dict[str, str]],
    *,
    temperature: float,
    use_rag: bool = False,
    tools: Sequence[dict[str, Any]] | None = None,
    api_url: str = DEFAULT_API_URL,
    model_id: str = DEFAULT_MODEL_ID,
    timeout: float = DEFAULT_TIMEOUT_S,
    token: str | None = None,
) -> Iterator[ChatStreamEvent]:
    """Потоково запросить ответ API и отдавать текст/вызовы инструментов.

    Raises:
        requests.RequestException: сервер недоступен, таймаут или HTTP-ошибка.
    """
    payload = build_payload(
        messages,
        model_id=model_id,
        temperature=temperature,
        use_rag=use_rag,
        tools=tools,
    )
    with requests.post(
        api_url,
        json=payload,
        headers=auth_headers(token),
        stream=True,
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines():
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if line.strip() == "data: [DONE]":
                break
            event = parse_sse_event(line)
            if event is not None:
                yield event


def stream_chat(
    messages: Sequence[dict[str, str]],
    *,
    temperature: float,
    use_rag: bool = False,
    tools: Sequence[dict[str, Any]] | None = None,
    api_url: str = DEFAULT_API_URL,
    model_id: str = DEFAULT_MODEL_ID,
    timeout: float = DEFAULT_TIMEOUT_S,
    token: str | None = None,
) -> Iterator[str]:
    """Потоково запросить ответ API и отдавать только текстовые дельты."""
    for event in stream_chat_events(
        messages,
        temperature=temperature,
        use_rag=use_rag,
        tools=tools,
        api_url=api_url,
        model_id=model_id,
        timeout=timeout,
        token=token,
    ):
        if event.content is not None:
            yield event.content


def _get_json_list(
    url: str,
    *,
    timeout: float,
    token: str | None = None,
) -> list[dict[str, Any]]:
    """GET-запрос, возвращающий список объектов."""
    response = requests.get(url, headers=auth_headers(token), timeout=timeout)
    response.raise_for_status()
    payload: Any = response.json()
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def fetch_appointments(
    api_url: str = DEFAULT_API_URL,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    token: str | None = None,
) -> list[dict[str, Any]]:
    """Получить записи на приём через ``GET /v1/appointments``."""
    return _get_json_list(
        f"{api_base_url(api_url)}/v1/appointments",
        timeout=timeout,
        token=token,
    )


def fetch_reminders(
    api_url: str = DEFAULT_API_URL,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    token: str | None = None,
) -> list[dict[str, Any]]:
    """Получить напоминания через ``GET /v1/reminders``."""
    return _get_json_list(
        f"{api_base_url(api_url)}/v1/reminders",
        timeout=timeout,
        token=token,
    )
