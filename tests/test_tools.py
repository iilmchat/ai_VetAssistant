"""Тесты Function Calling: схемы, парсинг и инструкции (T-030)."""

from __future__ import annotations

import json

from app.tools import (
    AVAILABLE_TOOLS,
    BOOK_APPOINTMENT_TOOL,
    SET_REMINDER_TOOL,
    TOOL_NAMES,
    ToolDefinition,
    build_tools_instruction,
    normalize_native_tool_calls,
    parse_tool_calls,
    with_tools_instruction,
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
