"""Тесты сборки DPO-каркаса из оценок (T-155).

Покрывают:
- train/val 80/20 и детерминированность при повторном запуске;
- дедупликацию повторных оценок одного ``message_id``;
- фильтры по периоду, рейтингу и лимиту;
- режим готового JSONL (``--input``) без БД;
- отсутствие текстов и ``user_id`` в датасете (152-ФЗ);
- пустую БД, битый JSONL и коды выхода.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.database import Database, Feedback, create_user
from scripts.build_dpo_dataset import main, parse_args

USER_A = "owner@example.com"
USER_B = "other@example.com"


def _db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'dpo.db').as_posix()}"


async def _seed(database_url: str, rows: list[tuple[str, int, datetime]]) -> None:
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
            owners = (user_a.id, user_b.id)
            for index, (message_id, rating, created_at) in enumerate(rows):
                session.add(
                    Feedback(
                        user_id=owners[index % 2],
                        message_id=message_id,
                        rating=rating,
                        created_at=created_at,
                    )
                )
            await session.commit()
    finally:
        await database.dispose()


def _seed_sync(database_url: str, rows: list[tuple[str, int, datetime]]) -> None:
    import asyncio

    asyncio.run(_seed(database_url, rows))


def _rows(count: int = 10) -> list[tuple[str, int, datetime]]:
    return [
        (
            f"msg-{index:02d}",
            1 if index % 2 == 0 else -1,
            datetime(2026, 11, 1 + index % 5, 10, 0, tzinfo=UTC),
        )
        for index in range(count)
    ]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_build_dpo_dataset_writes_train_val_and_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = _db_url(tmp_path)
    _seed_sync(database_url, _rows(10))
    output_dir = tmp_path / "dpo"

    assert (
        main(
            [
                "--database-url",
                database_url,
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    train = _read_jsonl(output_dir / "train.jsonl")
    val = _read_jsonl(output_dir / "val.jsonl")
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))

    assert len(train) == 8
    assert len(val) == 2
    assert manifest["total"] == 10
    assert manifest["splits"] == {"train": 8, "val": 2}
    assert manifest["ratings"] == {"1": 5, "-1": 5}
    assert manifest["source"] == "database"
    assert manifest["period"]["from"].startswith("2026-11-01T")
    assert "Собрано записей: 10" in capsys.readouterr().err


def test_rows_have_only_message_id_rating_and_split(tmp_path: Path) -> None:
    """152-ФЗ: ни текстов, ни реальных ``user_id``, ни псевдонимов."""
    database_url = _db_url(tmp_path)
    _seed_sync(database_url, _rows(10))
    output_dir = tmp_path / "dpo"

    assert main(["--database-url", database_url, "--output-dir", str(output_dir)]) == 0

    for path in (output_dir / "train.jsonl", output_dir / "val.jsonl"):
        for record in _read_jsonl(path):
            assert set(record) == {"message_id", "rating", "split"}
            assert record["rating"] in (1, -1)
            assert record["split"] in ("train", "val")


def test_dataset_is_deterministic(tmp_path: Path) -> None:
    database_url = _db_url(tmp_path)
    _seed_sync(database_url, _rows(10))
    first = tmp_path / "first"
    second = tmp_path / "second"

    assert main(["--database-url", database_url, "--output-dir", str(first)]) == 0
    assert main(["--database-url", database_url, "--output-dir", str(second)]) == 0

    for name in ("train.jsonl", "val.jsonl"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_duplicate_message_id_keeps_latest_rating(tmp_path: Path) -> None:
    database_url = _db_url(tmp_path)
    _seed_sync(
        database_url,
        [
            ("msg-same", 1, datetime(2026, 11, 1, 10, 0, tzinfo=UTC)),
            ("msg-same", -1, datetime(2026, 11, 2, 10, 0, tzinfo=UTC)),
            ("msg-other", 1, datetime(2026, 11, 2, 11, 0, tzinfo=UTC)),
        ],
    )
    output_dir = tmp_path / "dpo"

    assert main(["--database-url", database_url, "--output-dir", str(output_dir)]) == 0

    records = _read_jsonl(output_dir / "train.jsonl") + _read_jsonl(
        output_dir / "val.jsonl"
    )
    assert len(records) == 2
    assert {record["message_id"] for record in records} == {"msg-same", "msg-other"}
    same = next(record for record in records if record["message_id"] == "msg-same")
    assert same["rating"] == -1
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["duplicates_dropped"] == 1
    assert manifest["total"] == 2


def test_filters_by_rating_and_period(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = _db_url(tmp_path)
    _seed_sync(database_url, _rows(10))
    output_dir = tmp_path / "dpo"

    assert (
        main(
            [
                "--database-url",
                database_url,
                "--rating",
                "-1",
                "--since",
                "2026-11-02",
                "--until",
                "2026-11-03",
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    records = _read_jsonl(output_dir / "train.jsonl") + _read_jsonl(
        output_dir / "val.jsonl"
    )
    assert records
    assert {record["rating"] for record in records} == {-1}
    assert capsys.readouterr().err


def test_limit_is_applied(tmp_path: Path) -> None:
    database_url = _db_url(tmp_path)
    _seed_sync(database_url, _rows(10))
    output_dir = tmp_path / "dpo"

    assert (
        main(
            [
                "--database-url",
                database_url,
                "--limit",
                "3",
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["total"] == 3


def test_empty_database_creates_empty_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = _db_url(tmp_path)
    _seed_sync(database_url, [])
    output_dir = tmp_path / "dpo"

    assert main(["--database-url", database_url, "--output-dir", str(output_dir)]) == 0

    assert (output_dir / "train.jsonl").read_text(encoding="utf-8") == ""
    assert (output_dir / "val.jsonl").read_text(encoding="utf-8") == ""
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["total"] == 0
    assert manifest["splits"] == {"train": 0, "val": 0}
    assert "Собрано записей: 0" in capsys.readouterr().err


def test_input_jsonl_mode_does_not_need_database(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "export.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(
                {
                    "message_id": f"msg-{index}",
                    "rating": 1 if index % 2 == 0 else -1,
                    "created_at": "2026-11-01T10:00:00Z",
                }
            )
            for index in range(5)
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "dpo"

    assert main(["--input", str(source), "--output-dir", str(output_dir)]) == 0

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == str(source)
    assert manifest["total"] == 5
    assert manifest["splits"] == {"train": 4, "val": 1}
    assert manifest["period"] is not None
    assert "Собрано записей: 5" in capsys.readouterr().err


def test_input_jsonl_skips_blank_lines(tmp_path: Path) -> None:
    source = tmp_path / "export.jsonl"
    source.write_text(
        '\n{"message_id": "msg-1", "rating": 1}\n\n',
        encoding="utf-8",
    )
    output_dir = tmp_path / "dpo"

    assert main(["--input", str(source), "--output-dir", str(output_dir)]) == 0
    assert len(_read_jsonl(output_dir / "train.jsonl")) == 1


def test_dry_run_does_not_write_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = _db_url(tmp_path)
    _seed_sync(database_url, _rows(4))
    output_dir = tmp_path / "dpo"

    assert (
        main(
            [
                "--database-url",
                database_url,
                "--output-dir",
                str(output_dir),
                "--dry-run",
            ]
        )
        == 0
    )

    assert not output_dir.exists()
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["total"] == 4
    assert manifest["splits"] == {"train": 3, "val": 1}


def test_input_and_database_url_are_mutually_exclusive(tmp_path: Path) -> None:
    source = tmp_path / "export.jsonl"
    source.write_text('{"message_id": "msg-1", "rating": 1}\n', encoding="utf-8")

    assert (
        main(
            [
                "--input",
                str(source),
                "--database-url",
                _db_url(tmp_path),
            ]
        )
        == 2
    )


@pytest.mark.parametrize(
    "line",
    [
        "not-json",
        '{"rating": 1}',
        '{"message_id": "", "rating": 1}',
        '{"message_id": "msg-1", "rating": 0}',
        '{"message_id": "msg-1", "rating": true}',
        '{"message_id": "' + "x" * 129 + '", "rating": 1}',
        '{"message_id": "msg-1", "rating": 1, "created_at": "not-a-date"}',
    ],
)
def test_invalid_input_jsonl_returns_2(
    line: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "broken.jsonl"
    source.write_text(line + "\n", encoding="utf-8")

    assert main(["--input", str(source), "--output-dir", str(tmp_path / "dpo")]) == 2
    assert "Ошибка чтения оценок" in capsys.readouterr().err


def test_missing_input_file_returns_2(tmp_path: Path) -> None:
    assert (
        main(
            [
                "--input",
                str(tmp_path / "missing.jsonl"),
                "--output-dir",
                str(tmp_path / "dpo"),
            ]
        )
        == 2
    )


@pytest.mark.parametrize("ratio", ["0", "1", "-0.5", "1.5"])
def test_invalid_train_ratio_returns_2(ratio: str, tmp_path: Path) -> None:
    source = tmp_path / "export.jsonl"
    source.write_text('{"message_id": "msg-1", "rating": 1}\n', encoding="utf-8")

    assert (
        main(
            [
                "--input",
                str(source),
                "--output-dir",
                str(tmp_path / "dpo"),
                "--train-ratio",
                ratio,
            ]
        )
        == 2
    )


def test_parse_args_defaults() -> None:
    args = parse_args([])

    assert args.database_url is None
    assert args.input is None
    assert args.train_ratio == 0.8
    assert args.seed == 42
    assert args.limit == 0
    assert args.dry_run is False


def test_single_record_stays_in_train(tmp_path: Path) -> None:
    database_url = _db_url(tmp_path)
    _seed_sync(
        database_url,
        [("msg-1", 1, datetime(2026, 11, 1, 10, 0, tzinfo=UTC))],
    )
    output_dir = tmp_path / "dpo"

    assert main(["--database-url", database_url, "--output-dir", str(output_dir)]) == 0

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["splits"] == {"train": 1, "val": 0}
