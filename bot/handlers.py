"""aiogram-хендлеры Telegram-бота (T-035)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.service import VetAssistantBot


def build_router(service: VetAssistantBot) -> Router:
    """Собрать роутер, делегирующий обработку ``VetAssistantBot``."""
    router = Router(name="vetassistant")

    @router.message(CommandStart())
    async def handle_start(message: Message) -> None:
        await service.start(message)

    @router.message(Command("reset"))
    async def handle_reset(message: Message) -> None:
        await service.reset(message)

    @router.message(Command("help"))
    async def handle_help(message: Message) -> None:
        await service.help(message)

    @router.message(F.text)
    async def handle_text(message: Message) -> None:
        await service.handle_text(message)

    @router.message()
    async def handle_unsupported(message: Message) -> None:
        await service.handle_unsupported(message)

    return router
