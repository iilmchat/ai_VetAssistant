"""HTTP-клиент Streamlit-интерфейса VetAssistant (T-025).

Вынесен отдельно от `app/ui.py`, чтобы парсинг SSE и сборку запроса можно
было тестировать без запуска Streamlit.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

import requests

DEFAULT_API_URL = "http://127.0.0.1:8000/v1/chat/completions"
DEFAULT_MODEL_ID = "qwen3-8b-vet"
DEFAULT_TIMEOUT_S = 300.0


def build_payload(
    messages: Sequence[dict[str, str]],
    *,
    model_id: str,
    temperature: float,
    use_rag: bool = False,
) -> dict[str, Any]:
    """Собрать тело запроса к OpenAI-совместимому API."""
    return {
        "model": model_id,
        "messages": [dict(message) for message in messages],
        "temperature": temperature,
        "stream": True,
        "use_rag": use_rag,
    }


def parse_sse_line(line: str) -> str | None:
    """Вернуть текстовую дельту из строки SSE или ``None``."""
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
    return content if isinstance(content, str) and content else None


def stream_chat(
    messages: Sequence[dict[str, str]],
    *,
    temperature: float,
    use_rag: bool = False,
    api_url: str = DEFAULT_API_URL,
    model_id: str = DEFAULT_MODEL_ID,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Iterator[str]:
    """Потоково запросить ответ API и отдавать текстовые дельты.

    Raises:
        requests.RequestException: сервер недоступен, таймаут или HTTP-ошибка.
    """
    payload = build_payload(
        messages,
        model_id=model_id,
        temperature=temperature,
        use_rag=use_rag,
    )
    with requests.post(
        api_url,
        json=payload,
        stream=True,
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines():
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if line.strip() == "data: [DONE]":
                break
            content = parse_sse_line(line)
            if content is not None:
                yield content
