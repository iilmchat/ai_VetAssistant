"""Интеграционные тесты памяти в чате (T-162).

Проверяют сквозной сценарий: контекст пациента попадает в system prompt,
ответ сохраняется как эпизод, а память не ломает чат при сбоях.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password
from app.backends import CpuLlamaBackend
from app.database import (
    MEMORY_EMBEDDING_DIM,
    Database,
    Episode,
    create_user,
)
from app.main import app, get_backend_router, get_knowledge_base, limiter
from app.memory import PatientMemory, get_patient_memory
from app.router import BackendRouter
from app.settings import get_app_settings

OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "secret-pass-1"
OTHER_EMAIL = "other@example.com"
OTHER_PASSWORD = "secret-pass-2"


class FakeModel:
    """Заглушка llama-cpp-python: фиксирует промпты и отдаёт текст."""

    def __init__(self, text: str = "Рекомендую осмотр у ветеринара.") -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def create_chat_completion(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return iter(
                [
                    {
                        "id": "chatcmpl-fake",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "fake",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": self.text},
                                "finish_reason": None,
                            }
                        ],
                    },
                    {
                        "id": "chatcmpl-fake",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "fake",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop",
                            }
                        ],
                    },
                ]
            )
        return {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": 1,
            "model": "fake",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": self.text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }


def _vector(index: int) -> list[float]:
    values = [0.0] * MEMORY_EMBEDDING_DIM
    values[index] = 1.0
    return values


def _fake_embedder(text: str) -> Sequence[float]:
    if "сыпь" in text.casefold():
        return _vector(0)
    return _vector(1)


def _failing_embedder(text: str) -> Sequence[float]:
    raise RuntimeError("эмбеддер недоступен")


def _db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'memory_api.db').as_posix()}"


async def _seed_users(database_url: str) -> None:
    database = Database(database_url)
    try:
        await database.create_tables()
        async with database.session() as session:
            await create_user(
                session,
                email=OWNER_EMAIL,
                hashed_password=hash_password(OWNER_PASSWORD),
            )
            await create_user(
                session,
                email=OTHER_EMAIL,
                hashed_password=hash_password(OTHER_PASSWORD),
            )
    finally:
        await database.dispose()


async def _episodes(database_url: str) -> list[Episode]:
    database = Database(database_url)
    try:
        async with database.session() as session:
            result = await session.execute(select(Episode).order_by(Episode.id))
            return list(result.scalars().all())
    finally:
        await database.dispose()


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_patient(
    client: TestClient,
    *,
    name: str = "Бобик",
    species: str = "dog",
) -> int:
    response = client.post(
        "/v1/patients",
        json={
            "name": name,
            "species": species,
            "breed": "Корги",
            "known_allergies": "курица",
            "chronic_conditions": "артрит",
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


@pytest.fixture
def memory_client(
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
    memory = PatientMemory(embedder=_fake_embedder)
    app.dependency_overrides[get_backend_router] = lambda: backend
    app.dependency_overrides[get_knowledge_base] = lambda: None
    app.dependency_overrides[get_patient_memory] = lambda: memory

    with TestClient(app) as client:
        asyncio.run(_seed_users(database_url))
        yield client, database_url, fake_model

    app.dependency_overrides.clear()
    limiter.reset()
    get_app_settings.cache_clear()


def test_chat_injects_profile_and_saves_episode(
    memory_client: tuple[TestClient, str, FakeModel],
) -> None:
    client, database_url, fake_model = memory_client
    client.headers.update(_login(client, OWNER_EMAIL, OWNER_PASSWORD))
    patient_id = _create_patient(client)

    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "У Бобика снова сыпь"}],
            "patient_id": patient_id,
        },
    )

    assert response.status_code == 200, response.text
    system = fake_model.calls[0]["messages"][0]["content"]
    assert "Профиль пациента: Бобик" in system
    assert "Аллергии: курица" in system
    assert "Хронические болезни: артрит" in system

    episodes = asyncio.run(_episodes(database_url))
    assert len(episodes) == 1
    assert episodes[0].type == "chat"
    assert episodes[0].content.startswith("Вопрос: ")
    assert "сыпь" in episodes[0].content.casefold()
    assert "Рекомендую осмотр" in episodes[0].content


def test_second_chat_uses_saved_episode(
    memory_client: tuple[TestClient, str, FakeModel],
) -> None:
    client, database_url, fake_model = memory_client
    client.headers.update(_login(client, OWNER_EMAIL, OWNER_PASSWORD))
    patient_id = _create_patient(client)

    first = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "У Бобика сыпь на животе"}],
            "patient_id": patient_id,
        },
    )
    assert first.status_code == 200
    assert len(asyncio.run(_episodes(database_url))) == 1

    second = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Это снова та же сыпь?"}],
            "patient_id": patient_id,
        },
    )

    assert second.status_code == 200
    system = fake_model.calls[1]["messages"][0]["content"]
    assert "История:" in system
    assert "сыпь на животе" in system.casefold()
    assert len(asyncio.run(_episodes(database_url))) == 2


def test_stream_chat_saves_episode(
    memory_client: tuple[TestClient, str, FakeModel],
) -> None:
    client, database_url, _ = memory_client
    client.headers.update(_login(client, OWNER_EMAIL, OWNER_PASSWORD))
    patient_id = _create_patient(client)

    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Сыпь у кошки"}],
            "patient_id": patient_id,
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    assert "Рекомендую осмотр" in response.text

    episodes = asyncio.run(_episodes(database_url))
    assert len(episodes) == 1
    assert "Рекомендую осмотр" in episodes[0].content


def test_chat_without_patient_does_not_save_episode(
    memory_client: tuple[TestClient, str, FakeModel],
) -> None:
    client, database_url, fake_model = memory_client
    client.headers.update(_login(client, OWNER_EMAIL, OWNER_PASSWORD))

    response = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Сыпь"}]},
    )

    assert response.status_code == 200
    assert "Профиль пациента" not in fake_model.calls[0]["messages"][0]["content"]
    assert asyncio.run(_episodes(database_url)) == []


def test_foreign_patient_returns_404_and_skips_model(
    memory_client: tuple[TestClient, str, FakeModel],
) -> None:
    client, _, fake_model = memory_client

    client.headers.update(_login(client, OTHER_EMAIL, OTHER_PASSWORD))
    foreign_id = _create_patient(client, name="Рекс")

    client.headers.update(_login(client, OWNER_EMAIL, OWNER_PASSWORD))
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Сыпь"}],
            "patient_id": foreign_id,
        },
    )

    assert response.status_code == 404
    assert fake_model.calls == []


def test_embedder_failure_still_saves_episode(
    memory_client: tuple[TestClient, str, FakeModel],
) -> None:
    client, database_url, _ = memory_client
    client.headers.update(_login(client, OWNER_EMAIL, OWNER_PASSWORD))
    patient_id = _create_patient(client)
    app.dependency_overrides[get_patient_memory] = lambda: PatientMemory(
        embedder=_failing_embedder
    )

    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Сыпь"}],
            "patient_id": patient_id,
        },
    )

    assert response.status_code == 200
    episodes = asyncio.run(_episodes(database_url))
    assert len(episodes) == 1
    assert episodes[0].embedding is None
