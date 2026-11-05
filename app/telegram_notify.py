"""Уведомления API → Telegram о записях и напоминаниях (T-134.4).

Отправка идёт напрямую в Bot API (``sendMessage``) с таймаутом 5 секунд.
Любая ошибка Telegram только логируется: ответ API пользователю не должен
ломаться из-за недоступности мессенджера. Уведомления отправляются лишь
привязанным пользователям и не дублируются для запросов из бота — бот сам
отвечает в чат, а его запросы помечены заголовком ``X-Vet-Client``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from loguru import logger

from app.settings import get_app_settings

#: Таймаут запроса к Telegram Bot API, секунды.
NOTIFY_TIMEOUT_S = 5.0

#: Заголовок, которым бот помечает свои запросы к API.
BOT_CLIENT_HEADER = "X-Vet-Client"
BOT_CLIENT_VALUE = "telegram-bot"

#: Инструменты, после успешного выполнения которых шлём уведомление.
#: H-5: напоминания (set_reminder) намеренно не уведомляем — иначе бот
#: заваливает пользователя дублями; оставляем только запись к врачу.
NOTIFY_TOOLS = frozenset({"book_appointment"})


def is_bot_request(headers: Mapping[str, str]) -> bool:
    """Проверить, что запрос пришёл из Telegram-бота (по заголовку)."""
    value = headers.get(BOT_CLIENT_HEADER)
    return isinstance(value, str) and value.strip().casefold() == BOT_CLIENT_VALUE


def notification_for_tool(tool_name: str, message: str) -> str:
    """Собрать текст уведомления по имени инструмента и его сообщению."""
    icon = "🐾" if tool_name == "book_appointment" else "⏰"
    return f"{icon} {message.strip()}"


async def _post_message(url: str, payload: dict[str, Any]) -> httpx.Response:
    """POST в Bot API (отдельная функция — точка подмены в тестах)."""
    async with httpx.AsyncClient(timeout=NOTIFY_TIMEOUT_S) as client:
        return await client.post(url, json=payload)


async def send_telegram_message(chat_id: int, text: str) -> bool:
    """Отправить сообщение в Telegram; вернуть ``True`` при успехе.

    Ошибки не пробрасываются: вызывающий код (фоновая задача) не должен
    ломать ответ API. Токен и текст в логи не попадают.
    """
    settings = get_app_settings()
    if not settings.telegram_notify:
        logger.debug("Telegram notify: отключено настройкой VET_API_TELEGRAM_NOTIFY")
        return False

    token = settings.telegram_bot_token.strip()
    if not token:
        logger.debug("Telegram notify: TELEGRAM_BOT_TOKEN не задан — пропускаю")
        return False
    if chat_id <= 0 or not text.strip():
        return False

    url = f"{settings.telegram_api_base.rstrip('/')}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    try:
        response = await _post_message(url, payload)
    except httpx.HTTPError as exc:
        # URL содержит токен, поэтому логируем только тип ошибки.
        logger.warning(
            "Telegram notify: не удалось отправить chat {} — {}",
            chat_id,
            type(exc).__name__,
        )
        return False

    if response.status_code >= 400:
        logger.warning(
            "Telegram notify: Bot API вернул HTTP {} для chat {}",
            response.status_code,
            chat_id,
        )
        return False

    try:
        body = response.json()
    except ValueError:
        logger.warning("Telegram notify: Bot API вернул не-JSON")
        return False
    if not isinstance(body, dict) or not body.get("ok"):
        logger.warning("Telegram notify: Bot API вернул ok=false")
        return False

    logger.info("Telegram notify: сообщение отправлено chat {}", chat_id)
    return True
