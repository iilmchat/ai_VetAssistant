#!/usr/bin/env python
"""Смоук-тест слоя абстракции учителя (T-002).

Проверяет два сценария:

* ``--dry-run`` — только читает `.env` через `get_settings()`, API не вызывается;
* без флагов — делает один реальный запрос к учителю и печатает ответ и токены.

Запуск::

    python scripts/test_api.py --dry-run
    python scripts/test_api.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from loguru import logger
from openai import OpenAIError
from pydantic import ValidationError

from configs import get_settings
from data_pipeline.llm_client import TeacherAPIError, TeacherClient

TEST_PROMPT = "Скажи 'Привет, я ассистент'"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Проверка доступа к API учителя (OpenAI-совместимый endpoint).",
        epilog=f"Тестовый запрос: {TEST_PROMPT!r}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="только проверить наличие настроек в .env, не обращаясь к API",
    )
    return parser.parse_args(argv)


def _configure_logging() -> None:
    """Логи в stdout (RULES §3: без print), безопасно к кодировке консоли Windows."""
    logger.remove()
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="backslashreplace")
    logger.add(
        stream,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
    )


def _describe_validation_error(exc: ValidationError) -> str:
    """Собрать имена отсутствующих/некорректных переменных окружения."""
    names: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        names.append(location.upper() if location else "?")
    return ", ".join(names) if names else "неизвестно"


def _check_settings() -> int:
    """Проверить, что обязательные ключи читаются из `.env`."""
    try:
        settings = get_settings()
    except ValidationError as exc:
        logger.error("Настройки неполные. Проверьте .env: {}", _describe_validation_error(exc))
        logger.error("Подсказка: скопируйте .env.example в .env и заполните TEACHER_*")
        return 1

    logger.info("Settings OK")
    logger.info("base_url={}", settings.teacher_base_url)
    logger.info("model={}", settings.teacher_model)
    logger.info("api_key=*** (задан)")
    return 0


async def _request_teacher() -> int:
    """Сделать один реальный запрос и напечатать ответ и токены."""
    async with TeacherClient() as client:
        logger.info("Запрос к учителю: model={}", client.model)
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
    _configure_logging()

    if args.dry_run:
        return _check_settings()

    try:
        return asyncio.run(_request_teacher())
    except ValidationError as exc:
        logger.error("Настройки неполные. Проверьте .env: {}", _describe_validation_error(exc))
        return 1
    except TeacherAPIError as exc:
        logger.error("Некорректный ответ учителя: {}", exc)
        return 1
    except OpenAIError as exc:
        logger.error("Ошибка API учителя ({}): {}", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
