"""Инференс-бэкенды VetAssistant: GPU через LM Studio и CPU через llama.cpp (T-144).

GPU-бэкенд ходит в LM Studio по OpenAI-совместимому HTTP-протоколу
(``/v1/models``, ``/v1/chat/completions``, SSE). CPU-бэкенд оставляет текущий
путь на ``llama-cpp-python`` и удерживает общий ``threading.Lock`` (T-143/H-1):
одновременно с одним Llama-контекстом может работать только один вызов.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator, Callable, Generator, Iterable
from contextlib import suppress
from typing import Any, Protocol, cast

import httpx
from loguru import logger
from starlette.concurrency import run_in_threadpool

from app.inference_usage import StreamUsageTracker
from app.settings import AppSettings

#: Глобальный лок CPU-инференса: llama-cpp-python не потокобезопасен.
_GENERATION_LOCK = threading.Lock()

#: Сентинел завершения потока-продюсера SSE.
_STREAM_DONE = object()


class ChatModel(Protocol):
    """Минимальный интерфейс llama-cpp-python, нужный API."""

    def create_chat_completion(self, **kwargs: Any) -> Any: ...


class InferenceBackend(Protocol):
    """Общий интерфейс инференс-бэкенда (GPU/CPU)."""

    name: str

    async def probe(self) -> bool:
        """Проверить доступность бэкенда."""
        ...

    async def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        """Выполнить нестриминговую генерацию."""
        ...

    def stream_chat_completion(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """Выполнить потоковую генерацию и отдать чанки."""
        ...

    async def aclose(self) -> None:
        """Освободить ресурсы бэкенда."""
        ...


def _locked_chat_completion(model: ChatModel, **kwargs: Any) -> Any:
    """Вызвать ``create_chat_completion`` под глобальным локом (T-143/H-1)."""
    with _GENERATION_LOCK:
        return model.create_chat_completion(**kwargs)


def _locked_stream_chunks(model: ChatModel, **kwargs: Any) -> Generator[Any, None, None]:
    """Итератор стрима, удерживающий лок на всё время генерации.

    ``create_chat_completion(stream=True)`` возвращает ленивый генератор:
    генерация идёт при итерации, поэтому лок нельзя отпускать после
    создания генератора — он должен жить до последнего чанка.
    """
    stream = cast(Iterable[Any], model.create_chat_completion(**kwargs))
    with _GENERATION_LOCK:
        yield from stream


async def _iterate_locked_stream(model: ChatModel, **kwargs: Any) -> AsyncIterator[Any]:
    """Отдавать чанки CPU-стрима в event loop, не блокируя его локом.

    ``threading.Lock`` нельзя удерживать в корутине: это остановит весь
    сервер. Поток-продюсер держит лок, генерирует чанки и складывает их в
    ``asyncio.Queue``; event loop только читает очередь.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue()
    stop = threading.Event()

    def deliver(item: Any) -> None:
        with suppress(RuntimeError):
            # Event loop уже закрыт (остановка приложения) — терять нечего.
            loop.call_soon_threadsafe(queue.put_nowait, item)

    def produce() -> None:
        stream = _locked_stream_chunks(model, **kwargs)
        try:
            for chunk in stream:
                if stop.is_set():
                    break
                deliver(chunk)
        except BaseException as exc:
            # В том числе GeneratorExit/KeyboardInterrupt: потребитель должен
            # получить ошибку, а не зависнуть в ожидании _STREAM_DONE.
            deliver(exc)
        finally:
            try:
                stream.close()
            finally:
                deliver(_STREAM_DONE)

    threading.Thread(target=produce, name="llm-stream", daemon=True).start()
    try:
        while True:
            item = await queue.get()
            if item is _STREAM_DONE:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        # Клиент отключился: просим продюсер остановиться после текущего чанка.
        stop.set()


