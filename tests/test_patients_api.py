"""Тесты API карточек пациентов (T-161).

Покрывают:
- авторизацию всех эндпоинтов;
- создание, список, PATCH и историю эпизодов;
- изоляцию пользователей: чужой пациент всегда 404;
- валидацию полей и PATCH-семантику;
- отсутствие embedding и user_id в ответах истории.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import hash_password
from app.database import (
    Database,
    add_episode,
    create_user,
    get_user_by_email,
)
from app.main import app, limiter
from app.settings import get_app_settings

OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "secret-pass-1"
OTHER_EMAIL = "other@example.com"
OTHER_PASSWORD = "secret-pass-2"


def _db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'patients_api.db').as_posix()}"


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


async def _seed_episodes(
    database_url: str,
    email: str,
    patient_id: int,
    count: int,
) -> None:
    database = Database(database_url)
    try:
        async with database.session() as session:
            user = await get_user_by_email(session, email)
            assert user is not None
            for index in range(count):
                await add_episode(
                    session,
                    user_id=user.id,
                    patient_id=patient_id,
                    content=f"эпизод {index}",
                    episode_type="manual",
                )
    finally:
        await database.dispose()


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def patients_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Клиент API с временной SQLite-БД и двумя пользователями."""
    database_url = _db_url(tmp_path)
    monkeypatch.setenv("VET_API_DATABASE_URL", database_url)
    monkeypatch.setenv("VET_API_PROMETHEUS_URL", "")
    get_app_settings.cache_clear()
    limiter.reset()
    with TestClient(app) as client:
        asyncio.run(_seed_users(database_url))
        yield client
    limiter.reset()
    get_app_settings.cache_clear()


def _create_patient(
    client: TestClient,
    *,
    name: str = "Бобик",
    species: str = "dog",
    **extra: object,
) -> dict[str, object]:
    payload = {"name": name, "species": species, **extra}
    response = client.post("/v1/patients", json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_patients_require_authentication(patients_client: TestClient) -> None:
    endpoints = [
        ("GET", "/v1/patients"),
        ("POST", "/v1/patients"),
        ("PATCH", "/v1/patients/1"),
        ("GET", "/v1/patients/1/history"),
    ]
    for method, path in endpoints:
        response = patients_client.request(method, path, json={})
        assert response.status_code == 401, (method, path, response.text)


def test_create_patient_returns_card(patients_client: TestClient) -> None:
    patients_client.headers.update(_login(patients_client, OWNER_EMAIL, OWNER_PASSWORD))

    created = _create_patient(
        patients_client,
        name="  Бобик  ",
        species="dog",
        breed="Корги",
        birth_date="2020-05-01",
        weight=12.5,
        known_allergies="курица",
        chronic_conditions="артрит",
    )

    assert created["id"] == 1
    assert created["name"] == "Бобик"
    assert created["species"] == "dog"
    assert created["breed"] == "Корги"
    assert created["birth_date"] == "2020-05-01"
    assert created["weight"] == 12.5
    assert created["age_years"] >= 5
    assert created["known_allergies"] == "курица"
    assert created["chronic_conditions"] == "артрит"
    assert created["created_at"]
    assert created["updated_at"]
    assert "user_id" not in created


def test_list_patients_is_scoped_to_current_user(
    patients_client: TestClient,
) -> None:
    patients_client.headers.update(_login(patients_client, OWNER_EMAIL, OWNER_PASSWORD))
    own = _create_patient(patients_client, name="Бобик")

    patients_client.headers.update(_login(patients_client, OTHER_EMAIL, OTHER_PASSWORD))
    foreign = _create_patient(patients_client, name="Рекс")

    assert [
        item["id"] for item in patients_client.get("/v1/patients").json()
    ] == [foreign["id"]]

    patients_client.headers.update(_login(patients_client, OWNER_EMAIL, OWNER_PASSWORD))
    assert [
        item["id"] for item in patients_client.get("/v1/patients").json()
    ] == [own["id"]]

    # Чужой пациент не виден и не редактируется.
    assert (
        patients_client.patch(
            f"/v1/patients/{foreign['id']}", json={"name": "Чужой"}
        ).status_code
        == 404
    )
    assert (
        patients_client.get(f"/v1/patients/{foreign['id']}/history").status_code
        == 404
    )


def test_patch_patient_updates_and_clears_fields(
    patients_client: TestClient,
) -> None:
    patients_client.headers.update(_login(patients_client, OWNER_EMAIL, OWNER_PASSWORD))
    created = _create_patient(
        patients_client,
        breed="Корги",
        weight=10,
        known_allergies="курица",
    )

    response = patients_client.patch(
        f"/v1/patients/{created['id']}",
        json={"weight": 11.5, "breed": None, "chronic_conditions": "артрит"},
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["name"] == "Бобик"
    assert updated["weight"] == 11.5
    assert updated["breed"] is None
    assert updated["known_allergies"] == "курица"
    assert updated["chronic_conditions"] == "артрит"


def test_patch_patient_rejects_null_required_fields(
    patients_client: TestClient,
) -> None:
    patients_client.headers.update(_login(patients_client, OWNER_EMAIL, OWNER_PASSWORD))
    created = _create_patient(patients_client)

    for field in ("name", "species"):
        response = patients_client.patch(
            f"/v1/patients/{created['id']}",
            json={field: None},
        )
        assert response.status_code == 422, (field, response.text)


def test_patch_patient_without_changes_returns_card(
    patients_client: TestClient,
) -> None:
    patients_client.headers.update(_login(patients_client, OWNER_EMAIL, OWNER_PASSWORD))
    created = _create_patient(patients_client)

    response = patients_client.patch(f"/v1/patients/{created['id']}", json={})

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_patch_unknown_patient_returns_404(patients_client: TestClient) -> None:
    patients_client.headers.update(_login(patients_client, OWNER_EMAIL, OWNER_PASSWORD))
    response = patients_client.patch("/v1/patients/999", json={"name": "Никто"})
    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   ", "species": "dog"},
        {"name": "Бобик", "species": "hamster"},
        {"name": "Бобик", "species": "dog", "weight": 0},
        {"name": "Бобик", "species": "dog", "weight": -1},
        {
            "name": "Бобик",
            "species": "dog",
            "birth_date": (date.today() + timedelta(days=1)).isoformat(),
        },
        {"name": "Бобик", "species": "dog", "unknown": "поле"},
    ],
)
def test_create_patient_validates_payload(
    patients_client: TestClient,
    payload: dict[str, object],
) -> None:
    patients_client.headers.update(_login(patients_client, OWNER_EMAIL, OWNER_PASSWORD))
    response = patients_client.post("/v1/patients", json=payload)
    assert response.status_code == 422, response.text


