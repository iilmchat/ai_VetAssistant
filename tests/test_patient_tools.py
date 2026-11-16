"""Тесты agentic-создания карточки питомца (T-163).

Покрывают:
- инструмент ``create_patient``: создание, возраст→дата рождения, дубликаты;
- валидацию аргументов;
- серверную инъекцию инструмента, если карточка не выбрана, а питомец
  упомянут в сообщении;
- проактивную инструкцию в system prompt;
- сквозной agentic loop через API.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.backends import CpuLlamaBackend
from app.database import (
    Database,
    Patient,
    create_user,
    list_patients,
)
from app.main import (
    ChatCompletionRequest,
    _effective_tools,
    _mentions_pet,
    _requests_patient_creation,
    app,
    get_backend_router,
    get_knowledge_base,
    limiter,
)
from app.memory import PatientMemory, get_patient_memory
from app.router import BackendRouter
from app.settings import get_app_settings
from app.tools import (
    CREATE_PATIENT_TOOL,
    ToolDefinition,
    ToolExecutionError,
    build_tools_instruction,
    execute_tool,
)

OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "secret-pass-1"


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'patient_tools.db').as_posix()}")
    await db.create_tables()
    yield db
    await db.dispose()


@pytest.fixture
async def user_id(database: Database) -> int:
    async with database.session() as session:
        user = await create_user(
            session,
            email=OWNER_EMAIL,
            hashed_password="hash-1",
        )
    return user.id


async def test_create_patient_tool_persists_card(
    database: Database,
    user_id: int,
) -> None:
    async with database.session() as session:
        result = await execute_tool(
            "create_patient",
            {
                "name": "  Бобик ",
                "species": "DOG",
                "breed": "Корги",
                "age": 3,
            },
            session=session,
            user_id=user_id,
        )

    assert result["status"] == "success"
    assert result["message"] == "Карточка Бобик создана"
    async with database.session() as session:
        patients = await list_patients(session, user_id=user_id)
    assert len(patients) == 1
    assert patients[0].name == "Бобик"
    assert patients[0].species == "dog"
    assert patients[0].breed == "Корги"
    assert patients[0].birth_date is not None
    age_days = (date.today() - patients[0].birth_date).days
    assert abs(age_days - 3 * 365) <= 1


async def test_create_patient_tool_returns_existing_without_duplicate(
    database: Database,
    user_id: int,
) -> None:
    async with database.session() as session:
        first = await execute_tool(
            "create_patient",
            {"name": "Бобик", "species": "dog"},
            session=session,
            user_id=user_id,
        )
        second = await execute_tool(
            "create_patient",
            {"name": "бобик", "species": "dog", "breed": "Корги"},
            session=session,
            user_id=user_id,
        )

    assert second["status"] == "exists"
    assert second["patient_id"] == first["patient_id"]
    async with database.session() as session:
        patients = await list_patients(session, user_id=user_id)
    assert len(patients) == 1


@pytest.mark.parametrize(
    "arguments",
    [
        {"species": "dog"},
        {"name": "Бобик", "species": "hamster"},
        {"name": "Бобик", "species": "dog", "age": -1},
        {"name": "Бобик", "species": "dog", "age": 41},
        {"name": "Бобик", "species": "dog", "age": "3"},
        {"name": "Бобик", "species": "dog", "breed": 123},
    ],
)
async def test_create_patient_tool_validates_arguments(
    database: Database,
    user_id: int,
    arguments: dict[str, object],
) -> None:
    async with database.session() as session:
        with pytest.raises(ToolExecutionError):
            await execute_tool(
                "create_patient",
                arguments,
                session=session,
                user_id=user_id,
            )


def test_mentions_pet_detects_common_phrases() -> None:
    for text in (
        "У меня собака Бобик, чешется",
        "Мой пёс хромает",
        "Завели котёнка, что делать",
        "Есть кличка?",
        "Создай карточку Мурзика",
        "Создать питомца",
        "Добавь питомца",
        "Заведи карточку",
    ):
        assert _mentions_pet(text), text

    assert not _mentions_pet("Какая доза парацетамола для кошки?")
    assert not _mentions_pet("Кот не ест второй день")
    # «который» не должен считаться упоминанием кота.
    assert not _mentions_pet("Кашель, который длится неделю")


@pytest.mark.parametrize(
    "text",
    [
        "Создай карточку Мурзика",
        "Создайте карточку для кота",
        "Пожалуйста, создай новую карточку",
        "Создать питомца",
        "Создай питомца по имени Барсик",
        "Добавь питомца",
        "Добавьте питомца в список",
        "Заведи карточку",
        "Заведите карточку на собаку",
        "Завести карточку питомца",
        "Create a patient",
        "Create pet card",
        "Add a pet",
    ],
)
def test_requests_patient_creation_detects_explicit_phrases(text: str) -> None:
    assert _requests_patient_creation(text), text


@pytest.mark.parametrize(
    "text",
    [
        "Открой карточку Мурзика",
        "Покажи карточку питомца",
        "Какая доза парацетамола для кошки?",
        "Кот не ест второй день",
        "Запиши Мурзика на приём",
    ],
)
def test_requests_patient_creation_ignores_other_requests(text: str) -> None:
    assert not _requests_patient_creation(text), text


def _request(**overrides: Any) -> ChatCompletionRequest:
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": "Привет"}],
    }
    payload.update(overrides)
    return ChatCompletionRequest.model_validate(payload)


def test_effective_tools_injects_create_patient_for_pet_mention() -> None:
    request = _request()

    tools = _effective_tools(request, query="У меня собака Бобик, чешется")

    assert [tool.function.name for tool in tools] == ["create_patient"]


def test_effective_tools_injects_create_patient_for_explicit_request() -> None:
    request = _request()

    tools = _effective_tools(request, query="Создай карточку Мурзика")

    assert [tool.function.name for tool in tools] == ["create_patient"]


def test_effective_tools_explicit_request_overrides_selected_patient() -> None:
    request = _request(patient_id=5)

    tools = _effective_tools(request, query="Создай карточку Мурзика")

    assert [tool.function.name for tool in tools] == ["create_patient"]


def test_effective_tools_explicit_request_overrides_disable_flag() -> None:
    request = _request(use_patient_tools=False)

    tools = _effective_tools(request, query="Добавь питомца Мурзика")

    assert [tool.function.name for tool in tools] == ["create_patient"]


def test_effective_tools_skips_generic_question() -> None:
    request = _request()

    assert _effective_tools(request, query="Какая доза парацетамола?") == []


def test_effective_tools_skips_selected_patient() -> None:
    request = _request(patient_id=5)

    assert _effective_tools(request, query="У меня собака Бобик") == []


def test_effective_tools_respects_disable_flag() -> None:
    request = _request(use_patient_tools=False)

    assert _effective_tools(request, query="У меня собака Бобик") == []


def test_effective_tools_explicit_request_adds_to_client_tools() -> None:
    client_tools = [
        ToolDefinition.model_validate(
            {
                "type": "function",
                "function": {
                    "name": "book_appointment",
                    "description": "Запись",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        )
    ]
    request = _request(tools=client_tools)

    tools = _effective_tools(request, query="Создай карточку Мурзика")

    assert [tool.function.name for tool in tools] == [
        "book_appointment",
        "create_patient",
    ]


def test_effective_tools_does_not_duplicate_create_patient_for_explicit_request() -> None:
    request = _request(
        tools=[ToolDefinition.model_validate(CREATE_PATIENT_TOOL)],
    )

    tools = _effective_tools(request, query="Создай карточку Мурзика")

    assert [tool.function.name for tool in tools] == ["create_patient"]


def test_effective_tools_keeps_client_tools_and_avoids_duplicate() -> None:
    client_tools = [
        ToolDefinition.model_validate(
            {
                "type": "function",
                "function": {
                    "name": "book_appointment",
                    "description": "Запись",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ),
        ToolDefinition.model_validate(CREATE_PATIENT_TOOL),
    ]
    request = _request(tools=client_tools)

    tools = _effective_tools(request, query="У меня собака Бобик")

    assert [tool.function.name for tool in tools] == [
        "book_appointment",
        "create_patient",
    ]


def test_tools_instruction_is_proactive() -> None:
    tools = [ToolDefinition.model_validate(CREATE_PATIENT_TOOL)]

    instruction = build_tools_instruction(tools)

    assert "create_patient" in instruction
    assert "предложи создать её" in instruction
    assert "Не выдумывай кличку" in instruction
    assert "а не book_appointment" in instruction
    assert "создай карточку" in instruction


class FakeModel:
    """Модель, которая сначала просит создать карточку, затем отвечает."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_chat_completion(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return {
                "id": "chatcmpl-tool",
                "object": "chat.completion",
                "created": 1,
                "model": "fake",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "create_patient",
                                        "arguments": json.dumps(
                                            {
                                                "name": "Бобик",
                                                "species": "dog",
                                                "breed": "Корги",
                                                "age": 3,
                                            },
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }
        return {
            "id": "chatcmpl-final",
            "object": "chat.completion",
            "created": 2,
            "model": "fake",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Создал карточку Бобика. Расскажите, что беспокоит?",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        }


def _db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'patient_tools_api.db').as_posix()}"


