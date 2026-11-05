"""Привязка Telegram к веб-аккаунту: одноразовые коды и API (T-134.1/T-134.2).

Сайт выпускает код (``POST /v1/telegram/link-code``), пользователь отправляет
его боту, а бот подтверждает владение Telegram-аккаунтом
(``POST /v1/telegram/confirm``) под своим synthetic-JWT. В БД попадает только
HMAC-SHA256 от кода: сам код живёт 10 минут, используется один раз и не
пишется в логи.

Бот доказывает владение ID тем, что его synthetic-аккаунт называется
``telegram-<id>@bot.vetassistant.local`` (см. ``bot.client.telegram_credentials``).
Автоматического слияния аккаунтов нет: занятый ``telegram_id`` возвращает 409,
перенос записей — только вручную скриптом ``scripts/migrate_telegram_link.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from slowapi.util import get_remote_address
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import decode_access_token, get_current_user
from app.database import (
    Database,
    TelegramLinkCode,
    User,
    get_database,
    get_user_by_id,
    get_user_by_telegram_id,
)
from app.rate_limit import limiter
from app.settings import AppSettings, get_app_settings

router = APIRouter(prefix="/v1/telegram", tags=["telegram"])

#: Crockford base32 без визуально неоднозначных 0/O/1/I/U.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"

#: Длина кода привязки: 28^8 ≈ 3.8e11 вариантов.
CODE_LENGTH = 8

#: Срок жизни кода: 10 минут.
CODE_TTL = timedelta(minutes=10)

#: Сколько активных кодов можно держать одновременно.
MAX_ACTIVE_CODES = 3

#: Лимит выпуска кодов на пользователя.
LINK_CODE_RATE_LIMIT = "5/hour"

#: Границы ``BIGINT`` для Telegram ID.
MAX_TELEGRAM_ID = 2**63 - 1

#: Домен synthetic-аккаунтов Telegram-бота.
BOT_EMAIL_DOMAIN = "bot.vetassistant.local"

INVALID_CODE_DETAIL = "Код недействителен"
EXPIRED_CODE_DETAIL = "Срок действия кода истёк"
USED_CODE_DETAIL = "Код уже использован"
TOO_MANY_CODES_DETAIL = (
    f"Уже активны {MAX_ACTIVE_CODES} кода привязки. Используйте последний "
    "выданный или подождите 10 минут"
)
FOREIGN_BOT_DETAIL = "Токен не принадлежит боту этого Telegram-аккаунта"
TELEGRAM_BUSY_DETAIL = "Этот Telegram уже привязан к другому аккаунту"
ACCOUNT_BUSY_DETAIL = "Аккаунт уже привязан к другому Telegram"


@dataclass(frozen=True)
class IssuedLinkCode:
    """Выпущенный код и момент, когда он истечёт."""

    code: str
    expires_at: datetime


class TooManyActiveCodesError(RuntimeError):
    """У пользователя уже ``MAX_ACTIVE_CODES`` активных кодов."""


class TelegramConfirmRequest(BaseModel):
    """Тело запроса ``POST /v1/telegram/confirm`` (вызывает бот)."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=4, max_length=32)
    telegram_id: int = Field(gt=0, le=MAX_TELEGRAM_ID)


class TelegramUnlinkRequest(BaseModel):
    """Тело запроса ``POST /v1/telegram/unlink`` (вызывает бот)."""

    model_config = ConfigDict(extra="forbid")

    telegram_id: int = Field(gt=0, le=MAX_TELEGRAM_ID)


class TelegramLinkCodeResponse(BaseModel):
    """Выпущенный код привязки и инструкция для пользователя."""

    code: str
    expires_at: datetime
    bot_username: str | None = None
    instructions: str


class TelegramLinkResponse(BaseModel):
    """Статус привязки текущего пользователя."""

    linked: bool
    telegram_id: int | None = None
    linked_at: datetime | None = None
    email: str | None = None


class TelegramConfirmResponse(BaseModel):
    """Результат успешной привязки (бот показывает email пользователю)."""

    linked: bool
    user_id: int
    email: str
    telegram_id: int


