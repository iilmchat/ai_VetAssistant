"""Smoke-тест production-деплоя VetAssistant (T-042).

Запуск с Windows::

    python scripts/smoke_test.py

Проверяет:
1. главную страницу ``https://ai-pets.ru`` (HTTP 200);
2. регистрацию пользователя через ``/api/v1/auth/register``;
3. тестовое сообщение в ``/api/v1/chat/completions`` с JWT.

Скрипт печатает отчёт с ✅/❌ и возвращает exit code 0 только при успехе.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_BASE_URL = "https://ai-pets.ru"
DEFAULT_TIMEOUT = 30.0
DEFAULT_CHAT_TIMEOUT = 600.0
TEST_PROMPT = "Здравствуйте! Ответьте одним коротким предложением: кошка не ест сутки — это срочно?"


@dataclass(frozen=True)
class CheckResult:
    """Одна проверка smoke-теста."""

    name: str
    ok: bool
    detail: str
    elapsed_s: float = 0.0


def normalize_base_url(value: str) -> str:
    """Убрать завершающие слеши из базового URL."""
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("базовый URL не задан")
    return normalized


def api_base_url(base_url: str) -> str:
    """Получить корень API для внешнего Nginx-префикса ``/api``."""
    normalized = normalize_base_url(base_url)
    if normalized.endswith("/api"):
        return normalized
    return f"{normalized}/api"


def response_detail(response: requests.Response) -> str:
    """Достать читаемое описание ошибки из ответа API."""
    try:
        payload: Any = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:300] or f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    return f"HTTP {response.status_code}"


def check_site(
    session: requests.Session,
    base_url: str,
    *,
    timeout: float,
) -> CheckResult:
    """Проверить, что главная страница отвечает 200 OK."""
    started = time.perf_counter()
    try:
        response = session.get(base_url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        return CheckResult(
            "Главная страница",
            False,
            f"ошибка запроса: {exc}",
            time.perf_counter() - started,
        )
    elapsed = time.perf_counter() - started
    ok = response.status_code == 200
    detail = f"HTTP {response.status_code}"
    if not ok:
        detail += f" — {response_detail(response)}"
    return CheckResult("Главная страница", ok, detail, elapsed)


def register_user(
    session: requests.Session,
    base_url: str,
    *,
    timeout: float,
) -> tuple[CheckResult, str | None]:
    """Зарегистрировать уникального smoke-пользователя и вернуть JWT."""
    started = time.perf_counter()
    email = f"smoke-{uuid.uuid4().hex[:12]}@example.com"
    password = f"Smoke-{uuid.uuid4().hex[:16]}"
    url = f"{api_base_url(base_url)}/v1/auth/register"

    try:
        response = session.post(
            url,
            json={"email": email, "password": password},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return (
            CheckResult(
                "Регистрация",
                False,
                f"ошибка запроса: {exc}",
                time.perf_counter() - started,
            ),
            None,
        )

    elapsed = time.perf_counter() - started
    if response.status_code != 201:
        return (
            CheckResult(
                "Регистрация",
                False,
                f"HTTP {response.status_code} — {response_detail(response)}",
                elapsed,
            ),
            None,
        )

    try:
        payload: Any = response.json()
    except ValueError:
        payload = None
    token = payload.get("access_token") if isinstance(payload, dict) else None
    user = payload.get("user") if isinstance(payload, dict) else None
    user_id = user.get("id") if isinstance(user, dict) else "?"
    if not isinstance(token, str) or not token:
        return (
            CheckResult(
                "Регистрация",
                False,
                "API не вернул access_token",
                elapsed,
            ),
            None,
        )
    return (
        CheckResult(
            "Регистрация",
            True,
            f"создан пользователь id={user_id} ({email})",
            elapsed,
        ),
        token,
    )


def login_user(
    session: requests.Session,
    base_url: str,
    *,
    email: str,
    password: str,
    timeout: float,
) -> tuple[CheckResult, str | None]:
    """Войти существующим пользователем и вернуть JWT для smoke-теста."""
    started = time.perf_counter()
    url = f"{api_base_url(base_url)}/v1/auth/login"

    try:
        response = session.post(
            url,
            json={"email": email, "password": password},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return (
            CheckResult(
                "Вход",
                False,
                f"ошибка запроса: {exc}",
                time.perf_counter() - started,
            ),
            None,
        )

    elapsed = time.perf_counter() - started
    if response.status_code != 200:
        return (
            CheckResult(
                "Вход",
                False,
                f"HTTP {response.status_code} — {response_detail(response)}",
                elapsed,
            ),
            None,
        )

    try:
        payload: Any = response.json()
    except ValueError:
        payload = None
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        return (
            CheckResult("Вход", False, "API не вернул access_token", elapsed),
            None,
        )
    return (
        CheckResult("Вход", True, f"пользователь {email} авторизован", elapsed),
        token,
    )


def check_chat(
    session: requests.Session,
    base_url: str,
    token: str | None,
    *,
    timeout: float,
) -> CheckResult:
    """Отправить тестовое сообщение в чат и проверить ответ модели."""
    started = time.perf_counter()
    if token is None:
        return CheckResult(
            "Чат",
            False,
            "пропущен: нет JWT после аутентификации",
            time.perf_counter() - started,
        )

    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": TEST_PROMPT}],
        "temperature": 0.2,
        "max_tokens": 64,
        "stream": False,
        "use_rag": False,
    }
    url = f"{api_base_url(base_url)}/v1/chat/completions"
    try:
        response = session.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=(30, timeout),
        )
    except requests.RequestException as exc:
        return CheckResult(
            "Чат",
            False,
            f"ошибка запроса: {exc}",
            time.perf_counter() - started,
        )

    elapsed = time.perf_counter() - started
    if response.status_code != 200:
        return CheckResult(
            "Чат",
            False,
            f"HTTP {response.status_code} — {response_detail(response)}",
            elapsed,
        )

    try:
        data: Any = response.json()
    except ValueError:
        return CheckResult("Чат", False, "API вернул не-JSON", elapsed)

    content = ""
    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                content = message["content"].strip()

    if not content:
        return CheckResult(
            "Чат",
            False,
            "модель вернула пустой ответ",
            elapsed,
        )
    preview = " ".join(content.split())
    if len(preview) > 160:
        preview = f"{preview[:157]}..."
    return CheckResult(
        "Чат",
        True,
        f"ответ получен: «{preview}»",
        elapsed,
    )


def print_report(base_url: str, checks: list[CheckResult]) -> int:
    """Напечатать красивый отчёт и вернуть exit code."""
    passed = sum(1 for check in checks if check.ok)
    print()
    print("=" * 68)
    print("  🐾 VetAssistant — production smoke-тест")
    print(f"  {base_url}")
    print("=" * 68)
    for check in checks:
        icon = "✅" if check.ok else "❌"
        print(f"{icon} {check.name}: {check.detail} ({check.elapsed_s:.2f} с)")
    print("-" * 68)
    print(f"Итог: {passed}/{len(checks)} проверок пройдено")
    if passed == len(checks):
        print("✅ Production готов: сайт, аутентификация и чат работают.")
        return 0
    print("❌ Есть ошибки. Смотрите детали выше и логи контейнеров.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-тест VetAssistant.")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Корень сайта (по умолчанию https://ai-pets.ru)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Таймаут главной и регистрации, секунды",
    )
    parser.add_argument(
        "--chat-timeout",
        type=float,
        default=DEFAULT_CHAT_TIMEOUT,
        help="Таймаут генерации ответа, секунды",
    )
    parser.add_argument(
        "--email",
        default=None,
        help=(
            "Email существующего пользователя для входа. Нужен, если "
            "публичная регистрация закрыта (VET_API_ALLOW_PUBLIC_REGISTRATION=false)."
        ),
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Пароль для --email (если не задан, будет запрошен через getpass)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    base_url = normalize_base_url(args.base_url)
    session = requests.Session()
    session.headers["User-Agent"] = "VetAssistant-SmokeTest/1.0"

    checks = [check_site(session, base_url, timeout=args.timeout)]
    if args.email:
        password = args.password or getpass.getpass(f"Пароль {args.email}: ")
        authentication, token = login_user(
            session,
            base_url,
            email=args.email,
            password=password,
            timeout=args.timeout,
        )
    else:
        authentication, token = register_user(
            session,
            base_url,
            timeout=args.timeout,
        )
    checks.append(authentication)
    checks.append(
        check_chat(
            session,
            base_url,
            token,
            timeout=args.chat_timeout,
        )
    )
    return print_report(base_url, checks)


if __name__ == "__main__":
    raise SystemExit(main())
