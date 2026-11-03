#!/usr/bin/env python
"""Мониторинг памяти и конфигурации API VetAssistant (T-101).

Скрипт запрашивает ``/api/health`` и печатает:

* ``model_path_exists`` — найден ли GGUF-файл в контейнере API;
* текущую конфигурацию инференса (``n_ctx``, ``n_threads``,
  ``n_gpu_layers``), чтобы инфраструктурный агент видел, с каким
  контекстом работает модель;
* доступную память хоста (если доступен ``/proc/meminfo``).

Примеры::

    python scripts/check_ram.py
    python scripts/check_ram.py --base-url http://127.0.0.1:8000
    python scripts/check_ram.py --json

Exit code: ``0`` — API здоров и модель на месте, ``1`` — модель
отсутствует или API ответил не ``ok``, ``2`` — ошибка запроса/JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import requests

DEFAULT_BASE_URL = "https://ai-pets.ru"
DEFAULT_TIMEOUT_S = 15.0

#: Предел, выше которого стоит предупредить о расходе RAM на CPU-инференсе.
COMFORTABLE_N_CTX = 4096


def normalize_base_url(value: str) -> str:
    """Убрать завершающие слеши из базового URL."""
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("базовый URL не задан")
    return normalized


def health_urls(base_url: str) -> list[str]:
    """Собрать кандидатов URL health-эндпоинта.

    Снаружи Nginx проксирует ``/api/health`` в FastAPI ``/health``.
    Если скрипт запущен против API напрямую (``http://127.0.0.1:8000``),
    ``/api/health`` отвечает 404 — тогда пробуем ``/health``.
    """
    normalized = normalize_base_url(base_url)
    if normalized.endswith("/api"):
        return [f"{normalized}/health"]
    return [f"{normalized}/api/health", f"{normalized}/health"]


def host_memory_mib() -> dict[str, int] | None:
    """Прочитать ``MemTotal``/``MemAvailable`` из ``/proc/meminfo`` (Linux)."""
    meminfo = Path("/proc/meminfo")
    try:
        lines = meminfo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    values: dict[str, int] = {}
    for line in lines:
        key, _, raw = line.partition(":")
        if key not in {"MemTotal", "MemAvailable"}:
            continue
        parts = raw.split()
        if not parts:
            continue
        try:
            values[key] = int(parts[0]) // 1024
        except ValueError:
            continue

    if "MemTotal" not in values:
        return None
    result = {"total_mib": values["MemTotal"]}
    if "MemAvailable" in values:
        result["available_mib"] = values["MemAvailable"]
    return result


def fetch_health(
    session: requests.Session,
    urls: Sequence[str],
    *,
    timeout: float,
) -> tuple[str, dict[str, Any]]:
    """Запросить health-эндпоинт, перебирая кандидатов при 404."""
    for url in urls:
        response = session.get(url, timeout=timeout)
        if response.status_code == 404 and url != urls[-1]:
            continue
        response.raise_for_status()

        payload: Any = response.json()
        if not isinstance(payload, dict):
            raise ValueError("ответ health-эндпоинта не является JSON-объектом")
        return url, payload

    raise requests.RequestException("health-эндпоинт недоступен")


def _format_config(config: Any) -> list[str]:
    """Развернуть конфигурацию инференса в строки отчёта."""
    if not isinstance(config, Mapping):
        return ["  (нет данных: API не вернул config)"]

    lines: list[str] = []
    for key in ("n_ctx", "n_threads", "n_gpu_layers"):
        if key not in config:
            continue
        value = config[key]
        rendered = "auto" if key == "n_threads" and value is None else value
        lines.append(f"  {key}: {rendered}")

    if not lines:
        return ["  (нет данных: API не вернул config)"]
    return lines


def print_report(
    url: str,
    payload: Mapping[str, Any],
    memory: Mapping[str, int] | None,
) -> None:
    """Напечатать человекочитаемый отчёт."""
    exists = payload.get("model_path_exists")
    print(f"URL:               {url}")
    print(f"status:            {payload.get('status', '—')}")
    print(f"model:             {payload.get('model', '—')}")
    print(f"model_path:        {payload.get('model_path', '—')}")
    print(f"model_path_exists: {exists}")

    print("config:")
    for line in _format_config(payload.get("config")):
        print(line)

    if memory is not None:
        total = memory.get("total_mib")
        available = memory.get("available_mib")
        detail = f"{total} MiB всего"
        if available is not None:
            detail += f", {available} MiB доступно"
        print(f"RAM хоста:         {detail}")
    else:
        print("RAM хоста:         недоступна (/proc/meminfo не найден)")

    config = payload.get("config")
    n_ctx = config.get("n_ctx") if isinstance(config, Mapping) else None
    if isinstance(n_ctx, int) and n_ctx > COMFORTABLE_N_CTX:
        print(
            f"⚠ n_ctx={n_ctx} выше {COMFORTABLE_N_CTX}: при нехватке RAM "
            "снизьте VET_API_N_CTX до 2048–4096.",
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Проверить здоровье API, наличие GGUF и конфигурацию памяти.",
        epilog=(
            "По умолчанию опрашивается https://ai-pets.ru/api/health. "
            "Для локального API используйте --base-url http://127.0.0.1:8000."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        metavar="URL",
        help=f"корень сайта или API (по умолчанию {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        metavar="SEC",
        help=f"таймаут запроса в секундах (по умолчанию {DEFAULT_TIMEOUT_S})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="вывести машинночитаемый JSON для мониторинга",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа: запросить health и вернуть код состояния."""
    args = parse_args(argv)
    try:
        urls = health_urls(args.base_url)
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    memory = host_memory_mib()
    try:
        with requests.Session() as session:
            url, payload = fetch_health(session, urls, timeout=args.timeout)
    except requests.RequestException as exc:
        print(f"Ошибка запроса {', '.join(urls)}: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Некорректный ответ {', '.join(urls)}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "url": url,
                    "status": payload.get("status"),
                    "model": payload.get("model"),
                    "model_path": payload.get("model_path"),
                    "model_path_exists": payload.get("model_path_exists"),
                    "config": payload.get("config"),
                    "host_memory_mib": memory,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    else:
        print_report(url, payload, memory)

    if payload.get("status") != "ok":
        return 1
    if payload.get("model_path_exists") is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
