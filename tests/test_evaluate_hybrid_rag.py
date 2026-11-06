"""Тесты метрик замера гибридного RAG (T-141)."""

from __future__ import annotations

from scripts.evaluate_hybrid_rag import (
    QUESTIONS,
    RetrievalResult,
    hit_rank,
    summarize,
)


def test_question_set_has_12_base_and_5_drug_questions() -> None:
    assert len(QUESTIONS) == 17
    assert len({question.id for question in QUESTIONS}) == 17
    assert [question.id for question in QUESTIONS][-5:] == [
        "drug-fomepizole",
        "drug-acetylcysteine",
        "drug-ivermectin",
        "drug-phenobarbital",
        "drug-levetiracetam",
    ]


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
