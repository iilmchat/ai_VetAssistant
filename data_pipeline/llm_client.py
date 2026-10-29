"""Слой абстракции API учителя (T-002).

Единственный модуль, который знает про OpenAI SDK. Остальной пайплайн
работает с :class:`TeacherClient` и :class:`ChatResult`, поэтому смена
провайдера — это правка `.env`, а не кода (Design §3.3).

Ретраи выполняет только ``tenacity``: у SDK отключены собственные ретраи
(``max_retries=0``), иначе повторы складывались бы и поведение было бы
непредсказуемым.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from loguru import logger
from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)
from tenacity.wait import wait_base

from configs.settings import ProviderConfig

#: Сообщение чата в упрощённом виде: ``{"role": ..., "content": ...}``.
Message = Mapping[str, str]


class TeacherAPIError(RuntimeError):
    """Учитель вернул ответ, который нельзя использовать (пустой/битый)."""


def is_retryable_error(exc: BaseException) -> bool:
    """Ретраить ли ошибку.

    Повторяем только то, что имеет шанс пройти со второй попытки:
    сетевые сбои и таймауты, 429 (rate limit) и 5xx. Ошибки 400/401/403 —
    это проблемы запроса или ключа, повтор их не исправит (T-002).
    """
    if isinstance(exc, APIConnectionError):
        # APITimeoutError наследуется от APIConnectionError.
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _log_retry(retry_state: RetryCallState, max_attempts: int) -> None:
    """Пишем в лог каждую повторную попытку с причиной."""
    outcome = retry_state.outcome
    error = outcome.exception() if outcome is not None else None
    logger.warning(
        "Повтор запроса к учителю: попытка {}/{} после ошибки {}",
        retry_state.attempt_number + 1,
        max_attempts,
        type(error).__name__,
    )


@dataclass(frozen=True, slots=True)
class ChatResult:
    """Результат одного успешного обращения к учителю."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_s: float
    attempts: int
    finish_reason: str | None = None


