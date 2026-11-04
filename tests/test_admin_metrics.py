"""Тесты админской аналитики (T-135).

Покрывают:
- доступ только для администратора;
- fallback на in-process снимок, когда Prometheus не задан или недоступен;
- разбор ответов Prometheus (суммы, ряды, топ пользователей);
- топ пользователей с email из БД.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.admin as admin_module
from app.admin import AdminMetricsRead
from app.auth import hash_password
from app.database import Database, create_user
from app.main import app, limiter
from app.metrics import record_user_usage
from app.settings import get_app_settings


def _db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'admin_metrics.db').as_posix()}"


async def _create_admin(database_url: str) -> int:
    database = Database(database_url)
    try:
        async with database.session() as session:
            user = await create_user(
                session,
                email="admin@example.com",
                hashed_password=hash_password("admin-pass-1"),
                is_admin=True,
            )
            return int(user.id)
    finally:
        await database.dispose()


async def _create_regular(database_url: str) -> None:
    database = Database(database_url)
    try:
        async with database.session() as session:
            await create_user(
                session,
                email="owner@example.com",
                hashed_password=hash_password("secret-pass-1"),
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
def admin_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, int]]:
    """Админ-клиент с отключённым Prometheus (быстрый fallback)."""
    database_url = _db_url(tmp_path)
    monkeypatch.setenv("VET_API_DATABASE_URL", database_url)
    monkeypatch.setenv("VET_API_PROMETHEUS_URL", "")
    get_app_settings.cache_clear()
    limiter.reset()
    with TestClient(app) as client:
        admin_id = asyncio.run(_create_admin(database_url))
        client.headers["Authorization"] = _login(
            client,
            "admin@example.com",
            "admin-pass-1",
        )["Authorization"]
        yield client, admin_id
    limiter.reset()
    get_app_settings.cache_clear()


def test_metrics_requires_admin(
    admin_client: tuple[TestClient, int],
    tmp_path: Path,
) -> None:
    """T-120/T-135: обычный пользователь и аноним не видят аналитику."""
    client, _admin_id = admin_client
    database_url = _db_url(tmp_path)
    asyncio.run(_create_regular(database_url))

    client.headers["Authorization"] = _login(
        client,
        "owner@example.com",
        "secret-pass-1",
    )["Authorization"]
    assert client.get("/v1/admin/metrics").status_code == 403

    client.headers.pop("Authorization")
    assert client.get("/v1/admin/metrics").status_code == 401


def test_metrics_returns_in_process_snapshot(
    admin_client: tuple[TestClient, int],
) -> None:
    """Без Prometheus отдаётся снимок процесса и пустой ряд."""
    client, _admin_id = admin_client

    response = client.get("/v1/admin/metrics?window=24h")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "in_process"
    assert data["degraded"] is False
    assert data["series"] == []
    assert data["started_at"]
    assert data["window"] == "24h"
    assert {
        "requests",
        "prompt_tokens",
        "completion_tokens",
        "tokens",
        "rag_hits",
        "rag_misses",
        "error_rate",
    } <= set(data["totals"])


def test_metrics_falls_back_when_prometheus_unreachable(
    admin_client: tuple[TestClient, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Недоступный Prometheus не даёт 500: degraded=true и in_process."""
    client, _admin_id = admin_client
    monkeypatch.setenv("VET_API_PROMETHEUS_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("VET_API_PROMETHEUS_TIMEOUT_S", "0.2")
    get_app_settings.cache_clear()

    response = client.get("/v1/admin/metrics?window=7d")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "in_process"
    assert data["degraded"] is True
    assert data["window"] == "7d"


def test_metrics_uses_prometheus_when_available(
    admin_client: tuple[TestClient, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При рабочем Prometheus эндпоинт отдаёт его данные."""
    client, _admin_id = admin_client
    monkeypatch.setenv("VET_API_PROMETHEUS_URL", "http://prometheus:9090")
    get_app_settings.cache_clear()

    async def fake_metrics(
        base_url: str,
        timeout_s: float,
        window: str,
        database: Database,
    ) -> AdminMetricsRead:
        assert base_url == "http://prometheus:9090"
        assert window == "24h"
        return AdminMetricsRead(
            source="prometheus",
            degraded=False,
            window="24h",
            generated_at=admin_module.datetime.now(admin_module.UTC),
            started_at=None,
            totals=admin_module.MetricsTotals(requests=10, tokens=1000),
            series=[
                admin_module.MetricsPoint(
                    ts=admin_module.datetime.now(admin_module.UTC),
                    requests=5,
                    tokens=500,
                )
            ],
            top_users=[],
        )

    monkeypatch.setattr(admin_module, "_prometheus_metrics", fake_metrics)

    response = client.get("/v1/admin/metrics?window=24h")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "prometheus"
    assert data["degraded"] is False
    assert data["totals"]["requests"] == 10
    assert len(data["series"]) == 1


def test_metrics_lists_top_users_with_email(
    admin_client: tuple[TestClient, int],
) -> None:
    """Топ пользователей отдаётся с email и обоими счётчиками."""
    client, admin_id = admin_client
    record_user_usage(admin_id, prompt_tokens=7, completion_tokens=3)

    data = client.get("/v1/admin/metrics").json()

    top = data["top_users"]
    assert top
    assert top[0]["user_id"] == admin_id
    assert top[0]["email"] == "admin@example.com"
    assert top[0]["requests"] >= 1
    assert top[0]["tokens"] >= 10


def test_instant_helpers_group_and_sum_values() -> None:
    result = [
        {"metric": {"status": "success"}, "value": [0, "10"]},
        {"metric": {"status": "error"}, "value": [0, "2"]},
        {"metric": {"status": "success"}, "value": [0, "5"]},
    ]

    assert admin_module._instant_by_label(result, "status") == {
        "success": 15.0,
        "error": 2.0,
    }
    assert admin_module._instant_sum(result) == 17.0


def test_instant_helpers_survive_broken_samples() -> None:
    result = [{"metric": {}, "value": ["bad"]}, {"value": [0, "not-a-number"]}]

    assert admin_module._instant_sum(result) == 0.0
    assert admin_module._instant_by_label(result, "status") == {"": 0.0}


def test_range_values_flattens_matrix() -> None:
    result = [{"values": [[100, "1.5"], [160, "2"]]}]

    assert admin_module._range_values(result) == {100: 1.5, 160: 2.0}
    assert admin_module._range_values([]) == {}


def test_build_series_merges_timestamps() -> None:
    series = admin_module._build_series({100: 5.0}, {100: 50.0, 160: 10.0})

    assert [point.requests for point in series] == [5.0, 0.0]
    assert [point.tokens for point in series] == [50.0, 10.0]


def test_error_rate_bounds() -> None:
    assert admin_module._error_rate(0, 0) == 0.0
    assert admin_module._error_rate(1, 4) == 0.25


def test_prometheus_totals_parses_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_query(
        client: object,
        base_url: str,
        expression: str,
        **kwargs: object,
    ) -> list[dict[str, Any]]:
        if "vet_llm_generation_requests_total" in expression:
            return [
                {"metric": {"status": "success"}, "value": [0, "10"]},
                {"metric": {"status": "error"}, "value": [0, "1"]},
            ]
        if "prompt_tokens_total" in expression:
            return [{"value": [0, "500"]}]
        if "completion_tokens_total" in expression:
            return [{"value": [0, "200"]}]
        if "vet_rag_searches_total" in expression:
            return [
                {"metric": {"result": "hit"}, "value": [0, "5"]},
                {"metric": {"result": "miss"}, "value": [0, "2"]},
            ]
        return [{"value": [0, "1"]}]

    monkeypatch.setattr(admin_module, "_prom_query", fake_query)

    totals = asyncio.run(
        admin_module._prometheus_totals(None, "http://prometheus:9090", "24h")
    )

    assert totals.requests == 11.0
    assert totals.generation_errors == 1.0
    assert totals.tokens == 700.0
    assert totals.rag_hits == 5.0
    assert totals.rag_misses == 2.0
    assert totals.http_errors == 1.0
    assert totals.error_rate == pytest.approx(1 / 11)


def test_prometheus_top_usage_merges_requests_and_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_query(
        client: object,
        base_url: str,
        expression: str,
        **kwargs: object,
    ) -> list[dict[str, Any]]:
        if "user_requests_total" in expression:
            return [
                {"metric": {"user_id": "1"}, "value": [0, "10"]},
                {"metric": {"user_id": "2"}, "value": [0, "4"]},
            ]
        return [
            {"metric": {"user_id": "1"}, "value": [0, "100"]},
        ]

    monkeypatch.setattr(admin_module, "_prom_query", fake_query)

    usage = asyncio.run(
        admin_module._prometheus_top_usage(None, "http://prometheus:9090", "24h")
    )

    assert usage[1]["requests"] == 10.0
    assert usage[1]["tokens"] == 100.0
    assert usage[2]["requests"] == 4.0
    assert usage[2]["tokens"] == 0.0
