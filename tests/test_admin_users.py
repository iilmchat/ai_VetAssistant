"""Тесты управления пользователями в админ-панели (T-140.1, T-140.2).

Покрывают:
- список пользователей: права, пагинация, поиск и фильтр по статусу;
- блокировку: 403 по действующему JWT, аудит, идемпотентность;
- разблокировку;
- защиту от блокировки/удаления себя и последнего активного админа;
- удаление с подтверждением по email и каскад связанных записей.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.admin as admin_module
from app.auth import hash_password
from app.database import (
    AccessRequest,
    AdminAction,
    Appointment,
    Database,
    Reminder,
    TelegramLinkCode,
    create_user,
    get_user_by_email,
)
from app.main import app, limiter
from app.settings import get_app_settings

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-pass-1"


def _db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'admin_users.db').as_posix()}"


async def _create_user(
    database_url: str,
    email: str,
    password: str,
    *,
    is_admin: bool = False,
) -> int:
    database = Database(database_url)
    try:
        await database.create_tables()
        async with database.session() as session:
            user = await create_user(
                session,
                email=email,
                hashed_password=hash_password(password),
                is_admin=is_admin,
            )
            return int(user.id)
    finally:
        await database.dispose()


async def _seed_related(database_url: str, user_id: int) -> None:
    """Создать записи, которые должны исчезнуть/обнулиться при удалении."""
    database = Database(database_url)
    try:
        async with database.session() as session:
            session.add(
                Appointment(
                    user_id=user_id,
                    pet_name="Мурзик",
                    date="2026-11-09",
                    time="10:00",
                )
            )
            session.add(
                Reminder(
                    user_id=user_id,
                    text="Дать таблетку",
                    time="20:00",
                )
            )
            session.add(
                TelegramLinkCode(
                    user_id=user_id,
                    code_hash="a" * 64,
                    expires_at=datetime.now(UTC),
                )
            )
            session.add(
                AccessRequest(
                    email="pending@example.com",
                    reason="хочу доступ",
                    status="approved",
                    reviewed_by=user_id,
                    approved_user_id=user_id,
                )
            )
            await session.commit()
    finally:
        await database.dispose()


async def _actions(database_url: str) -> list[AdminAction]:
    database = Database(database_url)
    try:
        async with database.session() as session:
            result = await session.execute(select(AdminAction).order_by(AdminAction.id))
            return list(result.scalars().all())
    finally:
        await database.dispose()


async def _user_is_active(database_url: str, email: str) -> bool | None:
    database = Database(database_url)
    try:
        async with database.session() as session:
            user = await get_user_by_email(session, email)
            return None if user is None else bool(user.is_active)
    finally:
        await database.dispose()


async def _related_counts(database_url: str) -> tuple[int, int, int]:
    database = Database(database_url)
    try:
        async with database.session() as session:
            appointments = await session.scalar(
                select(func.count()).select_from(Appointment)
            )
            reminders = await session.scalar(
                select(func.count()).select_from(Reminder)
            )
            codes = await session.scalar(
                select(func.count()).select_from(TelegramLinkCode)
            )
            return int(appointments or 0), int(reminders or 0), int(codes or 0)
    finally:
        await database.dispose()


async def _access_request_owner_ids(database_url: str) -> tuple[int | None, int | None]:
    database = Database(database_url)
    try:
        async with database.session() as session:
            result = await session.execute(select(AccessRequest))
            request = result.scalar_one()
            return request.reviewed_by, request.approved_user_id
    finally:
        await database.dispose()


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, str]]:
    """TestClient с изолированной SQLite-БД."""
    database_url = _db_url(tmp_path)
    monkeypatch.setenv("VET_API_DATABASE_URL", database_url)
    monkeypatch.setenv("VET_API_GPU_BACKEND_ENABLED", "false")
    get_app_settings.cache_clear()
    limiter.reset()
    with TestClient(app) as client:
        yield client, database_url
    limiter.reset()
    get_app_settings.cache_clear()


@pytest.fixture
def admin_api(api: tuple[TestClient, str]) -> tuple[TestClient, str, int]:
    """Админский клиент и id администратора."""
    client, database_url = api
    admin_id = asyncio.run(
        _create_user(
            database_url,
            ADMIN_EMAIL,
            ADMIN_PASSWORD,
            is_admin=True,
        )
    )
    client.headers["Authorization"] = _login(
        client,
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
    )["Authorization"]
    return client, database_url, admin_id


def test_users_list_requires_admin(api: tuple[TestClient, str]) -> None:
    """Не-админ получает 403, аноним — 401."""
    client, database_url = api
    asyncio.run(_create_user(database_url, "owner@example.com", "owner-pass-1"))

    client.headers["Authorization"] = _login(
        client,
        "owner@example.com",
        "owner-pass-1",
    )["Authorization"]
    assert client.get("/v1/admin/users").status_code == 403

    client.headers.pop("Authorization")
    assert client.get("/v1/admin/users").status_code == 401


def test_users_list_paginates_searches_and_filters(
    admin_api: tuple[TestClient, str, int],
) -> None:
    client, database_url, admin_id = admin_api
    asyncio.run(_create_user(database_url, "alice@example.com", "alice-pass-1"))
    bob_id = asyncio.run(
        _create_user(database_url, "bob@example.com", "bob-pass-1")
    )
    asyncio.run(_create_user(database_url, "carol@example.com", "carol-pass-1"))

    first_page = client.get("/v1/admin/users?limit=2&offset=0")
    assert first_page.status_code == 200
    payload = first_page.json()
    assert payload["total"] == 4
    assert payload["limit"] == 2
    assert payload["offset"] == 0
    assert [item["id"] for item in payload["items"]] == [
        admin_id,
        admin_id + 1,
    ]
    assert "hashed_password" not in payload["items"][0]

    second_page = client.get("/v1/admin/users?limit=2&offset=2")
    assert [item["id"] for item in second_page.json()["items"]] == [
        admin_id + 2,
        admin_id + 3,
    ]

    search = client.get("/v1/admin/users?query=ali")
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["email"] == "alice@example.com"

    blocked = client.post(
        f"/v1/admin/users/{bob_id}/block",
        json={"reason": "спам"},
    )
    assert blocked.status_code == 200
    assert client.get("/v1/admin/users?status=active").json()["total"] == 3
    blocked_page = client.get("/v1/admin/users?status=blocked")
    assert blocked_page.json()["total"] == 1
    assert blocked_page.json()["items"][0]["id"] == bob_id


def test_block_rejects_existing_jwt_and_records_audit(
    admin_api: tuple[TestClient, str, int],
) -> None:
    client, database_url, admin_id = admin_api
    owner_id = asyncio.run(
        _create_user(database_url, "owner@example.com", "owner-pass-1")
    )
    owner_headers = _login(client, "owner@example.com", "owner-pass-1")
    client.headers["Authorization"] = owner_headers["Authorization"]
    assert client.get("/v1/auth/me").status_code == 200
    client.headers["Authorization"] = _login(
        client,
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
    )["Authorization"]

    response = client.post(
        f"/v1/admin/users/{owner_id}/block",
        json={"reason": "нарушение правил"},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert asyncio.run(_user_is_active(database_url, "owner@example.com")) is False

    client.headers["Authorization"] = owner_headers["Authorization"]
    assert client.get("/v1/auth/me").status_code == 403
    client.headers["Authorization"] = _login(
        client,
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
    )["Authorization"]

    # Повторная блокировка идемпотентна и не плодит записи аудита.
    repeated = client.post(
        f"/v1/admin/users/{owner_id}/block",
        json={"reason": "повтор"},
    )
    assert repeated.status_code == 200
    actions = asyncio.run(_actions(database_url))
    assert len(actions) == 1
    assert actions[0].admin_id == admin_id
    assert actions[0].target_user_id == owner_id
    assert actions[0].action == "block"
    assert actions[0].reason == "нарушение правил"

    unblocked = client.post(
        f"/v1/admin/users/{owner_id}/unblock",
        json={"reason": "разобрались"},
    )
    assert unblocked.status_code == 200
    assert unblocked.json()["is_active"] is True
    assert [item.action for item in asyncio.run(_actions(database_url))] == [
        "block",
        "unblock",
    ]

    client.headers["Authorization"] = owner_headers["Authorization"]
    assert client.get("/v1/auth/me").status_code == 200


def test_blocked_user_cannot_login(
    admin_api: tuple[TestClient, str, int],
) -> None:
    """T-140.3: login не выдаёт токен заблокированному пользователю."""
    client, database_url, _admin_id = admin_api
    owner_id = asyncio.run(
        _create_user(database_url, "owner@example.com", "owner-pass-1")
    )

    blocked = client.post(
        f"/v1/admin/users/{owner_id}/block",
        json={"reason": "нарушение правил"},
    )
    assert blocked.status_code == 200

    login = client.post(
        "/v1/auth/login",
        json={"email": "owner@example.com", "password": "owner-pass-1"},
    )
    assert login.status_code == 403
    assert (
        login.json()["detail"]
        == "Аккаунт заблокирован. Обратитесь к администратору"
    )

    # Неверный пароль по-прежнему 401: статус чужого аккаунта не раскрывается.
    wrong_password = client.post(
        "/v1/auth/login",
        json={"email": "owner@example.com", "password": "wrong-pass-1"},
    )
    assert wrong_password.status_code == 401

    unblocked = client.post(
        f"/v1/admin/users/{owner_id}/unblock",
        json={"reason": "разобрались"},
    )
    assert unblocked.status_code == 200
    assert (
        client.post(
            "/v1/auth/login",
            json={"email": "owner@example.com", "password": "owner-pass-1"},
        ).status_code
        == 200
    )


def test_block_requires_non_blank_reason(
    admin_api: tuple[TestClient, str, int],
) -> None:
    client, database_url, _admin_id = admin_api
    owner_id = asyncio.run(
        _create_user(database_url, "owner@example.com", "owner-pass-1")
    )

    response = client.post(
        f"/v1/admin/users/{owner_id}/block",
        json={"reason": "   "},
    )
    assert response.status_code == 400


def test_block_and_delete_reject_self(
    admin_api: tuple[TestClient, str, int],
) -> None:
    client, _database_url, admin_id = admin_api

    blocked = client.post(
        f"/v1/admin/users/{admin_id}/block",
        json={"reason": "сам себя"},
    )
    assert blocked.status_code == 400

    deleted = client.request(
        "DELETE",
        f"/v1/admin/users/{admin_id}",
        json={"confirm_email": ADMIN_EMAIL},
    )
    assert deleted.status_code == 400


def test_last_active_admin_is_protected(
    admin_api: tuple[TestClient, str, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database_url, _admin_id = admin_api
    second_admin_id = asyncio.run(
        _create_user(
            database_url,
            "admin2@example.com",
            "admin2-pass-1",
            is_admin=True,
        )
    )

    async def only_one_active_admin(_session: object) -> int:
        return 1

    monkeypatch.setattr(
        admin_module,
        "count_active_admins",
        only_one_active_admin,
    )

    blocked = client.post(
        f"/v1/admin/users/{second_admin_id}/block",
        json={"reason": "тест"},
    )
    assert blocked.status_code == 409

    deleted = client.request(
        "DELETE",
        f"/v1/admin/users/{second_admin_id}",
        json={"confirm_email": "admin2@example.com"},
    )
    assert deleted.status_code == 409


def test_delete_requires_email_and_cascades(
    admin_api: tuple[TestClient, str, int],
) -> None:
    client, database_url, admin_id = admin_api
    target_id = asyncio.run(
        _create_user(database_url, "target@example.com", "target-pass-1")
    )
    asyncio.run(_seed_related(database_url, target_id))

    wrong_email = client.request(
        "DELETE",
        f"/v1/admin/users/{target_id}",
        json={"confirm_email": "other@example.com"},
    )
    assert wrong_email.status_code == 400
    assert asyncio.run(_user_is_active(database_url, "target@example.com")) is True

    deleted = client.request(
        "DELETE",
        f"/v1/admin/users/{target_id}",
        json={"confirm_email": "TARGET@example.com", "reason": "по запросу"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["id"] == target_id
    assert asyncio.run(_user_is_active(database_url, "target@example.com")) is None
    assert asyncio.run(_related_counts(database_url)) == (0, 0, 0)
    assert asyncio.run(_access_request_owner_ids(database_url)) == (None, None)

    actions = asyncio.run(_actions(database_url))
    assert len(actions) == 1
    assert actions[0].admin_id == admin_id
    assert actions[0].target_user_id == target_id
    assert actions[0].action == "delete"
    assert actions[0].reason == "по запросу"


def test_block_and_delete_require_admin(api: tuple[TestClient, str]) -> None:
    """Обычный пользователь не может модерировать других."""
    client, database_url = api
    asyncio.run(_create_user(database_url, "owner@example.com", "owner-pass-1"))
    target_id = asyncio.run(
        _create_user(database_url, "target@example.com", "target-pass-1")
    )
    client.headers["Authorization"] = _login(
        client,
        "owner@example.com",
        "owner-pass-1",
    )["Authorization"]

    assert (
        client.post(
            f"/v1/admin/users/{target_id}/block",
            json={"reason": "нельзя"},
        ).status_code
        == 403
    )
    assert (
        client.request(
            "DELETE",
            f"/v1/admin/users/{target_id}",
            json={"confirm_email": "target@example.com"},
        ).status_code
        == 403
    )


def test_block_and_unblock_unknown_user(
    admin_api: tuple[TestClient, str, int],
) -> None:
    client, _database_url, _admin_id = admin_api

    assert (
        client.post(
            "/v1/admin/users/99999/block",
            json={"reason": "нет такого"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/admin/users/99999/unblock",
            json={"reason": "нет такого"},
        ).status_code
        == 404
    )
    assert (
        client.request(
            "DELETE",
            "/v1/admin/users/99999",
            json={"confirm_email": "none@example.com"},
        ).status_code
        == 404
    )
