"""Асинхронный клиент FastAPI для Telegram-бота (T-035)."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger
from pydantic import ValidationError

from app.telegram_notify import BOT_CLIENT_HEADER, BOT_CLIENT_VALUE
from app.tools import ToolCall

API_DOWN_MESSAGE = (
    "Не удалось связаться с сервером ветеринара. "
    "Проверьте, что API запущен, и попробуйте позже."
)
API_TIMEOUT_MESSAGE = "Ветеринар отвечает слишком долго. Попробуйте ещё раз чуть позже."
MODEL_UNAVAILABLE_MESSAGE = "Модель временно недоступна. Попробуйте позже."
API_ERROR_MESSAGE = "Не удалось получить ответ ветеринара. Попробуйте позже."
EMPTY_RESPONSE_MESSAGE = "Модель не вернула ответ. Попробуйте переформулировать вопрос."
AUTH_ERROR_MESSAGE = "Не удалось войти в сервис. Попробуйте позже."
AUTH_EXPIRED_MESSAGE = "Сессия истекла. Напишите /start, чтобы войти заново."
ACCOUNT_NOT_PROVISIONED_MESSAGE = (
    "Аккаунт для этого Telegram не создан. "
    "Запросите доступ на сайте ai-pets.ru и дождитесь одобрения."
)

#: Сообщения команд привязки Telegram (T-134.3).
LINK_CODE_INVALID_MESSAGE = "Код недействителен. Проверьте код и попробуйте снова."
LINK_CODE_EXPIRED_MESSAGE = (
    "Срок действия кода истёк (10 минут). Получите новый код на сайте."
)
LINK_CODE_USED_MESSAGE = "Этот код уже использован. Получите новый код на сайте."
LINK_TELEGRAM_BUSY_MESSAGE = (
    "Этот Telegram уже привязан к другому аккаунту. Обратитесь в поддержку."
)
LINK_FORBIDDEN_MESSAGE = (
    "Этот аккаунт уже привязан. Используйте /unlink, чтобы отвязать."
)
LINK_RATE_LIMIT_MESSAGE = "Слишком много попыток. Подождите немного и повторите."
LINK_UNAVAILABLE_MESSAGE = "Привязка Telegram временно недоступна. Попробуйте позже."


class VetApiError(RuntimeError):
    """Ошибка обращения к FastAPI с готовым сообщением для пользователя."""

    def __init__(
        self,
        message: str,
        *,
        user_message: str,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.user_message = user_message
        self.status = status


@dataclass(frozen=True)
class ChatResult:
    """Ответ API: текст и уже выполненные вызовы инструментов."""

    content: str
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class LinkStatus:
    """Статус привязки Telegram (``GET /v1/telegram/link``)."""

    linked: bool
    telegram_id: int | None = None
    email: str | None = None
    linked_at: str | None = None


def chat_endpoint(api_url: str) -> str:
    """Привести базовый URL или полный URL к ``/v1/chat/completions``."""
    normalized = api_url.rstrip("/")
    if normalized.endswith("/v1/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def api_base_url(api_url: str) -> str:
    """Привести базовый URL или полный URL к корню API."""
    normalized = api_url.rstrip("/")
    for suffix in ("/v1/chat/completions", "/v1"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def telegram_credentials(telegram_user_id: int, secret: str) -> tuple[str, str]:
    """Стабильные email и пароль синтетического аккаунта Telegram-пользователя.

    Пароль — HMAC-SHA256 от Telegram ID и секрета бота, поэтому после
    перезапуска бот может снова войти в тот же аккаунт, не храня пароли.
    """
    email = f"telegram-{telegram_user_id}@bot.vetassistant.local"
    digest = hmac.new(
        secret.encode("utf-8"),
        f"telegram:{telegram_user_id}".encode(),
        hashlib.sha256,
    ).digest()
    password = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return email, password


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


def _link_error_message(status: int, detail: str) -> str:
    """Человеческое сообщение для ошибок привязки Telegram."""
    if status == 401:
        return AUTH_EXPIRED_MESSAGE
    if status == 403:
        return LINK_FORBIDDEN_MESSAGE
    if status == 409:
        return LINK_TELEGRAM_BUSY_MESSAGE
    if status == 429:
        return LINK_RATE_LIMIT_MESSAGE
    if status == 503:
        return LINK_UNAVAILABLE_MESSAGE
    if status == 400:
        normalized = detail.casefold()
        if "истёк" in normalized or "истек" in normalized:
            return LINK_CODE_EXPIRED_MESSAGE
        if "использован" in normalized:
            return LINK_CODE_USED_MESSAGE
        return LINK_CODE_INVALID_MESSAGE
    return API_ERROR_MESSAGE


class VetApiClient:
    """HTTP-клиент к FastAPI: JWT-аутентификация и chat completions."""

    def __init__(
        self,
        api_url: str,
        *,
        model_id: str,
        timeout_s: float = 300.0,
        auth_secret: str = "vetassistant-bot-dev-secret",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint = chat_endpoint(api_url)
        self._base_url = api_base_url(api_url)
        self._model_id = model_id
        self._auth_secret = auth_secret
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._owns_client = client is None

    async def close(self) -> None:
        """Закрыть HTTP-соединения, если клиент создан внутри."""
        if self._owns_client:
            await self._client.aclose()

    async def _auth_request(self, path: str, payload: dict[str, str]) -> dict[str, Any]:
        """Выполнить register/login и вернуть JSON с токеном."""
        try:
            response = await self._client.post(f"{self._base_url}{path}", json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise VetApiError(
                "таймаут авторизации",
                user_message=AUTH_ERROR_MESSAGE,
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = _error_detail(exc.response)
            logger.warning("Bot auth: HTTP {} — {}", status, detail)
            user_message = (
                AUTH_EXPIRED_MESSAGE if status == 401 else AUTH_ERROR_MESSAGE
            )
            raise VetApiError(
                f"auth HTTP {status}: {detail}",
                user_message=user_message,
                status=status,
            ) from exc
        except httpx.RequestError as exc:
            logger.warning("Bot auth: API недоступен — {}", exc)
            raise VetApiError("API недоступен", user_message=API_DOWN_MESSAGE) from exc

        try:
            data: Any = response.json()
        except ValueError as exc:
            raise VetApiError(
                "некорректный JSON авторизации",
                user_message=AUTH_ERROR_MESSAGE,
            ) from exc
        if not isinstance(data, dict):
            raise VetApiError(
                "API вернул не объект",
                user_message=AUTH_ERROR_MESSAGE,
            )
        return data

    async def authenticate(self, telegram_user_id: int) -> str:
        """Войти в синтетический аккаунт Telegram-пользователя.

        Аккаунт создаёт только администратор после одобрения заявки; бот не
        регистрирует новых пользователей самостоятельно (T-121).

        Returns:
            JWT access-токен для запросов к защищённым эндпоинтам.
        """
        email, password = telegram_credentials(telegram_user_id, self._auth_secret)
        credentials = {"email": email, "password": password}

        try:
            data = await self._auth_request("/v1/auth/login", credentials)
        except VetApiError as exc:
            if exc.status != 401:
                raise
            raise VetApiError(
                "Аккаунт Telegram не создан",
                user_message=ACCOUNT_NOT_PROVISIONED_MESSAGE,
                status=401,
            ) from exc

        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise VetApiError(
                "API не вернул access_token",
                user_message=AUTH_ERROR_MESSAGE,
            )
        logger.info("Bot auth: Telegram user {} авторизован", telegram_user_id)
        return token

    async def _link_request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Запрос к эндпоинтам привязки Telegram с общим маппингом ошибок."""
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.warning("Bot link: таймаут API — {}", exc)
            raise VetApiError(
                "таймаут привязки Telegram",
                user_message=API_TIMEOUT_MESSAGE,
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = _error_detail(exc.response)
            logger.warning("Bot link: HTTP {} — {}", status, detail)
            raise VetApiError(
                f"link HTTP {status}: {detail}",
                user_message=_link_error_message(status, detail),
                status=status,
            ) from exc
        except httpx.RequestError as exc:
            logger.warning("Bot link: API недоступен — {}", exc)
            raise VetApiError(
                "API недоступен",
                user_message=API_DOWN_MESSAGE,
            ) from exc

        try:
            data: Any = response.json()
        except ValueError as exc:
            raise VetApiError(
                "некорректный JSON привязки",
                user_message=API_ERROR_MESSAGE,
            ) from exc
        if not isinstance(data, dict):
            raise VetApiError(
                "API вернул не объект",
                user_message=API_ERROR_MESSAGE,
            )
        return data

    async def confirm_link(
        self,
        code: str,
        telegram_id: int,
        *,
        token: str,
    ) -> str:
        """Подтвердить код привязки и вернуть email привязанного аккаунта."""
        data = await self._link_request(
            "POST",
            "/v1/telegram/confirm",
            token=token,
            payload={"code": code, "telegram_id": telegram_id},
        )
        email = data.get("email")
        if not isinstance(email, str) or not email:
            raise VetApiError(
                "API не вернул email привязки",
                user_message=API_ERROR_MESSAGE,
            )
        return email

    async def link_status(self, *, token: str) -> LinkStatus:
        """Вернуть статус привязки Telegram для владельца токена."""
        data = await self._link_request("GET", "/v1/telegram/link", token=token)
        telegram_id = data.get("telegram_id")
        linked_at = data.get("linked_at")
        email = data.get("email")
        return LinkStatus(
            linked=bool(data.get("linked")),
            telegram_id=telegram_id if isinstance(telegram_id, int) else None,
            email=email if isinstance(email, str) and email else None,
            linked_at=linked_at if isinstance(linked_at, str) else None,
        )

    async def unlink(self, *, token: str) -> None:
        """Отвязать Telegram от аккаунта владельца токена."""
        await self._link_request("DELETE", "/v1/telegram/link", token=token)

    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        token: str,
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
            response = await self._client.post(
                self._endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    # T-134.4: API не дублирует уведомления для запросов бота.
                    BOT_CLIENT_HEADER: BOT_CLIENT_VALUE,
                },
            )
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
            elif status == 401:
                user_message = AUTH_EXPIRED_MESSAGE
            elif status == 503:
                user_message = MODEL_UNAVAILABLE_MESSAGE
            else:
                user_message = API_ERROR_MESSAGE
            raise VetApiError(
                f"HTTP {status}: {detail}",
                user_message=user_message,
                status=status,
            ) from exc
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
