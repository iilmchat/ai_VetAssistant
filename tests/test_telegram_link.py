"""Тесты привязки Telegram к веб-аккаунту (T-134.1, T-134.2)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select, update

from app.auth import hash_password
from app.database import (
    Database,
    TelegramLinkCode,
    User,
    create_user,
    get_user_by_email,
    get_user_by_id,
)
from app.main import app, limiter
from app.settings import get_app_settings
from app.telegram_link import (
    CODE_ALPHABET,
    CODE_LENGTH,
    EXPIRED_CODE_DETAIL,
    INVALID_CODE_DETAIL,
    MAX_ACTIVE_CODES,
    TELEGRAM_BUSY_DETAIL,
    USED_CODE_DETAIL,
    hash_code,
)

WEB_EMAIL = "owner@example.com"
WEB_PASSWORD = "secret-pass-1"
BOT_USERNAME = "vetassistant_bot"
TELEGRAM_ID = 1_133_302_963
BOT_EMAIL = f"telegram-{TELEGRAM_ID}@bot.vetassistant.local"
BOT_PASSWORD = "bot-pass-1"

SECOND_EMAIL = "second@example.com"
SECOND_PASSWORD = "secret-pass-2"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient с изолированной SQLite-БД и уникальной настройкой бота."""
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'telegram.db').as_posix()}"
    monkeypatch.setenv("VET_API_DATABASE_URL", db_url)
    monkeypatch.setenv("VET_API_TELEGRAM_BOT_USERNAME", BOT_USERNAME)
    get_app_settings.cache_clear()
    limiter.reset()
    with TestClient(app) as test_client:
        yield test_client
    limiter.reset()
    get_app_settings.cache_clear()


def _seed_user(client: TestClient, email: str, password: str) -> int:
    """Создать пользователя напрямую в БД и вернуть его id."""
    database: Database = client.app.state.db

    async def seed() -> int:
        seeded = Database(database.url)
        try:
            async with seeded.session() as session:
                user = await create_user(
                    session,
                    email=email,
                    hashed_password=hash_password(password),
                )
                return user.id
        finally:
            await seeded.dispose()

    return asyncio.run(seed())


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    """Войти и вернуть заголовок Authorization."""
    response = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def web(client: TestClient) -> dict[str, str]:
    """Веб-пользователь, который инициирует привязку."""
    _seed_user(client, WEB_EMAIL, WEB_PASSWORD)
    return _login(client, WEB_EMAIL, WEB_PASSWORD)


@pytest.fixture
def bot(client: TestClient) -> dict[str, str]:
    """Synthetic-аккаунт бота, который подтверждает код."""
    _seed_user(client, BOT_EMAIL, BOT_PASSWORD)
    return _login(client, BOT_EMAIL, BOT_PASSWORD)


def _user_by_email(client: TestClient, email: str) -> User | None:
    """Прочитать пользователя из БД (свежие значения после запросов API)."""
    database: Database = client.app.state.db

    async def fetch() -> User | None:
        seeded = Database(database.url)
        try:
            async with seeded.session() as session:
                return await get_user_by_email(session, email)
        finally:
            await seeded.dispose()

    return asyncio.run(fetch())


def _user_by_id(client: TestClient, user_id: int) -> User | None:
    database: Database = client.app.state.db

    async def fetch() -> User | None:
        seeded = Database(database.url)
        try:
            async with seeded.session() as session:
                return await get_user_by_id(session, user_id)
        finally:
            await seeded.dispose()

    return asyncio.run(fetch())


def _link_codes(client: TestClient) -> list[TelegramLinkCode]:
    """Все коды привязки в порядке создания."""
    database: Database = client.app.state.db

    async def fetch() -> list[TelegramLinkCode]:
        seeded = Database(database.url)
        try:
            async with seeded.session() as session:
                result = await session.execute(
                    select(TelegramLinkCode).order_by(TelegramLinkCode.id)
                )
                return list(result.scalars().all())
        finally:
            await seeded.dispose()

    return asyncio.run(fetch())


def _expire_codes(client: TestClient, user_id: int) -> None:
    """Сдвинуть все коды пользователя в прошлое."""
    database: Database = client.app.state.db

    async def expire() -> None:
        seeded = Database(database.url)
        try:
            async with seeded.session() as session:
                await session.execute(
                    update(TelegramLinkCode)
                    .where(TelegramLinkCode.user_id == user_id)
                    .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
                )
                await session.commit()
        finally:
            await seeded.dispose()

    asyncio.run(expire())


