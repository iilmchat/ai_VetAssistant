#!/usr/bin/env python
"""Замер hit rate RAG-поиска до/после гибридного режима (T-141).

Скрипт измеряет **поиск**, а не ответ модели: для каждого вопроса проверяет,
попал ли ожидаемый источник (статья MSD) в top_k выданных чанков. Это
позволяет сравнивать режимы между собой без ожидания генерации.

Режимы:

* ``bm25`` — локальный BM25 по ``data/knowledge/`` без ChromaDB и без
  sentence-transformers. Работает офлайн и служит базой для проверки
  русско-английского глоссария (``--no-expand`` отключает расширение).
* ``vector`` — только эмбеддинги ChromaDB (поведение до T-141).
* ``hybrid`` — вектор + BM25 через RRF (новый режим).
* ``both`` — vector и hybrid подряд на одном индексе.

Примеры::

    # офлайн: BM25 с глоссарием и без, на локальном корпусе
    python scripts/evaluate_hybrid_rag.py --mode bm25
    python scripts/evaluate_hybrid_rag.py --mode bm25 --no-expand
    # то же через модуль (T-147): работает из любой директории
    python -m scripts.evaluate_hybrid_rag --mode bm25

    # на сервере, внутри контейнера api: до/после на реальном индексе
    docker compose -f docker-compose.edge.yml exec api \\
      python scripts/evaluate_hybrid_rag.py --mode both \\
        --chroma-dir /app/data/chroma_db \\
        --output /app/data/rag_hybrid_eval_results.json
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

# T-147: при `python scripts/evaluate_hybrid_rag.py` в sys.path попадает
# только scripts/, поэтому `import app` и `import scripts` падают. Добавляем
# корень репозитория — скрипт работает и напрямую, и через `python -m`.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rag_hybrid import RU_EN_TERMS, BM25Index
from scripts.evaluate_rag import QUESTIONS as BASE_QUESTIONS
from scripts.ingest_knowledge import build_chunks, load_documents

DEFAULT_KNOWLEDGE_DIR = Path("data") / "knowledge"
DEFAULT_CHROMA_DIR = Path("data") / "chroma_db"
DEFAULT_OUTPUT = Path("data") / "rag_hybrid_eval_results.json"
DEFAULT_COLLECTION = "msd_vet_manual"
DEFAULT_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
DEFAULT_TOP_K = 3
DEFAULT_CANDIDATES = 10


@dataclass(frozen=True)
class EvalQuestion:
    """Вопрос и статья, которая обязана попасть в top_k."""

    id: str
    topic: str
    question: str
    source: str


#: 12 вопросов T-133 + 5 новых с точными названиями препаратов (T-141).
QUESTIONS: tuple[EvalQuestion, ...] = (
    *tuple(
        EvalQuestion(
            id=item.id,
            topic=item.topic,
            question=item.question,
            source=item.source,
        )
        for item in BASE_QUESTIONS
    ),
    EvalQuestion(
        id="drug-fomepizole",
        topic="Антифриз",
        question="Чем лечат отравление антифризом у кошек — фомепизол или этанол?",
        source="msd_ethylene_glycol_toxicosis_animals.txt",
    ),
    EvalQuestion(
        id="drug-acetylcysteine",
        topic="Парацетамол",
        question="Какой антидот применяют при отравлении парацетамолом у кошек?",
        source="msd_toxicoses_from_human_analgesics.txt",
    ),
    EvalQuestion(
        id="drug-ivermectin",
        topic="Дирофиляриоз",
        question=(
            "Какие препараты, включая ивермектин, применяют для профилактики "
            "дирофиляриоза у собак?"
        ),
        source="msd_heartworm_dogs_cats_ferrets.txt",
    ),
    EvalQuestion(
        id="drug-phenobarbital",
        topic="Эпилепсия",
        question="Какие дозы фенобарбитала используют при эпилепсии у собак?",
        source="msd_epilepsy_seizures_small_animals.txt",
    ),
    EvalQuestion(
        id="drug-levetiracetam",
        topic="Эпилепсия",
        question="Какая доза леветирацетама при эпилепсии у собак и кошек?",
        source="msd_epilepsy_seizures_small_animals.txt",
    ),
    # T-156: узкие темы расширенной базы.
    EvalQuestion(
        id="dental-dogs",
        topic="Стоматология",
        question="Почему у собаки воспаляются дёсны и образуется зубной камень?",
        source="msd_dental_disorders_dogs.txt",
    ),
    EvalQuestion(
        id="dental-cats",
        topic="Стоматология",
        question="Какие болезни зубов и дёсен бывают у кошек?",
        source="msd_dental_disorders_cats.txt",
    ),
    EvalQuestion(
        id="glaucoma-dogs",
        topic="Офтальмология",
        question="Какие симптомы глаукомы у собаки и как её лечат?",
        source="msd_glaucoma_dogs.txt",
    ),
    EvalQuestion(
        id="thyroid-dogs",
        topic="Эндокринология",
        question="Признаки гипотиреоза у собак и лечение щитовидной железы",
        source="msd_thyroid_disorders_dogs.txt",
    ),
    EvalQuestion(
        id="thyroid-cats",
        topic="Эндокринология",
        question="Чем лечат гипертиреоз у кошек?",
        source="msd_thyroid_disorders_cats.txt",
    ),
    EvalQuestion(
        id="allergies-dogs",
        topic="Дерматология",
        question="Что вызывает аллергию и зуд у собаки?",
        source="msd_allergies_dogs.txt",
    ),
    EvalQuestion(
        id="ringworm-cats",
        topic="Дерматология",
        question="Как распознать лишай (дерматофитоз) у кошки?",
        source="msd_ringworm_cats.txt",
    ),
    EvalQuestion(
        id="osteoarthritis-dogs",
        topic="Ортопедия",
        question="Как лечат остеоартроз и боль в суставах у собак?",
        source="msd_osteoarthritis_dogs.txt",
    ),
    EvalQuestion(
        id="ckd-dogs",
        topic="Нефрология",
        question="Какие симптомы хронической болезни почек у собаки?",
        source="msd_chronic_kidney_disease_dogs.txt",
    ),
    EvalQuestion(
        id="feline-asthma",
        topic="Респираторные болезни",
        question="Какие признаки астмы и бронхита у кошек?",
        source="msd_feline_asthma_bronchitis.txt",
    ),
)


@dataclass
class RetrievalResult:
    """Результат поиска по одному вопросу в одном режиме."""

    question_id: str
    topic: str
    question: str
    expected_source: str
    retrieved_sources: list[str] = field(default_factory=list)
    hit_rank: int | None = None
    duration_ms: float = 0.0

    @property
    def hit(self) -> bool:
        return self.hit_rank is not None


def _source_name(value: str) -> str:
    """Сравнивать источники по имени файла: ``real/x.txt`` == ``x.txt``."""
    return Path(value).name


def hit_rank(sources: list[str], expected: str) -> int | None:
    """Позиция (с 1) первого чанка из ожидаемой статьи или ``None``."""
    expected_name = _source_name(expected)
    for index, source in enumerate(sources, start=1):
        if _source_name(source) == expected_name:
            return index
    return None


def _percentile(values: list[float], fraction: float) -> float:
    """Простой p95 без numpy: ближайший ранг сверху."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(math.ceil(fraction * len(ordered)) - 1, 0)
    return ordered[index]


