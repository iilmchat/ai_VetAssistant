"""Админ-панель: рассмотрение заявок на доступ (T-120).

Все эндпоинты защищены зависимостью :func:`app.auth.get_current_admin`.
Временный пароль при approve возвращается один раз и в логи не пишется.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.auth import UserRead, get_current_admin, hash_password
from app.database import (
    Database,
    User,
    create_user,
    get_access_request_by_id,
    get_database,
    get_user_by_email,
    list_access_requests,
)

router = APIRouter(prefix="/v1/admin", tags=["admin"])

StatusCode = Literal["pending", "approved", "rejected", "all"]


class AccessRequestRead(BaseModel):
    """Заявка на доступ с полями аудита."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    reason: str
    status: str
    created_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by: int | None = None
    approved_user_id: int | None = None
    rejection_reason: str | None = None


class ApproveAccessRequestResponse(BaseModel):
    """Результат approve: одноразовый временный пароль."""

    temp_password: str
    user_id: int
    email: str
    user: UserRead


class RejectAccessRequestRequest(BaseModel):
    """Тело reject-запроса."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


@router.get("/access-requests", response_model=list[AccessRequestRead])
async def get_access_requests(
    _current_admin: Annotated[User, Depends(get_current_admin)],
    database: Annotated[Database, Depends(get_database)],
    status_filter: Annotated[StatusCode, Query(alias="status")] = "pending",
) -> list[AccessRequestRead]:
    """Список заявок; по умолчанию только pending."""
    async with database.session() as session:
        filter_status = None if status_filter == "all" else status_filter
        requests = await list_access_requests(session, status=filter_status)
    return [AccessRequestRead.model_validate(item) for item in requests]


@router.post(
    "/access-requests/{request_id}/approve",
    response_model=ApproveAccessRequestResponse,
)
async def approve_access_request(
    request_id: int,
    current_admin: Annotated[User, Depends(get_current_admin)],
    database: Annotated[Database, Depends(get_database)],
) -> ApproveAccessRequestResponse:
    """Создать пользователя по заявке и вернуть временный пароль."""
    async with database.session() as session:
        access_request = await get_access_request_by_id(session, request_id)
        if access_request is None:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if access_request.status != "pending":
            raise HTTPException(
                status_code=400,
                detail="Заявка уже рассмотрена",
            )

        email = access_request.email.strip().lower()
        if await get_user_by_email(session, email) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Пользователь с таким email уже существует",
            )

        temp_password = secrets.token_urlsafe(12)
        user = await create_user(
            session,
            email=email,
            hashed_password=hash_password(temp_password),
            must_change_password=True,
        )

        access_request.status = "approved"
        access_request.reviewed_at = datetime.now(UTC)
        access_request.reviewed_by = current_admin.id
        access_request.approved_user_id = user.id
        await session.commit()
        await session.refresh(access_request)

    return ApproveAccessRequestResponse(
        temp_password=temp_password,
        user_id=user.id,
        email=email,
        user=UserRead.model_validate(user),
    )


@router.post(
    "/access-requests/{request_id}/reject",
    response_model=AccessRequestRead,
)
async def reject_access_request(
    request_id: int,
    payload: RejectAccessRequestRequest,
    current_admin: Annotated[User, Depends(get_current_admin)],
    database: Annotated[Database, Depends(get_database)],
) -> AccessRequestRead:
    """Отклонить заявку с указанием причины."""
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Укажите причину отказа")

    async with database.session() as session:
        access_request = await get_access_request_by_id(session, request_id)
        if access_request is None:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if access_request.status != "pending":
            raise HTTPException(
                status_code=400,
                detail="Заявка уже рассмотрена",
            )

        access_request.status = "rejected"
        access_request.reviewed_at = datetime.now(UTC)
        access_request.reviewed_by = current_admin.id
        access_request.rejection_reason = reason
        await session.commit()
        await session.refresh(access_request)

    return AccessRequestRead.model_validate(access_request)