def _issue_code(client: TestClient, headers: dict[str, str]) -> str:
    """Выпустить код и вернуть его значение."""
    response = client.post("/v1/telegram/link-code", headers=headers)
    assert response.status_code == 200, response.text
    return str(response.json()["code"])


def _confirm(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    telegram_id: int = TELEGRAM_ID,
) -> Response:
    """Вызвать confirm от имени бота."""
    return client.post(
        "/v1/telegram/confirm",
        headers=headers,
        json={"code": code, "telegram_id": telegram_id},
    )


def test_link_code_returns_short_code_and_stores_only_hash(
    client: TestClient,
    web: dict[str, str],
) -> None:
    owner = _user_by_email(client, WEB_EMAIL)
    assert owner is not None

    response = client.post("/v1/telegram/link-code", headers=web)

    assert response.status_code == 200, response.text
    payload = response.json()
    code = payload["code"]
    assert len(code) == CODE_LENGTH
    assert set(code) <= set(CODE_ALPHABET)
    assert payload["bot_username"] == BOT_USERNAME
    assert code in payload["instructions"]
    assert f"@{BOT_USERNAME}" in payload["instructions"]

    expires_at = datetime.fromisoformat(payload["expires_at"])
    remaining = expires_at - datetime.now(UTC)
    assert timedelta(minutes=9) < remaining <= timedelta(minutes=10, seconds=5)

    codes = _link_codes(client)
    assert len(codes) == 1
    assert codes[0].user_id == owner.id
    assert codes[0].code_hash == hash_code(code, get_app_settings().jwt_secret)
    assert codes[0].code_hash != code
    assert len(codes[0].code_hash) == 64
    assert codes[0].used_at is None


def test_link_status_is_unlinked_by_default(
    client: TestClient,
    web: dict[str, str],
) -> None:
    response = client.get("/v1/telegram/link", headers=web)

    assert response.status_code == 200
    assert response.json() == {
        "linked": False,
        "telegram_id": None,
        "linked_at": None,
    }


def test_confirm_links_telegram_to_code_owner(
    client: TestClient,
    web: dict[str, str],
    bot: dict[str, str],
) -> None:
    owner = _user_by_email(client, WEB_EMAIL)
    assert owner is not None
    code = _issue_code(client, web)

    response = _confirm(client, bot, code)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "linked": True,
        "user_id": owner.id,
        "email": WEB_EMAIL,
        "telegram_id": TELEGRAM_ID,
    }

    status = client.get("/v1/telegram/link", headers=web)
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["linked"] is True
    assert status_payload["telegram_id"] == TELEGRAM_ID
    assert status_payload["linked_at"] is not None

    refreshed = _user_by_id(client, owner.id)
    assert refreshed is not None
    assert refreshed.telegram_id == TELEGRAM_ID

    link = _link_codes(client)[0]
    assert link.used_at is not None
    assert link.telegram_id == TELEGRAM_ID


def test_confirm_accepts_lowercase_code_with_separators(
    client: TestClient,
    web: dict[str, str],
    bot: dict[str, str],
) -> None:
    code = _issue_code(client, web)
    spaced = f"  {code[:4].lower()}-{code[4:].lower()}  "

    response = _confirm(client, bot, spaced)

    assert response.status_code == 200, response.text


def test_confirm_rejects_expired_code(
    client: TestClient,
    web: dict[str, str],
    bot: dict[str, str],
) -> None:
    owner = _user_by_email(client, WEB_EMAIL)
    assert owner is not None
    code = _issue_code(client, web)
    _expire_codes(client, owner.id)

    response = _confirm(client, bot, code)

    assert response.status_code == 400
    assert response.json()["detail"] == EXPIRED_CODE_DETAIL
    refreshed = _user_by_id(client, owner.id)
    assert refreshed is not None
    assert refreshed.telegram_id is None


def test_confirm_rejects_unknown_code(
    client: TestClient,
    web: dict[str, str],
    bot: dict[str, str],
) -> None:
    _issue_code(client, web)

    response = _confirm(client, bot, "ZZZZZZZZ")

    assert response.status_code == 400
    assert response.json()["detail"] == INVALID_CODE_DETAIL


def test_confirm_rejects_malformed_code(
    client: TestClient,
    web: dict[str, str],
    bot: dict[str, str],
) -> None:
    """Символы вне алфавита (0/O/1/I) не проходят нормализацию."""
    _issue_code(client, web)

    response = _confirm(client, bot, "0000OOOO")

    assert response.status_code == 400
    assert response.json()["detail"] == INVALID_CODE_DETAIL


