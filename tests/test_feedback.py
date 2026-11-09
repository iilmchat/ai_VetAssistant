"""Тесты обратной связи по ответам 👍/👎 (T-139.1, T-139.2).

Покрывают:
- авторизацию и валидацию ``POST /v1/feedback``;
- upsert: одна оценка на пользователя и сообщение, повторная перезаписывает;
- изоляцию оценок разных пользователей;
- админскую сводку ``GET /v1/admin/feedback/stats`` и права доступа;
- удаление аккаунта вместе с оценками (каскад);
- ограничения схемы БД и наличие SQL-миграции для прода;
- отсутствие текстов сообщений в таблице (152-ФЗ).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.auth import hash_password
from app.database import (
    Database,
    Feedback,
    create_user,
    delete_user_account,
    get_feedback_stats,
    upsert_feedback,
)
from app.main import app, limiter
from app.settings import get_app_settings

OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "secret-pass-1"
OTHER_EMAIL = "other@example.com"
OTHER_PASSWORD = "secret-pass-2"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-pass-1"


def _db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'feedback.db').as_posix()}"


async def _seed_users(database_url: str) -> None:
    """Создать обычного пользователя, второго пользователя и админа."""
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
            await create_user(
                session,
                email=ADMIN_EMAIL,
                hashed_password=hash_password(ADMIN_PASSWORD),
                is_admin=True,
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
def feedback_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Клиент API с временной SQLite-БД и тремя пользователями."""
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


async def _feedback_rows(database_url: str) -> list[Feedback]:
    database = Database(database_url)
    try:
        async with database.session() as session:
            result = await session.execute(select(Feedback).order_by(Feedback.id))
            return list(result.scalars().all())
    finally:
        await database.dispose()


def _stats(client: TestClient) -> dict[str, float | int]:
    """Получить админскую сводку (admin-клиент обязателен)."""
    response = client.get("/v1/admin/feedback/stats")
    assert response.status_code == 200, response.text
    return dict(response.json())


# --- POST /v1/feedback --------------------------------------------------------


