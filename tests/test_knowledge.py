"""Тесты RAG-слоя FastAPI (T-026)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.knowledge import format_rag_context, get_knowledge_base, with_rag_context


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