class TelegramUnlinkResponse(BaseModel):
    """Результат отвязки Telegram."""

    linked: bool = False
    message: str


def generate_code() -> str:
    """Сгенерировать 8-символьный код из безопасного алфавита."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw: str) -> str | None:
    """Привести код к каноническому виду.

    Пользователь может прислать код строчными буквами, с пробелами или
    дефисами — это допустимо. Неверная длина или символы вне алфавита дают
    ``None`` (код считается недействительным, без подсказок).
    """
    cleaned = re.sub(r"[\s\-_]+", "", raw).upper()
    if len(cleaned) != CODE_LENGTH:
        return None
    if any(char not in CODE_ALPHABET for char in cleaned):
        return None
    return cleaned


def hash_code(code: str, secret: str) -> str:
    """Вернуть HMAC-SHA256 от кода (64 hex-символа) для хранения в БД."""
    return hmac.new(
        secret.encode("utf-8"),
        f"telegram-link:{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


def bot_email(telegram_id: int) -> str:
    """Synthetic-email аккаунта бота для указанного Telegram ID."""
    return f"telegram-{telegram_id}@{BOT_EMAIL_DOMAIN}"


def telegram_id_from_bot_email(email: str) -> int | None:
    """Достать Telegram ID из synthetic-email бота.

    ``None`` — email не принадлежит боту (обычный веб-пользователь) или ID
    вне допустимого диапазона.
    """
    normalized = email.strip().casefold()
    prefix = "telegram-"
    suffix = f"@{BOT_EMAIL_DOMAIN}"
    if not normalized.startswith(prefix) or not normalized.endswith(suffix):
        return None

    raw = normalized[len(prefix) : -len(suffix)]
    if not raw.isdigit():
        return None
    value = int(raw)
    if value <= 0 or value > MAX_TELEGRAM_ID:
        return None
    return value


def is_bot_account(email: str) -> bool:
    """Признак synthetic-аккаунта Telegram-бота (для отключения уведомлений)."""
    return telegram_id_from_bot_email(email) is not None


async def resolve_bot_login_user(session: AsyncSession, user: User) -> User:
    """Для synthetic-аккаунта вернуть привязанного веб-пользователя (T-134.3).

    Бот входит под synthetic-аккаунтом, пароль которого выводится из секрета
    бота. Если этот Telegram уже привязан к веб-аккаунту, бот должен работать
    от имени владельца: записи, напоминания и уведомления становятся общими с
    сайтом. Без привязки возвращается сам synthetic-аккаунт (прежнее поведение).
    """
    telegram_id = telegram_id_from_bot_email(user.email)
    if telegram_id is None:
        return user

    linked = await get_user_by_telegram_id(session, telegram_id)
    if linked is None or linked.id == user.id:
        return user

    logger.info(
        "Telegram: synthetic-вход {} → аккаунт {}",
        telegram_id,
        linked.id,
    )
    return linked


def build_instructions(bot_username: str, code: str) -> str:
    """Инструкция «отправьте боту /link КОД» для ответа API."""
    username = bot_username.strip().lstrip("@")
    target = f"@{username}" if username else "боту"
    return (
        f"Откройте Telegram и отправьте {target} команду /link {code}. "
        "Код действует 10 минут."
    )


def _as_utc(moment: datetime) -> datetime:
    """Привести значение из SQLite (naive UTC) к aware-UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def ensure_bot_identity(user: User, telegram_id: int) -> None:
    """Проверить, что JWT принадлежит боту именно этого Telegram-аккаунта.

    Raises:
        HTTPException: 403, если email пользователя не соответствует
            ``telegram-<telegram_id>@bot.vetassistant.local``.
    """
    if user.email.strip().casefold() != bot_email(telegram_id):
        logger.warning(
            "Telegram: отказ — пользователь {} не бот для Telegram {}",
            user.id,
            telegram_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=FOREIGN_BOT_DETAIL,
        )