async def _seed_user(database_url: str) -> None:
    database = Database(database_url)
    try:
        await database.create_tables()
        async with database.session() as session:
            await create_user(
                session,
                email=OWNER_EMAIL,
                hashed_password=hash_password(OWNER_PASSWORD),
            )
    finally:
        await database.dispose()


async def _patients(database_url: str) -> list[Patient]:
    database = Database(database_url)
    try:
        async with database.session() as session:
            result = await session.execute(select(Patient).order_by(Patient.id))
            return list(result.scalars().all())
    finally:
        await database.dispose()


@pytest.fixture
def agent_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str, FakeModel]]:
    database_url = _db_url(tmp_path)
    monkeypatch.setenv("VET_API_DATABASE_URL", database_url)
    monkeypatch.setenv("VET_API_GPU_BACKEND_ENABLED", "false")
    get_app_settings.cache_clear()
    limiter.reset()

    fake_model = FakeModel()
    backend = BackendRouter(
        gpu=None,
        cpu=CpuLlamaBackend(model=fake_model),
        settings=get_app_settings(),
    )
    memory = PatientMemory(embedder=lambda text: [1.0] * 384)
    app.dependency_overrides[get_backend_router] = lambda: backend
    app.dependency_overrides[get_knowledge_base] = lambda: None
    app.dependency_overrides[get_patient_memory] = lambda: memory

    with TestClient(app) as client:
        asyncio.run(_seed_user(database_url))
        login = client.post(
            "/v1/auth/login",
            json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
        )
        assert login.status_code == 200
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield client, database_url, fake_model

    app.dependency_overrides.clear()
    limiter.reset()
    get_app_settings.cache_clear()


