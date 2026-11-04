"""Тесты создания Bot с кастомным Telegram API (T-129)."""

from __future__ import annotations

import asyncio

from aiogram.client.session.aiohttp import AiohttpSession

from bot.main import create_bot
from bot.settings import BotSettings


def test_create_bot_uses_custom_api_base_without_network() -> None:
    """Bot создаётся с reverse-proxy URL, без запросов к Telegram."""
    settings = BotSettings(
        telegram_bot_token="123456:AAFakeTokenForTests",
        telegram_api_base="http://mock",
    )

    bot = create_bot(settings)
    try:
        assert isinstance(bot.session, AiohttpSession)
        assert bot.session.api.base.startswith("http://mock")
    finally:
        asyncio.run(bot.session.close())


def test_create_bot_defaults_to_public_telegram_api() -> None:
    settings = BotSettings(telegram_bot_token="123456:AAFakeTokenForTests")

    bot = create_bot(settings)
    try:
        assert bot.session.api.base.startswith("https://api.telegram.org")
    finally:
        asyncio.run(bot.session.close())
