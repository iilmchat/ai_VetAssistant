"""RAG-слой: локальная ChromaDB и контекст для FastAPI (T-026).

ChromaDB и sentence-transformers импортируются лениво: без установленных
RAG-зависимостей API продолжает работать без базы знаний.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from loguru import logger

from app.settings import get_app_settings


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
    """Поиск по локальной коллекции ChromaDB с эмбеддингами MiniLM."""

    def __init__(
        self,
        path: Path,
        *,
        collection_name: str,
        model_name: str,
        top_k: int = 3,
    ) -> None:
        from chromadb import PersistentClient
        from sentence_transformers import SentenceTransformer

        self._top_k = top_k
        self._collection = PersistentClient(path=str(path)).get_collection(collection_name)
        self._model = SentenceTransformer(model_name)

    @property
    def count(self) -> int:
        """Сколько чанков лежит в коллекции."""
        return int(self._collection.count())

    def search(self, query: str, *, top_k: int | None = None) -> list[str]:
        """Найти ближайшие чанки по эмбеддингу запроса."""
        limit = top_k if top_k is not None else self._top_k
        embedding = self._model.encode(query, normalize_embeddings=True)
        result = self._collection.query(
            query_embeddings=[embedding.tolist()],
            n_results=limit,
            include=["documents"],
        )
        documents = result.get("documents") or []
        if not documents:
            return []
        return [str(document) for document in documents[0] if document]


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
        )
        if knowledge.count == 0:
            logger.info("RAG: коллекция пуста, работа без базы знаний")
            return None
        logger.info("RAG: загружено {} чанков из {}", knowledge.count, path)
        return knowledge
    except Exception as exc:
        logger.warning("RAG недоступен ({}), работа без базы знаний", exc)
        return None
