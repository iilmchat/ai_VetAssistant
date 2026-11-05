#!/usr/bin/env python
"""Перенести данные synthetic-аккаунта Telegram на веб-аккаунт (T-134.3).

Бот продолжает входить под техническим аккаунтом
``telegram-<id>@bot.vetassistant.local``, но API выдаёт JWT привязанного
веб-пользователя (T-134.3). Скрипт переносит старые ``appointments`` и
``reminders`` с synthetic-аккаунта на веб-аккаунт и **не удаляет** synthetic:
он остаётся идентичностью бота для его HMAC-пароля. Удаление сломало бы вход.

Примеры::

    # Отчёт: какие synthetic-аккаунты есть и сколько у них данных (без записи)
    python scripts/migrate_telegram_link.py

    # Предпросмотр переноса
    python scripts/migrate_telegram_link.py \
        --merge-user owner@example.com 1133302963 --dry-run

    # Перенос записей и привязка telegram_id к веб-аккаунту
    python scripts/migrate_telegram_link.py \
        --merge-user owner@example.com 1133302963

Скрипт идемпотентен: повторный запуск с теми же аргументами ничего не меняет.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import (
    Appointment,
    Database,
    Reminder,
    User,
    get_user_by_email,
    get_user_by_telegram_id,
)
from app.settings import get_app_settings
from app.telegram_link import MAX_TELEGRAM_ID, bot_email, telegram_id_from_bot_email

BOT_EMAIL_SUFFIX = "@bot.vetassistant.local"


class MergeError(RuntimeError):
    """Перенос невозможен: конфликт аккаунтов или нет пользователя."""


@dataclass(frozen=True)
class SyntheticAccountReport:
    """Synthetic-аккаунт бота и количество привязанных к нему строк."""

    email: str
    user_id: int
    telegram_id: int | None
    appointments: int
    reminders: int


@dataclass(frozen=True)
class MergeReport:
    """Результат переноса данных с synthetic-аккаунта."""

    target_email: str
    target_user_id: int
    telegram_id: int
    synthetic_email: str | None
    appointments: int
    reminders: int
    changed: bool


async def _count(session: AsyncSession, model: Any, user_id: int) -> int:
    """Посчитать строки модели, принадлежащие пользователю."""
    total = await session.scalar(
        select(func.count())
        .select_from(model)
        .where(model.user_id == user_id)
    )
    return int(total or 0)


async def list_synthetic_accounts(database_url: str) -> list[SyntheticAccountReport]:
    """Вернуть все synthetic-аккаунты бота с числом записей и напоминаний."""
    database = Database(database_url)
    try:
        await database.create_tables()
        async with database.session() as session:
            result = await session.execute(
                select(User)
                .where(User.email.like(f"telegram-%{BOT_EMAIL_SUFFIX}"))
                .order_by(User.id)
            )
            reports: list[SyntheticAccountReport] = []
            for user in result.scalars().all():
                telegram_id = telegram_id_from_bot_email(user.email)
                if telegram_id is None:
                    continue
                reports.append(
                    SyntheticAccountReport(
                        email=user.email,
                        user_id=user.id,
                        telegram_id=user.telegram_id,
                        appointments=await _count(session, Appointment, user.id),
                        reminders=await _count(session, Reminder, user.id),
                    )
                )
            return reports
    finally:
        await database.dispose()


async def merge_synthetic_account(
    database_url: str,
    *,
    email: str,
    telegram_id: int,
    dry_run: bool = False,
) -> MergeReport:
    """Перенести записи synthetic-аккаунта на веб-аккаунт ``email``.

    ``telegram_id`` привязывается к веб-аккаунту (если ещё не привязан).
    Synthetic-аккаунт остаётся для авторизации бота.

    Raises:
        MergeError: пользователь не найден, ``telegram_id`` занят другим
            аккаунтом или у аккаунтов конфликтующие привязки.
        ValueError: ``telegram_id`` вне допустимого диапазона.
    """
    if telegram_id <= 0 or telegram_id > MAX_TELEGRAM_ID:
        raise ValueError("Telegram ID вне допустимого диапазона BIGINT")

    normalized_email = email.strip().lower()
    synthetic_email = bot_email(telegram_id)

    database = Database(database_url)
    try:
        await database.create_tables()
        async with database.session() as session:
            target = await get_user_by_email(session, normalized_email)
            if target is None:
                raise MergeError(f"пользователь {normalized_email} не найден")

            synthetic = await get_user_by_email(session, synthetic_email)
            if synthetic is not None and synthetic.id == target.id:
                synthetic = None

            busy = await get_user_by_telegram_id(session, telegram_id)
            allowed_ids = {target.id}
            if synthetic is not None:
                allowed_ids.add(synthetic.id)
            if busy is not None and busy.id not in allowed_ids:
                raise MergeError(
                    f"Telegram {telegram_id} уже привязан к {busy.email} "
                    f"(user_id={busy.id})"
                )

            if target.telegram_id not in (None, telegram_id):
                raise MergeError(
                    f"аккаунт {target.email} уже привязан к Telegram "
                    f"{target.telegram_id}"
                )
            if synthetic is not None and synthetic.telegram_id not in (
                None,
                telegram_id,
            ):
                raise MergeError(
                    f"synthetic-аккаунт {synthetic.email} привязан к другому "
                    f"Telegram {synthetic.telegram_id}"
                )

            appointments = (
                await _count(session, Appointment, synthetic.id)
                if synthetic is not None
                else 0
            )
            reminders = (
                await _count(session, Reminder, synthetic.id)
                if synthetic is not None
                else 0
            )
            changed = bool(
                appointments
                or reminders
                or target.telegram_id != telegram_id
                or (synthetic is not None and synthetic.telegram_id is not None)
            )

            # Значения фиксируем до rollback: rollback истекает объекты сессии,
            # а обращение к ним после него в async-сессии уже недопустимо.
            target_email = target.email
            target_user_id = target.id
            synthetic_email_value = (
                synthetic.email if synthetic is not None else None
            )

            if not dry_run and changed:
                if synthetic is not None:
                    if synthetic.telegram_id is not None:
                        # Сначала освобождаем уникальный telegram_id.
                        synthetic.telegram_id = None
                        await session.flush()
                    await session.execute(
                        update(Appointment)
                        .where(Appointment.user_id == synthetic.id)
                        .values(user_id=target.id)
                    )
                    await session.execute(
                        update(Reminder)
                        .where(Reminder.user_id == synthetic.id)
                        .values(user_id=target.id)
                    )
                target.telegram_id = telegram_id
                await session.commit()
            else:
                await session.rollback()

            return MergeReport(
                target_email=target_email,
                target_user_id=target_user_id,
                telegram_id=telegram_id,
                synthetic_email=synthetic_email_value,
                appointments=appointments,
                reminders=reminders,
                changed=changed,
            )
    finally:
        await database.dispose()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description=(
            "Перенести записи synthetic-аккаунта Telegram на веб-аккаунт "
            "и привязать telegram_id (T-134.3)."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        metavar="URL",
        help="SQLAlchemy async URL (по умолчанию VET_API_DATABASE_URL)",
    )
    parser.add_argument(
        "--merge-user",
        nargs=2,
        default=None,
        metavar=("EMAIL", "TELEGRAM_ID"),
        help="перенести данные на EMAIL и привязать TELEGRAM_ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать, что будет сделано, не меняя БД",
    )
    return parser.parse_args(argv)


def _print_synthetic(reports: Sequence[SyntheticAccountReport]) -> None:
    if not reports:
        print("Synthetic-аккаунтов Telegram не найдено.")
        return
    print(f"Synthetic-аккаунтов найдено: {len(reports)}")
    for report in reports:
        linked = report.telegram_id if report.telegram_id is not None else "—"
        print(
            f"  {report.email} (user_id={report.user_id}, telegram_id={linked}): "
            f"записей {report.appointments}, напоминаний {report.reminders}"
        )
    print(
        "\nПеренос: python scripts/migrate_telegram_link.py "
        "--merge-user EMAIL TELEGRAM_ID [--dry-run]"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    database_url: str = args.database_url or get_app_settings().database_url

    if args.merge_user is None:
        reports = asyncio.run(list_synthetic_accounts(database_url))
        _print_synthetic(reports)
        return 0

    email, raw_telegram_id = args.merge_user
    try:
        telegram_id = int(raw_telegram_id)
    except ValueError:
        print("Ошибка: TELEGRAM_ID должен быть целым числом")
        return 2

    try:
        report = asyncio.run(
            merge_synthetic_account(
                database_url,
                email=email,
                telegram_id=telegram_id,
                dry_run=bool(args.dry_run),
            )
        )
    except (MergeError, ValueError) as exc:
        print(f"Ошибка: {exc}")
        return 1

    prefix = "[dry-run] " if args.dry_run else ""
    verb = "Будет перенесено" if args.dry_run else "Перенесено"
    if report.synthetic_email is None:
        print(
            f"{prefix}Synthetic-аккаунт {bot_email(report.telegram_id)} не найден: "
            "переносить нечего."
        )
    elif not report.changed:
        print(f"{prefix}Данные уже перенесены, изменений нет.")
    else:
        print(
            f"{prefix}{verb} на {report.target_email} (user_id="
            f"{report.target_user_id}): записей {report.appointments}, "
            f"напоминаний {report.reminders}."
        )
    print(
        f"{prefix}telegram_id={report.telegram_id} привязан к {report.target_email}; "
        "synthetic-аккаунт сохранён для входа бота."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
