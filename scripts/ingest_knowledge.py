#!/usr/bin/env python
"""Индексация базы знаний в локальную ChromaDB (T-026, T-030, T-117).

Скрипт рекурсивно читает ``*.txt`` и ``*.pdf`` из ``data/knowledge/``,
режет текст на чанки по 500 символов, считает эмбеддинги через
sentence-transformers и сохраняет их в ``data/chroma_db``. PDF извлекаются
через ``pypdf``.

По умолчанию индекс обновляется инкрементально: коллекция не удаляется,
чанки записываются через ``upsert`` (совпадающие id обновляются, новые
добавляются). Полная пересборка с удалением коллекции — ``--rebuild``.
Модель эмбеддингов скачивается при первом запуске и кешируется HuggingFace.

Примеры::

    python scripts/ingest_knowledge.py --help
    python scripts/ingest_knowledge.py --dry-run
    python scripts/ingest_knowledge.py
    python scripts/ingest_knowledge.py --rebuild
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from data_pipeline.cli import configure_logging, positive_int

# Пути по умолчанию считаются от текущей рабочей директории: в контейнере это
# /app, поэтому получаются /app/data/knowledge и /app/data/chroma_db. От
# PROJECT_ROOT их считать нельзя — установленный пакет лежит в site-packages,
# где каталога data нет (T-119).
DEFAULT_KNOWLEDGE_DIR = Path.cwd() / "data" / "knowledge"
DEFAULT_CHROMA_DIR = Path.cwd() / "data" / "chroma_db"
DEFAULT_COLLECTION = "msd_vet_manual"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_CHUNK_SIZE = 500
DEFAULT_OVERLAP = 50
SUPPORTED_SUFFIXES = frozenset({".txt", ".pdf"})

#: Максимальная длина заголовка документа в метаданных (T-141).
TITLE_LIMIT = 200


@dataclass(frozen=True)
class KnowledgeChunk:
    """Один чанк справочника, готовый к индексации."""

    id: str
    text: str
    source: str
    title: str = ""


def document_title(text: str, *, fallback: str = "") -> str:
    """Заголовок документа для метаданных и BM25 (T-141).

    У статей MSD Vet Manual заголовок лежит в строке ``Title: ...`` после
    ``Source:``; у остальных файлов берётся первая содержательная строка.
    Служебные строки ``Source:``/``Downloaded:`` пропускаются. Длина
    ограничена :data:`TITLE_LIMIT` символами.
    """
    first_line = ""
    for line in text.splitlines()[:10]:
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith("title:"):
            value = stripped.split(":", 1)[1].strip()
            if value:
                return value[:TITLE_LIMIT]
            continue
        if lowered.startswith(("source:", "downloaded:")):
            continue
        if not first_line:
            first_line = stripped[:TITLE_LIMIT]
    return first_line or fallback[:TITLE_LIMIT]


def chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """Разбить текст на чанки не длиннее ``chunk_size`` символов.

    Границы по возможности выравниваются по пробелам; ``overlap`` задаёт
    перекрытие соседних чанков.

    Raises:
        ValueError: некорректные размеры чанка или перекрытия.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size должен быть >= 1")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap должен быть в диапазоне 0 <= overlap < chunk_size")

    normalized = " ".join(text.split())
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [normalized]

    chunks: list[str] = []
    start = 0
    length = len(normalized)

    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            break_at = normalized.rfind(" ", start, end)
            if break_at > start + chunk_size // 2:
                end = break_at

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break

        next_start = max(end - overlap, start + 1)
        if next_start < length:
            next_space = normalized.find(" ", next_start, end)
            if next_space != -1:
                next_start = next_space + 1
        start = next_start

    return chunks


