"""Тесты индексации базы знаний (T-026, T-117)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from loguru import logger

from scripts.ingest_knowledge import (
    _existing_ids_count,
    build_chunks,
    chunk_text,
    document_title,
    ingest_chunks,
    load_documents,
    main,
    read_pdf,
)


def _install_fake_rag(
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing_ids: list[str] | None = None,
) -> tuple[list[dict[str, object]], list[str], object]:
    """Подменить chromadb/sentence-transformers, не скачивая torch."""
    upserts: list[dict[str, object]] = []
    deleted: list[str] = []

    class FakeCollection:
        def __init__(self) -> None:
            self.ids: list[str] = list(existing_ids or [])

        def get(
            self,
            ids: list[str],
            include: list[str] | None = None,
        ) -> dict[str, list[str]]:
            return {"ids": [item for item in ids if item in self.ids]}

        def count(self) -> int:
            return len(self.ids)

        def upsert(self, **kwargs: object) -> None:
            upserts.append(kwargs)
            batch_ids = kwargs.get("ids")
            if isinstance(batch_ids, list):
                for item in batch_ids:
                    if isinstance(item, str) and item not in self.ids:
                        self.ids.append(item)

    collection = FakeCollection()

    class FakeClient:
        def __init__(self, path: str) -> None:
            self.path = path

        def delete_collection(self, name: str) -> None:
            deleted.append(name)

        def get_or_create_collection(
            self,
            name: str,
            metadata: dict[str, str] | None = None,
        ) -> FakeCollection:
            assert metadata == {"hnsw:space": "cosine"}
            return collection

    class FakeVector(list[float]):
        def tolist(self) -> list[float]:
            return list(self)

    class FakeModel:
        def __init__(self, name: str) -> None:
            self.name = name

        def encode(self, texts: list[str], **kwargs: object) -> list[FakeVector]:
            return [FakeVector([0.1, 0.2]) for _ in texts]

    chromadb = types.ModuleType("chromadb")
    chromadb.PersistentClient = FakeClient  # type: ignore[attr-defined]
    sentence_transformers = types.ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = FakeModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "chromadb", chromadb)
    monkeypatch.setitem(sys.modules, "sentence_transformers", sentence_transformers)
    return upserts, deleted, collection


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


def test_load_documents_reads_nested_txt(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "article.txt").write_text("Реальный текст статьи", encoding="utf-8")

    documents = load_documents(tmp_path)

    assert documents == [("real/article.txt", "Реальный текст статьи")]


def test_load_documents_reads_pdf_via_pypdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "article.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(
        "scripts.ingest_knowledge.read_pdf",
        lambda path: f"Текст из {path.name}",
    )

    documents = load_documents(tmp_path)

    assert documents == [("article.pdf", "Текст из article.pdf")]


def test_read_pdf_extracts_real_text(tmp_path: Path) -> None:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    path = tmp_path / "article.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Paracetamol is toxic to cats.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    writer.write(path)

    assert "Paracetamol is toxic to cats." in read_pdf(path)


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


def test_build_chunks_includes_relative_path_in_id() -> None:
    chunks = build_chunks([("real/article.txt", "Текст статьи")])

    assert chunks[0].id == "real-article-0001"
    assert chunks[0].source == "real/article.txt"


def test_document_title_prefers_title_line() -> None:
    """T-141: заголовок из MSD-файла уходит в metadata и BM25."""
    text = (
        "Source: https://www.msdvetmanual.com/toxicology\n"
        "Title: Ethylene Glycol Toxicosis in Animals\n"
        "Downloaded: 2026-11-04\n\n"
        "All animals are susceptible..."
    )

    assert document_title(text) == "Ethylene Glycol Toxicosis in Animals"


def test_document_title_falls_back_to_first_content_line() -> None:
    assert (
        document_title("\n\nПарацетамол опасен для кошек.\nЕщё текст")
        == "Парацетамол опасен для кошек."
    )
    assert document_title("\n\n", fallback="article") == "article"


def test_build_chunks_keeps_document_title() -> None:
    chunks = build_chunks([("real/article.txt", "Title: Test\nBody text")])

    assert chunks[0].title == "Test"


def test_ingest_chunks_writes_title_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    upserts, _deleted, _collection = _install_fake_rag(monkeypatch)
    chunks = build_chunks([("real/article.txt", "Title: Xylitol\nXylitol text")])

    ingest_chunks(
        chunks,
        chroma_dir=tmp_path,
        collection_name="msd_vet_manual",
        model_name="fake-model",
    )

    assert upserts[0]["metadatas"] == [
        {"source": "real/article.txt", "title": "Xylitol"}
    ]


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


def test_ingest_chunks_upserts_without_deleting_existing_collection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """T-117: повторный ingest дополняет индекс, не удаляя коллекцию."""
    upserts, deleted, _collection = _install_fake_rag(monkeypatch)
    chunks = build_chunks([("real/article.txt", "Текст статьи")])

    count = ingest_chunks(
        chunks,
        chroma_dir=tmp_path,
        collection_name="msd_vet_manual",
        model_name="fake-model",
    )

    assert count == len(chunks) == 1
    assert deleted == []
    assert upserts[0]["ids"] == [chunks[0].id]
    assert upserts[0]["documents"] == [chunks[0].text]


def test_ingest_chunks_logs_new_chunks_without_touching_old_ones(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """T-133: в лог попадает, сколько чанков новых, а сколько обновится."""
    old_id = "real-article-0001"
    upserts, deleted, collection = _install_fake_rag(
        monkeypatch,
        existing_ids=[old_id],
    )
    chunks = build_chunks([("real/article.txt", "Обновлённый текст статьи")])
    messages: list[str] = []
    sink_id = logger.add(
        lambda message: messages.append(message),
        level="INFO",
        format="{message}",
    )

    try:
        ingest_chunks(
            chunks,
            chroma_dir=tmp_path,
            collection_name="msd_vet_manual",
            model_name="fake-model",
        )
    finally:
        logger.remove(sink_id)

    assert deleted == []
    assert chunks[0].id == old_id
    assert upserts
    assert any("Новых чанков: 0" in message for message in messages)
    assert any("будет обновлено: 1" in message for message in messages)
    assert collection.count() == 1


def test_existing_ids_count_returns_none_for_unreadable_collection() -> None:
    """Старая версия chromadb без get() не должна ломать ingest."""

    class BrokenCollection:
        def get(self, **kwargs: object) -> dict[str, list[str]]:
            raise RuntimeError("get() unavailable")

    assert _existing_ids_count(BrokenCollection(), ["a"]) is None


def test_existing_ids_count_counts_matches() -> None:
    class Collection:
        def get(
            self,
            ids: list[str],
            include: list[str] | None = None,
        ) -> dict[str, list[str]]:
            return {"ids": [item for item in ids if item.startswith("old")]}

    assert _existing_ids_count(Collection(), ["old-1", "new-1", "old-2"]) == 2


def test_ingest_chunks_rebuild_deletes_collection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """--rebuild — единственный режим, который удаляет коллекцию."""
    upserts, deleted, _collection = _install_fake_rag(monkeypatch)
    chunks = build_chunks([("real/article.txt", "Текст статьи")])

    ingest_chunks(
        chunks,
        chroma_dir=tmp_path,
        collection_name="msd_vet_manual",
        model_name="fake-model",
        rebuild=True,
    )

    assert deleted == ["msd_vet_manual"]
    assert upserts


def test_default_paths_are_relative_to_working_directory() -> None:
    """T-119: дефолты не зависят от site-packages установленного пакета."""
    from scripts import ingest_knowledge

    knowledge_dir = ingest_knowledge.DEFAULT_KNOWLEDGE_DIR
    chroma_dir = ingest_knowledge.DEFAULT_CHROMA_DIR
    assert knowledge_dir == Path.cwd() / "data" / "knowledge"
    assert chroma_dir == Path.cwd() / "data" / "chroma_db"