def test_feedback_requires_authentication(feedback_client: TestClient) -> None:
    response = feedback_client.post(
        "/v1/feedback",
        json={"message_id": "msg-1", "rating": 1},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_feedback_rejects_invalid_rating(feedback_client: TestClient) -> None:
    feedback_client.headers.update(
        _login(feedback_client, OWNER_EMAIL, OWNER_PASSWORD)
    )

    for rating in (0, 2, 10):
        response = feedback_client.post(
            "/v1/feedback",
            json={"message_id": "msg-1", "rating": rating},
        )
        assert response.status_code == 422, rating

    missing = feedback_client.post("/v1/feedback", json={"message_id": "msg-1"})
    assert missing.status_code == 422


def test_feedback_rejects_empty_message_id(feedback_client: TestClient) -> None:
    feedback_client.headers.update(
        _login(feedback_client, OWNER_EMAIL, OWNER_PASSWORD)
    )

    for message_id in ("", "   "):
        response = feedback_client.post(
            "/v1/feedback",
            json={"message_id": message_id, "rating": 1},
        )
        assert response.status_code == 422, message_id


def test_feedback_saves_rating_and_strips_message_id(
    feedback_client: TestClient,
    tmp_path: Path,
) -> None:
    feedback_client.headers.update(
        _login(feedback_client, OWNER_EMAIL, OWNER_PASSWORD)
    )

    response = feedback_client.post(
        "/v1/feedback",
        json={"message_id": "  msg-1  ", "rating": 1},
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": "Спасибо за оценку",
        "message_id": "msg-1",
        "rating": 1,
    }
    rows = asyncio.run(_feedback_rows(_db_url(tmp_path)))
    assert [(row.message_id, row.rating) for row in rows] == [("msg-1", 1)]

    feedback_client.headers.update(_login(feedback_client, ADMIN_EMAIL, ADMIN_PASSWORD))
    assert _stats(feedback_client)["total"] == 1


def test_feedback_upserts_single_rating_per_message(
    feedback_client: TestClient,
    tmp_path: Path,
) -> None:
    """T-139.2: повторная оценка перезаписывает, а не дублирует строку."""
    feedback_client.headers.update(
        _login(feedback_client, OWNER_EMAIL, OWNER_PASSWORD)
    )

    first = feedback_client.post(
        "/v1/feedback",
        json={"message_id": "msg-1", "rating": 1},
    )
    second = feedback_client.post(
        "/v1/feedback",
        json={"message_id": "msg-1", "rating": -1},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["rating"] == -1

    rows = asyncio.run(_feedback_rows(_db_url(tmp_path)))
    assert len(rows) == 1
    assert rows[0].message_id == "msg-1"
    assert rows[0].rating == -1


def test_feedback_is_isolated_between_users(feedback_client: TestClient) -> None:
    owner_headers = _login(feedback_client, OWNER_EMAIL, OWNER_PASSWORD)

    feedback_client.headers.update(owner_headers)
    assert (
        feedback_client.post(
            "/v1/feedback",
            json={"message_id": "same-message", "rating": 1},
        ).status_code
        == 200
    )

    feedback_client.headers.update(_login(feedback_client, OTHER_EMAIL, OTHER_PASSWORD))
    assert (
        feedback_client.post(
            "/v1/feedback",
            json={"message_id": "same-message", "rating": -1},
        ).status_code
        == 200
    )

    feedback_client.headers.update(_login(feedback_client, ADMIN_EMAIL, ADMIN_PASSWORD))
    stats = _stats(feedback_client)
    assert stats["total"] == 2
    assert stats["positive"] == 1
    assert stats["negative"] == 1
    assert stats["positive_ratio"] == pytest.approx(0.5)


# --- GET /v1/admin/feedback/stats --------------------------------------------


def test_feedback_stats_requires_admin(feedback_client: TestClient) -> None:
    feedback_client.headers.update(
        _login(feedback_client, OWNER_EMAIL, OWNER_PASSWORD)
    )

    response = feedback_client.get("/v1/admin/feedback/stats")

    assert response.status_code == 403


def test_feedback_stats_requires_authentication(feedback_client: TestClient) -> None:
    response = feedback_client.get("/v1/admin/feedback/stats")

    assert response.status_code == 401


def test_feedback_stats_empty(feedback_client: TestClient) -> None:
    feedback_client.headers.update(_login(feedback_client, ADMIN_EMAIL, ADMIN_PASSWORD))

    assert _stats(feedback_client) == {
        "total": 0,
        "positive": 0,
        "negative": 0,
        "positive_ratio": 0.0,
    }


def test_feedback_stats_counts_and_ratio(feedback_client: TestClient) -> None:
    feedback_client.headers.update(
        _login(feedback_client, OWNER_EMAIL, OWNER_PASSWORD)
    )
    for message_id, rating in (("m-1", 1), ("m-2", 1), ("m-3", -1)):
        assert (
            feedback_client.post(
                "/v1/feedback",
                json={"message_id": message_id, "rating": rating},
            ).status_code
            == 200
        )

    feedback_client.headers.update(_login(feedback_client, ADMIN_EMAIL, ADMIN_PASSWORD))
    stats = _stats(feedback_client)

    assert stats["total"] == 3
    assert stats["positive"] == 2
    assert stats["negative"] == 1
    assert stats["positive_ratio"] == pytest.approx(2 / 3)


# --- Схема БД и каскад --------------------------------------------------------


async def test_deleting_user_removes_feedback(tmp_path: Path) -> None:
    database = Database(_db_url(tmp_path))
    try:
        await database.create_tables()
        async with database.session() as session:
            user = await create_user(
                session,
                email=OWNER_EMAIL,
                hashed_password=hash_password(OWNER_PASSWORD),
            )
            await upsert_feedback(
                session,
                user_id=user.id,
                message_id="msg-1",
                rating=1,
            )
            assert (await get_feedback_stats(session)).total == 1

            assert await delete_user_account(session, user.id) is True
            await session.commit()

            stats = await get_feedback_stats(session)
            assert stats.total == 0
            assert stats.positive == 0
            assert stats.negative == 0
            assert stats.positive_ratio == 0.0
    finally:
        await database.dispose()


async def test_feedback_schema_has_no_message_text(tmp_path: Path) -> None:
    """152-ФЗ: в таблице нет колонок с содержимым сообщений."""
    database = Database(_db_url(tmp_path))
    try:
        await database.create_tables()
        async with database.engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync_connection: {
                    column["name"]
                    for column in inspect(sync_connection).get_columns("feedback")
                }
            )
    finally:
        await database.dispose()

    assert columns == {"id", "user_id", "message_id", "rating", "created_at"}


async def test_feedback_db_enforces_rating_and_uniqueness(tmp_path: Path) -> None:
    database = Database(_db_url(tmp_path))
    try:
        await database.create_tables()
        async with database.session() as session:
            user = await create_user(
                session,
                email=OWNER_EMAIL,
                hashed_password=hash_password(OWNER_PASSWORD),
            )
            user_id = int(user.id)

            session.add(Feedback(user_id=user_id, message_id="msg-1", rating=1))
            await session.commit()

            # Одна оценка на пользователя и сообщение.
            session.add(Feedback(user_id=user_id, message_id="msg-1", rating=-1))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

            # Разрешены только 1 и -1.
            session.add(Feedback(user_id=user_id, message_id="msg-2", rating=0))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        await database.dispose()


def test_feedback_migration_sql_matches_model() -> None:
    """Прод-миграция T-139.1: идемпотентная таблица, индексы и ограничения."""
    sql = Path("scripts/migrations/2026-11-09_feedback.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE TABLE IF NOT EXISTS feedback" in sql
    assert "REFERENCES users(id) ON DELETE CASCADE" in sql
    assert "CONSTRAINT ck_feedback_rating" in sql
    assert "CONSTRAINT uq_feedback_user_message" in sql
    assert "CREATE INDEX IF NOT EXISTS ix_feedback_user_id" in sql
    assert "CREATE INDEX IF NOT EXISTS ix_feedback_message_id" in sql
    assert "BEGIN;" in sql
    assert "COMMIT;" in sql


def test_feedback_migration_adds_no_message_text() -> None:
    """152-ФЗ: миграция не добавляет колонок под текст сообщения."""
    sql = Path("scripts/migrations/2026-11-09_feedback.sql").read_text(
        encoding="utf-8"
    )
    table_body = sql.split("CREATE TABLE IF NOT EXISTS feedback", 1)[1].split(
        ");", 1
    )[0]

    assert "message_id" in table_body
    assert "rating" in table_body
    for forbidden in ("content", "message_text", "prompt", "response"):
        assert forbidden not in table_body.lower()