def test_api_injects_tool_and_creates_patient_agentically(
    agent_client: tuple[TestClient, str, FakeModel],
) -> None:
    client, database_url, fake_model = agent_client

    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {"role": "user", "content": "У меня собака Бобик, 3 года, чешется"}
            ]
        },
    )

    assert response.status_code == 200, response.text
    assert len(fake_model.calls) == 2
    first_tools = fake_model.calls[0].get("tools") or []
    assert any(
        tool["function"]["name"] == "create_patient" for tool in first_tools
    )
    system = fake_model.calls[0]["messages"][0]["content"]
    assert "предложи создать её" in system

    patients = asyncio.run(_patients(database_url))
    assert len(patients) == 1
    assert patients[0].name == "Бобик"
    assert patients[0].species == "dog"
    assert response.json()["choices"][0]["message"]["tool_calls"][0]["function"][
        "name"
    ] == "create_patient"


def test_api_does_not_inject_tool_for_generic_question(
    agent_client: tuple[TestClient, str, FakeModel],
) -> None:
    client, database_url, fake_model = agent_client

    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Какая доза парацетамола?"}]
        },
    )

    assert response.status_code == 200
    assert fake_model.calls[0].get("tools") is None
    assert asyncio.run(_patients(database_url)) == []


def test_api_explicit_card_request_wins_over_client_appointment_tool(
    agent_client: tuple[TestClient, str, FakeModel],
) -> None:
    client, database_url, fake_model = agent_client

    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Создай карточку Мурзика"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "book_appointment",
                        "description": "Запись на приём",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    first_tools = fake_model.calls[0].get("tools") or []
    assert {tool["function"]["name"] for tool in first_tools} == {
        "book_appointment",
        "create_patient",
    }
    system = fake_model.calls[0]["messages"][0]["content"]
    assert "а не book_appointment" in system

    patients = asyncio.run(_patients(database_url))
    assert len(patients) == 1
    assert patients[0].name == "Бобик"