def read_pdf(path: Path) -> str:
    """Извлечь текст из PDF через pypdf.

    Raises:
        ValueError: файл не удалось прочитать как PDF.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise ValueError(f"не удалось открыть PDF: {exc}") from exc

    pages: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            logger.warning("{}: страница {} не прочитана: {}", path, page_number, exc)
            continue
        if text.strip():
            pages.append(text)
    return "\n\n".join(pages).strip()


def read_document(path: Path) -> str:
    """Прочитать TXT или PDF."""
    if path.suffix.lower() == ".pdf":
        return read_pdf(path)
    return path.read_text(encoding="utf-8")


def load_documents(directory: Path) -> list[tuple[str, str]]:
    """Рекурсивно прочитать непустые TXT/PDF (относительный путь, текст)."""
    if not directory.exists():
        raise FileNotFoundError(f"Папка базы знаний не найдена: {directory}")
    if not directory.is_dir():
        raise FileNotFoundError(f"Ожидалась папка с текстами: {directory}")

    documents: list[tuple[str, str]] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        try:
            text = read_document(path).strip()
        except (OSError, ValueError) as exc:
            logger.warning("Пропущен {}: {}", path, exc)
            continue
        if text:
            source = path.relative_to(directory).as_posix()
            documents.append((source, text))
    return documents


def build_chunks(
    documents: Sequence[tuple[str, str]],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[KnowledgeChunk]:
    """Нарезать документы на чанки с уникальными id."""
    chunks: list[KnowledgeChunk] = []
    for source, text in documents:
        source_stem = Path(source).with_suffix("").as_posix().replace("/", "-")
        title = document_title(text, fallback=Path(source).stem)
        for index, chunk in enumerate(
            chunk_text(text, chunk_size=chunk_size, overlap=overlap),
            start=1,
        ):
            chunks.append(
                KnowledgeChunk(
                    id=f"{source_stem}-{index:04d}",
                    text=chunk,
                    source=source,
                    title=title,
                )
            )
    return chunks


def _existing_ids_count(collection: Any, ids: Sequence[str]) -> int | None:
    """Сколько из ``ids`` уже есть в коллекции (T-133).

    ``None`` — прочитать существующие id не удалось (старая версия chromadb
    или подменённая коллекция в тестах); тогда статистика новых чанков
    просто не выводится.
    """
    existing = 0
    try:
        for start in range(0, len(ids), 500):
            batch = list(ids[start : start + 500])
            result = collection.get(ids=batch, include=[])
            existing += len(result.get("ids") or [])
    except Exception as exc:
        logger.debug("Не удалось прочитать существующие id: {}", exc)
        return None
    return existing


def ingest_chunks(
    chunks: Sequence[KnowledgeChunk],
    *,
    chroma_dir: Path,
    collection_name: str,
    model_name: str,
    rebuild: bool = False,
) -> int:
    """Записать эмбеддинги чанков в ChromaDB.

    По умолчанию коллекция не удаляется: чанки пишутся через ``upsert``,
    поэтому уже собранный индекс дополняется и обновляется. При
    ``rebuild=True`` коллекция пересоздаётся с нуля.

    В лог пишется, сколько чанков новых, сколько обновлено и сколько всего
    стало в коллекции (T-133).
    """
    # Тяжёлые зависимости импортируются здесь: --dry-run и тесты не требуют
    # скачивать torch/sentence-transformers.
    from chromadb import PersistentClient
    from sentence_transformers import SentenceTransformer

    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = PersistentClient(path=str(chroma_dir))
    if rebuild:
        try:
            client.delete_collection(collection_name)
            logger.info("Старая коллекция {} удалена (--rebuild)", collection_name)
        except Exception:
            logger.debug("Коллекция {} ещё не существует", collection_name)

    # get_or_create: существующая коллекция сохраняется, новая создаётся.
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    model = SentenceTransformer(model_name)
    logger.info("Модель эмбеддингов загружена: {}", model_name)

    ids = [chunk.id for chunk in chunks]
    already_indexed = _existing_ids_count(collection, ids)
    if already_indexed is None:
        logger.info(
            "Новых чанков: неизвестно (не удалось прочитать существующие id) | к записи: {}",
            len(ids),
        )
    else:
        logger.info(
            "Новых чанков: {} | будет обновлено: {} | к записи: {}",
            len(ids) - already_indexed,
            already_indexed,
            len(ids),
        )

    batch_size = 64
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        embeddings = model.encode(
            [chunk.text for chunk in batch],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        collection.upsert(
            ids=[chunk.id for chunk in batch],
            documents=[chunk.text for chunk in batch],
            metadatas=[{"source": chunk.source, "title": chunk.title} for chunk in batch],
            embeddings=[vector.tolist() for vector in embeddings],
        )
        logger.info("Записано чанков: {}/{}", min(start + len(batch), len(chunks)), len(chunks))

    try:
        total_in_collection = collection.count()
    except Exception:  # pragma: no cover - зависит от версии chromadb
        total_in_collection = None
    if total_in_collection is not None:
        logger.info(
            "В коллекции {} теперь {} чанков",
            collection_name,
            total_in_collection,
        )

    return len(chunks)


def _non_negative_int(value: str) -> int:
    """argparse-тип: целое число >= 0."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"ожидалось целое число, получено {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("значение должно быть >= 0")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Индексация текстовой базы знаний в локальную ChromaDB.",
    )
    parser.add_argument(
        "--knowledge-dir",
        type=Path,
        default=DEFAULT_KNOWLEDGE_DIR,
        metavar="PATH",
        help=f"папка с *.txt/*.pdf, рекурсивно (по умолчанию {DEFAULT_KNOWLEDGE_DIR})",
    )
    parser.add_argument(
        "--chroma-dir",
        type=Path,
        default=DEFAULT_CHROMA_DIR,
        metavar="PATH",
        help=f"папка ChromaDB (по умолчанию {DEFAULT_CHROMA_DIR})",
    )
    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION,
        metavar="NAME",
        help=f"имя коллекции (по умолчанию {DEFAULT_COLLECTION})",
    )
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        metavar="ID",
        help=f"модель sentence-transformers (по умолчанию {DEFAULT_EMBEDDING_MODEL})",
    )
    parser.add_argument(
        "--chunk-size",
        type=positive_int,
        default=DEFAULT_CHUNK_SIZE,
        metavar="N",
        help=f"размер чанка в символах (по умолчанию {DEFAULT_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--overlap",
        type=_non_negative_int,
        default=DEFAULT_OVERLAP,
        metavar="N",
        help=f"перекрытие чанков в символах (по умолчанию {DEFAULT_OVERLAP})",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="удалить коллекцию и собрать индекс заново (по умолчанию upsert)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать файлы и чанки, не создавая ChromaDB",
    )
    args = parser.parse_args(argv)

    if args.overlap >= args.chunk_size:
        parser.error("--overlap должен быть меньше --chunk-size")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    try:
        documents = load_documents(args.knowledge_dir)
    except FileNotFoundError as exc:
        logger.error("{}", exc)
        return 1

    if not documents:
        logger.error("В {} нет непустых .txt/.pdf файлов", args.knowledge_dir)
        return 1

    chunks = build_chunks(
        documents,
        chunk_size=int(args.chunk_size),
        overlap=int(args.overlap),
    )
    logger.info(
        "Файлов: {} | чанков: {} | размер: {} | перекрытие: {}",
        len(documents),
        len(chunks),
        args.chunk_size,
        args.overlap,
    )

    if args.dry_run:
        for chunk in chunks[:5]:
            logger.info("DRY-RUN {} [{}]: {}", chunk.id, chunk.source, chunk.text[:120])
        return 0

    logger.info(
        "Режим: {}",
        "полная пересборка (--rebuild)"
        if args.rebuild
        else "инкрементальное обновление (upsert, коллекция сохраняется)",
    )

    try:
        count = ingest_chunks(
            chunks,
            chroma_dir=args.chroma_dir,
            collection_name=str(args.collection),
            model_name=str(args.embedding_model),
            rebuild=bool(args.rebuild),
        )
    except Exception as exc:
        logger.exception("Не удалось построить базу знаний: {}", exc)
        return 1

    logger.info("Готово: {} чанков в {}", count, args.chroma_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
