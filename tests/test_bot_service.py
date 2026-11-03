"""Тесты логики Telegram-бота с фейковыми Telegram и FastAPI (T-035)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.tools import AVAILABLE_TOOLS, ToolCall, ToolCallFunction
from bot.client import ChatResult, VetApiError
from bot.conversation import ConversationStore
from bot.service import (
    GENERIC_ERROR_TEXT,
    START_TEXT,
    UNSUPPORTED_TEXT,
    VetAssistantBot,
    compose_answer,
    format_tool_calls,
    split_message,
)


class FakeBot:
    """Заглушка Telegram Bot API."""

    def __init__(self) -> None:
        self.actions: list[tuple[int, str]] = []

    async def send_chat_action(self, *, chat_id: int, action: str) -> None:
        self.actions.append((chat_id, action))


class FakeUser:
    """Заглушка пользователя Telegram."""

    def __init__(self, user_id: int) -> None:
        self.id = user_id


class FakeChat:
    """Заглушка чата Telegram."""

    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class FakeMessage:
    """Заглушка сообщения Telegram: запоминает ответы вместо отправки."""

    def __init__(self, text: str | None, *, user_id: int = 1) -> None:
        self.text = text
        self.from_user = FakeUser(user_id)
        self.chat = FakeChat(user_id)
        self.bot = FakeBot()
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


class FakeApi:
    """Заглушка FastAPI: возвращает заранее заданные ответы или ошибки."""

    def __init__(self, outcomes: Sequence[ChatResult | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float,
        use_rag: bool,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> ChatResult:
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "temperature": temperature,
                "use_rag": use_rag,
                "tools": tools,
            }
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def close(self) -> None:
        self.closed = True


def _tool_call(
    name: str,
    arguments: str,
    *,
    call_id: str = "call_1",
) -> ToolCall:
    return ToolCall(
        id=call_id,
        function=ToolCallFunction(name=name, arguments=arguments),
    )


async def test_start_sends_disclaimer_and_clears_history() -> None:
    store = ConversationStore()
    store.save(
        1,
        [
            {"role": "user", "content": "Старый вопрос"},
            {"role": "assistant", "content": "Старый ответ"},
        ],
    )
    api = FakeApi([])
    bot = VetAssistantBot(api, store)
    message = FakeMessage("/start")

    await bot.start(message)

    assert message.answers == [START_TEXT]
    assert "искусственный интеллект" in message.answers[0]
    assert "не заменяют" in message.answers[0]
    assert store.history(1) == []
    assert api.calls == []
    assert message.bot.actions == []


async def test_text_uses_history_and_saves_assistant_reply() -> None:
    store = ConversationStore()
    store.save(
        7,
        [
            {"role": "user", "content": "Старый вопрос"},
            {"role": "assistant", "content": "Старый ответ"},
        ],
    )
    api = FakeApi([ChatResult("Новый ответ")])
    bot = VetAssistantBot(api, store, temperature=0.3, use_rag=True)
    message = FakeMessage("Новый вопрос", user_id=7)

    await bot.handle_text(message)

    assert message.answers == ["Новый ответ"]
    assert message.bot.actions == [(7, "typing")]
    assert len(api.calls) == 1
    assert api.calls[0]["messages"] == [
        {"role": "user", "content": "Старый вопрос"},
        {"role": "assistant", "content": "Старый ответ"},
        {"role": "user", "content": "Новый вопрос"},
    ]
    assert api.calls[0]["temperature"] == 0.3
    assert api.calls[0]["use_rag"] is True
    assert api.calls[0]["tools"] == AVAILABLE_TOOLS
    assert store.history(7)[-2:] == [
        {"role": "user", "content": "Новый вопрос"},
        {"role": "assistant", "content": "Новый ответ"},
    ]


async def test_tool_call_is_rendered_as_appointment_confirmation() -> None:
    api = FakeApi(
        [
            ChatResult(
                "Запись создана.",
                (
                    _tool_call(
                        "book_appointment",
                        '{"date": "2026-11-04", "time": "10:00", "pet_name": "Мурзик"}',
                    ),
                ),
            )
        ]
    )
    store = ConversationStore()
    bot = VetAssistantBot(api, store)
    message = FakeMessage("Запиши Мурзика на завтра")

    await bot.handle_text(message)

    assert "✅ Я записал вашего питомца на приём: Мурзик, 2026-11-04 в 10:00." in (
        message.answers[0]
    )
    assert "Запись создана." in message.answers[0]
    assert store.history(1)[-1]["content"] == "Запись создана."


async def test_reminder_tool_is_rendered_as_confirmation() -> None:
    api = FakeApi(
        [
            ChatResult(
                "Напоминание готово.",
                (
                    _tool_call(
                        "set_reminder",
                        '{"time": "2026-11-04 09:00", "text": "Дать таблетку"}',
                    ),
                ),
            )
        ]
    )
    bot = VetAssistantBot(api, ConversationStore())
    message = FakeMessage("Напомни дать таблетку")

    await bot.handle_text(message)

    assert "⏰ Напоминание создано: Дать таблетку (2026-11-04 09:00)." in message.answers[0]


async def test_tools_can_be_disabled() -> None:
    api = FakeApi(
        [
            ChatResult(
                "Готово.",
                (_tool_call("book_appointment", '{"pet_name": "Мурзик"}'),),
            )
        ]
    )
    bot = VetAssistantBot(api, ConversationStore(), use_tools=False)
    message = FakeMessage("Запиши Мурзика")

    await bot.handle_text(message)

    assert api.calls[0]["tools"] is None
    assert "✅" not in message.answers[0]
    assert message.answers[0] == "Готово."


async def test_api_error_is_shown_and_history_is_not_saved() -> None:
    api = FakeApi([VetApiError("boom", user_message="Сервер ветеринара спит")])
    store = ConversationStore()
    bot = VetAssistantBot(api, store)
    message = FakeMessage("Кот не ест")

    await bot.handle_text(message)

    assert message.answers == ["Сервер ветеринара спит"]
    assert store.history(1) == []


async def test_unexpected_api_error_is_shown() -> None:
    api = FakeApi([RuntimeError("boom")])
    bot = VetAssistantBot(api, ConversationStore())
    message = FakeMessage("Кот не ест")

    await bot.handle_text(message)

    assert message.answers == [GENERIC_ERROR_TEXT]


async def test_empty_text_is_ignored() -> None:
    api = FakeApi([])
    bot = VetAssistantBot(api, ConversationStore())
    message = FakeMessage("   ")

    await bot.handle_text(message)

    assert message.answers == []
    assert api.calls == []


async def test_reset_clears_history() -> None:
    store = ConversationStore()
    store.save(
        3,
        [
            {"role": "user", "content": "Вопрос"},
            {"role": "assistant", "content": "Ответ"},
        ],
    )
    bot = VetAssistantBot(FakeApi([]), store)
    message = FakeMessage("/reset", user_id=3)

    await bot.reset(message)

    assert "История диалога очищена" in message.answers[0]
    assert store.history(3) == []


async def test_unsupported_message_is_answered() -> None:
    bot = VetAssistantBot(FakeApi([]), ConversationStore())
    message = FakeMessage(None)

    await bot.handle_unsupported(message)

    assert message.answers == [UNSUPPORTED_TEXT]


async def test_histories_are_isolated_per_user() -> None:
    api = FakeApi([ChatResult("Ответ первому"), ChatResult("Ответ второму")])
    store = ConversationStore()
    bot = VetAssistantBot(api, store)
    first = FakeMessage("Вопрос первого", user_id=1)
    second = FakeMessage("Вопрос второго", user_id=2)

    await bot.handle_text(first)
    await bot.handle_text(second)

    assert api.calls[1]["messages"] == [
        {"role": "user", "content": "Вопрос второго"}
    ]
    assert store.history(1)[-1]["content"] == "Ответ первому"
    assert store.history(2)[-1]["content"] == "Ответ второму"


async def test_long_answer_is_split_for_telegram() -> None:
    api = FakeApi([ChatResult("а" * 5000)])
    bot = VetAssistantBot(api, ConversationStore())
    message = FakeMessage("Длинный вопрос")

    await bot.handle_text(message)

    assert len(message.answers) >= 2
    assert all(len(answer) <= 4000 for answer in message.answers)
    assert "".join(message.answers) == "а" * 5000


def test_conversation_store_keeps_pairs_and_limit() -> None:
    store = ConversationStore(max_messages=4)
    messages = [
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "1a"},
        {"role": "user", "content": "2"},
        {"role": "assistant", "content": "2a"},
        {"role": "user", "content": "3"},
        {"role": "assistant", "content": "3a"},
    ]

    store.save(1, messages)

    assert store.history(1) == messages[-4:]
    store.clear(1)
    assert store.history(1) == []


def test_format_tool_calls_handles_unknown_tool() -> None:
    assert format_tool_calls([_tool_call("unknown_tool", "{}")]) == [
        "🛠️ Выполнен инструмент: unknown_tool."
    ]


def test_compose_answer_keeps_tool_confirmation_and_model_text() -> None:
    assert compose_answer("Текст модели", ["✅ Готово."]) == "✅ Готово.\n\nТекст модели"
    assert compose_answer("", ["✅ Готово."]) == "✅ Готово."
    assert compose_answer("Текст модели", []) == "Текст модели"


def test_split_message_respects_limit() -> None:
    text = "\n".join(["Строка текста"] * 1000)

    chunks = split_message(text, limit=500)

    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 500 for chunk in chunks)
    assert "\n".join(chunks).replace("\n", "") == text.replace("\n", "")


@pytest.mark.parametrize("max_messages", [0, 1])
def test_conversation_store_rejects_small_limit(max_messages: int) -> None:
    with pytest.raises(ValueError):
        ConversationStore(max_messages=max_messages)
