"""Точка входа Telegram-бота (T-035).

Запуск:

    python -m bot

Требует переменную окружения ``TELEGRAM_BOT_TOKEN`` от @BotFather.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from loguru import logger

from bot.client import VetApiClient
from bot.conversation import ConversationStore
from bot.handlers import build_router
from bot.service import VetAssistantBot
from bot.settings import BotSettings, get_bot_settings
from data_pipeline.cli import configure_logging


def create_service(settings: BotSettings) -> VetAssistantBot:
    """Собрать сервис бота из настроек (отдельно — для тестируемости)."""
    api = VetApiClient(
        settings.api_url,
        model_id=settings.model_id,
        timeout_s=settings.timeout_s,
        auth_secret=settings.resolved_auth_secret,
    )
    store = ConversationStore(max_messages=settings.max_history_messages)
    return VetAssistantBot(
        api,
        store,
        temperature=settings.temperature,
        use_rag=settings.use_rag,
        use_tools=settings.use_tools,
    )


async def run(settings: BotSettings) -> None:
    """Запустить long polling aiogram."""
    token = settings.telegram_bot_token.strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не задан")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=None))
    dispatcher = Dispatcher()
    service = create_service(settings)
    dispatcher.include_router(build_router(service))
    logger.info(
        "Telegram-бот запущен: API={}, модель={}, RAG={}, tools={}",
        settings.api_url,
        settings.model_id,
        settings.use_rag,
        settings.use_tools,
    )

    try:
        await dispatcher.start_polling(bot)
    finally:
        await service.close()
        await bot.session.close()


def main() -> None:
    """Синхронная точка входа для ``python -m bot``."""
    configure_logging()
    settings = get_bot_settings()
    if not settings.telegram_bot_token.strip():
        logger.error(
            "TELEGRAM_BOT_TOKEN не задан. Получите токен у @BotFather и добавьте "
            "его в .env или переменные окружения."
        )
        raise SystemExit(1)

    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        logger.info("Telegram-бот остановлен")


if __name__ == "__main__":
    main()
