"""Тесты BM25, токенизации и RRF для гибридного RAG (T-141)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.rag_hybrid import (
    BM25Index,
    expand_query_terms,
    reciprocal_rank_fusion,
    tokenize,
    weight_query_terms,
)
from app.settings import AppSettings


def test_tokenize_lowercases_and_keeps_numbers() -> None:
    assert tokenize("Ксилитом отравилась собака, доза 1,5 г") == [
        "ксилитом",
        "отравилась",
        "собака",
        "доза",
        "1",
        "5",
        "г",
    ]


def test_tokenize_strips_latin_plural_only() -> None:
    assert tokenize("grapes doses signs cats") == ["grape", "dose", "sign", "cat"]
    # Кириллица не стеммится: окончания разбирает глоссарий.
    assert tokenize("собаки") == ["собаки"]


def test_expand_query_terms_translates_russian_drug_names() -> None:
    expanded = expand_query_terms(tokenize("отравление ксилитом"))

    assert "xylitol" in expanded
    assert "ксилитом" in expanded

    expanded = expand_query_terms(tokenize("доза фомепизола"))
    assert "fomepizole" in expanded


def test_expand_query_terms_does_not_match_short_keys_inside_words() -> None:
    """Ключ «кот» короче 4 символов, поэтому «который» не превращается в cat."""
    assert "cat" not in expand_query_terms(tokenize("который"))


def test_expand_query_terms_keeps_english_query_untouched() -> None:
    tokens = tokenize("xylitol toxicosis")

    assert expand_query_terms(tokens) == tokens


def test_bm25_finds_english_chunk_by_russian_query() -> None:
    documents = [
        "General care of dogs and cats.",
        "Xylitol toxicosis causes hypoglycemia and liver failure in dogs.",
        "Vaccination schedule for puppies.",
    ]
    index = BM25Index(documents)

    results = index.search("ксилитом", limit=2)

    assert results
    assert results[0][0] == 1


def test_bm25_without_glossary_does_not_match_translation() -> None:
    documents = ["Xylitol toxicosis in dogs.", "Vaccination schedule."]
    index = BM25Index(documents, glossary={})

    assert index.search("ксилитом") == []
    # Английский запрос работает и без глоссария.
    assert index.search("xylitol")[0][0] == 0


def test_bm25_returns_empty_for_empty_or_unknown_query() -> None:
    index = BM25Index(["Xylitol toxicosis in dogs."])

    assert index.search("") == []
    assert index.search("совершенно посторонние слова") == []
    assert index.size == 1


def test_bm25_title_tokens_are_weighted() -> None:
    index = BM25Index(
        ["Body text without the key term.", "Body text without the key term."],
        titles=["Ethylene Glycol Toxicosis", "Vaccination"],
    )

    results = index.search("ethylene glycol")

    assert results[0][0] == 0


def test_bm25_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError):
        BM25Index(["text"], k1=0)
    with pytest.raises(ValueError):
        BM25Index(["text"], b=1.5)


def test_reciprocal_rank_fusion_prefers_items_in_both_rankings() -> None:
    fused = reciprocal_rank_fusion([[0, 1], [1, 2]])

    assert [item for item, _ in fused][:2] == [1, 0]


def test_reciprocal_rank_fusion_applies_weights() -> None:
    fused = reciprocal_rank_fusion([[0], [1]], weights=[1.0, 5.0])

    assert [item for item, _ in fused] == [1, 0]


def test_reciprocal_rank_fusion_is_deterministic_for_ties() -> None:
    fused = reciprocal_rank_fusion([[3], [1]])

    assert [item for item, _ in fused] == [1, 3]


def test_reciprocal_rank_fusion_validates_weights() -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[0]], weights=[1.0, 2.0])


def test_weight_query_terms_downsizes_russian_tokens() -> None:
    weighted = dict(weight_query_terms(tokenize("ксилитом у собаки")))

    assert weighted["xylitol"] == 1.0
    assert weighted["dog"] == 1.0
    assert weighted["ксилитом"] == 0.25
    assert weighted["собаки"] == 0.25


def test_weight_query_terms_keeps_english_at_full_weight() -> None:
    weighted = dict(weight_query_terms(tokenize("xylitol dogs")))

    assert weighted == {"xylitol": 1.0, "dog": 1.0}


def test_rag_settings_defaults_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "VET_API_RAG_MODE",
        "VET_API_RAG_CANDIDATES",
        "VET_API_RAG_BM25_WEIGHT",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = AppSettings(_env_file=None)
    assert settings.rag_mode == "hybrid"
    assert settings.rag_candidates == 10
    assert settings.rag_bm25_weight == 1.0

    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, rag_mode="bm25")