def link_code_rate_key(request: Request) -> str:
    """Ключ rate limit: пользователь из JWT, иначе IP клиента."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    subject: object = None
    if scheme.casefold() == "bearer" and token:
        try:
            subject = decode_access_token(token, get_app_settings()).get("sub")
        except jwt.PyJWTError:
            subject = None
    if isinstance(subject, str) and subject:
        return f"user:{subject}"
    return get_remote_address(request)


async def _purge_expired(
    session: AsyncSession,
    *,
    user_id: int,
    moment: datetime,
) -> None:
    """Удалить просроченные неиспользованные коды пользователя."""
    await session.execute(
        delete(TelegramLinkCode).where(
            TelegramLinkCode.user_id == user_id,
            TelegramLinkCode.used_at.is_(None),
            TelegramLinkCode.expires_at <= moment,
        )
    )


async def issue_link_code(
    session: AsyncSession,
    *,
    user: User,
    settings: AppSettings,
    now: datetime | None = None,
) -> IssuedLinkCode:
    """Выпустить код привязки для пользователя.

    Raises:
        TooManyActiveCodesError: у пользователя уже 3 активных кода.
    """
    moment = now or datetime.now(UTC)
    await _purge_expired(session, user_id=user.id, moment=moment)

    active = await session.scalar(
        select(func.count())
        .select_from(TelegramLinkCode)
        .where(
            TelegramLinkCode.user_id == user.id,
            TelegramLinkCode.used_at.is_(None),
            TelegramLinkCode.expires_at > moment,
        )
    )
    if int(active or 0) >= MAX_ACTIVE_CODES:
        raise TooManyActiveCodesError

    code = generate_code()
    expires_at = moment + CODE_TTL
    session.add(
        TelegramLinkCode(
            user_id=user.id,
            code_hash=hash_code(code, settings.jwt_secret),
            expires_at=expires_at,
        )
    )
    await session.commit()
    return IssuedLinkCode(code=code, expires_at=expires_at)


async def _load_usable_code(
    session: AsyncSession,
    *,
    digest: str,
) -> TelegramLinkCode:
    """Найти код по хэшу и проверить одноразовость и TTL.

    Raises:
        HTTPException: 400 с нейтральным ``detail`` для неверного,
            просроченного или уже использованного кода.
    """
    result = await session.execute(
        select(TelegramLinkCode).where(TelegramLinkCode.code_hash == digest)
    )
    link = result.scalar_one_or_none()
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_CODE_DETAIL,
        )
    if link.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=USED_CODE_DETAIL,
        )
    if _as_utc(link.expires_at) <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=EXPIRED_CODE_DETAIL,
        )
    return link


async def _detach_telegram(session: AsyncSession, user: User) -> None:
    """Отвязать Telegram и удалить ещё не использованные коды."""
    user.telegram_id = None
    await session.execute(
        delete(TelegramLinkCode).where(
            TelegramLinkCode.user_id == user.id,
            TelegramLinkCode.used_at.is_(None),
        )
    )
    await session.commit()


@router.post("/link-code", response_model=TelegramLinkCodeResponse)
@limiter.limit(LINK_CODE_RATE_LIMIT, key_func=link_code_rate_key)
async def create_telegram_link_code(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[AppSettings, Depends(get_app_settings)],
) -> TelegramLinkCodeResponse:
    """Выпустить одноразовый код привязки для текущего пользователя."""
    async with database.session() as session:
        try:
            issued = await issue_link_code(
                session,
                user=current_user,
                settings=settings,
            )
        except TooManyActiveCodesError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=TOO_MANY_CODES_DETAIL,
            ) from exc

    bot_username = settings.telegram_bot_username.strip().lstrip("@")
    logger.info(
        "Telegram: код привязки выпущен пользователю {}",
        current_user.id,
    )
    return TelegramLinkCodeResponse(
        code=issued.code,
        expires_at=issued.expires_at,
        bot_username=bot_username or None,
        instructions=build_instructions(bot_username, issued.code),
    )


@router.get("/link", response_model=TelegramLinkResponse)
async def get_telegram_link(
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[Database, Depends(get_database)],
) -> TelegramLinkResponse:
    """Вернуть статус привязки текущего пользователя."""
    if current_user.telegram_id is None:
        return TelegramLinkResponse(linked=False, email=current_user.email)

    async with database.session() as session:
        used_at = await session.scalar(
            select(TelegramLinkCode.used_at)
            .where(
                TelegramLinkCode.user_id == current_user.id,
                TelegramLinkCode.telegram_id == current_user.telegram_id,
                TelegramLinkCode.used_at.is_not(None),
            )
            .order_by(TelegramLinkCode.used_at.desc())
            .limit(1)
        )

    linked_at = _as_utc(used_at) if isinstance(used_at, datetime) else None
    return TelegramLinkResponse(
        linked=True,
        telegram_id=current_user.telegram_id,
        linked_at=linked_at,
        email=current_user.email,
    )


@router.post("/confirm", response_model=TelegramConfirmResponse)
async def confirm_telegram_link(
    payload: TelegramConfirmRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[AppSettings, Depends(get_app_settings)],
) -> TelegramConfirmResponse:
    """Подтвердить привязку кодом (вызывается ботом под synthetic-JWT)."""
    ensure_bot_identity(current_user, payload.telegram_id)
    code = normalize_code(payload.code)
    if code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_CODE_DETAIL,
        )

    digest = hash_code(code, settings.jwt_secret)
    now = datetime.now(UTC)

    async with database.session() as session:
        link = await _load_usable_code(session, digest=digest)
        owner = await get_user_by_id(session, link.user_id)
        if owner is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=INVALID_CODE_DETAIL,
            )

        busy = await session.scalar(
            select(User).where(User.telegram_id == payload.telegram_id)
        )
        if busy is not None and busy.id != owner.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=TELEGRAM_BUSY_DETAIL,
            )
        if owner.telegram_id is not None and owner.telegram_id != payload.telegram_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ACCOUNT_BUSY_DETAIL,
            )

        owner.telegram_id = payload.telegram_id
        link.used_at = now
        link.telegram_id = payload.telegram_id
        await session.execute(
            delete(TelegramLinkCode).where(
                TelegramLinkCode.user_id == owner.id,
                TelegramLinkCode.id != link.id,
                TelegramLinkCode.used_at.is_(None),
            )
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=TELEGRAM_BUSY_DETAIL,
            ) from exc

    logger.info(
        "Telegram: аккаунт {} привязан к Telegram {}",
        owner.id,
        payload.telegram_id,
    )
    return TelegramConfirmResponse(
        linked=True,
        user_id=owner.id,
        email=owner.email,
        telegram_id=payload.telegram_id,
    )


@router.delete("/link", response_model=TelegramUnlinkResponse)
async def unlink_telegram(
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[Database, Depends(get_database)],
) -> TelegramUnlinkResponse:
    """Отвязать Telegram от текущего веб-аккаунта."""
    if current_user.telegram_id is None:
        return TelegramUnlinkResponse(message="Telegram не был привязан")

    async with database.session() as session:
        user = await get_user_by_id(session, current_user.id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Требуется авторизация",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await _detach_telegram(session, user)

    logger.info("Telegram: аккаунт {} отвязал Telegram", current_user.id)
    return TelegramUnlinkResponse(message="Telegram отвязан")


@router.post("/unlink", response_model=TelegramUnlinkResponse)
async def unlink_telegram_by_bot(
    payload: TelegramUnlinkRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    database: Annotated[Database, Depends(get_database)],
) -> TelegramUnlinkResponse:
    """Отвязать Telegram (вызывается ботом под synthetic-JWT)."""
    ensure_bot_identity(current_user, payload.telegram_id)

    async with database.session() as session:
        owner = await session.scalar(
            select(User).where(User.telegram_id == payload.telegram_id)
        )
        if owner is None:
            return TelegramUnlinkResponse(message="Telegram не был привязан")
        await _detach_telegram(session, owner)
        owner_id = owner.id

    logger.info(
        "Telegram: аккаунт {} отвязал Telegram {}",
        owner_id,
        payload.telegram_id,
    )
    return TelegramUnlinkResponse(message="Telegram отвязан")
