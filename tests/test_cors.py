"""Тесты CORS для React-фронтенда и мобильной оболочки (T-037, T-177)."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import CORS_ALLOWED_ORIGINS, app, get_backend_router


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Клиент без lifespan: CORS-заголовки не требуют БД и модели."""
    fake_backend = SimpleNamespace(
        active_backend_name="cpu",
        gpu_enabled=False,
        gpu_available=False,
    )
    app.dependency_overrides[get_backend_router] = lambda: fake_backend
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_cors_allows_vite_dev_server(client: TestClient) -> None:
    response = client.options(
        "/v1/chat/completions",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "http://localhost:5173" in CORS_ALLOWED_ORIGINS


def test_cors_allows_docker_frontend_port(client: TestClient) -> None:
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_allows_production_and_mobile_origin(client: TestClient) -> None:
    """T-177: мобильная оболочка может ходить в API напрямую."""
    response = client.options(
        "/v1/chat/completions",
        headers={
            "Origin": "https://app.ai-pets.ru",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.ai-pets.ru"
    assert "https://app.ai-pets.ru" in CORS_ALLOWED_ORIGINS