def summarize(results: list[RetrievalResult]) -> dict[str, Any]:
    """Агрегаты режима: hit rate, MRR, среднее и p95 времени."""
    total = len(results)
    hits = sum(1 for item in results if item.hit)
    mrr = sum(1 / item.hit_rank for item in results if item.hit_rank) / total if total else 0.0
    durations = [item.duration_ms for item in results]
    return {
        "questions": total,
        "hits": hits,
        "hit_rate": (hits / total) if total else None,
        "mrr": mrr,
        "avg_ms": (sum(durations) / total) if total else 0.0,
        "p95_ms": _percentile(durations, 0.95),
    }


def _local_bm25_results(
    questions: tuple[EvalQuestion, ...],
    *,
    knowledge_dir: Path,
    top_k: int,
    expand: bool,
) -> list[RetrievalResult]:
    """BM25 по локальному корпусу без ChromaDB и модели эмбеддингов."""
    documents = load_documents(knowledge_dir)
    chunks = build_chunks(documents)
    index = BM25Index(
        [chunk.text for chunk in chunks],
        titles=[chunk.title for chunk in chunks],
        glossary=RU_EN_TERMS if expand else {},
    )
    logger.info(
        "BM25: {} чанков, расширение запроса {}",
        len(chunks),
        "включено" if expand else "выключено",
    )

    results: list[RetrievalResult] = []
    for question in questions:
        started = time.perf_counter()
        ranked = index.search(question.question, limit=top_k, expand=expand)
        duration_ms = (time.perf_counter() - started) * 1000
        sources = [chunks[position].source for position, _ in ranked]
        results.append(
            RetrievalResult(
                question_id=question.id,
                topic=question.topic,
                question=question.question,
                expected_source=question.source,
                retrieved_sources=sources,
                hit_rank=hit_rank(sources, question.source),
                duration_ms=duration_ms,
            )
        )
    return results


