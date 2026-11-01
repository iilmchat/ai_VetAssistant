"""Слой абстракции API учителя (T-002).

Единственный модуль, который знает про OpenAI SDK. Остальной пайплайн
работает с :class:`TeacherClient` и :class:`ChatResult`, поэтому смена
провайдера — это правка `.env`, а не кода (Design §3.3).

Ретраи выполняет только ``tenacity``: у SDK отключены собственные ретраи
(``max_retries=0``), иначе повторы складывались бы и поведение было бы
непредсказуемым.
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import httpx2
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

from configs.settings import GigaChatConfig, ProviderConfig, ProviderSpec

#: Сообщение чата в упрощённом виде: ``{"role": ..., "content": ...}``.
Message = Mapping[str, str]

#: Тело для отключения thinking-режима DeepSeek при генерации данных.
#: Судья (LLM-Judge) этот флаг не передаёт и работает с включённым thinking.
THINKING_DISABLED_BODY: Mapping[str, Any] = {"thinking": {"type": "disabled"}}


class TeacherAPIError(RuntimeError):
    """Учитель вернул ответ, который нельзя использовать (пустой/битый)."""


#: GigaChat выдаёт access_token на 30 минут; обновляемся заранее.
GIGACHAT_TOKEN_TTL_S = 30 * 60
GIGACHAT_REFRESH_MARGIN_S = 60.0

#: AsyncOpenAI требует непустой api_key; для GigaChat он заменяется OAuth-токеном.
GIGACHAT_PLACEHOLDER_API_KEY = "gigachat-oauth"

#: Запасной срок жизни токена, если OAuth не вернул ``expires_at``.
GIGACHAT_FALLBACK_TOKEN_TTL_S = float(GIGACHAT_TOKEN_TTL_S)


@dataclass(frozen=True, slots=True)
class _OAuthToken:
    """OAuth-токен GigaChat и момент его истечения (epoch seconds)."""

    value: str
    expires_at: float


def _expires_at_seconds(raw: object) -> float:
    """Перевести ``expires_at`` GigaChat (миллисекунды) в epoch seconds."""
    if isinstance(raw, (int, float)):
        value = float(raw)
        # GigaChat отдаёт миллисекунды (≈1.7e12), но допускаем и секунды.
        return value / 1000.0 if value > 1e11 else value
    return time.time() + GIGACHAT_FALLBACK_TOKEN_TTL_S


class _GigaChatAuth:
    """Ленивый OAuth-клиент GigaChat с кешем и защитой от гонок.

    Токен запрашивается при первом обращении и обновляется за
    :data:`GIGACHAT_REFRESH_MARGIN_S` секунд до истечения. ``asyncio.Lock``
    гарантирует, что при конкурентных запросах OAuth вызовется один раз.
    """

    def __init__(
        self,
        provider: GigaChatConfig,
        *,
        client: httpx2.AsyncClient | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._provider = provider
        self._owns_client = client is None
        self._client = client if client is not None else httpx2.AsyncClient(timeout=timeout_s)
        self._token: _OAuthToken | None = None
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        """Закрыть OAuth-соединение, если клиент создан нами."""
        if self._owns_client:
            await self._client.aclose()

    def _is_valid(self) -> bool:
        return (
            self._token is not None
            and self._token.expires_at - time.time() > GIGACHAT_REFRESH_MARGIN_S
        )

    async def access_token(self, *, force_refresh: bool = False) -> str:
        """Вернуть действующий токен, при необходимости запросив новый."""
        async with self._lock:
            if not force_refresh and self._is_valid():
                assert self._token is not None  # сужено _is_valid()
                return self._token.value

            self._token = await self._request_token()
            logger.info(
                "GigaChat OAuth: получен access_token, действует до {}",
                time.strftime("%H:%M:%S", time.localtime(self._token.expires_at)),
            )
            return self._token.value

    async def _request_token(self) -> _OAuthToken:
        """Запросить access_token по client_credentials (RFC 6749)."""
        client_id = self._provider.client_id.get_secret_value()
        client_secret = self._provider.client_secret.get_secret_value()
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {basic}",
        }
        try:
            response = await self._client.post(
                self._provider.oauth_url,
                data={"scope": self._provider.scope},
                headers=headers,
            )
            response.raise_for_status()
        except httpx2.HTTPError as exc:
            raise TeacherAPIError(f"GigaChat OAuth недоступен: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise TeacherAPIError("GigaChat OAuth вернул не-JSON ответ") from exc

        token = payload.get("access_token") if isinstance(payload, Mapping) else None
        if not isinstance(token, str) or not token:
            raise TeacherAPIError("GigaChat OAuth не вернул access_token")

        expires_at = _expires_at_seconds(payload.get("expires_at"))
        return _OAuthToken(value=token, expires_at=expires_at)


#: HTTP-статусы, при которых повторять/продолжать бессмысленно: ключ, доступ, баланс.
FATAL_PROVIDER_STATUSES = frozenset({401, 402, 403})


def is_fatal_provider_error(exc: BaseException) -> bool:
    """Ошибка ключа/доступа/баланса — прогон нужно немедленно остановить."""
    return isinstance(exc, APIStatusError) and exc.status_code in FATAL_PROVIDER_STATUSES


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
        provider: ProviderSpec,
        *,
        client: AsyncOpenAI | None = None,
        oauth_client: httpx2.AsyncClient | None = None,
        max_attempts: int = 3,
        timeout_s: float = 60.0,
        wait_strategy: wait_base | None = None,
        disable_thinking: bool = False,
    ) -> None:
        """Создать клиент.

        Args:
            provider: конфигурация провайдера (ключ, base_url, модель).
            client: готовый `AsyncOpenAI` (для тестов и переиспользования соединений).
            oauth_client: готовый HTTP-клиент для OAuth GigaChat (для тестов;
                по умолчанию создаётся собственный).
            max_attempts: общее число попыток на один запрос (>= 1).
            timeout_s: таймаут одного HTTP-запроса в секундах.
            wait_strategy: стратегия паузы между попытками (в тестах — `wait_none()`).
            disable_thinking: отключить thinking-режим DeepSeek (только для
                генерации данных; судья должен работать с включённым thinking).
                Для GigaChat и других провайдеров параметр игнорируется.
        """
        if max_attempts < 1:
            raise ValueError("max_attempts должен быть >= 1")

        self._provider = provider
        self._max_attempts = max_attempts
        self._disable_thinking = disable_thinking
        self._wait = (
            wait_strategy
            if wait_strategy is not None
            else wait_exponential_jitter(initial=1.0, max=20.0)
        )
        self._gigachat = (
            _GigaChatAuth(provider, client=oauth_client, timeout_s=timeout_s)
            if isinstance(provider, GigaChatConfig)
            else None
        )
        self._owns_client = client is None
        self._client = client if client is not None else self._build_client(timeout_s)

    def _build_client(self, timeout_s: float) -> AsyncOpenAI:
        """Собрать SDK-клиент из конфигурации провайдера."""
        api_key = (
            self._provider.api_key.get_secret_value()
            if isinstance(self._provider, ProviderConfig)
            else GIGACHAT_PLACEHOLDER_API_KEY
        )
        return AsyncOpenAI(
            api_key=api_key,
            base_url=self._provider.base_url,
            timeout=timeout_s,
            max_retries=0,
        )

    @property
    def provider(self) -> ProviderSpec:
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
        """Закрыть HTTP-соединения, созданные самим `TeacherClient`."""
        if self._owns_client:
            await self._client.close()
        if self._gigachat is not None:
            await self._gigachat.aclose()

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
        # thinking — особенность DeepSeek; GigaChat и другие его не понимают.
        if (
            self._disable_thinking
            and isinstance(self._provider, ProviderConfig)
            and self._provider.thinking_mode == "deepseek"
        ):
            request["extra_body"] = dict(THINKING_DISABLED_BODY)

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
        if self._gigachat is not None:
            await self._authorize_gigachat()

        started = time.perf_counter()
        try:
            completion = await self._client.chat.completions.create(**request)
        except APIStatusError as exc:
            # Токен мог истечь между проверкой и запросом: обновляем и повторяем
            # один раз. Повторные 401 обрабатывает обычная политика ошибок.
            if self._gigachat is not None and exc.status_code == 401:
                logger.warning("GigaChat отклонил OAuth-токен (401), обновляю токен")
                await self._authorize_gigachat(force_refresh=True)
                completion = await self._client.chat.completions.create(**request)
            else:
                raise
        return completion, time.perf_counter() - started

    async def _authorize_gigachat(self, *, force_refresh: bool = False) -> None:
        """Получить токен GigaChat и подставить его в Bearer-заголовок SDK."""
        if self._gigachat is None:  # pragma: no cover - вызывается только для GigaChat
            return
        token = await self._gigachat.access_token(force_refresh=force_refresh)
        self._client.api_key = token

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

        # Некоторые провайдеры при исчерпании max_tokens возвращают content=""
        # и finish_reason="length". Без этой проверки ошибка выглядела бы как
        # «модель вернула пустоту» без указания причины.
        if not content and finish_reason == "length":
            raise TeacherAPIError(
                "Провайдер вернул пустой ответ при finish_reason=length "
                "(исчерпан max_tokens); увеличьте max_tokens "
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
