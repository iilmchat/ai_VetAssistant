"""Инструменты Function Calling для VetAssistant (T-030).

Модуль содержит OpenAI-совместимые JSON-схемы инструментов, модели для
`tool_calls` и парсер ответа локальной модели. llama-cpp-python умеет
передавать ``tools`` в chat template и принудительно включать грамматику
для выбранного инструмента, но при ``tool_choice="auto"`` возвращает
обычный текст. Поэтому ответ дополнительно разбирается здесь: поддерживаются
нативный формат Qwen ``<tool_call>{...}</tool_call>`` и чистый JSON.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Iterator, Sequence
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Patient, list_patients
from app.database import book_appointment as create_appointment
from app.database import create_patient as create_patient_record
from app.database import set_reminder as create_reminder

ToolName = Literal["book_appointment", "set_reminder", "create_patient"]

#: Инструмент записи питомца на приём.
BOOK_APPOINTMENT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "book_appointment",
        "description": (
            "Записать питомца на приём к ветеринарному врачу. Запись создаётся "
            "только для питомца с карточкой; если карточки нет, передай species "
            "для её автоматического создания."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Дата приёма в формате YYYY-MM-DD.",
                },
                "time": {
                    "type": "string",
                    "description": "Время приёма в формате HH:MM.",
                },
                "pet_name": {
                    "type": "string",
                    "description": "Кличка питомца.",
                },
                "species": {
                    "type": "string",
                    "enum": ["dog", "cat"],
                    "description": (
                        "Вид питомца, если известен. Нужен, чтобы автоматически "
                        "создать карточку при первой записи."
                    ),
                },
                "patient_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "ID карточки питомца, если он известен из контекста. "
                        "Позволяет выбрать одного из питомцев с одинаковой кличкой."
                    ),
                },
            },
            "required": ["date", "time", "pet_name"],
            "additionalProperties": False,
        },
    },
}

#: Инструмент создания напоминания.
SET_REMINDER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "set_reminder",
        "description": "Создать напоминание, например дать питомцу таблетку.",
        "parameters": {
            "type": "object",
            "properties": {
                "time": {
                    "type": "string",
                    "description": "Когда напомнить: ISO-время или понятная фраза.",
                },
                "text": {
                    "type": "string",
                    "description": "Текст напоминания.",
                },
            },
            "required": ["time", "text"],
            "additionalProperties": False,
        },
    },
}

#: Инструмент создания карточки питомца (T-163).
CREATE_PATIENT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_patient",
        "description": (
            "Создать карточку питомца. Вызывай этот инструмент СРАЗУ, как только "
            "пользователь назвал кличку и вид. Не задавай вопросы про вес, "
            "вакцинацию, породу — они необязательны."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Кличка питомца.",
                },
                "species": {
                    "type": "string",
                    "enum": ["dog", "cat"],
                    "description": "Вид: dog — собака, cat — кошка.",
                },
                "breed": {
                    "type": "string",
                    "description": "Порода, если пользователь её назвал.",
                },
                "age": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 40,
                    "description": "Возраст в полных годах, если известен.",
                },
            },
            "required": ["name", "species"],
            "additionalProperties": False,
        },
    },
}

#: Все инструменты, доступные UI по умолчанию.
AVAILABLE_TOOLS: tuple[dict[str, Any], ...] = (
    BOOK_APPOINTMENT_TOOL,
    SET_REMINDER_TOOL,
    CREATE_PATIENT_TOOL,
)

#: Имена инструментов для валидации ответа модели.
TOOL_NAMES: frozenset[str] = frozenset(str(tool["function"]["name"]) for tool in AVAILABLE_TOOLS)

_TOOL_CALL_BLOCK = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.IGNORECASE | re.DOTALL,
)
_FENCED_JSON = re.compile(
    r"^```(?:json)?\s*(.*?)\s*```$",
    re.IGNORECASE | re.DOTALL,
)


class ToolFunctionDefinition(BaseModel):
    """Описание одной функции в запросе ``tools``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolDefinition(BaseModel):
    """OpenAI-совместимое описание инструмента."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["function"] = "function"
    function: ToolFunctionDefinition


class ToolCallFunction(BaseModel):
    """Имя и аргументы вызванной функции."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    arguments: str = "{}"