def _chroma_results(
    questions: tuple[EvalQuestion, ...],
    *,
    mode: str,
    chroma_dir: Path,
    collection_name: str,
    embedding_model: str,
    top_k: int,
    candidates: int,
    bm25_weight: float,
) -> list[RetrievalResult]:
    """Поиск по реальному индексу ChromaDB в режиме ``vector``/``hybrid``."""
    from app.knowledge import ChromaKnowledgeBase

    knowledge = ChromaKnowledgeBase(
        chroma_dir,
        collection_name=collection_name,
        model_name=embedding_model,
        top_k=top_k,
        mode=mode,
        candidates=candidates,
        bm25_weight=bm25_weight,
    )
    logger.info(
        "ChromaDB: {} чанков, фактический режим {}, BM25 {} чанков",
        knowledge.count,
        knowledge.mode,
        knowledge.bm25_size,
    )

    results: list[RetrievalResult] = []
    for question in questions:
        started = time.perf_counter()
        chunks = knowledge.search_details(question.question, top_k=top_k)
        duration_ms = (time.perf_counter() - started) * 1000
        sources = [chunk.source for chunk in chunks]
        results.append(
            RetrievalResult(
                question_id=question.id,
                topic=question.topic,
                question=question.question,
                expected_source=question.source,
                retrieved_sources=sources,
                hit_rank=hit_rank(sources, question.source),
                duration_ms=duration_ms,
            )
        )
    return results