class TeacherClient:
    """Async-обёртка над OpenAI-совместимым API одного провайдера.

    Конфигурация передаётся снаружи (`ProviderConfig`), поэтому клиент не
    зависит от глобальных настроек и легко переключается между primary и
    fallback (T-008).

    Пример::

        provider = get_provider("primary")
        async with TeacherClient(provider) as client:
            result = await client.chat([{"role": "user", "content": "Привет"}])
            logger.info(result.content)
    """

    def __init__(
        self,
        provider: ProviderConfig,
        *,
        client: AsyncOpenAI | None = None,
        max_attempts: int = 3,
        timeout_s: float = 60.0,
        wait_strategy: wait_base | None = None,
    ) -> None:
        """Создать клиент.

        Args:
            provider: конфигурация провайдера (ключ, base_url, модель).
            client: готовый `AsyncOpenAI` (для тестов и переиспользования соединений).
            max_attempts: общее число попыток на один запрос (>= 1).
            timeout_s: таймаут одного HTTP-запроса в секундах.
            wait_strategy: стратегия паузы между попытками (в тестах — `wait_none()`).
        """
        if max_attempts < 1:
            raise ValueError("max_attempts должен быть >= 1")

        self._provider = provider
        self._max_attempts = max_attempts
        self._wait = (
            wait_strategy
            if wait_strategy is not None
            else wait_exponential_jitter(initial=1.0, max=20.0)
        )
        self._owns_client = client is None
        self._client = client if client is not None else self._build_client(timeout_s)

    def _build_client(self, timeout_s: float) -> AsyncOpenAI:
        """Собрать SDK-клиент из конфигурации провайдера."""
        return AsyncOpenAI(
            api_key=self._provider.api_key.get_secret_value(),
            base_url=self._provider.base_url,
            timeout=timeout_s,
            max_retries=0,
        )

    @property
    def provider(self) -> ProviderConfig:
        """Конфигурация провайдера, с которой работает клиент."""
        return self._provider

    @property
    def model(self) -> str:
        """Идентификатор модели провайдера."""
        return self._provider.model

    async def __aenter__(self) -> TeacherClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Закрыть HTTP-соединения, если клиент создан самим `TeacherClient`."""
        if self._owns_client:
            await self._client.close()

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Mapping[str, Any] | None = None,
    ) -> ChatResult:
        """Отправить сообщения учителю и вернуть ответ с метриками.

        Args:
            messages: история чата (``role``/``content``).
            temperature: температура сэмплирования; `None` — не передавать.
            max_tokens: лимит токенов ответа; `None` — не передавать.
            response_format: например ``{"type": "json_object"}``.

        Raises:
            TeacherAPIError: учитель вернул ответ без `choices`.
            openai.OpenAIError: ошибка API не была ретраена или попытки кончились.
        """
        if not messages:
            raise ValueError("messages не может быть пустым")

        request: dict[str, Any] = {
            "model": self._provider.model,
            "messages": cast("list[ChatCompletionMessageParam]", [dict(m) for m in messages]),
        }
        if temperature is not None:
            request["temperature"] = temperature
        if max_tokens is not None:
            request["max_tokens"] = max_tokens
        if response_format is not None:
            request["response_format"] = dict(response_format)

        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=self._wait,
            retry=retry_if_exception(is_retryable_error),
            before_sleep=lambda state: _log_retry(state, self._max_attempts),
            reraise=True,
        )

        completion: ChatCompletion | None = None
        latency_s = 0.0
        attempts = 0
        async for attempt in retrying:
            with attempt:
                attempts = attempt.retry_state.attempt_number
                completion, latency_s = await self._call_once(request)

        if completion is None:  # pragma: no cover - недостижимо при reraise=True
            raise TeacherAPIError("Учитель не вернул ответ")

        return self._to_result(completion, latency_s=latency_s, attempts=attempts)

    async def _call_once(self, request: Mapping[str, Any]) -> tuple[ChatCompletion, float]:
        """Один HTTP-запрос с замером latency (без учёта пауз между ретраями)."""
        started = time.perf_counter()
        completion = await self._client.chat.completions.create(**request)
        return completion, time.perf_counter() - started

    def _to_result(
        self,
        completion: ChatCompletion,
        *,
        latency_s: float,
        attempts: int,
    ) -> ChatResult:
        """Разобрать ответ SDK, залогировать токены и вернуть `ChatResult`."""
        if not completion.choices:
            raise TeacherAPIError("Учитель вернул ответ без choices")

        content = completion.choices[0].message.content or ""
        finish_reason = completion.choices[0].finish_reason
        model = completion.model or self._provider.model

        usage = completion.usage
        if usage is None:
            logger.warning("Провайдер не вернул usage: токены неизвестны (model={})", model)

        # Reasoning-модели (например, deepseek-flash) тратят max_tokens на
        # скрытые reasoning-токены. Если лимит исчерпан до ответа, content пуст,
        # а finish_reason == "length" — без этой проверки ошибка выглядела бы
        # как «модель вернула пустоту».
        if not content and finish_reason == "length":
            raise TeacherAPIError(
                "Провайдер израсходовал max_tokens на reasoning и вернул пустой ответ; "
                "увеличьте max_tokens или отключите reasoning у модели "
                f"(model={model}, completion_tokens={usage.completion_tokens if usage else 0})"
            )

        result = ChatResult(
            content=content,
            model=model,
            prompt_tokens=usage.prompt_tokens if usage is not None else 0,
            completion_tokens=usage.completion_tokens if usage is not None else 0,
            total_tokens=usage.total_tokens if usage is not None else 0,
            latency_s=latency_s,
            attempts=attempts,
            finish_reason=finish_reason,
        )

        logger.info(
            "Учитель ответил: model={} prompt_tokens={} completion_tokens={} "
            "total_tokens={} latency={:.2f}s attempts={} finish={}",
            result.model,
            result.prompt_tokens,
            result.completion_tokens,
            result.total_tokens,
            result.latency_s,
            result.attempts,
            result.finish_reason,
        )
        return result