def test_history_is_empty_for_new_patient(patients_client: TestClient) -> None:
    patients_client.headers.update(_login(patients_client, OWNER_EMAIL, OWNER_PASSWORD))
    created = _create_patient(patients_client)

    response = patients_client.get(f"/v1/patients/{created['id']}/history")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }


def test_history_paginates_and_hides_embedding(
    patients_client: TestClient,
    tmp_path: Path,
) -> None:
    database_url = _db_url(tmp_path)
    patients_client.headers.update(_login(patients_client, OWNER_EMAIL, OWNER_PASSWORD))
    created = _create_patient(patients_client)
    asyncio.run(
        _seed_episodes(database_url, OWNER_EMAIL, int(created["id"]), count=3)
    )

    response = patients_client.get(
        f"/v1/patients/{created['id']}/history",
        params={"limit": 2, "offset": 0},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert [item["content"] for item in body["items"]] == [
        "эпизод 2",
        "эпизод 1",
    ]
    assert set(body["items"][0]) == {
        "id",
        "patient_id",
        "type",
        "content",
        "created_at",
    }

    second = patients_client.get(
        f"/v1/patients/{created['id']}/history",
        params={"limit": 2, "offset": 2},
    )
    assert [item["content"] for item in second.json()["items"]] == ["эпизод 0"]
    assert second.json()["total"] == 3


def test_history_limit_is_validated(patients_client: TestClient) -> None:
    patients_client.headers.update(_login(patients_client, OWNER_EMAIL, OWNER_PASSWORD))
    created = _create_patient(patients_client)

    for limit in (0, 101):
        response = patients_client.get(
            f"/v1/patients/{created['id']}/history",
            params={"limit": limit},
        )
        assert response.status_code == 422, limit

    response = patients_client.get(
        f"/v1/patients/{created['id']}/history",
        params={"offset": -1},
    )
    assert response.status_code == 422