def render_markdown(
    summaries: dict[str, dict[str, Any]],
    results_by_mode: dict[str, list[RetrievalResult]],
) -> str:
    """Markdown-отчёт: сводка по режимам + позиции по вопросам."""
    lines = [
        "# RAG hybrid eval — hit rate поиска (T-141)",
        "",
        "## Сводка",
        "",
        "| Режим | Вопросов | Hit | Hit rate | MRR | Среднее, мс | p95, мс |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, summary in summaries.items():
        rate = summary["hit_rate"]
        rate_text = f"{rate:.1%}" if isinstance(rate, float) else "n/a"
        lines.append(
            f"| {mode} | {summary['questions']} | {summary['hits']} | "
            f"{rate_text} | {summary['mrr']:.3f} | {summary['avg_ms']:.1f} | "
            f"{summary['p95_ms']:.1f} |"
        )

    modes = list(results_by_mode)
    header = "| # | Тема | Вопрос | Ожидаемый источник | " + " | ".join(
        f"rank {mode}" for mode in modes
    ) + " |"
    separator = "|---|---|---|---|" + "---|" * len(modes)
    lines.extend(["", "## Позиции по вопросам", "", header, separator])
    for index, question in enumerate(QUESTIONS, start=1):
        cells = []
        for mode in modes:
            result = next(
                (
                    item
                    for item in results_by_mode[mode]
                    if item.question_id == question.id
                ),
                None,
            )
            if result is None or result.hit_rank is None:
                cells.append("—")
            else:
                cells.append(str(result.hit_rank))
        lines.append(
            f"| {index} | {question.topic} | {question.question} | "
            f"`{question.source}` | " + " | ".join(cells) + " |"
        )
    lines.append("")
    lines.append(
        "Hit — ожидаемая статья попала в top_k поиска; rank — её позиция "
        "(1 = первый чанк). Замеряется поиск, а не ответ модели: генерация "
        "для сравнения режимов не нужна."
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Замерить hit rate RAG-поиска: vector vs hybrid (T-141).",
    )
    parser.add_argument(
        "--mode",
        choices=("bm25", "vector", "hybrid", "both"),
        default="bm25",
        help="Что мерить: локальный BM25, ChromaD-vector, hybrid или оба (по умолчанию bm25)",
    )
    parser.add_argument(
        "--knowledge-dir",
        type=Path,
        default=DEFAULT_KNOWLEDGE_DIR,
        help=f"Корпус для режима bm25 (по умолчанию {DEFAULT_KNOWLEDGE_DIR})",
    )
    parser.add_argument(
        "--chroma-dir",
        type=Path,
        default=DEFAULT_CHROMA_DIR,
        help=f"Индекс ChromaDB (по умолчанию {DEFAULT_CHROMA_DIR})",
    )
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="Имя коллекции")
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Модель эмбеддингов",
    )
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Сколько чанков")
    parser.add_argument(
        "--candidates",
        type=int,
        default=DEFAULT_CANDIDATES,
        help="Кандидатов на канал до RRF",
    )
    parser.add_argument(
        "--bm25-weight",
        type=float,
        default=1.0,
        help="Вес BM25 в RRF",
    )
    parser.add_argument(
        "--no-expand",
        action="store_true",
        help="Отключить русско-английский глоссарий (только для --mode bm25)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSON с результатами (по умолчанию {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=None,
        help="Дополнительно сохранить markdown-отчёт",
    )
    parser.add_argument("--dry-run", action="store_true", help="Показать вопросы и выйти")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    if args.dry_run:
        for index, question in enumerate(QUESTIONS, start=1):
            print(f"{index:2d}. [{question.topic}] {question.question}  <{question.source}>")
        print(f"\nВсего вопросов: {len(QUESTIONS)} (замеры не выполнялись)")
        return 0

    results_by_mode: dict[str, list[RetrievalResult]] = {}
    started = time.perf_counter()

    chroma_ready = (args.chroma_dir / "chroma.sqlite3").exists()
    if args.mode in {"vector", "hybrid", "both"} and not chroma_ready:
        print(
            f"Ошибка: нет индекса ChromaDB в {args.chroma_dir}. "
            "Режимы vector/hybrid требуют собранный индекс "
            "(scripts/ingest_knowledge.py) и sentence-transformers.",
            file=sys.stderr,
        )
        return 2

    if args.mode == "bm25":
        expand = not args.no_expand
        results_by_mode["bm25+glossary" if expand else "bm25"] = _local_bm25_results(
            QUESTIONS,
            knowledge_dir=args.knowledge_dir,
            top_k=args.top_k,
            expand=expand,
        )

    if args.mode in {"vector", "hybrid", "both"}:
        modes = ("vector", "hybrid") if args.mode == "both" else (args.mode,)
        for mode in modes:
            results_by_mode[mode] = _chroma_results(
                QUESTIONS,
                mode=mode,
                chroma_dir=args.chroma_dir,
                collection_name=args.collection,
                embedding_model=args.embedding_model,
                top_k=args.top_k,
                candidates=args.candidates,
                bm25_weight=args.bm25_weight,
            )

    summaries = {mode: summarize(items) for mode, items in results_by_mode.items()}
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "questions": len(QUESTIONS),
        "top_k": args.top_k,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "summaries": summaries,
        "results": {
            mode: [asdict(item) for item in items]
            for mode, items in results_by_mode.items()
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Результаты сохранены: {args.output}")

    markdown = render_markdown(summaries, results_by_mode)
    if args.markdown_out is not None:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown + "\n", encoding="utf-8", newline="\n")
        print(f"Markdown-отчёт сохранён: {args.markdown_out}")
    print()
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
