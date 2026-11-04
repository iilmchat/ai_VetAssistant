"""Тесты allowlist Telegram ID (T-121)."""

from __future__ import annotations

import pytest

from bot.settings import BotSettings


def test_allowed_ids_are_parsed_from_comma_or_space_separated_string() -> None:
    settings = BotSettings(allowed_telegram_ids="111, 222 333")

    assert settings.allowed_id_set == frozenset({111, 222, 333})


def test_empty_allowlist_is_empty_set() -> None:
    assert BotSettings(allowed_telegram_ids="  ").allowed_id_set == frozenset()


def test_invalid_allowlist_raises() -> None:
    settings = BotSettings(allowed_telegram_ids="111, not-a-number")

    with pytest.raises(ValueError, match="целые числа"):
        _ = settings.allowed_id_set


def test_telegram_api_base_defaults_to_public_api() -> None:
    assert BotSettings().telegram_api_base == "https://api.telegram.org"


def test_telegram_api_base_can_point_to_reverse_proxy() -> None:
    settings = BotSettings(telegram_api_base="https://tg.example.workers.dev")

    assert settings.telegram_api_base == "https://tg.example.workers.dev"