def test_confirm_code_is_single_use(
    client: TestClient,
    web: dict[str, str],
    bot: dict[str, str],
) -> None:
    code = _issue_code(client, web)
    assert _confirm(client, bot, code).status_code == 200

    second = _confirm(client, bot, code)

    assert second.status_code == 400
    assert second.json()["detail"] == USED_CODE_DETAIL


def test_confirm_rejects_foreign_telegram_id(
    client: TestClient,
    web: dict[str, str],
    bot: dict[str, str],
) -> None:
    owner = _user_by_email(client, WEB_EMAIL)
    assert owner is not None
    code = _issue_code(client, web)

    response = _confirm(client, bot, code, telegram_id=TELEGRAM_ID + 1)

    assert response.status_code == 403
    refreshed = _user_by_id(client, owner.id)
    assert refreshed is not None
    assert refreshed.telegram_id is None


def test_confirm_rejects_non_bot_token(
    client: TestClient,
    web: dict[str, str],
) -> None:
    """Обычный JWT не может подтвердить привязку за бота."""
    code = _issue_code(client, web)

    response = _confirm(client, web, code)

    assert response.status_code == 403


def test_confirm_conflicts_when_telegram_is_linked_to_another_account(
    client: TestClient,
    web: dict[str, str],
    bot: dict[str, str],
) -> None:
    first_code = _issue_code(client, web)
    assert _confirm(client, bot, first_code).status_code == 200

    _seed_user(client, SECOND_EMAIL, SECOND_PASSWORD)
    second = _login(client, SECOND_EMAIL, SECOND_PASSWORD)
    second_code = _issue_code(client, second)

    response = _confirm(client, bot, second_code)

    assert response.status_code == 409
    assert response.json()["detail"] == TELEGRAM_BUSY_DETAIL
    second_user = _user_by_email(client, SECOND_EMAIL)
    assert second_user is not None
    assert second_user.telegram_id is None
    web_user = _user_by_email(client, WEB_EMAIL)
    assert web_user is not None
    assert web_user.telegram_id == TELEGRAM_ID


def test_link_code_limit_is_three_active_codes(
    client: TestClient,
    web: dict[str, str],
) -> None:
    for _ in range(MAX_ACTIVE_CODES):
        response = client.post("/v1/telegram/link-code", headers=web)
        assert response.status_code == 200, response.text

    response = client.post("/v1/telegram/link-code", headers=web)

    assert response.status_code == 429
    assert str(MAX_ACTIVE_CODES) in response.json()["detail"]
    assert len(_link_codes(client)) == MAX_ACTIVE_CODES


def test_link_code_requires_authentication(client: TestClient) -> None:
    response = client.post("/v1/telegram/link-code")

    assert response.status_code == 401


def test_unlink_from_website(
    client: TestClient,
    web: dict[str, str],
    bot: dict[str, str],
) -> None:
    code = _issue_code(client, web)
    assert _confirm(client, bot, code).status_code == 200

    response = client.delete("/v1/telegram/link", headers=web)

    assert response.status_code == 200
    assert response.json()["linked"] is False
    user = _user_by_email(client, WEB_EMAIL)
    assert user is not None
    assert user.telegram_id is None
    assert client.get("/v1/telegram/link", headers=web).json()["linked"] is False


def test_unlink_from_website_is_idempotent(
    client: TestClient,
    web: dict[str, str],
) -> None:
    response = client.delete("/v1/telegram/link", headers=web)

    assert response.status_code == 200
    assert response.json()["linked"] is False


def test_unlink_from_bot(
    client: TestClient,
    web: dict[str, str],
    bot: dict[str, str],
) -> None:
    code = _issue_code(client, web)
    assert _confirm(client, bot, code).status_code == 200

    response = client.post(
        "/v1/telegram/unlink",
        headers=bot,
        json={"telegram_id": TELEGRAM_ID},
    )

    assert response.status_code == 200
    assert response.json()["linked"] is False
    user = _user_by_email(client, WEB_EMAIL)
    assert user is not None
    assert user.telegram_id is None

    again = client.post(
        "/v1/telegram/unlink",
        headers=bot,
        json={"telegram_id": TELEGRAM_ID},
    )
    assert again.status_code == 200
    assert "не был привязан" in again.json()["message"]


def test_unlink_from_bot_rejects_foreign_telegram_id(
    client: TestClient,
    bot: dict[str, str],
) -> None:
    response = client.post(
        "/v1/telegram/unlink",
        headers=bot,
        json={"telegram_id": TELEGRAM_ID + 1},
    )

    assert response.status_code == 403
