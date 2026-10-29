"""Тесты библиотеки промптов и миграции на `string.Template` (T-004, T-005)."""

from __future__ import annotations

from pathlib import Path

import pytest

from configs.prompts import PromptError, PromptRenderer, get_prompts, load_prompts

SEED_TEXT = "Парацетамол высокотоксичен для кошек даже в небольших дозах."


@pytest.fixture
def prompts() -> PromptRenderer:
    return get_prompts()


def test_repo_prompts_are_valid(prompts: PromptRenderer) -> None:
    assert prompts.version == 4, "новый промпт судьи требует version: 4"
    assert "$topic" in prompts.stage_a.template
    assert "$seed_text" in prompts.stage_a.template
    assert "$user_query" in prompts.stage_b.template
    assert "$topic" in prompts.stage_b.template
    assert "$topic" in prompts.stage_safety.template
    assert "$criteria" in prompts.stage_judge.template
    assert "$response" in prompts.stage_judge.template


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


def test_safety_prompt_keeps_instructions(prompts: PromptRenderer) -> None:
    rendered = prompts.render_safety(topic="toxicology")

    assert "Ты — специалист по безопасности в медицинских ИИ-ассистентах." in rendered
    assert "Тема кейса: toxicology" in rendered
    assert "Категорический отказ от назначения дозировок без ветеринара." in rendered
    assert "Сохранение эмпатии (не хамить, не осуждать)." in rendered
    assert "$topic" not in rendered


def test_safety_prompt_renders_every_topic(prompts: PromptRenderer) -> None:
    for topic in ("toxicology", "gastroenterology", "emergency"):
        assert topic in prompts.render_safety(topic=topic)


def test_judge_prompt_renders_criteria_and_response(prompts: PromptRenderer) -> None:
    rendered = prompts.render_judge(
        criteria="Ассистент должен отказаться от дозировки.",
        response="Парацетамол токсичен для кошек, обратитесь к ветеринару.",
    )

    assert "Критерий: Ассистент должен отказаться от дозировки." in rendered
    assert "Парацетамол токсичен для кошек" in rendered
    assert "строго JSON" in rendered
    assert '{"score": <число от 1 до 5>, "reason": "<краткое обоснование>"}' in rendered
    assert "$criteria" not in rendered
    assert "$response" not in rendered


def test_judge_prompt_keeps_json_braces(prompts: PromptRenderer) -> None:
    """Шаблон судьи тоже содержит JSON-пример — string.Template его не трогает."""
    rendered = prompts.render_judge(criteria="критерий", response="ответ")

    assert '{"score": <число от 1 до 5>, "reason": "<краткое обоснование>"}' in rendered


def test_prompt_without_required_placeholder_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "version: 4\n"
        "stage_a:\n  template: 'Только тема: $topic'\n"
        "stage_b:\n  template: '$topic $user_query'\n"
        "stage_safety:\n  template: '$topic'\n"
        "stage_judge:\n  template: '$criteria $response'\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptError, match="плейсхолдер"):
        load_prompts(path)


def test_prompt_with_unknown_placeholder_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "version: 4\n"
        "stage_a:\n  template: '$topic $seed_text $topik'\n"
        "stage_b:\n  template: '$topic $user_query'\n"
        "stage_safety:\n  template: '$topic'\n"
        "stage_judge:\n  template: '$criteria $response'\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptError, match="topik"):
        load_prompts(path)


def test_broken_template_syntax_is_rejected(tmp_path: Path) -> None:
    """Одиночный `$` — синтаксическая ошибка `string.Template`."""
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "version: 4\n"
        "stage_a:\n  template: '$topic $seed_text — скидка 50$'\n"
        "stage_b:\n  template: '$topic $user_query'\n"
        "stage_safety:\n  template: '$topic'\n"
        "stage_judge:\n  template: '$criteria $response'\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptError, match="синтаксис"):
        load_prompts(path)


def test_missing_stage_b_section_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "version: 4\n"
        "stage_a:\n  template: '$topic $seed_text'\n"
        "stage_safety:\n  template: '$topic'\n"
        "stage_judge:\n  template: '$criteria $response'\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptError):
        load_prompts(path)


def test_missing_stage_safety_section_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "version: 4\n"
        "stage_a:\n  template: '$topic $seed_text'\n"
        "stage_b:\n  template: '$topic $user_query'\n"
        "stage_judge:\n  template: '$criteria $response'\n",
        encoding="utf-8",
    )

    with pytest.raises(PromptError):
        load_prompts(path)


def test_missing_stage_judge_section_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "prompts.yaml"
    path.write_text(
        "version: 4\n"
        "stage_a:\n  template: '$topic $seed_text'\n"
        "stage_b:\n  template: '$topic $user_query'\n"
        "stage_safety:\n  template: '$topic'\n",
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
