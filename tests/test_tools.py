"""Тесты Function Calling: схемы, парсинг и инструкции (T-030)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.database import Database, User, create_user, list_appointments, list_reminders
from app.tools import (
    AVAILABLE_TOOLS,
    BOOK_APPOINTMENT_TOOL,
    SET_REMINDER_TOOL,
    TOOL_NAMES,
    ToolDefinition,
    ToolExecutionError,
    build_tools_instruction,
    execute_tool,
    normalize_native_tool_calls,
    parse_tool_arguments,
    parse_tool_calls,
    with_tools_instruction,
)


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'tools.db').as_posix()}")
    await db.create_tables()
    yield db
    await db.dispose()


@pytest.fixture
async def user(database: Database) -> User:
    """Владелец записей, создаваемых инструментами."""
    async with database.session() as session:
        return await create_user(
            session,
            email="owner@example.com",
            hashed_password="hash",
        )


def test_default_tools_have_expected_names_and_required_fields() -> None:
    assert {"book_appointment", "set_reminder"} == TOOL_NAMES

    appointment = BOOK_APPOINTMENT_TOOL["function"]
    reminder = SET_REMINDER_TOOL["function"]
    assert appointment["name"] == "book_appointment"
    assert appointment["parameters"]["required"] == ["date", "time", "pet_name"]
    assert reminder["name"] == "set_reminder"
    assert reminder["parameters"]["required"] == ["time", "text"]
    assert len(AVAILABLE_TOOLS) == 2


def test_parse_qwen_tool_call_block() -> None:
    text = (
        "Записываю питомца.\n"
        '<tool_call>{"name": "book_appointment", "arguments": '
        '{"date": "2026-11-04", "time": "10:00", "pet_name": "Мурзик"}}</tool_call>'
    )

    calls, remaining = parse_tool_calls(text, allowed_tools=TOOL_NAMES)

    assert len(calls) == 1
    assert calls[0].function.name == "book_appointment"
    assert json.loads(calls[0].function.arguments) == {
        "date": "2026-11-04",
        "time": "10:00",
        "pet_name": "Мурзик",
    }
    assert remaining == "Записываю питомца."


def test_parse_plain_json_tool_call() -> None:
    text = '{"name": "set_reminder", "arguments": {"time": "20:00", "text": "Дать таблетку"}}'

    calls, remaining = parse_tool_calls(text, allowed_tools=TOOL_NAMES)

    assert len(calls) == 1
    assert calls[0].function.name == "set_reminder"
    assert json.loads(calls[0].function.arguments)["text"] == "Дать таблетку"
    assert remaining == ""


def test_parse_openai_tool_calls_wrapper() -> None:
    text = json.dumps(
        {
            "tool_calls": [
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "set_reminder",
                        "arguments": '{"time": "08:00", "text": "Корм"}',
                    },
                }
            ]
        }
    )

    calls, _ = parse_tool_calls(text, allowed_tools=TOOL_NAMES)

    assert len(calls) == 1
    assert calls[0].id == "call_123"
    assert calls[0].function.name == "set_reminder"


def test_parse_fenced_json_tool_call() -> None:
    text = (
        "```json\n"
        '{"name": "book_appointment", "arguments": '
        '{"date": "2026-11-05", "time": "12:30", "pet_name": "Барсик"}}\n'
        "```"
    )

    calls, remaining = parse_tool_calls(text, allowed_tools=TOOL_NAMES)

    assert len(calls) == 1
    assert calls[0].function.name == "book_appointment"
    assert remaining == ""


def test_unknown_tool_is_ignored() -> None:
    text = '{"name": "delete_database", "arguments": {}}'

    calls, remaining = parse_tool_calls(text, allowed_tools=TOOL_NAMES)

    assert calls == []
    assert remaining == text


def test_plain_text_is_not_a_tool_call() -> None:
    text = "Кошка должна пить воду. Запишитесь на приём, если состояние ухудшится."

    calls, remaining = parse_tool_calls(text, allowed_tools=TOOL_NAMES)

    assert calls == []
    assert remaining == text


def test_normalize_native_tool_calls() -> None:
    raw = [
        {
            "id": "call_native",
            "type": "function",
            "function": {
                "name": "book_appointment",
                "arguments": '{"date": "2026-11-06", "time": "09:00", "pet_name": "Рекс"}',
            },
        }
    ]

    calls = normalize_native_tool_calls(raw, allowed_tools=TOOL_NAMES)

    assert len(calls) == 1
    assert calls[0].id == "call_native"
    assert calls[0].type == "function"


def test_tools_instruction_extends_system_prompt_without_mutation() -> None:
    tools = [ToolDefinition.model_validate(BOOK_APPOINTMENT_TOOL)]
    messages = [
        {"role": "system", "content": "Отвечай кратко."},
        {"role": "user", "content": "Запиши кота на приём"},
    ]

    result = with_tools_instruction(messages, tools)

    assert result[0]["content"].startswith("Отвечай кратко.")
    assert "book_appointment" in result[0]["content"]
    assert "верни ТОЛЬКО JSON" in result[0]["content"]
    assert result[1] == messages[1]
    assert messages[0]["content"] == "Отвечай кратко."


def test_tools_instruction_is_empty_without_tools() -> None:
    assert build_tools_instruction([]) == ""
    messages = [{"role": "user", "content": "Вопрос"}]
    assert with_tools_instruction(messages, []) == messages


async def test_execute_tool_book_appointment(database: Database, user: User) -> None:
    async with database.session() as session:
        result = await execute_tool(
            "book_appointment",
            '{"date": "2026-11-04", "time": "10:00", "pet_name": "Мурзик"}',
            session=session,
            user_id=user.id,
        )

    assert result["status"] == "success"
    assert "Записали Мурзика" in result["message"]
    async with database.session() as session:
        appointments = await list_appointments(session, user_id=user.id)
    assert len(appointments) == 1
    assert appointments[0].date == "2026-11-04"
    assert appointments[0].user_id == user.id


async def test_execute_tool_set_reminder(database: Database, user: User) -> None:
    async with database.session() as session:
        result = await execute_tool(
            "set_reminder",
            {"time": "20:00", "text": "Дать таблетку"},
            session=session,
            user_id=user.id,
        )

    assert result["status"] == "success"
    assert "Дать таблетку" in result["message"]
    async with database.session() as session:
        reminders = await list_reminders(session, user_id=user.id)
    assert len(reminders) == 1
    assert reminders[0].time == "20:00"
    assert reminders[0].user_id == user.id


async def test_execute_tool_rejects_unknown_name(database: Database, user: User) -> None:
    async with database.session() as session:
        with pytest.raises(ToolExecutionError, match="неизвестный инструмент"):
            await execute_tool("delete_database", {}, session=session, user_id=user.id)


async def test_execute_tool_rejects_missing_arguments(
    database: Database,
    user: User,
) -> None:
    async with database.session() as session:
        with pytest.raises(ToolExecutionError, match="pet_name"):
            await execute_tool(
                "book_appointment",
                {"date": "2026-11-04", "time": "10:00"},
                session=session,
                user_id=user.id,
            )


def test_parse_tool_arguments_rejects_invalid_json() -> None:
    with pytest.raises(ToolExecutionError, match="не JSON"):
        parse_tool_arguments("{not json}")