class ToolCall(BaseModel):
    """Один вызов инструмента в ответе ассистента."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: Literal["function"] = "function"
    function: ToolCallFunction


class ToolExecutionRequest(BaseModel):
    """Тело запроса ``POST /v1/tools/execute``."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    arguments: dict[str, Any] | str = Field(default_factory=dict)


class ToolExecutionError(ValueError):
    """Инструмент не найден или получил некорректные аргументы."""


def parse_tool_arguments(arguments: str | dict[str, Any] | None) -> dict[str, Any]:
    """Разобрать аргументы инструмента из JSON-строки или словаря.

    Raises:
        ToolExecutionError: аргументы не являются JSON-объектом.
    """
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        try:
            parsed: Any = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ToolExecutionError(f"аргументы инструмента не JSON: {exc}") from exc
    elif isinstance(arguments, dict):
        parsed = arguments
    else:
        raise ToolExecutionError("аргументы инструмента должны быть JSON-объектом")

    if not isinstance(parsed, dict):
        raise ToolExecutionError("аргументы инструмента должны быть JSON-объектом")
    return parsed


def _required_string(arguments: dict[str, Any], name: str) -> str:
    """Взять обязательный непустой строковый аргумент."""
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolExecutionError(f"не хватает параметра {name}")
    return value.strip()


def _optional_string(arguments: dict[str, Any], name: str) -> str | None:
    """Взять необязательный строковый аргумент (пустая строка → None)."""
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolExecutionError(f"параметр {name} должен быть строкой")
    value = value.strip()
    return value or None


def _optional_age(arguments: dict[str, Any]) -> int | None:
    """Взять возраст в годах (0…40) из аргументов инструмента."""
    value = arguments.get("age")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolExecutionError("возраст должен быть целым числом лет")
    if not 0 <= value <= 40:
        raise ToolExecutionError("возраст должен быть от 0 до 40 лет")
    return value


def _optional_positive_int(arguments: dict[str, Any], name: str) -> int | None:
    """Взять необязательный положительный integer из аргументов."""
    value = arguments.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolExecutionError(f"параметр {name} должен быть положительным целым")
    return value


def _pet_name_accusative(name: str) -> str:
    """Простая эвристика для фразы «Записали <кличку в винительном>»."""
    lower = name.lower()
    if lower.endswith("а"):
        return f"{name[:-1]}у"
    if lower.endswith("я"):
        return f"{name[:-1]}ю"
    if lower.endswith(("й", "ь")):
        return f"{name[:-1]}я"
    if lower.endswith(("о", "е", "ё", "у", "ю", "ы", "и", "э")):
        return name
    return f"{name}а"


