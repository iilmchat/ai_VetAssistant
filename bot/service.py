"""Бизнес-логика Telegram-бота без зависимости от aiogram (T-035).

Сервис принимает любой объект, похожий на ``aiogram.types.Message``:
достаточно ``text``, ``from_user.id``, ``chat.id``, ``bot`` и ``answer``.
Поэтому логику можно тестировать с фейковыми Telegram- и API-клиентами.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Sequence
from typing import Any, Protocol

from loguru import logger

from app.tools import AVAILABLE_TOOLS, ToolCall
from bot.client import ChatResult, VetApiError
from bot.conversation import ConversationStore

START_TEXT = (
    "Здравствуйте! Я VetAssistant — ИИ-ветеринар для владельцев животных. 🐾\n\n"
    "Помогу разобраться с симптомами, уходом и подготовкой к визиту. "
    "Могу записать питомца на приём и создать напоминание.\n\n"
    "⚠️ Важно: я искусственный интеллект, а не живой ветеринарный врач. "
    "Мои ответы не заменяют осмотр, диагностику и назначения специалиста. "
    "При опасных симптомах (затруднённое дыхание, судороги, отравление, "
    "сильное кровотечение) немедленно обратитесь в клинику.\n\n"
    "Напишите, что беспокоит питомца. Контекст диалога сохраняется; "
    "команда /reset очищает историю."
)

HELP_TEXT = (
    "🐾 Как я могу помочь:\n"
    "• отвечу на вопросы о здоровье и уходе;\n"
    "• помогу подготовиться к визиту к ветеринару;\n"
    "• запишу питомца на приём и создам напоминание.\n\n"
    "Команды:\n"
    "/start — приветствие и дисклеймер\n"
    "/reset — очистить историю диалога\n"
    "/help — эта справка\n\n"
    "⚠️ Я ИИ-ассистент, а не врач. При экстренных симптомах сразу "
    "обращайтесь в ветеринарную клинику."
)

RESET_TEXT = "История диалога очищена. Начнём заново — опишите, что беспокоит питомца."
UNSUPPORTED_TEXT = (
    "Пока я понимаю только текстовые сообщения. "
    "Опишите, что беспокоит питомца, текстом."
)
GENERIC_ERROR_TEXT = "Не удалось получить ответ. Попробуйте ещё раз чуть позже."
NO_RESPONSE_TEXT = "Модель не вернула ответ. Попробуйте переформулировать вопрос."
ACCESS_DENIED_TEXT = (
    "Доступ к боту ограничен. Пожалуйста, запросите доступ на сайте ai-pets.ru"
)


class TelegramUser(Protocol):
    """Минимальный интерфейс пользователя Telegram."""

    id: int


class TelegramChat(Protocol):
    """Минимальный интерфейс чата Telegram."""

    id: int


class TelegramBot(Protocol):
    """Минимальный интерфейс бота Telegram."""

    def send_chat_action(self, *, chat_id: int, action: str) -> Awaitable[Any]: ...


class TelegramMessage(Protocol):
    """Минимальный интерфейс сообщения Telegram."""

    @property
    def text(self) -> str | None: ...

    @property
    def from_user(self) -> TelegramUser | None: ...

    @property
    def chat(self) -> TelegramChat: ...

    @property
    def bot(self) -> TelegramBot | None: ...

    def answer(self, text: str) -> Awaitable[Any]: ...


class ChatApi(Protocol):
    """Минимальный интерфейс клиента API (удобно подменять в тестах)."""

    async def authenticate(self, telegram_user_id: int) -> str: ...

    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        token: str,
        temperature: float,
        use_rag: bool,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> ChatResult: ...

    async def close(self) -> None: ...


def split_message(text: str, *, limit: int = 4000) -> list[str]:
    """Разбить длинный ответ на части, помещающиеся в сообщение Telegram."""
    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= limit:
        return [normalized]

    chunks: list[str] = []
    remaining = normalized
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _parse_arguments(raw: str) -> dict[str, Any]:
    """Разобрать JSON-аргументы инструмента, вернув пустой словарь при ошибке."""
    try:
        value: Any = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def format_tool_calls(tool_calls: Sequence[ToolCall]) -> list[str]:
    """Сделать человекочитаемые подтверждения выполнения инструментов."""
    messages: list[str] = []
    for tool_call in tool_calls:
        name = tool_call.function.name
        arguments = _parse_arguments(tool_call.function.arguments)

        if name == "book_appointment":
            pet_name = str(arguments.get("pet_name") or "питомца")
            date = str(arguments.get("date") or "—")
            time = str(arguments.get("time") or "—")
            messages.append(
                f"✅ Я записал вашего питомца на приём: {pet_name}, {date} в {time}."
            )
        elif name == "set_reminder":
            text = str(arguments.get("text") or "напоминание")
            time = str(arguments.get("time") or "—")
            messages.append(f"⏰ Напоминание создано: {text} ({time}).")
        else:
            messages.append(f"🛠️ Выполнен инструмент: {name}.")
    return messages


def compose_answer(content: str, tool_messages: Sequence[str]) -> str:
    """Склеить подтверждения инструментов и финальный текст модели."""
    parts = [*tool_messages]
    if content.strip():
        parts.append(content.strip())
    return "\n\n".join(parts).strip()


def _user_id(message: TelegramMessage) -> int | None:
    """Вернуть Telegram user_id или ``None`` для сообщений без автора."""
    return message.from_user.id if message.from_user is not None else None


class VetAssistantBot:
    """Обработчик сообщений: история, API, инструменты и ответы Telegram."""

    def __init__(
        self,
        api: ChatApi,
        store: ConversationStore,
        *,
        temperature: float = 0.7,
        use_rag: bool = True,
        use_tools: bool = True,
        tools: Sequence[dict[str, Any]] = AVAILABLE_TOOLS,
        allowed_ids: frozenset[int] | None = None,
    ) -> None:
        self._api = api
        self._store = store
        self._temperature = temperature
        self._use_rag = use_rag
        self._use_tools = use_tools
        self._tools = tools
        self._allowed_ids = allowed_ids
        self._tokens: dict[int, str] = {}

    async def _deny_if_not_allowed(self, message: TelegramMessage) -> bool:
        """Ответить отказом, если Telegram ID вне allowlist.

        ``allowed_ids is None`` — allowlist не настроен (dev/тесты): доступ
        разрешён. Пустое множество запрещает всех.
        """
        if self._allowed_ids is None:
            return False
        user_id = _user_id(message)
        if user_id is not None and user_id in self._allowed_ids:
            return False
        logger.warning("Bot: доступ запрещён Telegram user {}", user_id)
        await message.answer(ACCESS_DENIED_TEXT)
        return True

    async def _token_for(self, user_id: int) -> str:
        """Вернуть JWT пользователя, при необходимости авторизовав его."""
        token = self._tokens.get(user_id)
        if token is not None:
            return token
        token = await self._api.authenticate(user_id)
        self._tokens[user_id] = token
        return token

    async def start(self, message: TelegramMessage) -> None:
        """Обработать /start: очистить историю и авторизовать пользователя."""
        if await self._deny_if_not_allowed(message):
            return
        user_id = _user_id(message)
        if user_id is not None:
            self._store.clear(user_id)
            self._tokens.pop(user_id, None)
            try:
                self._tokens[user_id] = await self._api.authenticate(user_id)
            except VetApiError as exc:
                # Приветствие не должно зависеть от доступности API:
                # повторная попытка входа произойдёт при первом сообщении.
                logger.warning(
                    "Bot: не удалось авторизовать Telegram user {}: {}",
                    user_id,
                    exc,
                )
        await message.answer(START_TEXT)

    async def help(self, message: TelegramMessage) -> None:
        """Обработать /help."""
        if await self._deny_if_not_allowed(message):
            return
        await message.answer(HELP_TEXT)

    async def reset(self, message: TelegramMessage) -> None:
        """Обработать /reset: забыть контекст пользователя."""
        if await self._deny_if_not_allowed(message):
            return
        user_id = _user_id(message)
        if user_id is not None:
            self._store.clear(user_id)
        await message.answer(RESET_TEXT)

    async def handle_unsupported(self, message: TelegramMessage) -> None:
        """Ответить на нетекстовое сообщение."""
        if await self._deny_if_not_allowed(message):
            return
        await message.answer(UNSUPPORTED_TEXT)

    async def _chat_once(
        self,
        user_id: int,
        history: Sequence[dict[str, str]],
    ) -> ChatResult:
        """Вызвать API; при 401 один раз обновить токен и повторить."""
        token = await self._token_for(user_id)
        try:
            return await self._api.chat(
                history,
                token=token,
                temperature=self._temperature,
                use_rag=self._use_rag,
                tools=self._tools if self._use_tools else None,
            )
        except VetApiError as exc:
            if exc.status != 401:
                raise
            logger.info("Bot: токен user {} истёк, повторная авторизация", user_id)
            self._tokens.pop(user_id, None)
            token = await self._token_for(user_id)
            return await self._api.chat(
                history,
                token=token,
                temperature=self._temperature,
                use_rag=self._use_rag,
                tools=self._tools if self._use_tools else None,
            )

    async def handle_text(self, message: TelegramMessage) -> None:
        """Отправить текст в API и вернуть ответ с учётом истории."""
        if await self._deny_if_not_allowed(message):
            return
        text = (message.text or "").strip()
        if not text:
            return

        user_id = _user_id(message)
        if user_id is None:
            await message.answer("Не удалось определить пользователя. Попробуйте ещё раз.")
            return

        await self._send_typing(message)
        history = [*self._store.history(user_id), {"role": "user", "content": text}]

        try:
            result = await self._chat_once(user_id, history)
        except VetApiError as exc:
            logger.warning("Bot: ошибка API для user {}: {}", user_id, exc)
            await message.answer(exc.user_message)
            return
        except Exception as exc:
            logger.exception("Bot: неожиданная ошибка для user {}: {}", user_id, exc)
            await message.answer(GENERIC_ERROR_TEXT)
            return

        tool_messages = format_tool_calls(result.tool_calls) if self._use_tools else []
        answer = compose_answer(result.content, tool_messages)
        if not answer:
            await message.answer(NO_RESPONSE_TEXT)
            return

        for chunk in split_message(answer):
            try:
                await message.answer(chunk)
            except Exception as exc:
                logger.exception("Bot: не удалось отправить ответ user {}: {}", user_id, exc)
                return

        assistant_content = result.content.strip() or "\n".join(tool_messages) or NO_RESPONSE_TEXT
        self._store.save(
            user_id,
            [*history, {"role": "assistant", "content": assistant_content}],
        )

    async def _send_typing(self, message: TelegramMessage) -> None:
        """Показать индикатор набора текста; ошибки Telegram не критичны."""
        bot = message.bot
        if bot is None:
            return
        try:
            await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        except Exception as exc:
            logger.debug("Bot: не удалось отправить typing — {}", exc)

    async def close(self) -> None:
        """Закрыть HTTP-клиент API."""
        await self._api.close()
