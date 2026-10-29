#!/usr/bin/env python
"""Смоук-тест слоя абстракции учителя (T-002, T-008).

Проверяет два сценария:

* ``--dry-run`` — только читает `.env` через `get_provider()`, API не вызывается;
* без флагов — делает один реальный запрос к выбранному провайдеру.

Запуск::

    python scripts/test_api.py --dry-run
    python scripts/test_api.py --provider primary
    python scripts/test_api.py --provider fallback
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from loguru import logger
from openai import OpenAIError
from pydantic import ValidationError

from configs.settings import (
    PROVIDER_NAMES,
    ProviderName,
    ProviderNotConfiguredError,
    get_provider,
)
from data_pipeline.cli import configure_logging
from data_pipeline.llm_client import TeacherAPIError, TeacherClient

TEST_PROMPT = "Скажи 'Привет, я ассистент'"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Проверка доступа к API учителя (OpenAI-совместимый endpoint).",
        epilog=f"Тестовый запрос: {TEST_PROMPT!r}",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDER_NAMES,
        default="primary",
        help="какой провайдер проверять (по умолчанию primary)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="только проверить наличие настроек в .env, не обращаясь к API",
    )
    return parser.parse_args(argv)


def _describe_validation_error(exc: ValidationError) -> str:
    """Собрать имена отсутствующих/некорректных переменных окружения."""
    names: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        names.append(location.upper() if location else "?")
    return ", ".join(names) if names else "неизвестно"


def _check_settings(provider_name: ProviderName) -> int:
    """Проверить, что выбранный провайдер читается из `.env`."""
    try:
        provider = get_provider(provider_name)
    except ValidationError as exc:
        logger.error("Настройки неполные. Проверьте .env: {}", _describe_validation_error(exc))
        logger.error("Подсказка: скопируйте .env.example в .env и заполните TEACHER_PRIMARY_*")
        return 1
    except ProviderNotConfiguredError as exc:
        logger.error("{}", exc)
        return 1

    logger.info("Provider OK: {}", provider.name)
    logger.info("base_url={}", provider.base_url)
    logger.info("model={}", provider.model)
    logger.info("api_key=*** (задан)")
    return 0


async def _request_teacher(provider_name: ProviderName) -> int:
    """Сделать один реальный запрос и напечатать ответ и токены."""
    async with TeacherClient(get_provider(provider_name)) as client:
        logger.info("Запрос к {}: model={}", client.provider.name, client.model)
        result = await client.chat([{"role": "user", "content": TEST_PROMPT}])

    logger.info("Ответ учителя:\n{}", result.content)
    logger.info(
        "Токены: prompt={} completion={} total={} | latency={:.2f}s | попыток={}",
        result.prompt_tokens,
        result.completion_tokens,
        result.total_tokens,
        result.latency_s,
        result.attempts,
    )
    logger.info("OK")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI. Возвращает код выхода процесса."""
    args = parse_args(argv)
    configure_logging()
    provider_name: ProviderName = args.provider

    if args.dry_run:
        return _check_settings(provider_name)

    try:
        return asyncio.run(_request_teacher(provider_name))
    except ValidationError as exc:
        logger.error("Настройки неполные. Проверьте .env: {}", _describe_validation_error(exc))
        return 1
    except ProviderNotConfiguredError as exc:
        logger.error("{}", exc)
        return 1
    except TeacherAPIError as exc:
        logger.error("Некорректный ответ учителя: {}", exc)
        return 1
    except OpenAIError as exc:
        logger.error("Ошибка API учителя ({}): {}", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