async def execute_tool(
    name: str,
    arguments: str | dict[str, Any] | None = None,
    *,
    session: AsyncSession,
    user_id: int,
) -> dict[str, str]:
    """Выполнить инструмент и вернуть статус и человекочитаемое сообщение.

    ``user_id`` берётся из JWT и никогда из аргументов модели, поэтому
    запись всегда попадает владельцу текущей сессии.

    Raises:
        ToolExecutionError: неизвестный инструмент или некорректные аргументы.
    """
    parsed = parse_tool_arguments(arguments)

    if name == "create_patient":
        patient_name = _required_string(parsed, "name")
        species = _required_string(parsed, "species").casefold()
        if species not in ("dog", "cat"):
            raise ToolExecutionError("вид питомца должен быть dog или cat")
        breed = _optional_string(parsed, "breed")
        age = _optional_age(parsed)

        # Не создаём дубликат, если карточка с такой кличкой и видом уже есть.
        existing_patients = await list_patients(session, user_id=user_id)
        for existing in existing_patients:
            if (
                existing.name.casefold() == patient_name.casefold()
                and existing.species == species
            ):
                return {
                    "status": "exists",
                    "patient_id": str(existing.id),
                    "message": f"Карточка {existing.name} уже существует",
                }

        birth_date = (
            date.today() - timedelta(days=age * 365) if age is not None else None
        )
        patient = await create_patient_record(
            session,
            user_id=user_id,
            name=patient_name,
            species=species,
            breed=breed,
            birth_date=birth_date,
        )
        return {
            "status": "success",
            "patient_id": str(patient.id),
            "message": f"Карточка {patient.name} создана",
        }

    if name == "book_appointment":
        pet_name = _required_string(parsed, "pet_name")
        date_value = _required_string(parsed, "date")
        time_value = _required_string(parsed, "time")
        patient_id = _optional_positive_int(parsed, "patient_id")
        species_value = _optional_string(parsed, "species")
        if species_value is not None:
            species_value = species_value.casefold()
            if species_value not in ("dog", "cat"):
                raise ToolExecutionError("вид питомца должен быть dog или cat")

        # T-173: запись всегда привязана к карточке. Ищем по id, затем по
        # кличке (+ виду); если карточки нет, но вид известен — создаём её.
        patients = await list_patients(session, user_id=user_id)
        patient_card: Patient | None = None
        if patient_id is not None:
            patient_card = next(
                (item for item in patients if item.id == patient_id),
                None,
            )
            if patient_card is None:
                raise ToolExecutionError(
                    "карточка питомца не найдена; выберите питомца из списка"
                )
        else:
            matches = [
                item
                for item in patients
                if item.name.casefold() == pet_name.casefold()
                and (species_value is None or item.species == species_value)
            ]
            if len(matches) == 1:
                patient_card = matches[0]
            elif len(matches) > 1:
                raise ToolExecutionError(
                    "несколько питомцев с такой кличкой; укажите patient_id "
                    "или выберите питомца в интерфейсе"
                )

        created_patient = False
        if patient_card is None:
            if species_value is None:
                raise ToolExecutionError(
                    f"питомец «{pet_name}» не найден среди карточек; создайте "
                    "карточку питомца (нужны кличка и вид) и повторите запись"
                )
            patient_card = await create_patient_record(
                session,
                user_id=user_id,
                name=pet_name,
                species=species_value,
            )
            created_patient = True

        appointment = await create_appointment(
            session,
            user_id=user_id,
            patient_id=patient_card.id,
            pet_name=patient_card.name,
            date=date_value,
            time=time_value,
        )
        message = (
            f"Записали {_pet_name_accusative(appointment.pet_name)} "
            f"на {appointment.date} в {appointment.time}"
        )
        if created_patient:
            message += f". Карточка {patient_card.name} создана автоматически"
        return {
            "status": "success",
            "patient_id": str(patient_card.id),
            "message": message,
        }

    if name == "set_reminder":
        reminder = await create_reminder(
            session,
            user_id=user_id,
            text=_required_string(parsed, "text"),
            time=_required_string(parsed, "time"),
        )
        return {
            "status": "success",
            "message": f"Напоминание создано: {reminder.text} ({reminder.time})",
        }

    raise ToolExecutionError(f"неизвестный инструмент: {name}")


def build_tools_instruction(tools: Sequence[ToolDefinition]) -> str:
    """Собрать инструкцию по вызову доступных инструментов."""
    names = ", ".join(tool.function.name for tool in tools)
    if not names:
        return ""
    tool_names = {tool.function.name for tool in tools}
    patient_rule = ""
    if "create_patient" in tool_names:
        patient_rule = (
            " Если пользователь просит создать карточку, вызывай create_patient "
            "немедленно, не задавая уточняющих вопросов. Вызывай его сразу, как "
            "только названы кличка и вид: вес, вакцинация и порода необязательны. "
            "Если питомец только упомянут и карточки ещё нет, предложи создать её "
            "и вызови create_patient, не выдумывая кличку и вид."
        )
    appointment_rule = ""
    if "book_appointment" in tool_names:
        appointment_rule = (
            " Для book_appointment сначала убедись, что у питомца есть карточка. "
            "Если карточки нет, вызови create_patient (или передай species в "
            "book_appointment, чтобы карточка создалась автоматически). Не "
            "создавай запись на приём без карточки питомца."
        )
    return (
        f"Тебе доступны инструменты: {names}. "
        "Если пользователь просит записать питомца на приём или создать напоминание, "
        "верни ТОЛЬКО JSON-объект без markdown и пояснений в формате "
        '{"name": "<имя инструмента>", "arguments": {...}}. '
        "Не выдумывай дату, время или кличку, если пользователь их не указал."
        f"{patient_rule}{appointment_rule}"
    )


