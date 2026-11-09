"""Админ-панель: рассмотрение заявок на доступ (T-120) и аналитика (T-135).

Все эндпоинты защищены зависимостью :func:`app.auth.get_current_admin`.
Временный пароль при approve возвращается один раз и в логи не пишется.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from app.auth import UserRead, get_current_admin, hash_password
from app.database import (
    Database,
    User,
    count_active_admins,
    create_user,
    delete_user_account,
    get_access_request_by_id,
    get_database,
    get_feedback_stats,
    get_user_by_email,
    get_user_by_id,
    get_users_by_ids,
    list_access_requests,
    list_users,
    record_admin_action,
)
from app.metrics import PROCESS_STARTED_AT, MetricsSnapshot, snapshot
from app.settings import get_app_settings

router = APIRouter(prefix="/v1/admin", tags=["admin"])

StatusCode = Literal["pending", "approved", "rejected", "all"]
UserStatus = Literal["all", "active", "blocked"]
MetricsWindow = Literal["24h", "7d"]

#: Параметры выборки по окну: (длина окна, шаг точки на графике).
WINDOW_SECONDS: dict[str, int] = {"24h": 24 * 3600, "7d": 7 * 24 * 3600}
WINDOW_STEP: dict[str, tuple[int, str]] = {"24h": (3600, "1h"), "7d": (6 * 3600, "6h")}
TOP_USERS_LIMIT = 5


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


class AdminUserRead(BaseModel):
    """Пользователь в админ-списке: без хэша пароля и токенов (T-140.2)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    is_admin: bool
    is_active: bool
    must_change_password: bool
    telegram_id: int | None = None
    created_at: datetime


class AdminUserListRead(BaseModel):
    """Страница списка пользователей."""

    items: list[AdminUserRead]
    total: int
    limit: int
    offset: int


