"""Тесты индексации базы знаний (T-026)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ingest_knowledge import build_chunks, chunk_text, load_documents, main


def test_chunk_text_respects_max_size() -> None:
    text = " ".join(["слово"] * 300)

    chunks = chunk_text(text, chunk_size=200, overlap=20)

    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 200 for chunk in chunks)
    assert chunks[0].startswith("слово")


def test_chunk_text_short_text_is_single_chunk() -> None:
    assert chunk_text("Короткий текст.", chunk_size=500) == ["Короткий текст."]


def test_chunk_text_empty_text_returns_empty() -> None:
    assert chunk_text("   \n\n  ") == []


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(0, 0), (500, 500), (500, -1)],
)
def test_chunk_text_rejects_invalid_sizes(chunk_size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_text("текст", chunk_size=chunk_size, overlap=overlap)


def test_load_documents_reads_only_non_empty_txt(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Текст A", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Текст B", encoding="utf-8")
    (tmp_path / "empty.txt").write_text("   ", encoding="utf-8")
    (tmp_path / "ignore.md").write_text("Markdown", encoding="utf-8")

    documents = load_documents(tmp_path)

    assert [name for name, _ in documents] == ["a.txt", "b.txt"]


def test_build_chunks_ids_are_unique() -> None:
    documents = [
        ("paracetamol_cats.txt", "Факт о парацетамоле. " * 100),
        ("diarrhea_dogs.txt", "Факт о диарее. " * 100),
    ]

    chunks = build_chunks(documents, chunk_size=100, overlap=10)

    ids = [chunk.id for chunk in chunks]
    assert ids
    assert len(ids) == len(set(ids))
    assert all(chunk.source in {"paracetamol_cats.txt", "diarrhea_dogs.txt"} for chunk in chunks)
    assert all(chunk.text for chunk in chunks)


def test_dry_run_reads_documents_without_chroma(tmp_path: Path) -> None:
    (tmp_path / "fact.txt").write_text(
        "Парацетамол опасен для кошек. " * 30,
        encoding="utf-8",
    )

    exit_code = main(["--knowledge-dir", str(tmp_path), "--dry-run"])

    assert exit_code == 0


def test_dry_run_reports_missing_directory(tmp_path: Path) -> None:
    directory = tmp_path / "absent"

    exit_code = main(["--knowledge-dir", str(directory), "--dry-run"])

    assert exit_code == 1