def with_tools_instruction(
    messages: Sequence[dict[str, str]],
    tools: Sequence[ToolDefinition],
) -> list[dict[str, str]]:
    """Добавить инструкцию по инструментам в system message."""
    instruction = build_tools_instruction(tools)
    result = [dict(message) for message in messages]
    if not instruction:
        return result

    for index, message in enumerate(result):
        if message.get("role") == "system":
            content = message.get("content", "").strip()
            result[index] = {
                **message,
                "content": f"{content}\n\n{instruction}".strip(),
            }
            return result

    return [{"role": "system", "content": instruction}, *result]


def _loads_json(text: str) -> Any | None:
    """Разобрать JSON, вернув ``None`` при ошибке."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _arguments_json(value: Any) -> str:
    """Привести аргументы к JSON-строке, как в OpenAI API."""
    if value is None:
        value = {}
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "{}"
        parsed = _loads_json(stripped)
        if parsed is None:
            return stripped
        value = parsed
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _iter_payloads(payload: Any) -> Iterator[dict[str, Any]]:
    """Развернуть одиночный вызов, список или обёртку ``tool_calls``."""
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_payloads(item)
        return
    if not isinstance(payload, dict):
        return

    nested = payload.get("tool_calls")
    if isinstance(nested, list):
        for item in nested:
            yield from _iter_payloads(item)
        return

    function = payload.get("function")
    if isinstance(function, dict):
        yield payload
        return

    yield payload


def _payload_to_call(payload: Any, allowed: set[str]) -> ToolCall | None:
    """Преобразовать один JSON-объект в :class:`ToolCall`."""
    if not isinstance(payload, dict):
        return None

    function = payload.get("function")
    if not isinstance(function, dict):
        function = payload

    name = function.get("name")
    if not isinstance(name, str) or name not in allowed:
        return None

    raw_arguments = function.get("arguments")
    if raw_arguments is None:
        raw_arguments = function.get("parameters")
    if raw_arguments is None:
        raw_arguments = payload.get("arguments")
    if raw_arguments is None:
        raw_arguments = payload.get("parameters")

    raw_id = payload.get("id") or function.get("id")
    call_id = str(raw_id) if raw_id else f"call_{uuid.uuid4().hex[:24]}"
    return ToolCall(
        id=call_id,
        function=ToolCallFunction(
            name=name,
            arguments=_arguments_json(raw_arguments),
        ),
    )


def normalize_native_tool_calls(
    raw_calls: Any,
    *,
    allowed_tools: Iterable[str],
) -> list[ToolCall]:
    """Преобразовать нативные ``message.tool_calls`` llama-cpp-python."""
    allowed = {name for name in allowed_tools if name}
    if not allowed or not isinstance(raw_calls, list):
        return []
    calls = [
        call for payload in raw_calls if (call := _payload_to_call(payload, allowed)) is not None
    ]
    return calls


def parse_tool_calls(
    text: str,
    *,
    allowed_tools: Iterable[str],
) -> tuple[list[ToolCall], str]:
    """Найти вызовы инструментов в тексте ответа модели.

    Returns:
        ``(tool_calls, remaining_text)``. Если вызовов нет, возвращает
        пустой список и исходный текст без изменений.
    """
    allowed = {name for name in allowed_tools if name}
    if not allowed or not text.strip():
        return [], text

    blocks = list(_TOOL_CALL_BLOCK.finditer(text))
    if blocks:
        calls: list[ToolCall] = []
        for match in blocks:
            payload = _loads_json(match.group(1).strip())
            if payload is None:
                continue
            calls.extend(
                call
                for item in _iter_payloads(payload)
                if (call := _payload_to_call(item, allowed)) is not None
            )
        if not calls:
            return [], text
        remaining = _TOOL_CALL_BLOCK.sub(" ", text).strip()
        return calls, remaining

    fenced = _FENCED_JSON.fullmatch(text.strip())
    candidate = fenced.group(1).strip() if fenced else text.strip()
    start = candidate.find("{")
    if start == -1:
        return [], text

    decoder = json.JSONDecoder()
    try:
        payload, end = decoder.raw_decode(candidate[start:])
    except json.JSONDecodeError:
        return [], text

    calls = [
        call
        for item in _iter_payloads(payload)
        if (call := _payload_to_call(item, allowed)) is not None
    ]
    if not calls:
        return [], text

    remaining = (candidate[:start] + candidate[start + end :]).strip()
    return calls, remaining
