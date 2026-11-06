"""Тесты RAG-слоя FastAPI (T-026, T-141)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.knowledge import (
    ChromaKnowledgeBase,
    format_rag_context,
    get_knowledge_base,
    with_rag_context,
)


class _FakeEmbedding(list[float]):
    def tolist(self) -> list[float]:
        return list(self)


class _FakeModel:
    def encode(self, query: str, **kwargs: Any) -> _FakeEmbedding:
        return _FakeEmbedding([0.1, 0.2])


class _FakeCollection:
    """Минимальная замена Chroma-коллекции: заданный порядок векторов."""

    def __init__(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, str]],
        *,
        query_order: list[str] | None = None,
        get_error: Exception | None = None,
    ) -> None:
        self._ids = ids
        self._documents = documents
        self._metadatas = metadatas
        self._query_order = query_order or ids
        self._get_error = get_error

    def count(self) -> int:
        return len(self._ids)

    def get(self, include: list[str] | None = None) -> dict[str, Any]:
        if self._get_error is not None:
            raise self._get_error
        return {
            "ids": list(self._ids),
            "documents": list(self._documents),
            "metadatas": list(self._metadatas),
        }

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        selected = self._query_order[:n_results]
        indexes = [self._ids.index(item) for item in selected]
        return {
            "ids": [selected],
            "documents": [[self._documents[index] for index in indexes]],
            "metadatas": [[self._metadatas[index] for index in indexes]],
        }


def _hybrid_base(
    *,
    query_order: list[str] | None = None,
    mode: str = "hybrid",
    get_error: Exception | None = None,
    bm25_weight: float = 1.0,
) -> ChromaKnowledgeBase:
    collection = _FakeCollection(
        ["doc-a", "doc-b"],
        [
            "General information about dogs and cats.",
            "Xylitol toxicosis causes hypoglycemia in dogs.",
        ],
        [
            {"source": "general.txt", "title": "General"},
            {"source": "xylitol.txt", "title": "Xylitol Toxicosis"},
        ],
        query_order=query_order,
        get_error=get_error,
    )
    return ChromaKnowledgeBase(
        Path("unused"),
        collection_name="test",
        model_name="test",
        mode=mode,
        bm25_weight=bm25_weight,
        collection=collection,
        model=_FakeModel(),
    )


def test_format_rag_context_is_empty_for_empty_chunks() -> None:
    assert format_rag_context([]) == ""
    assert format_rag_context(["", "   "]) == ""


def test_format_rag_context_numbers_chunks() -> None:
    context = format_rag_context(["Первый факт.", "Второй факт."])

    assert context.startswith("Справочная информация из MSD Vet Manual:")
    assert "[1] Первый факт." in context
    assert "[2] Второй факт." in context


def test_with_rag_context_extends_existing_system_prompt() -> None:
    messages = [
        {"role": "system", "content": "Отвечай кратко."},
        {"role": "user", "content": "Вопрос"},
    ]

    result = with_rag_context(messages, ["Факт из справочника."])

    assert result[0]["role"] == "system"
    assert result[0]["content"].startswith("Отвечай кратко.")
    assert "Факт из справочника." in result[0]["content"]
    assert messages[0]["content"] == "Отвечай кратко."


def test_with_rag_context_adds_system_prompt_if_missing() -> None:
    result = with_rag_context([{"role": "user", "content": "Вопрос"}], ["Факт."])

    assert result[0]["role"] == "system"
    assert "Справочная информация из MSD Vet Manual" in result[0]["content"]
    assert result[1] == {"role": "user", "content": "Вопрос"}


def test_with_rag_context_returns_copy_for_empty_chunks() -> None:
    messages = [{"role": "user", "content": "Вопрос"}]

    result = with_rag_context(messages, [])

    assert result == messages
    assert result is not messages


def test_get_knowledge_base_returns_none_for_missing_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    get_knowledge_base.cache_clear()
    settings = SimpleNamespace(chroma_dir=tmp_path / "absent")
    monkeypatch.setattr("app.knowledge.get_app_settings", lambda: settings)

    assert get_knowledge_base() is None

    get_knowledge_base.cache_clear()


def test_vector_mode_follows_embedding_order() -> None:
    knowledge = _hybrid_base(mode="vector")

    chunks = knowledge.search_details("ксилитом", top_k=2)

    assert knowledge.mode == "vector"
    assert knowledge.bm25_size == 0
    assert [chunk.source for chunk in chunks] == ["general.txt", "xylitol.txt"]


def test_hybrid_mode_promotes_bm25_hit_over_vector_order() -> None:
    knowledge = _hybrid_base()

    chunks = knowledge.search_details("ксилитом", top_k=2)

    assert knowledge.mode == "hybrid"
    assert knowledge.bm25_size == 2
    # Вектор поставил general.txt первым, но BM25 нашёл xylitol.txt.
    assert chunks[0].source == "xylitol.txt"
    assert "hypoglycemia" in chunks[0].text


def test_hybrid_search_honours_top_k() -> None:
    knowledge = _hybrid_base()

    assert len(knowledge.search_details("собака", top_k=1)) == 1
    assert knowledge.search("собака", top_k=1)


def test_hybrid_falls_back_to_vector_when_corpus_unreadable() -> None:
    knowledge = _hybrid_base(get_error=RuntimeError("get() unavailable"))

    assert knowledge.mode == "vector"
    assert knowledge.bm25_size == 0
    chunks = knowledge.search_details("ксилитом", top_k=2)
    assert [chunk.source for chunk in chunks] == ["general.txt", "xylitol.txt"]


def test_empty_query_returns_nothing() -> None:
    knowledge = _hybrid_base()

    assert knowledge.search_details("   ") == []
    assert knowledge.search("") == []


def test_search_returns_plain_texts_for_rag_context() -> None:
    knowledge = _hybrid_base()

    chunks = knowledge.search("ксилитом", top_k=1)

    assert chunks == ["Xylitol toxicosis causes hypoglycemia in dogs."]
