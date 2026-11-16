"""Тесты слоя памяти PatientMemory (T-162).

Покрывают:
- сборку профиля, последних эпизодов и семантических фактов;
- бюджет контекста и деградацию без эмбеддера;
- сохранение выжимки эпизода и обрезку до 500 символов;
- изоляцию пациентов и вставку контекста в system prompt.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import date
from pathlib import Path

import pytest

from app.database import (
    MEMORY_EMBEDDING_DIM,
    Database,
    Episode,
    add_episode,
    create_patient,
    create_user,
    list_episodes,
)
from app.memory import (
    PatientMemory,
    summarize_episode,
    with_patient_context,
)


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'memory.db').as_posix()}")
    await db.create_tables()
    yield db
    await db.dispose()


@pytest.fixture
async def users(database: Database) -> tuple[int, int]:
    async with database.session() as session:
        owner = await create_user(
            session,
            email="owner@example.com",
            hashed_password="hash-1",
        )
        other = await create_user(
            session,
            email="other@example.com",
            hashed_password="hash-2",
        )
    return owner.id, other.id


def _vector(index: int) -> list[float]:
    values = [0.0] * MEMORY_EMBEDDING_DIM
    values[index] = 1.0
    return values


def _fake_embedder(text: str) -> Sequence[float]:
    if "сыпь" in text.casefold():
        return _vector(0)
    if "привив" in text.casefold():
        return _vector(1)
    return _vector(2)


def _failing_embedder(text: str) -> Sequence[float]:
    raise RuntimeError("модель эмбеддингов недоступна")


async def _make_patient(
    database: Database,
    user_id: int,
    *,
    name: str = "Бобик",
) -> int:
    async with database.session() as session:
        patient = await create_patient(
            session,
            user_id=user_id,
            name=name,
            species="dog",
            breed="Корги",
            birth_date=date(2020, 5, 1),
            weight=12.5,
            known_allergies="курица",
            chronic_conditions="артрит",
        )
    return patient.id


async def test_build_context_includes_profile_recent_and_similar(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, _ = users
    patient_id = await _make_patient(database, owner_id)
    async with database.session() as session:
        relevant = await add_episode(
            session,
            user_id=owner_id,
            patient_id=patient_id,
            content="Сыпь на животе, подозрение на аллергию",
            embedding=_vector(0),
        )
        for index in range(5):
            await add_episode(
                session,
                user_id=owner_id,
                patient_id=patient_id,
                content=f"Плановая запись {index}",
                embedding=_vector(1),
            )

    memory = PatientMemory(embedder=_fake_embedder)
    async with database.session() as session:
        context = await memory.build_context(
            session,
            user_id=owner_id,
            patient_id=patient_id,
            query="Это снова та же сыпь?",
        )

    assert "Профиль пациента: Бобик" in context
    assert "собака" in context
    assert "Аллергии: курица" in context
    assert "Хронические болезни: артрит" in context
    assert "История:" in context
    assert "Релевантные факты:" in context
    assert relevant.content in context
    assert len(context) <= 1200


async def test_build_context_without_query_has_no_facts(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, _ = users
    patient_id = await _make_patient(database, owner_id)
    async with database.session() as session:
        await add_episode(
            session,
            user_id=owner_id,
            patient_id=patient_id,
            content="Сыпь на животе",
            embedding=_vector(0),
        )

    memory = PatientMemory(embedder=_fake_embedder)
    async with database.session() as session:
        context = await memory.build_context(
            session,
            user_id=owner_id,
            patient_id=patient_id,
        )

    assert "Профиль пациента" in context
    assert "История:" in context
    assert "Релевантные факты:" not in context


async def test_build_context_respects_char_budget(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, _ = users
    async with database.session() as session:
        patient = await create_patient(
            session,
            user_id=owner_id,
            name="Бобик",
            species="dog",
            known_allergies="курица, " * 20,
            chronic_conditions="артрит, " * 20,
        )
        for _ in range(5):
            await add_episode(
                session,
                user_id=owner_id,
                patient_id=patient.id,
                content="Очень длинное описание эпизода " * 10,
                embedding=_vector(0),
            )

    memory = PatientMemory(embedder=_fake_embedder, max_context_chars=200)
    async with database.session() as session:
        context = await memory.build_context(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            query="сыпь",
        )

    assert len(context) <= 200
    assert context.endswith("…")


async def test_build_context_rejects_foreign_patient(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, other_id = users
    patient_id = await _make_patient(database, owner_id)

    memory = PatientMemory(embedder=_fake_embedder)
    async with database.session() as session:
        with pytest.raises(LookupError):
            await memory.build_context(
                session,
                user_id=other_id,
                patient_id=patient_id,
                query="сыпь",
            )


async def test_build_context_degrades_when_embedder_fails(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, _ = users
    patient_id = await _make_patient(database, owner_id)
    async with database.session() as session:
        await add_episode(
            session,
            user_id=owner_id,
            patient_id=patient_id,
            content="Сыпь на животе",
            embedding=_vector(0),
        )

    memory = PatientMemory(embedder=_failing_embedder)
    async with database.session() as session:
        context = await memory.build_context(
            session,
            user_id=owner_id,
            patient_id=patient_id,
            query="сыпь",
        )

    assert "Профиль пациента" in context
    assert "История:" in context
    assert "Релевантные факты:" not in context


async def test_save_episode_stores_summary_and_embedding(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, _ = users
    patient_id = await _make_patient(database, owner_id)
    memory = PatientMemory(embedder=_fake_embedder)

    async with database.session() as session:
        episode = await memory.save_episode(
            session,
            user_id=owner_id,
            patient_id=patient_id,
            question="У Бобика снова сыпь, что делать?" * 20,
            answer="Рекомендую осмотр и обработку от блох." * 30,
        )

    assert episode is not None
    assert episode.type == "chat"
    assert episode.content.startswith("Вопрос: ")
    assert len(episode.content) <= 500
    assert episode.embedding is not None
    assert len(episode.embedding) == MEMORY_EMBEDDING_DIM


async def test_save_episode_without_answer_is_noop(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, _ = users
    patient_id = await _make_patient(database, owner_id)
    memory = PatientMemory(embedder=_fake_embedder)

    async with database.session() as session:
        episode = await memory.save_episode(
            session,
            user_id=owner_id,
            patient_id=patient_id,
            question="Вопрос без ответа",
            answer="   ",
        )

    assert episode is None


async def test_save_episode_survives_embedder_failure(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, _ = users
    patient_id = await _make_patient(database, owner_id)
    memory = PatientMemory(embedder=_failing_embedder)

    async with database.session() as session:
        episode = await memory.save_episode(
            session,
            user_id=owner_id,
            patient_id=patient_id,
            question="Сыпь",
            answer="Наблюдаем",
        )

    assert episode is not None
    assert episode.embedding is None


async def test_save_episode_rejects_foreign_patient(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, other_id = users
    patient_id = await _make_patient(database, owner_id)
    memory = PatientMemory(embedder=_fake_embedder)

    async with database.session() as session:
        with pytest.raises(LookupError):
            await memory.save_episode(
                session,
                user_id=other_id,
                patient_id=patient_id,
                question="Чужой вопрос",
                answer="Чужой ответ",
            )


def test_summarize_episode_limits_length() -> None:
    summary = summarize_episode("вопрос " * 200, "ответ " * 200)

    assert len(summary) <= 500
    assert summary.startswith("Вопрос: ")
    assert "\n" not in summary


def test_with_patient_context_appends_to_existing_system() -> None:
    messages = [
        {"role": "system", "content": "Ты ветеринарный ассистент."},
        {"role": "user", "content": "Сыпь"},
    ]

    result = with_patient_context(messages, "Профиль пациента: Бобик.")

    assert result[0]["content"] == (
        "Ты ветеринарный ассистент.\n\nПрофиль пациента: Бобик."
    )
    assert result[1] == {"role": "user", "content": "Сыпь"}
    assert messages[0]["content"] == "Ты ветеринарный ассистент."


def test_with_patient_context_creates_system_message() -> None:
    result = with_patient_context(
        [{"role": "user", "content": "Сыпь"}],
        "Профиль пациента: Бобик.",
    )

    assert result[0] == {"role": "system", "content": "Профиль пациента: Бобик."}
    assert result[1]["role"] == "user"


async def test_recent_episodes_are_not_duplicated_in_facts(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, _ = users
    patient_id = await _make_patient(database, owner_id)
    async with database.session() as session:
        episode = await add_episode(
            session,
            user_id=owner_id,
            patient_id=patient_id,
            content="Сыпь на животе",
            embedding=_vector(0),
        )

    memory = PatientMemory(embedder=_fake_embedder)
    async with database.session() as session:
        context = await memory.build_context(
            session,
            user_id=owner_id,
            patient_id=patient_id,
            query="сыпь",
        )
        episodes = await list_episodes(
            session,
            user_id=owner_id,
            patient_id=patient_id,
        )

    assert episodes[0].id == episode.id
    assert context.count("Сыпь на животе") == 1
    assert "Релевантные факты:" not in context


def test_episode_model_is_used(database: Database) -> None:
    """Модель Episode импортируется и имеет ожидаемые поля."""
    columns = set(Episode.__table__.c.keys())
    assert {"id", "patient_id", "user_id", "type", "content", "embedding"} <= columns
