"""Тесты уведомлений API → Telegram (T-134.4)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.settings import get_app_settings
from app.telegram_notify import (
    BOT_CLIENT_HEADER,
    BOT_CLIENT_VALUE,
    is_bot_request,
    notification_for_tool,
    send_telegram_message,
)

TOKEN = "123456:test-token"
API_BASE = "https://tg.example"


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("VET_API_TELEGRAM_API_BASE", API_BASE)
    monkeypatch.delenv("VET_API_TELEGRAM_NOTIFY", raising=False)
    get_app_settings.cache_clear()
    yield
    get_app_settings.cache_clear()


def _patch_post(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
) -> None:
    monkeypatch.setattr("app.telegram_notify._post_message", handler)


async def test_send_message_posts_to_bot_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post(url: str, payload: dict[str, Any]) -> httpx.Response:
        captured["url"] = url
        captured["payload"] = payload
        return httpx.Response(200, json={"ok": True})

    _patch_post(monkeypatch, fake_post)

    sent = await send_telegram_message(42, "Записали Мурзика")

    assert sent is True
    assert captured["url"] == f"{API_BASE}/bot{TOKEN}/sendMessage"
    assert captured["payload"]["chat_id"] == 42
    assert captured["payload"]["text"] == "Записали Мурзика"


async def test_notify_can_be_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VET_API_TELEGRAM_NOTIFY", "false")
    get_app_settings.cache_clear()

    async def fake_post(url: str, payload: dict[str, Any]) -> httpx.Response:
        raise AssertionError("HTTP не должен вызываться при выключенных уведомлениях")

    _patch_post(monkeypatch, fake_post)

    assert await send_telegram_message(42, "Текст") is False


async def test_notify_without_token_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    get_app_settings.cache_clear()

    async def fake_post(url: str, payload: dict[str, Any]) -> httpx.Response:
        raise AssertionError("HTTP не должен вызываться без токена")

    _patch_post(monkeypatch, fake_post)

    assert await send_telegram_message(42, "Текст") is False


async def test_http_error_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(url: str, payload: dict[str, Any]) -> httpx.Response:
        return httpx.Response(500, json={"ok": False})

    _patch_post(monkeypatch, fake_post)

    assert await send_telegram_message(42, "Текст") is False


async def test_bot_api_ok_false_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(url: str, payload: dict[str, Any]) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "description": "blocked"})

    _patch_post(monkeypatch, fake_post)

    assert await send_telegram_message(42, "Текст") is False


async def test_non_json_response_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(url: str, payload: dict[str, Any]) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    _patch_post(monkeypatch, fake_post)

    assert await send_telegram_message(42, "Текст") is False


async def test_network_error_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_post(url: str, payload: dict[str, Any]) -> httpx.Response:
        raise httpx.ConnectError("telegram down")

    _patch_post(monkeypatch, fake_post)

    assert await send_telegram_message(42, "Текст") is False


def test_bot_request_header_is_detected() -> None:
    headers = httpx.Headers({BOT_CLIENT_HEADER: BOT_CLIENT_VALUE})

    assert is_bot_request(headers) is True
    assert is_bot_request(httpx.Headers()) is False
    assert is_bot_request({"x-vet-client": "web"}) is False


def test_notification_text_has_context_icon() -> None:
    assert notification_for_tool(
        "book_appointment",
        "Записали Мурзика на 2026-11-06 в 10:00",
    ) == "🐾 Записали Мурзика на 2026-11-06 в 10:00"
    assert notification_for_tool(
        "set_reminder",
        "Напоминание создано: Дать таблетку (20:00)",
    ) == "⏰ Напоминание создано: Дать таблетку (20:00)"