class CpuLlamaBackend:
    """CPU-инференс на локальной GGUF-модели через llama-cpp-python."""

    name = "cpu"

    def __init__(
        self,
        *,
        model: ChatModel | None = None,
        model_factory: Callable[[], ChatModel] | None = None,
    ) -> None:
        if (model is None) == (model_factory is None):
            raise ValueError("Нужен ровно один из аргументов: model или model_factory")
        self._model = model
        self._model_factory = model_factory
        self._load_lock = threading.Lock()

    def _get_model(self) -> ChatModel:
        """Лениво загрузить GGUF: при живом GPU модель в память не тянем."""
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    if self._model_factory is None:  # pragma: no cover - защита типа
                        raise RuntimeError("Фабрика CPU-модели не задана")
                    self._model = self._model_factory()
        return self._model

    async def probe(self) -> bool:
        """CPU-бэкенд доступен, пока жив процесс API."""
        return True

    async def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        result = await run_in_threadpool(
            _locked_chat_completion,
            self._get_model(),
            **kwargs,
        )
        return cast(dict[str, Any], result)

    async def stream_chat_completion(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """Стрим CPU-модели с подсчётом токенов (T-138).

        ``llama-cpp-python`` не отдаёт ``usage`` в стриме, поэтому после
        последнего чанка добавляется синтетический usage-чанк. Токены считает
        :class:`StreamUsageTracker`: ``n_tokens`` модели и её tokenizer.
        """
        model = self._get_model()
        tracker = StreamUsageTracker(model, kwargs.get("messages"))
        last_chunk: dict[str, Any] | None = None

        async for chunk in _iterate_locked_stream(model, **kwargs):
            if isinstance(chunk, dict):
                typed_chunk = cast(dict[str, Any], chunk)
                tracker.observe(typed_chunk)
                last_chunk = typed_chunk
                yield typed_chunk

        usage = tracker.finalize()
        base = last_chunk or {}
        yield {
            "id": base.get("id", "chatcmpl-usage"),
            "object": "chat.completion.chunk",
            "created": base.get("created", int(time.time())),
            "model": base.get("model", kwargs.get("model") or ""),
            "choices": [],
            "usage": usage.as_dict(),
        }

    async def aclose(self) -> None:
        """Освобождать нечего: модель живёт до остановки процесса."""
        return None


class GpuHttpBackend:
    """GPU-инференс через LM Studio (OpenAI-совместимый HTTP)."""

    name = "gpu"

    def __init__(
        self,
        settings: AppSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._base = settings.gpu_backend_base.rstrip("/")
        self._api_key = settings.gpu_backend_api_key.strip()
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                300.0,
                connect=settings.gpu_backend_probe_timeout_s,
            )
        )
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        """Заданы ли base и токен LM Studio."""
        return bool(self._base and self._api_key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def probe(self) -> bool:
        """Проверить LM Studio через ``GET /models``."""
        if not self.configured:
            logger.debug("GPU backend: base/API key не заданы — probe пропущен")
            return False
        try:
            response = await self._client.get(
                f"{self._base}/models",
                headers=self._headers(),
                timeout=self._settings.gpu_backend_probe_timeout_s,
            )
        except httpx.HTTPError as exc:
            logger.warning("GPU backend: probe не удался — {}", type(exc).__name__)
            return False
        return response.status_code == 200

    async def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        """POST ``/chat/completions`` без стрима."""
        payload = dict(kwargs)
        payload.setdefault("model", self._settings.gpu_backend_model)
        response = await self._client.post(
            f"{self._base}/chat/completions",
            json=payload,
            headers=self._headers(),
        )
        response.raise_for_status()
        data: Any = response.json()
        if not isinstance(data, dict):
            raise ValueError("GPU backend вернул не объект JSON")
        return cast(dict[str, Any], data)

    async def stream_chat_completion(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        """POST ``/chat/completions`` со ``stream=true`` и разбор SSE."""
        payload = {**kwargs, "stream": True}
        payload.setdefault("model", self._settings.gpu_backend_model)
        # T-138: просим LM Studio прислать финальный usage-чанк. Без
        # OpenAI-совместимого stream_options.include_usage токены стрима не
        # попадают ни в SSE-ответ, ни в метрики (проверено 2026-11-09).
        payload.setdefault("stream_options", {"include_usage": True})
        async with self._client.stream(
            "POST",
            f"{self._base}/chat/completions",
            json=payload,
            headers=self._headers(),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                chunk = _parse_sse_line(line)
                if chunk is not None:
                    # Финальный usage-чанк (stream_options.include_usage)
                    # пробрасываем как есть: main.py извлечёт usage, запишет
                    # метрики и отдаст клиенту отдельным чанком.
                    yield chunk

    async def aclose(self) -> None:
        """Закрыть HTTP-клиент, если он создан внутри бэкенда."""
        if self._owns_client:
            await self._client.aclose()


def _parse_sse_line(line: str) -> dict[str, Any] | None:
    """Разобрать одну строку SSE; вернуть ``None`` для служебных строк."""
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        return None
    if not stripped.startswith("data:"):
        return None
    data = stripped[len("data:") :].strip()
    if not data or data == "[DONE]":
        return None
    try:
        chunk: Any = json.loads(data)
    except json.JSONDecodeError:
        logger.warning("GPU backend: пропускаю невалидный SSE-чанк")
        return None
    if not isinstance(chunk, dict):
        return None
    return cast(dict[str, Any], chunk)
