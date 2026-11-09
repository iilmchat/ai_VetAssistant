"""Тесты экспорта оценок в JSONL (T-150).

Покрывают:
- выгрузку всех оценок в stdout и в файл;
- фильтры по периоду (``--since``/``--until``), оценке и лимиту;
- псевдонимизацию ``user_id`` и обязательную соль для неё;
- отсутствие текстов диалогов в выгрузке (152-ФЗ);
- коды выхода и валидацию аргументов.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.database import Database, Feedback, create_user
from scripts.export_feedback import (
    PSEUDONYM_HEX_LEN,
    PSEUDONYM_PREFIX,
    PSEUDONYM_SALT_ENV,
    build_records,
    main,
    parse_args,
)

USER_A = "owner@example.com"
USER_B = "other@example.com"
SALT = "test-salt-please-change"


def _db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'export_feedback.db').as_posix()}"


async def _seed(database_url: str) -> dict[str, int]:
    """Четыре оценки двух пользователей в разные дни."""
    database = Database(database_url)
    try:
        await database.create_tables()
        async with database.session() as session:
            user_a = await create_user(
                session,
                email=USER_A,
                hashed_password="hash-a",
            )
            user_b = await create_user(
                session,
                email=USER_B,
                hashed_password="hash-b",
            )
            rows = (
                (user_a.id, "msg-a1", 1, datetime(2026, 11, 1, 10, 0, tzinfo=UTC)),
                (user_a.id, "msg-a2", -1, datetime(2026, 11, 2, 12, 30, tzinfo=UTC)),
                (user_b.id, "msg-b1", 1, datetime(2026, 11, 2, 23, 59, 59, tzinfo=UTC)),
                (user_b.id, "msg-b2", -1, datetime(2026, 11, 3, 0, 0, 0, tzinfo=UTC)),
            )
            for user_id, message_id, rating, created_at in rows:
                session.add(
                    Feedback(
                        user_id=user_id,
                        message_id=message_id,
                        rating=rating,
                        created_at=created_at,
                    )
                )
            await session.commit()
            return {"a": int(user_a.id), "b": int(user_b.id)}
    finally:
        await database.dispose()


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return _db_url(tmp_path)


@pytest.fixture
def seeded(database_url: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    monkeypatch.delenv(PSEUDONYM_SALT_ENV, raising=False)
    return _seed_sync(database_url)


def _seed_sync(database_url: str) -> dict[str, int]:
    import asyncio

    return asyncio.run(_seed(database_url))


def _exported(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    """Разобрать JSONL из stdout после запуска ``main``."""
    captured = capsys.readouterr()
    return [json.loads(line) for line in captured.out.splitlines() if line.strip()]


# --- stdout и состав записей -------------------------------------------------


def test_export_all_to_stdout(
    seeded: dict[str, int],
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--database-url", database_url]) == 0

    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines() if line.strip()]
    assert [record["message_id"] for record in records] == [
        "msg-a1",
        "msg-a2",
        "msg-b1",
        "msg-b2",
    ]
    assert [record["rating"] for record in records] == [1, -1, 1, -1]
    assert all(str(record["created_at"]).endswith("Z") for record in records)
    assert records[0]["created_at"] == "2026-11-01T10:00:00Z"
    assert "Выгружено оценок: 4" in captured.err


def test_export_has_no_message_text_and_no_user_id_by_default(
    seeded: dict[str, int],
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """152-ФЗ: в выгрузке только id сообщения, оценка и время."""
    assert main(["--database-url", database_url]) == 0

    for record in _exported(capsys):
        assert set(record) == {"message_id", "rating", "created_at"}


# --- фильтры -----------------------------------------------------------------


def test_export_filters_by_rating(
    seeded: dict[str, int],
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--database-url", database_url, "--rating", "-1"]) == 0
    records = _exported(capsys)

    assert [record["message_id"] for record in records] == ["msg-a2", "msg-b2"]
    assert {record["rating"] for record in records} == {-1}

    assert main(["--database-url", database_url, "--rating", "1"]) == 0
    positive = _exported(capsys)
    assert [record["message_id"] for record in positive] == ["msg-a1", "msg-b1"]


def test_export_filters_by_date_period(
    seeded: dict[str, int],
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--until`` датой включает весь день, следующий — уже нет."""
    assert (
        main(
            [
                "--database-url",
                database_url,
                "--since",
                "2026-11-02",
                "--until",
                "2026-11-02",
            ]
        )
        == 0
    )

    records = _exported(capsys)
    assert [record["message_id"] for record in records] == ["msg-a2", "msg-b1"]


def test_export_filters_by_datetime_period(
    seeded: dict[str, int],
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(
            [
                "--database-url",
                database_url,
                "--since",
                "2026-11-02T12:30:00Z",
                "--until",
                "2026-11-03T00:00:00Z",
            ]
        )
        == 0
    )

    assert [record["message_id"] for record in _exported(capsys)] == ["msg-a2", "msg-b1"]


