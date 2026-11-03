"""Тесты CORS для React-фронтенда (T-037)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import CORS_ALLOWED_ORIGINS, app


def test_cors_allows_vite_dev_server() -> None:
    client = TestClient(app)
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


def test_cors_allows_docker_frontend_port() -> None:
    client = TestClient(app)
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
