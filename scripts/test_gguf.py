#!/usr/bin/env python
"""Смоук-тест GGUF-модели через OpenAI-совместимый endpoint (T-020).

Проверяет, что LM Studio (или другой сервер) отвечает на запрос к указанной
модели и что ответ можно разобрать как JSON. Это быстрая проверка связки
перед полным eval-прогоном.

Примеры::

    python scripts/test_gguf.py --dry-run
    python scripts/test_gguf.py --base-url http://127.0.0.1:1234/v1 --model-id gguf@q4_k_m
    python scripts/test_gguf.py --plain --prompt "Ответь одним словом: OK"
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

from loguru import logger
from openai import OpenAIError
from pydantic import SecretStr, ValidationError

from configs.settings import ProviderConfig
from data_pipeline.cli import configure_logging, positive_int
from data_pipeline.llm_client import TeacherAPIError, TeacherClient

DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_MODEL_ID = "gguf@q4_k_m"
DEFAULT_API_KEY = "lm-studio"
DEFAULT_TIMEOUT_S = 300.0
DEFAULT_MAX_TOKENS = 256
DEFAULT_JSON_PROMPT = (
    'Верни строго JSON-объект {"status": "ok", "role": "veterinary_assistant"} '
    "без markdown и пояснений."
)
DEFAULT_PLAIN_PROMPT = "Ответь одним словом: OK"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Смоук-тест GGUF-модели через OpenAI-совместимый API.",
        epilog="По умолчанию просит у модели JSON и проверяет, что он парсится.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        metavar="URL",
        help=f"endpoint модели (по умолчанию {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--model-id",
        default=DEFAULT_MODEL_ID,
        metavar="ID",
        help=f"идентификатор модели (по умолчанию {DEFAULT_MODEL_ID})",
    )
    parser.add_argument(
        "--api-key",
        default=DEFAULT_API_KEY,
        metavar="KEY",
        help=f"API-ключ (по умолчанию {DEFAULT_API_KEY})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        metavar="SEC",
        help=f"таймаут запроса в секундах (по умолчанию {DEFAULT_TIMEOUT_S:.0f})",
    )
    parser.add_argument(
        "--max-tokens",
        type=positive_int,
        default=DEFAULT_MAX_TOKENS,
        metavar="N",
        help=f"лимит токенов ответа (по умолчанию {DEFAULT_MAX_TOKENS})",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        metavar="TEXT",
        help="свой промпт (по умолчанию JSON-проверка или --plain)",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="не требовать JSON: просто проверить, что ответ непустой",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать настройки и промпт, не обращаясь к API",
    )
    return parser.parse_args(argv)


def _extract_json(content: str) -> Mapping[str, Any]:
    """Вытащить JSON-объект из ответа модели (допускается текст вокруг)."""
    cleaned = content.strip()
    candidates = [cleaned]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])

    for candidate in candidates:
        try:
            payload: Any = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            return payload

    snippet = " ".join(cleaned.split())[:200]
    raise ValueError(f"ответ модели не содержит JSON-объекта: {snippet!r}")


def _provider(args: argparse.Namespace) -> ProviderConfig:
    """Собрать конфигурацию локального провайдера."""
    return ProviderConfig(
        name="primary",
        api_key=SecretStr(args.api_key),
        base_url=args.base_url,
        model=args.model_id,
    )


def _dry_run(args: argparse.Namespace, prompt: str) -> None:
    """Показать параметры запроса без сети."""
    logger.info("base_url={}", args.base_url)
    logger.info("model={}", args.model_id)
    logger.info("api_key=*** (задан)")
    logger.info("timeout={:.0f}s max_tokens={}", args.timeout, args.max_tokens)
    logger.info("json_check={}", not args.plain)
    logger.info("prompt:\n{}", prompt)
    logger.info("--dry-run: API не вызывается")


async def _check(args: argparse.Namespace, prompt: str) -> int:
    """Сделать один запрос и проверить ответ."""
    provider = _provider(args)
    async with TeacherClient(provider, max_attempts=2, timeout_s=args.timeout) as client:
        result = await client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=args.max_tokens,
        )

    logger.info("Ответ модели:\n{}", result.content)
    logger.info(
        "Токены: prompt={} completion={} total={} | latency={:.2f}s | попыток={}",
        result.prompt_tokens,
        result.completion_tokens,
        result.total_tokens,
        result.latency_s,
        result.attempts,
    )

    if not result.content.strip():
        logger.error("Модель вернула пустой ответ")
        return 1

    if not args.plain:
        try:
            payload = _extract_json(result.content)
        except ValueError as exc:
            logger.error("{}", exc)
            return 1
        logger.info("JSON OK: {}", json.dumps(dict(payload), ensure_ascii=False))

    logger.info("OK")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()
    prompt = args.prompt or (DEFAULT_PLAIN_PROMPT if args.plain else DEFAULT_JSON_PROMPT)

    if args.dry_run:
        _dry_run(args, prompt)
        return 0

    try:
        return asyncio.run(_check(args, prompt))
    except ValidationError as exc:
        logger.error("Некорректные параметры подключения: {}", exc)
        return 1
    except TeacherAPIError as exc:
        logger.error("Некорректный ответ модели: {}", exc)
        return 1
    except OpenAIError as exc:
        logger.error("Ошибка API ({}): {}", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
