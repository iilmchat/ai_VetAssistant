"""Тесты метрик замера гибридного RAG (T-141)."""

from __future__ import annotations

from pathlib import Path

from scripts.evaluate_hybrid_rag import (
    QUESTIONS,
    RetrievalResult,
    hit_rank,
    summarize,
)


def test_question_set_has_12_base_5_drug_and_10_expansion_questions() -> None:
    assert len(QUESTIONS) == 27
    assert len({question.id for question in QUESTIONS}) == 27
    assert [question.id for question in QUESTIONS][-5:] == [
        "allergies-dogs",
        "ringworm-cats",
        "osteoarthritis-dogs",
        "ckd-dogs",
        "feline-asthma",
    ]


def test_expansion_questions_cover_new_topics_and_files() -> None:
    """T-156: у каждого нового вопроса есть статья в локальном корпусе."""
    expansion = QUESTIONS[17:]
    assert {question.topic for question in expansion} >= {
        "Стоматология",
        "Офтальмология",
        "Эндокринология",
        "Дерматология",
        "Ортопедия",
        "Нефрология",
        "Респираторные болезни",
    }
    knowledge_dir = Path(__file__).resolve().parents[1] / "data" / "knowledge" / "real"
    missing = [
        question.source
        for question in expansion
        if not (knowledge_dir / question.source).is_file()
    ]
    assert missing == []


def test_hit_rank_compares_by_basename() -> None:
    sources = ["real/msd_xylitol_toxicosis_dogs.txt", "real/other.txt"]

    assert hit_rank(sources, "msd_xylitol_toxicosis_dogs.txt") == 1
    assert hit_rank(sources, "real/msd_xylitol_toxicosis_dogs.txt") == 1
    assert hit_rank(sources, "msd_absent.txt") is None


def test_summarize_counts_hits_and_mrr() -> None:
    results = [
        RetrievalResult("q1", "t", "?", "a.txt", ["a.txt"], hit_rank=1, duration_ms=10),
        RetrievalResult("q2", "t", "?", "b.txt", ["x.txt"], hit_rank=None, duration_ms=30),
        RetrievalResult("q3", "t", "?", "c.txt", ["x.txt", "c.txt"], hit_rank=2, duration_ms=20),
    ]

    summary = summarize(results)

    assert summary["questions"] == 3
    assert summary["hits"] == 2
    assert summary["hit_rate"] == 2 / 3
    assert summary["mrr"] == (1 + 0.5) / 3
    assert summary["p95_ms"] == 30
    assert summary["avg_ms"] == 20