def test_export_limit(
    seeded: dict[str, int],
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--database-url", database_url, "--limit", "2"]) == 0

    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines() if line.strip()]
    assert [record["message_id"] for record in records] == ["msg-a1", "msg-a2"]
    assert "Выгружено оценок: 2" in captured.err


def test_export_no_matching_rows(
    seeded: dict[str, int],
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # --since в будущем отсекает все строки.
    assert main(["--database-url", database_url, "--since", "2030-01-01"]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Выгружено оценок: 0" in captured.err


# --- файл и stdout ------------------------------------------------------------


def test_export_to_file(
    seeded: dict[str, int],
    database_url: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "exports" / "feedback.jsonl"

    assert main(["--database-url", database_url, "--output", str(output)]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert str(output) in captured.err

    lines = [line for line in output.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 4
    assert json.loads(lines[0])["message_id"] == "msg-a1"
    assert output.read_text(encoding="utf-8").endswith("\n")


def test_export_to_file_without_rows_creates_empty_file(
    seeded: dict[str, int],
    database_url: str,
    tmp_path: Path,
) -> None:
    output = tmp_path / "empty.jsonl"

    assert (
        main(
            [
                "--database-url",
                database_url,
                "--since",
                "2030-01-01",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    assert output.exists()
    assert output.read_text(encoding="utf-8") == ""


# --- псевдонимизация user_id --------------------------------------------------


def test_export_include_user_id_requires_salt(
    seeded: dict[str, int],
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(PSEUDONYM_SALT_ENV, raising=False)

    assert main(["--database-url", database_url, "--include-user-id"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert PSEUDONYM_SALT_ENV in captured.err


def test_export_include_user_id_pseudonymizes(
    seeded: dict[str, int],
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(PSEUDONYM_SALT_ENV, SALT)

    assert main(["--database-url", database_url, "--include-user-id"]) == 0
    records = _exported(capsys)

    expected_keys = {"message_id", "rating", "created_at", "user_id"}
    assert all(set(record) == expected_keys for record in records)
    pseudonyms = {str(record["user_id"]) for record in records}
    assert len(pseudonyms) == 2
    for pseudonym in pseudonyms:
        assert pseudonym.startswith(PSEUDONYM_PREFIX)
        assert len(pseudonym) == len(PSEUDONYM_PREFIX) + PSEUDONYM_HEX_LEN
    raw_ids = {str(value) for value in seeded.values()}
    assert pseudonyms.isdisjoint(raw_ids)

    # Детерминированный псевдоним: повторный запуск даёт те же значения.
    assert main(["--database-url", database_url, "--include-user-id"]) == 0
    again = _exported(capsys)
    assert [record["user_id"] for record in again] == [
        record["user_id"] for record in records
    ]


def test_pseudonymize_depends_on_salt() -> None:
    from scripts.export_feedback import pseudonymize

    assert pseudonymize(1, SALT) != pseudonymize(1, "another-salt")
    assert pseudonymize(1, SALT) == pseudonymize(1, SALT)
    assert pseudonymize(1, SALT) != pseudonymize(2, SALT)


def test_build_records_omits_user_id_without_flag() -> None:
    row = Feedback(
        user_id=42,
        message_id="msg-1",
        rating=1,
        created_at=datetime(2026, 11, 9, 9, 0, tzinfo=UTC),
    )

    records = build_records([row], include_user_id=False, salt=SALT)
    assert records == [
        {
            "message_id": "msg-1",
            "rating": 1,
            "created_at": "2026-11-09T09:00:00Z",
        }
    ]


# --- валидация аргументов -----------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--rating", "0"],
        ["--rating", "2"],
        ["--since", "not-a-date"],
        ["--until", "2026-13-40"],
        ["--limit", "-1"],
    ],
)
def test_export_rejects_invalid_arguments(
    argv: list[str],
    database_url: str,
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        parse_args(["--database-url", database_url, *argv])

    assert exc_info.value.code == 2


def test_parse_args_defaults(database_url: str) -> None:
    args = parse_args(["--database-url", database_url])

    assert args.since is None
    assert args.until is None
    assert args.rating is None
    assert args.limit == 0
    assert args.output is None
    assert args.include_user_id is False


def test_parse_args_until_date_covers_whole_day(database_url: str) -> None:
    args = parse_args(["--database-url", database_url, "--until", "2026-11-02"])

    assert args.until == datetime(2026, 11, 3, 0, 0, tzinfo=UTC)


def test_parse_args_since_date_is_midnight(database_url: str) -> None:
    args = parse_args(["--database-url", database_url, "--since", "2026-11-02"])

    assert args.since == datetime(2026, 11, 2, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_salt(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """По умолчанию соли нет — тесты выставляют её явно."""
    monkeypatch.delenv(PSEUDONYM_SALT_ENV, raising=False)
    yield
