"""RAG-слой: локальная ChromaDB и контекст для FastAPI (T-026, T-141).

ChromaDB и sentence-transformers импортируются лениво: без установленных
RAG-зависимостей API продолжает работать без базы знаний.

С T-141 поиск умеет работать в двух режимах:

* ``vector`` — только эмбеддинги (поведение до T-141);
* ``hybrid`` — векторный top-N и BM25 top-N сливаются через Reciprocal Rank
  Fusion (см. :mod:`app.rag_hybrid`).

Режим задаётся настройкой ``VET_API_RAG_MODE``. Если BM25 не удалось
построить, база прозрачно деградирует до ``vector`` с предупреждением в лог.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from loguru import logger

from app.rag_hybrid import BM25Index, reciprocal_rank_fusion
from app.settings import get_app_settings


@dataclass(frozen=True)
class RetrievedChunk:
    """Найденный чанк и его источник (нужен для замеров hit rate)."""

    text: str
    source: str = ""


class KnowledgeBase(Protocol):
    """Интерфейс поиска по базе знаний (удобно подменять в тестах)."""

    def search(self, query: str, *, top_k: int = 3) -> list[str]: ...


def format_rag_context(chunks: Sequence[str]) -> str:
    """Собрать блок «Справочная информация...» из найденных чанков."""
    cleaned = [chunk.strip() for chunk in chunks if chunk.strip()]
    if not cleaned:
        return ""
    body = "\n\n".join(f"[{index}] {chunk}" for index, chunk in enumerate(cleaned, 1))
    return f"Справочная информация из MSD Vet Manual:\n\n{body}"


def with_rag_context(
    messages: Sequence[dict[str, str]],
    chunks: Sequence[str],
) -> list[dict[str, str]]:
    """Добавить RAG-контекст в system message (или создать его)."""
    context = format_rag_context(chunks)
    result = [dict(message) for message in messages]
    if not context:
        return result

    for index, message in enumerate(result):
        if message.get("role") == "system":
            content = message.get("content", "").strip()
            result[index] = {
                **message,
                "content": f"{content}\n\n{context}".strip(),
            }
            return result

    return [{"role": "system", "content": context}, *result]


class ChromaKnowledgeBase:
    """Поиск по локальной коллекции ChromaDB с эмбеддингами MiniLM.

    В гибридном режиме в память загружаются те же чанки, что лежат в
    коллекции, и по ним строится BM25. Индекс пересобирается при старте API:
    после ``scripts/ingest_knowledge.py`` сервис нужно перезапустить (см.
    DEPLOYMENT.md).
    """

    def __init__(
        self,
        path: Path,
        *,
        collection_name: str,
        model_name: str,
        top_k: int = 3,
        mode: str = "hybrid",
        candidates: int = 10,
        bm25_weight: float = 1.0,
        rrf_k: int = 60,
        collection: Any | None = None,
        model: Any | None = None,
    ) -> None:
        if collection is None:
            from chromadb import PersistentClient

            collection = PersistentClient(path=str(path)).get_collection(collection_name)
        if model is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_name)

        self._top_k = top_k
        self._mode = "hybrid" if mode == "hybrid" else "vector"
        self._candidates = max(candidates, top_k)
        self._bm25_weight = bm25_weight
        self._rrf_k = rrf_k
        self._collection = collection
        self._model = model

        self._documents: list[str] = []
        self._sources: list[str] = []
        self._index_by_id: dict[str, int] = {}
        self._bm25: BM25Index | None = None
        if self._mode == "hybrid":
            self._build_bm25()
        else:
            logger.info("RAG: режим поиска vector (BM25 выключен)")

    @property
    def count(self) -> int:
        """Сколько чанков лежит в коллекции."""
        return int(self._collection.count())

    @property
    def mode(self) -> str:
        """Фактический режим поиска: ``hybrid`` или ``vector``."""
        return self._mode

    @property
    def bm25_size(self) -> int:
        """Сколько чанков проиндексировано BM25 (0 в vector-режиме)."""
        return self._bm25.size if self._bm25 is not None else 0

    def search(self, query: str, *, top_k: int | None = None) -> list[str]:
        """Найти ближайшие чанки (тексты) в текущем режиме."""
        return [chunk.text for chunk in self.search_details(query, top_k=top_k)]

    def search_details(
        self,
        query: str,
        *,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """Найти чанки вместе с источниками (для оценки hit rate)."""
        if not query.strip():
            return []
        limit = top_k if top_k is not None else self._top_k
        if self._mode == "hybrid" and self._bm25 is not None:
            try:
                return self._hybrid_search(query, limit)
            except Exception as exc:  # pragma: no cover - защита от сбоев Chroma
                logger.warning(
                    "RAG: гибридный поиск не удался ({}), fallback на vector",
                    exc,
                )
        return self._vector_search(query, limit)

    def _build_bm25(self) -> None:
        """Загрузить чанки из коллекции и построить по ним BM25."""
        try:
            payload = self._collection.get(include=["documents", "metadatas"])
        except Exception as exc:
            logger.warning(
                "RAG: не удалось прочитать чанки для BM25 ({}), режим vector",
                exc,
            )
            self._mode = "vector"
            return

        ids = [str(item) for item in payload.get("ids") or []]
        documents = [str(item or "") for item in payload.get("documents") or []]
        metadatas = list(payload.get("metadatas") or [])
        if not documents:
            logger.warning("RAG: в коллекции нет документов, BM25 не построен")
            self._mode = "vector"
            return

        titles: list[str] = []
        for index, document in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) else None
            if not isinstance(metadata, dict):
                metadata = {}
            source = str(metadata.get("source") or "")
            title = str(metadata.get("title") or "")
            self._documents.append(document)
            self._sources.append(source)
            titles.append(title)
            if index < len(ids):
                self._index_by_id[ids[index]] = index

        started = time.perf_counter()
        self._bm25 = BM25Index(self._documents, titles=titles)
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "RAG: гибридный режим, BM25 по {} чанкам собран за {:.1f} мс",
            self._bm25.size,
            elapsed_ms,
        )

    def _vector_ids(self, query: str, limit: int) -> list[str]:
        """Идентификаторы top-N векторного поиска."""
        embedding = self._model.encode(query, normalize_embeddings=True)
        payload = self._collection.query(
            query_embeddings=[embedding.tolist()],
            n_results=min(limit, max(self.count, 1)),
            include=["documents"],
        )
        ids = (payload.get("ids") or [[]])[0]
        return [str(item) for item in ids if item]

    def _vector_search(self, query: str, limit: int) -> list[RetrievedChunk]:
        """Обычный поиск только по эмбеддингам."""
        embedding = self._model.encode(query, normalize_embeddings=True)
        payload = self._collection.query(
            query_embeddings=[embedding.tolist()],
            n_results=min(limit, max(self.count, 1)),
            include=["documents", "metadatas"],
        )
        documents = (payload.get("documents") or [[]])[0]
        metadatas = (payload.get("metadatas") or [[]])[0]
        chunks: list[RetrievedChunk] = []
        for index, document in enumerate(documents):
            if not document:
                continue
            metadata = metadatas[index] if index < len(metadatas) else None
            source = str((metadata or {}).get("source") or "") if metadata else ""
            chunks.append(RetrievedChunk(str(document), source))
        return chunks

    def _hybrid_search(self, query: str, limit: int) -> list[RetrievedChunk]:
        """Слить векторный и BM25-топ через RRF и вернуть top_k."""
        if self._bm25 is None:  # pragma: no cover - вызывается только при наличии
            return self._vector_search(query, limit)

        candidates = min(self._candidates, max(self.count, 1))
        vector_ranking = [
            self._index_by_id[item]
            for item in self._vector_ids(query, candidates)
            if item in self._index_by_id
        ]
        bm25_ranking = [
            index for index, _ in self._bm25.search(query, limit=candidates)
        ]
        fused = reciprocal_rank_fusion(
            [vector_ranking, bm25_ranking],
            k=self._rrf_k,
            weights=[1.0, self._bm25_weight],
        )
        return [
            RetrievedChunk(self._documents[index], self._sources[index])
            for index, _ in fused[:limit]
        ]


@lru_cache(maxsize=1)
def get_knowledge_base() -> KnowledgeBase | None:
    """FastAPI-зависимость: вернуть базу знаний или ``None``.

    ``None`` означает «работаем как раньше»: база не создана, пуста или
    RAG-зависимости не установлены.
    """
    settings = get_app_settings()
    path = settings.chroma_dir
    if not path.exists():
        logger.info("RAG: ChromaDB не найдена ({}), работа без базы знаний", path)
        return None

    try:
        knowledge = ChromaKnowledgeBase(
            path,
            collection_name=settings.chroma_collection,
            model_name=settings.embedding_model,
            top_k=settings.rag_top_k,
            mode=settings.rag_mode,
            candidates=settings.rag_candidates,
            bm25_weight=settings.rag_bm25_weight,
        )
        if knowledge.count == 0:
            logger.info("RAG: коллекция пуста, работа без базы знаний")
            return None
        logger.info(
            "RAG: загружено {} чанков из {} (режим {}, BM25: {})",
            knowledge.count,
            path,
            knowledge.mode,
            knowledge.bm25_size,
        )
        return knowledge
    except Exception as exc:
        logger.warning("RAG недоступен ({}), работа без базы знаний", exc)
        return None
