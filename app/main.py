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
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Any, Literal, Protocol, cast

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from app.database import Database, list_appointments, list_reminders
from app.knowledge import KnowledgeBase, get_knowledge_base, with_rag_context
from app.router import triage_message, with_emergency_instruction
from app.settings import AppSettings, get_app_settings
from app.tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutionError,
    ToolExecutionRequest,
    execute_tool,
    normalize_native_tool_calls,
    parse_tool_calls,
    with_tools_instruction,
)

DEFAULT_TEMPERATURE = 0.2
DEFAULT_TOP_P = 0.95
DEFAULT_MAX_TOKENS = 1024
MAX_AGENT_STEPS = 3

#: Origins React-фронтенда: Vite dev server и Docker/Nginx.
CORS_ALLOWED_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)

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
    use_rag: bool = Field(
        default=False,
        description="Использовать поиск по локальной базе знаний",
    )
    tools: list[ToolDefinition] | None = Field(
        default=None,
        description="OpenAI-совместимые инструменты для Function Calling",
    )


class ResponseMessage(BaseModel):
    """Ответ ассистента внутри choice."""

    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


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


class AppointmentRead(BaseModel):
    """Запись на приём для GET /v1/appointments."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_name: str
    date: str
    time: str


class ReminderRead(BaseModel):
    """Напоминание для GET /v1/reminders."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    time: str


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


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Создать таблицы при старте и закрыть пул БД при остановке."""
    settings = get_app_settings()
    database = Database(settings.database_url)
    application.state.db = database
    await database.create_tables()
    logger.info(
        "БД готова: {}",
        database.engine.url.render_as_string(hide_password=True),
    )
    try:
        yield
    finally:
        await database.dispose()


app = FastAPI(title="VetAssistant API", version="0.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(CORS_ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_database(request: Request) -> Database:
    """FastAPI-зависимость: БД, созданная в lifespan."""
    database = getattr(request.app.state, "db", None)
    if not isinstance(database, Database):
        raise HTTPException(status_code=503, detail="База данных недоступна")
    return database


def build_messages(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    """Добавить ветеринарный system prompt, если клиент его не передал."""
    payload = [message.model_dump() for message in messages]
    if any(message.role == "system" for message in messages):
        return payload
    return [{"role": "system", "content": VET_SYSTEM_PROMPT}, *payload]


def _model_name(request: ChatCompletionRequest, settings: AppSettings) -> str:
    return request.model or settings.model_id


def _last_user_message(messages: Sequence[ChatMessage]) -> str | None:
    """Вернуть текст последнего сообщения пользователя."""
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return None


def _tool_names(request: ChatCompletionRequest) -> set[str]:
    """Имена инструментов, разрешённых в текущем запросе."""
    return {tool.function.name for tool in request.tools or []}


def _generation_kwargs(request: ChatCompletionRequest) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "temperature": request.temperature,
        "top_p": request.top_p,
        "max_tokens": request.max_tokens,
    }
    if request.tools:
        kwargs["tools"] = [tool.model_dump(exclude_none=True) for tool in request.tools]
        kwargs["tool_choice"] = "auto"
    return kwargs


async def _generate_once(
    model: ChatModel,
    messages: Sequence[dict[str, Any]],
    request: ChatCompletionRequest,
    model_name: str,
) -> ChatCompletionResponse:
    """Один вызов модели с приведением ответа к формату OpenAI."""
    result = await run_in_threadpool(
        model.create_chat_completion,
        messages=messages,
        **_generation_kwargs(request),
    )
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

    allowed_tools = _tool_names(request)
    content = str(message.get("content") or "")
    tool_calls = normalize_native_tool_calls(
        message.get("tool_calls"),
        allowed_tools=allowed_tools,
    )
    if request.tools and not tool_calls:
        tool_calls, content = parse_tool_calls(content, allowed_tools=allowed_tools)

    response_content: str | None = content
    if tool_calls and not content:
        response_content = None
    finish_reason = "tool_calls" if tool_calls else str(choice.get("finish_reason") or "stop")

    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=model_name,
        choices=[
            ChatCompletionChoice(
                message=ResponseMessage(
                    content=response_content,
                    tool_calls=tool_calls or None,
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )


async def _execute_tool_calls(
    tool_calls: Sequence[ToolCall],
    *,
    database: Database,
) -> list[dict[str, Any]]:
    """Выполнить вызовы и сформировать сообщения с ролью ``tool``."""
    messages: list[dict[str, Any]] = []
    async with database.session() as session:
        for tool_call in tool_calls:
            name = tool_call.function.name
            try:
                result = await execute_tool(
                    name,
                    tool_call.function.arguments,
                    session=session,
                )
            except ToolExecutionError as exc:
                logger.warning("Agent: инструмент {} не выполнен — {}", name, exc)
                result = {"status": "error", "message": str(exc)}
            except Exception as exc:
                logger.exception("Agent: ошибка выполнения инструмента {}", name)
                result = {
                    "status": "error",
                    "message": f"Ошибка выполнения инструмента {name}: {exc}",
                }

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
    return messages


async def _complete(
    model: ChatModel,
    messages: Sequence[dict[str, Any]],
    request: ChatCompletionRequest,
    model_name: str,
    *,
    database: Database,
) -> ChatCompletionResponse:
    """Сгенерировать ответ, выполняя tool_calls в agentic loop."""
    working = [dict(message) for message in messages]
    executed: list[ToolCall] = []
    response = await _generate_once(model, working, request, model_name)

    for _ in range(MAX_AGENT_STEPS):
        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            break

        executed.extend(tool_calls)
        logger.info("Agent: выполняю инструментов: {}", len(tool_calls))
        working.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [tool_call.model_dump() for tool_call in tool_calls],
            }
        )
        working.extend(await _execute_tool_calls(tool_calls, database=database))
        response = await _generate_once(model, working, request, model_name)

    if executed:
        # Оставляем вызовы в ответе как визуальную индикацию для UI.
        response.choices[0].message.tool_calls = executed
    return response


def _sse_chunk(payload: dict[str, Any]) -> str:
    """Сериализовать один SSE-чанк."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_with_tools(
    model: ChatModel,
    messages: Sequence[dict[str, Any]],
    request: ChatCompletionRequest,
    model_name: str,
    *,
    database: Database,
) -> AsyncIterator[str]:
    """Отдать SSE-поток после выполнения agentic loop.

    Модель вызывается без ``stream``, чтобы корректно разобрать tool_calls
    и выполнить инструменты. Финальный текст отдаётся одним чанком; вызовы
    инструментов остаются в ``delta.tool_calls`` как индикация для UI.
    """
    try:
        response = await _complete(
            model,
            messages,
            request,
            model_name,
            database=database,
        )
        message = response.choices[0].message
        delta: dict[str, Any] = {
            "role": "assistant",
            "content": message.content or "",
        }
        if message.tool_calls:
            delta["tool_calls"] = [
                {"index": index, **tool_call.model_dump()}
                for index, tool_call in enumerate(message.tool_calls)
            ]
        yield _sse_chunk(
            {
                "id": response.id,
                "object": "chat.completion.chunk",
                "created": response.created,
                "model": model_name,
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            }
        )
        yield _sse_chunk(
            {
                "id": response.id,
                "object": "chat.completion.chunk",
                "created": response.created,
                "model": model_name,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
        )
    except Exception as exc:
        logger.error("Ошибка генерации с инструментами: {}", exc)
        error = {"error": {"message": str(exc), "type": "server_error"}}
        yield _sse_chunk(error)
    yield "data: [DONE]\n\n"


async def _stream(
    model: ChatModel,
    messages: Sequence[dict[str, Any]],
    request: ChatCompletionRequest,
    model_name: str,
    *,
    database: Database,
) -> AsyncIterator[str]:
    """Отдать ответ потоком SSE в формате OpenAI."""
    if request.tools:
        async for chunk in _stream_with_tools(
            model,
            messages,
            request,
            model_name,
            database=database,
        ):
            yield chunk
        return

    try:
        stream = await run_in_threadpool(
            model.create_chat_completion,
            messages=messages,
            stream=True,
            **_generation_kwargs(request),
        )
        async for chunk in iterate_in_threadpool(stream):
            payload = {**chunk, "model": model_name} if isinstance(chunk, dict) else chunk
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
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
async def chat_completions(
    request: ChatCompletionRequest,
    model: Annotated[ChatModel, Depends(get_model)],
    knowledge: Annotated[KnowledgeBase | None, Depends(get_knowledge_base)],
    database: Annotated[Database, Depends(get_database)],
) -> ChatCompletionResponse | StreamingResponse:
    """Сгенерировать ответ модели в формате OpenAI Chat Completions."""
    # Быстрый триаж до генерации: не тратим ресурсы LLM на prompt injection
    # и сразу помечаем угрожающие жизни случаи.
    user_message = _last_user_message(request.messages) or ""
    triage = triage_message(user_message)
    if triage["injection_detected"]:
        logger.warning("Triage: запрос отклонён — {}", triage["reason"])
        raise HTTPException(
            status_code=400,
            detail=f"Запрос отклонён системой безопасности: {triage['reason']}",
        )
    if triage["is_emergency"]:
        logger.info("Triage: экстренный случай — {}", triage["reason"])

    settings = get_app_settings()
    model_name = _model_name(request, settings)
    messages = build_messages(request.messages)

    if request.use_rag and knowledge is not None:
        query = _last_user_message(request.messages)
        if query:
            try:
                chunks = knowledge.search(query, top_k=settings.rag_top_k)
            except Exception as exc:
                logger.warning("RAG: поиск не удался — {}", exc)
                chunks = []
            if chunks:
                messages = with_rag_context(messages, chunks)
                logger.info("RAG: добавлено чанков: {}", len(chunks))

    if request.tools:
        messages = with_tools_instruction(messages, request.tools)

    # Инструкция добавляется последней, чтобы модель прочитала её после RAG.
    if triage["is_emergency"]:
        messages = with_emergency_instruction(messages)

    if request.stream:
        return StreamingResponse(
            _stream(
                model,
                messages,
                request,
                model_name,
                database=database,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return await _complete(
        model,
        messages,
        request,
        model_name,
        database=database,
    )


@app.get("/v1/appointments", response_model=list[AppointmentRead])
async def get_appointments(
    database: Annotated[Database, Depends(get_database)],
) -> list[AppointmentRead]:
    """Вернуть все записи на приём."""
    async with database.session() as session:
        appointments = await list_appointments(session)
    return [AppointmentRead.model_validate(item) for item in appointments]


@app.get("/v1/reminders", response_model=list[ReminderRead])
async def get_reminders(
    database: Annotated[Database, Depends(get_database)],
) -> list[ReminderRead]:
    """Вернуть все напоминания."""
    async with database.session() as session:
        reminders = await list_reminders(session)
    return [ReminderRead.model_validate(item) for item in reminders]


@app.post("/v1/tools/execute")
async def execute_tool_endpoint(
    request: ToolExecutionRequest,
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, str]:
    """Выполнить инструмент и сохранить результат в БД."""
    logger.info("Tool execute: name={} arguments={}", request.name, request.arguments)
    async with database.session() as session:
        try:
            return await execute_tool(
                request.name,
                request.arguments,
                session=session,
            )
        except ToolExecutionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
