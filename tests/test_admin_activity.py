"""Тесты админской активности пользователей (T-151).

Покрывают:
- доступ только для администратора;
- graceful fallback, когда Prometheus не задан или недоступен;
- расчёт DAU по дням и WAU из ответов Prometheus;
- корректные параметры range-запроса (шаг — сутки, окно 7d/30d).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.admin as admin_module
from app.admin import AdminActivityRead
from app.auth import hash_password
from app.database import Database, create_user
from app.main import app, limiter
from app.settings import get_app_settings


def _db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'admin_activity.db').as_posix()}"


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


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Админ-клиент с отключённым Prometheus (быстрый fallback)."""
    database_url = _db_url(tmp_path)
    monkeypatch.setenv("VET_API_DATABASE_URL", database_url)
    monkeypatch.setenv("VET_API_PROMETHEUS_URL", "")
    get_app_settings.cache_clear()
    limiter.reset()
    with TestClient(app) as client:
        asyncio.run(_create_user(database_url, "admin@example.com", "admin-pass-1", is_admin=True))
        asyncio.run(
            _create_user(database_url, "owner@example.com", "secret-pass-1")
        )
        client.headers["Authorization"] = _login(
            client,
            "admin@example.com",
            "admin-pass-1",
        )["Authorization"]
        yield client
    limiter.reset()
    get_app_settings.cache_clear()


# --- доступ -------------------------------------------------------------------


def test_activity_requires_admin(admin_client: TestClient) -> None:
    admin_client.headers["Authorization"] = _login(
        admin_client,
        "owner@example.com",
        "secret-pass-1",
    )["Authorization"]
    assert admin_client.get("/v1/admin/activity").status_code == 403

    admin_client.headers.pop("Authorization")
    assert admin_client.get("/v1/admin/activity").status_code == 401


def test_activity_rejects_unknown_window(admin_client: TestClient) -> None:
    response = admin_client.get("/v1/admin/activity?window=1d")

    assert response.status_code == 422


# --- graceful fallback --------------------------------------------------------


def test_activity_falls_back_without_prometheus(admin_client: TestClient) -> None:
    """Без Prometheus — пустая история, UI не падает."""
    response = admin_client.get("/v1/admin/activity?window=7d")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "unavailable"
    assert data["degraded"] is False
    assert data["window"] == "7d"
    assert data["series"] == []
    assert data["dau"] == 0
    assert data["wau"] == 0
    assert data["generated_at"]


def test_activity_falls_back_when_prometheus_unreachable(
    admin_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VET_API_PROMETHEUS_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("VET_API_PROMETHEUS_TIMEOUT_S", "0.2")
    get_app_settings.cache_clear()

    response = admin_client.get("/v1/admin/activity?window=30d")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "unavailable"
    assert data["degraded"] is True
    assert data["window"] == "30d"
    assert data["series"] == []


# --- Prometheus ---------------------------------------------------------------


def test_activity_uses_prometheus_when_available(
    admin_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VET_API_PROMETHEUS_URL", "http://prometheus:9090")
    get_app_settings.cache_clear()

    async def fake_activity(
        base_url: str,
        timeout_s: float,
        window: str,
    ) -> AdminActivityRead:
        assert base_url == "http://prometheus:9090"
        assert window == "30d"
        return AdminActivityRead(
            source="prometheus",
            degraded=False,
            window="30d",
            generated_at=datetime.now(UTC),
            series=[
                admin_module.ActivityPoint(
                    date="2026-11-08",
                    active_users=3,
                    requests=12.0,
                )
            ],
            dau=3,
            wau=9,
        )

    monkeypatch.setattr(admin_module, "_prometheus_activity", fake_activity)

    response = admin_client.get("/v1/admin/activity?window=30d")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "prometheus"
    assert data["degraded"] is False
    assert data["dau"] == 3
    assert data["wau"] == 9
    assert data["series"] == [
        {"date": "2026-11-08", "active_users": 3, "requests": 12.0}
    ]


def test_prometheus_activity_builds_dau_series_and_wau(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DAU-ряд по дням, WAU и параметры range-запроса (шаг — сутки)."""
    day = 24 * 3600
    timestamps = [1_760_000_000, 1_760_000_000 + day, 1_760_000_000 + 2 * day]
    captured: dict[str, Any] = {}

    async def fake_query(
        client: object,
        base_url: str,
        expression: str,
        **kwargs: object,
    ) -> list[dict[str, Any]]:
        if "[7d]" in expression:
            return [{"value": [0, "9"]}]
        if expression.startswith("sum("):
            captured["requests_range"] = kwargs
            return [
                {
                    "values": [
                        [str(ts), "10"] if index == 0 else [str(ts), "4"]
                        for index, ts in enumerate(timestamps)
                    ]
                }
            ]
        if "start" in kwargs:
            captured["dau_range"] = kwargs
            return [
                {
                    "values": [
                        [str(timestamps[0]), "3"],
                        [str(timestamps[1]), "5"],
                        [str(timestamps[2]), "0"],
                    ]
                }
            ]
        return [{"value": [0, "3"]}]

    monkeypatch.setattr(admin_module, "_prom_query", fake_query)

    activity = asyncio.run(
        admin_module._prometheus_activity("http://prometheus:9090", 1.0, "7d")
    )

    assert activity.source == "prometheus"
    assert activity.dau == 3
    assert activity.wau == 9
    assert [point.active_users for point in activity.series] == [3, 5, 0]
    assert [point.requests for point in activity.series] == [10.0, 4.0, 4.0]
    assert [point.date for point in activity.series] == [
        datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d") for ts in timestamps
    ]

    dau_range = captured["dau_range"]
    assert dau_range["step"] == 24 * 3600
    assert dau_range["end"] - dau_range["start"] == 6 * 24 * 3600
    requests_range = captured["requests_range"]
    assert requests_range["step"] == 24 * 3600


def test_prometheus_activity_thirty_day_window(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_query(
        client: object,
        base_url: str,
        expression: str,
        **kwargs: object,
    ) -> list[dict[str, Any]]:
        captured.setdefault("expressions", []).append(expression)
        if "start" in kwargs:
            captured["range"] = kwargs
            return [{"values": [[str(1_760_000_000), "2"]]}]
        return [{"value": [0, "2"]}]

    monkeypatch.setattr(admin_module, "_prom_query", fake_query)

    activity = asyncio.run(
        admin_module._prometheus_activity("http://prometheus:9090", 1.0, "30d")
    )

    assert activity.window == "30d"
    assert captured["range"]["step"] == 24 * 3600
    assert captured["range"]["end"] - captured["range"]["start"] == 29 * 24 * 3600


def test_empty_activity_marks_fallback_source() -> None:
    activity = admin_module._empty_activity("7d", degraded=True)

    assert activity.source == "unavailable"
    assert activity.degraded is True
    assert activity.series == []
    assert activity.dau == 0
    assert activity.wau == 0