class ModerationRequest(BaseModel):
    """Причина блокировки или разблокировки."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class DeleteUserRequest(BaseModel):
    """Подтверждение удаления: email должен совпасть с аккаунтом."""

    model_config = ConfigDict(extra="forbid")

    confirm_email: str = Field(min_length=1, max_length=320)
    reason: str | None = Field(default=None, max_length=500)


class FeedbackStatsRead(BaseModel):
    """Сводка оценок ответов для админ-аналитики (T-139.2, T-139.4)."""

    total: int
    positive: int
    negative: int
    positive_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="Доля 👍 среди всех оценок; 0.0, если оценок нет",
    )


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


# --- Управление пользователями (T-140.2) -------------------------------------


def _normalized_reason(raw: str) -> str:
    """Причина модерации не может быть пустой строкой."""
    reason = raw.strip()
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Укажите причину",
        )
    return reason


@router.get("/users", response_model=AdminUserListRead)
async def get_users(
    _current_admin: Annotated[User, Depends(get_current_admin)],
    database: Annotated[Database, Depends(get_database)],
    query: Annotated[str | None, Query(max_length=320)] = None,
    status_filter: Annotated[UserStatus, Query(alias="status")] = "all",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminUserListRead:
    """Список пользователей с поиском по email и пагинацией (T-140.2)."""
    normalized_query = query.strip() if query else None
    if status_filter == "active":
        is_active: bool | None = True
    elif status_filter == "blocked":
        is_active = False
    else:
        is_active = None

    async with database.session() as session:
        users, total = await list_users(
            session,
            query=normalized_query or None,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
    return AdminUserListRead(
        items=[AdminUserRead.model_validate(user) for user in users],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/users/{user_id}/block", response_model=AdminUserRead)
async def block_user(
    user_id: int,
    payload: ModerationRequest,
    current_admin: Annotated[User, Depends(get_current_admin)],
    database: Annotated[Database, Depends(get_database)],
) -> AdminUserRead:
    """Заблокировать пользователя: его действующий JWT сразу получает 403."""
    reason = _normalized_reason(payload.reason)

    async with database.session() as session:
        target = await get_user_by_id(session, user_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден",
            )
        if target.id == current_admin.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя заблокировать собственную учётную запись",
            )
        if (
            target.is_admin
            and target.is_active
            and await count_active_admins(session) <= 1
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Нельзя заблокировать последнего активного администратора",
            )
        if not target.is_active:
            return AdminUserRead.model_validate(target)

        target.is_active = False
        record_admin_action(
            session,
            admin_id=current_admin.id,
            target_user_id=target.id,
            action="block",
            reason=reason,
        )
        await session.commit()
        await session.refresh(target)

    logger.info(
        "Admin: {} заблокировал пользователя {} (причина: {})",
        current_admin.id,
        user_id,
        reason,
    )
    return AdminUserRead.model_validate(target)


@router.post("/users/{user_id}/unblock", response_model=AdminUserRead)
async def unblock_user(
    user_id: int,
    payload: ModerationRequest,
    current_admin: Annotated[User, Depends(get_current_admin)],
    database: Annotated[Database, Depends(get_database)],
) -> AdminUserRead:
    """Разблокировать пользователя и вернуть ему доступ."""
    reason = _normalized_reason(payload.reason)

    async with database.session() as session:
        target = await get_user_by_id(session, user_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден",
            )
        if target.is_active:
            return AdminUserRead.model_validate(target)

        target.is_active = True
        record_admin_action(
            session,
            admin_id=current_admin.id,
            target_user_id=target.id,
            action="unblock",
            reason=reason,
        )
        await session.commit()
        await session.refresh(target)

    logger.info(
        "Admin: {} разблокировал пользователя {} (причина: {})",
        current_admin.id,
        user_id,
        reason,
    )
    return AdminUserRead.model_validate(target)


@router.delete("/users/{user_id}", response_model=AdminUserRead)
async def delete_user(
    user_id: int,
    payload: DeleteUserRequest,
    current_admin: Annotated[User, Depends(get_current_admin)],
    database: Annotated[Database, Depends(get_database)],
) -> AdminUserRead:
    """Удалить аккаунт после подтверждения по email (T-140.2)."""
    async with database.session() as session:
        target = await get_user_by_id(session, user_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден",
            )
        if target.id == current_admin.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя удалить собственную учётную запись",
            )
        if (
            target.is_admin
            and target.is_active
            and await count_active_admins(session) <= 1
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Нельзя удалить последнего активного администратора",
            )
        if payload.confirm_email.strip().lower() != target.email.strip().lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email подтверждения не совпадает",
            )

        reason = payload.reason.strip() if payload.reason else None
        deleted = AdminUserRead.model_validate(target)
        record_admin_action(
            session,
            admin_id=current_admin.id,
            target_user_id=target.id,
            action="delete",
            reason=reason,
        )
        await delete_user_account(session, target.id)
        await session.commit()

    logger.info(
        "Admin: {} удалил пользователя {} (причина: {})",
        current_admin.id,
        user_id,
        reason or "не указана",
    )
    return deleted


# --- Аналитика использования (T-135) -----------------------------------------


class MetricsTotals(BaseModel):
    """Суммарные показатели за окно (или с момента старта API)."""

    requests: float = 0.0
    generation_errors: float = 0.0
    prompt_tokens: float = 0.0
    completion_tokens: float = 0.0
    tokens: float = 0.0
    rag_hits: float = 0.0
    rag_misses: float = 0.0
    rag_errors: float = 0.0
    http_errors: float = 0.0
    error_rate: float = 0.0


class MetricsPoint(BaseModel):
    """Точка графика: сколько запросов и токенов пришлось на интервал."""

    ts: datetime
    requests: float
    tokens: float


class TopUserRead(BaseModel):
    """Строка таблицы «топ пользователей»."""

    user_id: int
    email: str
    requests: float
    tokens: float


class AdminMetricsRead(BaseModel):
    """Ответ ``GET /v1/admin/metrics``."""

    source: Literal["prometheus", "in_process"]
    degraded: bool
    window: MetricsWindow
    generated_at: datetime
    started_at: datetime | None
    totals: MetricsTotals
    series: list[MetricsPoint]
    top_users: list[TopUserRead]


def _error_rate(errors: float, requests: float) -> float:
    """Доля ошибок генерации (0..1)."""
    return errors / requests if requests > 0 else 0.0


def _prom_value(sample: dict[str, Any]) -> float:
    """Числовое значение образца Prometheus (``value`` — [ts, "1.0"])."""
    try:
        value = sample.get("value") or [0, "0"]
        return float(value[1])
    except (TypeError, ValueError, IndexError):
        return 0.0


def _instant_sum(result: Sequence[dict[str, Any]]) -> float:
    """Сумма значений instant-запроса."""
    return sum(_prom_value(item) for item in result)


def _instant_by_label(
    result: Sequence[dict[str, Any]],
    label: str,
) -> dict[str, float]:
    """Сгруппировать instant-результат по метке."""
    grouped: dict[str, float] = {}
    for item in result:
        metric = item.get("metric") or {}
        key = str(metric.get(label, ""))
        grouped[key] = grouped.get(key, 0.0) + _prom_value(item)
    return grouped


def _range_values(result: Sequence[dict[str, Any]]) -> dict[int, float]:
    """Развернуть matrix-ответ Prometheus в {timestamp: value}."""
    if not result:
        return {}
    values: dict[int, float] = {}
    for raw in result[0].get("values") or []:
        try:
            values[int(float(raw[0]))] = float(raw[1])
        except (TypeError, ValueError, IndexError):
            continue
    return values


def _build_series(
    requests: dict[int, float],
    tokens: dict[int, float],
) -> list[MetricsPoint]:
    """Склеить два ряда по общим меткам времени."""
    return [
        MetricsPoint(
            ts=datetime.fromtimestamp(ts, UTC),
            requests=round(requests.get(ts, 0.0), 3),
            tokens=round(tokens.get(ts, 0.0), 3),
        )
        for ts in sorted(set(requests) | set(tokens))
    ]


async def _prom_query(
    client: httpx.AsyncClient,
    base_url: str,
    expression: str,
    *,
    start: float | None = None,
    end: float | None = None,
    step: int | None = None,
) -> list[dict[str, Any]]:
    """Выполнить запрос к Prometheus HTTP API.

    Выражения формирует только сервер (allowlist), клиент выбирает лишь окно.
    """
    if start is None:
        response = await client.get(
            f"{base_url}/api/v1/query",
            params={"query": expression},
        )
    else:
        response = await client.get(
            f"{base_url}/api/v1/query_range",
            params={
                "query": expression,
                "start": start,
                "end": end,
                "step": step,
            },
        )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ValueError(f"Prometheus ответил не success: {payload!r}")
    data = payload.get("data") or {}
    result = data.get("result")
    if not isinstance(result, list):
        raise ValueError("Prometheus вернул пустой result")
    return [item for item in result if isinstance(item, dict)]


async def _prometheus_totals(
    client: httpx.AsyncClient,
    base_url: str,
    window: MetricsWindow,
) -> MetricsTotals:
    """Суммы за окно через instant-запросы."""
    duration = f"{WINDOW_SECONDS[window]}s"
    expressions = (
        f"sum by (status) (increase(vet_llm_generation_requests_total[{duration}]))",
        f"sum(increase(vet_llm_prompt_tokens_total[{duration}]))",
        f"sum(increase(vet_llm_completion_tokens_total[{duration}]))",
        f'sum by (result) (increase(vet_rag_searches_total[{duration}]))',
        f'sum(increase(http_requests_total{{status=~"5.."}}[{duration}]))',
    )
    generation, prompt, completion, rag, http = await asyncio.gather(
        *(_prom_query(client, base_url, expression) for expression in expressions)
    )

    by_status = _instant_by_label(generation, "status")
    requests = sum(by_status.values())
    errors = by_status.get("error", 0.0)
    rag_by_result = _instant_by_label(rag, "result")
    prompt_tokens = _instant_sum(prompt)
    completion_tokens = _instant_sum(completion)

    return MetricsTotals(
        requests=requests,
        generation_errors=errors,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tokens=prompt_tokens + completion_tokens,
        rag_hits=rag_by_result.get("hit", 0.0),
        rag_misses=rag_by_result.get("miss", 0.0),
        rag_errors=rag_by_result.get("error", 0.0),
        http_errors=_instant_sum(http),
        error_rate=_error_rate(errors, requests),
    )


async def _prometheus_series(
    client: httpx.AsyncClient,
    base_url: str,
    window: MetricsWindow,
) -> list[MetricsPoint]:
    """Ряд запросов и токенов по интервалам окна."""
    step, step_label = WINDOW_STEP[window]
    end = time.time()
    start = end - WINDOW_SECONDS[window]
    requests_expr = f"sum(increase(vet_llm_generation_requests_total[{step_label}]))"
    tokens_expr = (
        f"sum(increase(vet_llm_prompt_tokens_total[{step_label}]))"
        f" + sum(increase(vet_llm_completion_tokens_total[{step_label}]))"
    )
    requests_result, tokens_result = await asyncio.gather(
        _prom_query(
            client,
            base_url,
            requests_expr,
            start=start,
            end=end,
            step=step,
        ),
        _prom_query(
            client,
            base_url,
            tokens_expr,
            start=start,
            end=end,
            step=step,
        ),
    )
    return _build_series(
        _range_values(requests_result),
        _range_values(tokens_result),
    )


async def _prometheus_top_usage(
    client: httpx.AsyncClient,
    base_url: str,
    window: MetricsWindow,
) -> dict[int, dict[str, float]]:
    """Топ пользователей по запросам и токенам (два topk + объединение)."""
    duration = f"{WINDOW_SECONDS[window]}s"
    requests_expr = (
        f"topk({TOP_USERS_LIMIT}, "
        f"sum by (user_id) (increase(vet_llm_user_requests_total[{duration}])))"
    )
    tokens_expr = (
        f"topk({TOP_USERS_LIMIT}, "
        f"sum by (user_id) (increase(vet_llm_user_tokens_total[{duration}])))"
    )
    requests_result, tokens_result = await asyncio.gather(
        _prom_query(client, base_url, requests_expr),
        _prom_query(client, base_url, tokens_expr),
    )

    merged: dict[int, dict[str, float]] = {}
    for result, key in (
        (requests_result, "requests"),
        (tokens_result, "tokens"),
    ):
        for item in result:
            metric = item.get("metric") or {}
            raw_user_id = str(metric.get("user_id", ""))
            if not raw_user_id.isdigit():
                continue
            entry = merged.setdefault(
                int(raw_user_id),
                {"requests": 0.0, "tokens": 0.0},
            )
            entry[key] += _prom_value(item)
    return merged


async def _resolve_top_users(
    database: Database,
    usage: dict[int, dict[str, float]],
) -> list[TopUserRead]:
    """Дополнить топ пользователей email из БД."""
    if not usage:
        return []
    async with database.session() as session:
        users = await get_users_by_ids(session, list(usage))
    emails = {user.id: user.email for user in users}
    rows = [
        TopUserRead(
            user_id=user_id,
            email=emails.get(user_id, f"user #{user_id}"),
            requests=round(values.get("requests", 0.0), 3),
            tokens=round(values.get("tokens", 0.0), 3),
        )
        for user_id, values in usage.items()
    ]
    rows.sort(key=lambda row: (row.requests, row.tokens), reverse=True)
    return rows[:TOP_USERS_LIMIT]


async def _prometheus_metrics(
    base_url: str,
    timeout_s: float,
    window: MetricsWindow,
    database: Database,
) -> AdminMetricsRead:
    """Собрать аналитику из Prometheus."""
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        totals, series, usage = await asyncio.gather(
            _prometheus_totals(client, base_url, window),
            _prometheus_series(client, base_url, window),
            _prometheus_top_usage(client, base_url, window),
        )
    return AdminMetricsRead(
        source="prometheus",
        degraded=False,
        window=window,
        generated_at=datetime.now(UTC),
        started_at=None,
        totals=totals,
        series=series,
        top_users=await _resolve_top_users(database, usage),
    )


def _in_process_totals(state: MetricsSnapshot) -> MetricsTotals:
    """Перевести снимок registry в модель ответа."""
    return MetricsTotals(
        requests=state.requests,
        generation_errors=state.generation_errors,
        prompt_tokens=state.prompt_tokens,
        completion_tokens=state.completion_tokens,
        tokens=state.tokens,
        rag_hits=state.rag_hits,
        rag_misses=state.rag_misses,
        rag_errors=state.rag_errors,
        http_errors=state.http_errors,
        error_rate=_error_rate(state.generation_errors, state.requests),
    )


async def _in_process_metrics(
    window: MetricsWindow,
    database: Database,
    *,
    degraded: bool,
) -> AdminMetricsRead:
    """Fallback: снимок метрик процесса без истории."""
    state = snapshot()
    usage = {
        user_id: {"requests": item.requests, "tokens": item.tokens}
        for user_id, item in state.users.items()
    }
    return AdminMetricsRead(
        source="in_process",
        degraded=degraded,
        window=window,
        generated_at=datetime.now(UTC),
        started_at=PROCESS_STARTED_AT,
        totals=_in_process_totals(state),
        series=[],
        top_users=await _resolve_top_users(database, usage),
    )


@router.get("/metrics", response_model=AdminMetricsRead)
async def get_admin_metrics(
    _current_admin: Annotated[User, Depends(get_current_admin)],
    database: Annotated[Database, Depends(get_database)],
    window: Annotated[MetricsWindow, Query()] = "24h",
) -> AdminMetricsRead:
    """Аналитика использования модели и RAG для админ-панели (T-135).

    Если ``VET_API_PROMETHEUS_URL`` задан и Prometheus отвечает — отдаются
    суммы и ряды за окно ``24h``/``7d``. Иначе (или при ошибке) — снимок
    in-process метрик с момента старта API и флагом ``degraded``.
    """
    settings = get_app_settings()
    base_url = settings.prometheus_url.strip().rstrip("/")
    if base_url:
        try:
            return await _prometheus_metrics(
                base_url,
                settings.prometheus_timeout_s,
                window,
                database,
            )
        except Exception as exc:
            logger.warning("Админ-аналитика: Prometheus недоступен ({}): {}", base_url, exc)
    return await _in_process_metrics(window, database, degraded=bool(base_url))


@router.get("/feedback/stats", response_model=FeedbackStatsRead)
async def get_admin_feedback_stats(
    _current_admin: Annotated[User, Depends(get_current_admin)],
    database: Annotated[Database, Depends(get_database)],
) -> FeedbackStatsRead:
    """Сводка оценок ответов для админ-панели (T-139.2, T-139.4).

    Считается по таблице ``feedback``: общее число оценок, расклад 👍/👎 и
    доля положительных. Тексты сообщений не участвуют — их в БД нет.
    """
    async with database.session() as session:
        stats = await get_feedback_stats(session)
    return FeedbackStatsRead(
        total=stats.total,
        positive=stats.positive,
        negative=stats.negative,
        positive_ratio=stats.positive_ratio,
    )

