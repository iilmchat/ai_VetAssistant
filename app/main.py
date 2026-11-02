"""OpenAI-совместимый API поверх локальной GGUF-модели (T-022).

Запуск::

    uvicorn app.main:app --host 0.0.0.0 --port 8000

Эндпоинт ``POST /v1/chat/completions`` принимает стандартный OpenAI-формат
(JSON с ``messages``) и поддерживает потоковый ответ (SSE) при
``"stream": true``.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator, Sequence
from functools import lru_cache
from typing import Annotated, Any, Literal, Protocol, cast

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.settings import AppSettings, get_app_settings

DEFAULT_TEMPERATURE = 0.2
DEFAULT_TOP_P = 0.95
DEFAULT_MAX_TOKENS = 1024

#: Системная инструкция ветеринарного ассистента (добавляется, если клиент
#: не передал собственный system message).
VET_SYSTEM_PROMPT = (
    "Ты — ветеринарный ассистент для владельцев животных. Отвечай на русском языке, "
    "кратко и по делу. Не ставь диагноз без осмотра и не назначай лекарства с дозировками; "
    "при опасных симптомах направляй к ветеринарному врачу."
)


class ChatMessage(BaseModel):
    """Сообщение в формате OpenAI."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ChatCompletionRequest(BaseModel):
    """Запрос ``POST /v1/chat/completions``."""

    model_config = ConfigDict(extra="ignore")

    model: str | None = None
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=DEFAULT_TEMPERATURE, ge=0.0, le=2.0)
    top_p: float = Field(default=DEFAULT_TOP_P, gt=0.0, le=1.0)
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=1)
    stream: bool = False


class ResponseMessage(BaseModel):
    """Ответ ассистента внутри choice."""

    role: Literal["assistant"] = "assistant"
    content: str


class ChatCompletionChoice(BaseModel):
    """Один вариант ответа в формате OpenAI."""

    index: int = 0
    message: ResponseMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    """Счётчики токенов (если модель их вернула)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    """Нестриминговый ответ в формате OpenAI."""

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: Usage


class ChatModel(Protocol):
    """Минимальный интерфейс llama-cpp-python, нужный API."""

    def create_chat_completion(self, **kwargs: Any) -> Any: ...


@lru_cache(maxsize=1)
def _load_model() -> ChatModel:
    """Загрузить GGUF один раз на процесс."""
    settings = get_app_settings()
    path = settings.model_path
    if not path.exists():
        raise FileNotFoundError(f"GGUF-модель не найдена: {path}")

    # Импорт внутри функции: llama-cpp-python — тяжёлая опциональная
    # зависимость, тесты API подменяют модель и не должны её грузить.
    from llama_cpp import Llama

    logger.info("Загружаю GGUF-модель: {}", path)
    return cast(
        ChatModel,
        Llama(
            model_path=str(path),
            n_ctx=settings.n_ctx,
            n_threads=settings.n_threads,
            n_gpu_layers=settings.n_gpu_layers,
            verbose=False,
        ),
    )


def get_model() -> ChatModel:
    """FastAPI-зависимость: ленивая загрузка модели.

    В тестах переопределяется через ``app.dependency_overrides``.
    """
    try:
        return _load_model()
    except Exception as exc:
        logger.error("Не удалось загрузить модель: {}", exc)
        raise HTTPException(status_code=503, detail="Модель недоступна") from exc


app = FastAPI(title="VetAssistant API", version="0.1.0")


def build_messages(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    """Добавить ветеринарный system prompt, если клиент его не передал."""
    payload = [message.model_dump() for message in messages]
    if any(message.role == "system" for message in messages):
        return payload
    return [{"role": "system", "content": VET_SYSTEM_PROMPT}, *payload]


def _model_name(request: ChatCompletionRequest, settings: AppSettings) -> str:
    return request.model or settings.model_id


def _generation_kwargs(request: ChatCompletionRequest) -> dict[str, Any]:
    return {
        "temperature": request.temperature,
        "top_p": request.top_p,
        "max_tokens": request.max_tokens,
    }


def _complete(
    model: ChatModel,
    messages: Sequence[dict[str, str]],
    request: ChatCompletionRequest,
    model_name: str,
) -> ChatCompletionResponse:
    """Сгенерировать полный ответ и привести его к формату OpenAI."""
    result = model.create_chat_completion(messages=messages, **_generation_kwargs(request))
    choices = result.get("choices") or []
    if not choices:
        raise HTTPException(status_code=502, detail="Модель вернула пустой ответ")

    choice = choices[0]
    message = choice.get("message") or {}
    usage_payload = result.get("usage") or {}
    usage = Usage(
        prompt_tokens=int(usage_payload.get("prompt_tokens", 0)),
        completion_tokens=int(usage_payload.get("completion_tokens", 0)),
        total_tokens=int(usage_payload.get("total_tokens", 0)),
    )

    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=model_name,
        choices=[
            ChatCompletionChoice(
                message=ResponseMessage(content=str(message.get("content") or "")),
                finish_reason=str(choice.get("finish_reason") or "stop"),
            )
        ],
        usage=usage,
    )


def _stream(
    model: ChatModel,
    messages: Sequence[dict[str, str]],
    request: ChatCompletionRequest,
    model_name: str,
) -> Iterator[str]:
    """Отдать ответ потоком SSE в формате OpenAI."""
    try:
        stream = model.create_chat_completion(
            messages=messages,
            stream=True,
            **_generation_kwargs(request),
        )
        for chunk in stream:
            if isinstance(chunk, dict):
                chunk = {**chunk, "model": model_name}
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    except Exception as exc:
        logger.error("Ошибка потоковой генерации: {}", exc)
        error = {"error": {"message": str(exc), "type": "server_error"}}
        yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@app.get("/health")
def health() -> dict[str, Any]:
    """Проверка живости API и наличия файла модели."""
    settings = get_app_settings()
    return {
        "status": "ok",
        "model": settings.model_id,
        "model_path": str(settings.model_path),
        "model_path_exists": settings.model_path.exists(),
    }


@app.post("/v1/chat/completions", response_model=None)
def chat_completions(
    request: ChatCompletionRequest,
    model: Annotated[ChatModel, Depends(get_model)],
) -> ChatCompletionResponse | StreamingResponse:
    """Сгенерировать ответ модели в формате OpenAI Chat Completions."""
    settings = get_app_settings()
    model_name = _model_name(request, settings)
    messages = build_messages(request.messages)

    if request.stream:
        return StreamingResponse(
            _stream(model, messages, request, model_name),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return _complete(model, messages, request, model_name)
