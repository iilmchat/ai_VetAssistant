"""Тесты библиотеки промптов и миграции на `string.Template` (T-004)."""

from __future__ import annotations

from pathlib import Path

import pytest

from configs.prompts import PromptError, PromptRenderer, get_prompts, load_prompts

SEED_TEXT = "Парацетамол высокотоксичен для кошек даже в небольших дозах."


@pytest.fixture
def prompts() -> PromptRenderer:
    return get_prompts()


def test_repo_prompts_are_valid(prompts: PromptRenderer) -> None:
    assert prompts.version == 2, "миграция на $placeholders требует version: 2"
    assert "$topic" in prompts.stage_a.template
    assert "$seed_text" in prompts.stage_a.template
    assert "$user_query" in prompts.stage_b.template
    assert "$topic" in prompts.stage_b.template


def test_stage_a_substitutes_dollar_placeholders(prompts: PromptRenderer) -> None:
    rendered = prompts.render_stage_a(topic="toxicology", seed_text=SEED_TEXT)

    assert "toxicology" in rendered
    assert SEED_TEXT in rendered
    assert "$topic" not in rendered
    assert "$seed_text" not in rendered


def test_stage_b_substitutes_dollar_placeholders(prompts: PromptRenderer) -> None:
    rendered = prompts.render_stage_b(topic="gastroenterology", user_query="Кота рвёт второй день.")

    assert "gastroenterology" in rendered
    assert "Кота рвёт второй день." in rendered
    assert "$topic" not in rendered
    assert "$user_query" not in rendered


def test_stage_b_keeps_json_braces_intact(prompts: PromptRenderer) -> None:
    """Главная причина миграции: `str.format` упал бы на этом примере."""
    rendered = prompts.render_stage_b(topic="dermatology", user_query="Собака чешет ухо.")

    assert '{"role": "user", "content": "..."}' in rendered
    assert '{"role": "assistant", "content": "..."}' in rendered
    assert "[" in rendered and "]" in rendered


def test_stage_a_prompt_keeps_instructions(prompts: PromptRenderer) -> None:
    """Текст промпта не должен пострадать при миграции (RULES §5)."""
    rendered = prompts.render_stage_a(topic="urology", seed_text=SEED_TEXT)

    assert "Ты — имитатор реальных пользователей ветеринарного чата." in rendered
    assert "Верни только текст вопроса, без кавычек и пояснений." in rendered


def test_prompt_without_required_placeholder_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "version: 2\n"
        "stage_a:\n  template: 'Только тема: $topic'\n"
        "stage_b:\n  template: '$topic $user_query'\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptError, match="плейсхолдер"):
        load_prompts(path)


def test_prompt_with_unknown_placeholder_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "version: 2\n"
        "stage_a:\n  template: '$topic $seed_text $topik'\n"
        "stage_b:\n  template: '$topic $user_query'\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptError, match="topik"):
        load_prompts(path)


def test_broken_template_syntax_is_rejected(tmp_path: Path) -> None:
    """Одиночный `$` — синтаксическая ошибка `string.Template`."""
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "version: 2\n"
        "stage_a:\n  template: '$topic $seed_text — скидка 50$'\n"
        "stage_b:\n  template: '$topic $user_query'\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptError, match="синтаксис"):
        load_prompts(path)


def test_missing_stage_b_section_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "version: 2\nstage_a:\n  template: '$topic $seed_text'\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptError):
        load_prompts(path)


def test_missing_prompts_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="не найден"):
        load_prompts(tmp_path / "absent.yaml")


def test_non_mapping_yaml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text("- просто список\n", encoding="utf-8")

    with pytest.raises(PromptError, match="YAML-объект"):
        load_prompts(path)
