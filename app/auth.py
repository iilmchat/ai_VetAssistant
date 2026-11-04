"""JWT-аутентификация и хэширование паролей (T-039).

Пароли хранятся как bcrypt-хэши (``passlib[bcrypt]``), access-токены —
подписанные HS256 JWT с ``sub`` = ``users.id``. Все защищённые эндпоинты
получают пользователя через зависимость :func:`get_current_user`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.database import Database, User, get_database, get_user_by_id
from app.settings import AppSettings, get_app_settings

ALGORITHM = "HS256"
MAX_PASSWORD_BYTES = 72

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)

UNAUTHORIZED_DETAIL = "Недействительный или просроченный токен"


def _ensure_bcrypt_length(value: str) -> str:
    """Проверить, что пароль помещается в лимит bcrypt (72 байта)."""
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("пароль длиннее 72 байт")
    return value


class RegisterRequest(BaseModel):
    """Тело запроса ``POST /v1/auth/register``."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=MAX_PASSWORD_BYTES)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        """bcrypt принимает не больше 72 байт, а не символов."""
        return _ensure_bcrypt_length(value)


class LoginRequest(BaseModel):
    """Тело запроса ``POST /v1/auth/login``."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_BYTES)


class ChangePasswordRequest(BaseModel):
    """Тело запроса ``POST /v1/auth/change-password``."""

    model_config = ConfigDict(extra="forbid")

    old_password: str = Field(min_length=1, max_length=MAX_PASSWORD_BYTES)
    new_password: str = Field(min_length=8, max_length=MAX_PASSWORD_BYTES)
    # Необязательное подтверждение: UI присылает его, API-клиенты могут нет.
    new_password_confirm: str | None = Field(
        default=None,
        max_length=MAX_PASSWORD_BYTES,
    )

    @field_validator("new_password", "new_password_confirm")
    @classmethod
    def password_fits_bcrypt(cls, value: str | None) -> str | None:
        """Проверить лимит bcrypt для нового пароля и подтверждения."""
        if value is None:
            return None
        return _ensure_bcrypt_length(value)


class UserRead(BaseModel):
    """Публичные данные пользователя."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime
    is_admin: bool = False
    must_change_password: bool = False


class AuthResponse(BaseModel):
    """Ответ register/login: JWT и данные пользователя."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserRead


class ChangePasswordResponse(BaseModel):
    """Ответ успешной смены пароля."""

    message: str


class AccessRequestCreate(BaseModel):
    """Тело запроса ``POST /v1/access/request``."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_is_not_blank(cls, value: str) -> str:
        """Не принимать заявку с одной пустой строкой."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("укажите причину или кто вы")
        return stripped


class AccessRequestResponse(BaseModel):
    """Ответ на заявку о доступе."""

    message: str


def hash_password(password: str) -> str:
    """Вернуть bcrypt-хэш пароля."""
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("пароль длиннее 72 байт")
    return str(password_context.hash(password))


def verify_password(password: str, hashed_password: str) -> bool:
    """Проверить пароль по bcrypt-хэшу."""
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bool(password_context.verify(password, hashed_password))
    except ValueError:
        return False


def create_access_token(
    *,
    user_id: int,
    email: str,
    settings: AppSettings,
) -> str:
    """Создать подписанный access-токен для пользователя."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str, settings: AppSettings) -> dict[str, Any]:
    """Разобрать и проверить JWT.

    Raises:
        jwt.PyJWTError: подпись неверна или токен истёк.
    """
    decoded = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    return decoded


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[AppSettings, Depends(get_app_settings)],
) -> User:
    """FastAPI-зависимость: пользователь из ``Authorization: Bearer <token>``."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials, settings)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=UNAUTHORIZED_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    async with database.session() as session:
        user = await get_user_by_id(session, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=UNAUTHORIZED_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """FastAPI-зависимость: текущий пользователь должен быть администратором."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Требуются права администратора",
        )
    return current_user
