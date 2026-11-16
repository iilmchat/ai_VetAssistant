"""Тесты моделей и repository пациентов/эпизодов (T-160.1).

Покрывают:
- CRUD карточек и изоляцию владельцев на уровне repository;
- нормализацию и валидацию полей;
- PATCH-семантику (отсутствующие поля не меняются, ``None`` очищает);
- сохранение эпизодов, пагинацию и семантический поиск на SQLite-фолбэке;
- каскадное удаление данных вместе с пользователем;
- соответствие ORM-моделей SQL-миграции для PostgreSQL.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, func, select
from sqlalchemy.dialects import postgresql, sqlite

from app.database import (
    MEMORY_EMBEDDING_DIM,
    Database,
    Episode,
    Patient,
    add_episode,
    count_episodes,
    create_patient,
    create_user,
    delete_user_account,
    get_patient,
    list_episodes,
    list_patients,
    search_similar_episodes,
    update_patient,
)
from configs.settings import PROJECT_ROOT


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'patients.db').as_posix()}")
    await db.create_tables()
    yield db
    await db.dispose()


@pytest.fixture
async def users(database: Database) -> tuple[int, int]:
    """Два пользователя для проверки мультитенантной изоляции."""
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


def _vector(index: int, *, tail: float = 0.0) -> list[float]:
    """Единичный вектор размерности эмбеддера с опциональным вторым весом."""
    values = [0.0] * MEMORY_EMBEDDING_DIM
    values[index] = 1.0
    values[(index + 1) % MEMORY_EMBEDDING_DIM] = tail
    return values


async def test_create_list_and_get_only_owner(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, other_id = users
    async with database.session() as session:
        first = await create_patient(
            session,
            user_id=owner_id,
            name="Бобик",
            species="dog",
        )
        second = await create_patient(
            session,
            user_id=owner_id,
            name="Мурка",
            species="cat",
        )
        foreign = await create_patient(
            session,
            user_id=other_id,
            name="Рекс",
            species="dog",
        )

    async with database.session() as session:
        owner_patients = await list_patients(session, user_id=owner_id)
        other_patients = await list_patients(session, user_id=other_id)
        assert [item.id for item in owner_patients] == [first.id, second.id]
        assert [item.name for item in other_patients] == ["Рекс"]

        assert await get_patient(
            session, user_id=owner_id, patient_id=foreign.id
        ) is None
        assert await get_patient(
            session, user_id=owner_id, patient_id=first.id
        ) is not None


async def test_create_patient_normalizes_fields(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, _ = users
    async with database.session() as session:
        patient = await create_patient(
            session,
            user_id=owner_id,
            name="  Бобик  ",
            species="dog",
            breed="  Корги  ",
            birth_date=date(2020, 5, 1),
            weight=12.5,
            known_allergies="  ",
            chronic_conditions="  артрит  ",
        )

    assert patient.name == "Бобик"
    assert patient.breed == "Корги"
    assert patient.weight == Decimal("12.5")
    assert patient.known_allergies is None
    assert patient.chronic_conditions == "артрит"
    assert patient.created_at is not None
    assert patient.updated_at is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "   "),
        ("name", "x" * 121),
        ("species", "hamster"),
        ("species", "DOG"),
        ("weight", 0),
        ("weight", -1),
        ("weight", 10000),
        ("birth_date", date.today() + timedelta(days=1)),
    ],
)
async def test_create_patient_rejects_invalid_fields(
    database: Database,
    users: tuple[int, int],
    field: str,
    value: object,
) -> None:
    owner_id, _ = users
    payload: dict[str, object] = {
        "user_id": owner_id,
        "name": "Бобик",
        "species": "dog",
    }
    payload[field] = value

    async with database.session() as session:
        with pytest.raises(ValueError):
            await create_patient(session, **payload)  # type: ignore[arg-type]


async def test_update_patient_is_partial_and_clears_optional_fields(
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
            breed="Корги",
            weight=10,
        )

    async with database.session() as session:
        updated = await update_patient(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            changes={"weight": 11.5, "breed": None, "chronic_conditions": "артрит"},
        )

    assert updated is not None
    assert updated.name == "Бобик"
    assert updated.species == "dog"
    assert updated.breed is None
    assert updated.weight == Decimal("11.5")
    assert updated.chronic_conditions == "артрит"
    assert updated.updated_at >= updated.created_at


async def test_update_patient_returns_none_for_foreign(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, other_id = users
    async with database.session() as session:
        patient = await create_patient(
            session,
            user_id=owner_id,
            name="Бобик",
            species="dog",
        )

    async with database.session() as session:
        assert (
            await update_patient(
                session,
                user_id=other_id,
                patient_id=patient.id,
                changes={"name": "Чужой"},
            )
            is None
        )

    async with database.session() as session:
        stored = await get_patient(
            session, user_id=owner_id, patient_id=patient.id
        )
    assert stored is not None
    assert stored.name == "Бобик"


async def test_add_episode_requires_owned_patient(
    database: Database,
    users: tuple[int, int],
) -> None:
    owner_id, other_id = users
    async with database.session() as session:
        patient = await create_patient(
            session,
            user_id=owner_id,
            name="Бобик",
            species="dog",
        )

    async with database.session() as session:
        with pytest.raises(LookupError):
            await add_episode(
                session,
                user_id=other_id,
                patient_id=patient.id,
                content="чужая запись",
            )

        episode = await add_episode(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            content="  Сыпь на животе, назначен осмотр  ",
            embedding=_vector(0),
        )

    assert episode.patient_id == patient.id
    assert episode.user_id == owner_id
    assert episode.type == "chat"
    assert episode.content == "Сыпь на животе, назначен осмотр"
    assert episode.embedding == _vector(0)


@pytest.mark.parametrize(
    ("content", "episode_type", "embedding"),
    [
        ("   ", "chat", None),
        ("x" * 501, "chat", None),
        ("текст", "unknown", None),
        ("текст", "chat", [0.0, 1.0]),
    ],
)
async def test_add_episode_validates_payload(
    database: Database,
    users: tuple[int, int],
    content: str,
    episode_type: str,
    embedding: list[float] | None,
) -> None:
    owner_id, _ = users
    async with database.session() as session:
        patient = await create_patient(
            session,
            user_id=owner_id,
            name="Бобик",
            species="dog",
        )

    async with database.session() as session:
        with pytest.raises(ValueError):
            await add_episode(
                session,
                user_id=owner_id,
                patient_id=patient.id,
                content=content,
                episode_type=episode_type,
                embedding=embedding,
            )


async def test_list_episodes_paginates_newest_first(
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
        )
        episodes = [
            await add_episode(
                session,
                user_id=owner_id,
                patient_id=patient.id,
                content=f"эпизод {index}",
                episode_type="manual",
            )
            for index in range(5)
        ]

    async with database.session() as session:
        first_page = await list_episodes(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            limit=2,
            offset=0,
        )
        second_page = await list_episodes(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            limit=2,
            offset=2,
        )
        total = await count_episodes(
            session,
            user_id=owner_id,
            patient_id=patient.id,
        )

    assert [item.id for item in first_page] == [episodes[4].id, episodes[3].id]
    assert [item.id for item in second_page] == [episodes[2].id, episodes[1].id]
    assert total == 5


async def test_search_similar_episodes_ranks_and_filters(
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
        )
        related = await add_episode(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            content="Сыпь на животе, обсудили аллергию",
            embedding=_vector(0, tail=0.05),
        )
        unrelated = await add_episode(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            content="Прививка от бешенства",
            embedding=_vector(2),
        )
        without_vector = await add_episode(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            content="Запись на приём",
        )

    async with database.session() as session:
        found = await search_similar_episodes(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            embedding=_vector(0),
        )

    assert [item.id for item in found] == [related.id]
    assert unrelated.id not in {item.id for item in found}
    assert without_vector.id not in {item.id for item in found}

    async with database.session() as session:
        excluded = await search_similar_episodes(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            embedding=_vector(0),
            exclude_ids=[related.id],
        )
    assert excluded == []


async def test_search_similar_episodes_respects_limit(
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
        )
        await add_episode(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            content="Сыпь, аллергия",
            embedding=_vector(0),
        )
        await add_episode(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            content="Зуд, дерматит",
            embedding=_vector(0, tail=0.2),
        )

    async with database.session() as session:
        found = await search_similar_episodes(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            embedding=_vector(0),
            limit=1,
        )

    assert len(found) == 1
    assert found[0].content == "Сыпь, аллергия"


async def test_deleting_user_removes_patients_and_episodes(
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
        )
        await add_episode(
            session,
            user_id=owner_id,
            patient_id=patient.id,
            content="Сыпь на животе",
            embedding=_vector(0),
        )

    async with database.session() as session:
        assert await delete_user_account(session, owner_id) is True
        await session.commit()

        patient_count = int(
            (
                await session.execute(
                    select(func.count()).select_from(Patient)
                )
            ).scalar_one()
        )
        episode_count = int(
            (
                await session.execute(
                    select(func.count()).select_from(Episode)
                )
            ).scalar_one()
        )

    assert patient_count == 0
    assert episode_count == 0


def test_embedding_uses_vector_on_postgres_and_json_on_sqlite() -> None:
    column_type = Episode.__table__.c.embedding.type

    postgres_type = column_type.dialect_impl(postgresql.dialect())
    sqlite_type = column_type.dialect_impl(sqlite.dialect())

    assert isinstance(postgres_type, Vector)
    assert postgres_type.dim == MEMORY_EMBEDDING_DIM
    assert isinstance(sqlite_type, JSON)


def test_embedding_comparator_supports_pgvector_cosine_distance() -> None:
    """T-170: базовым типом должен быть Vector, иначе нет cosine_distance."""
    comparator = Episode.embedding.comparator

    assert hasattr(comparator, "cosine_distance")
    distance = comparator.cosine_distance(_vector(0))
    compiled = str(distance.compile(dialect=postgresql.dialect()))
    assert "<=>" in compiled


def test_appointments_patient_migration_declares_fk() -> None:
    migration = (
        PROJECT_ROOT
        / "scripts"
        / "migrations"
        / "2026-11-17_appointments_patient.sql"
    ).read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS patient_id" in migration
    assert "REFERENCES patients(id) ON DELETE SET NULL" in migration
    assert "ix_appointments_patient_id" in migration


def test_migration_declares_pgvector_schema() -> None:
    migration = (
        PROJECT_ROOT / "scripts" / "migrations" / "2026-11-16_patients.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector;" in migration
    assert "CREATE TABLE IF NOT EXISTS patients" in migration
    assert "CREATE TABLE IF NOT EXISTS episodes" in migration
    assert "embedding   vector(384)" in migration
    assert "USING hnsw (embedding vector_cosine_ops)" in migration
    assert "REFERENCES users(id) ON DELETE CASCADE" in migration
    assert "REFERENCES patients(id) ON DELETE CASCADE" in migration
    assert "BEGIN;" in migration
    assert "COMMIT;" in migration
