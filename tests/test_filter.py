"""Тесты PII-фильтра и дедупликации (T-005)."""

from __future__ import annotations

from typing import Any

import pytest

from data_pipeline.filter import (
    COMMON_RU_NAMES,
    FilterReport,
    dialogue_fingerprint,
    filter_dataset,
    find_pii,
    first_user_fingerprint,
)


def _dialogue(
    first_user: str,
    *,
    record_id: str = "case-1",
    answer: str = "Сколько коту лет и как давно началась рвота?",
    tail: str = "Покажите кота ветеринару в ближайшие сутки.",
) -> dict[str, Any]:
    return {
        "id": record_id,
        "stage": "B",
        "topic": "gastroenterology",
        "messages": [
            {"role": "user", "content": first_user},
            {"role": "assistant", "content": answer},
            {"role": "user", "content": "Два года, рвота второй день."},
            {"role": "assistant", "content": tail},
        ],
    }


# --- PII --------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Пишите мне на kot@example.com",
        "Мой e-mail: ivan.petrov+vet@mail.ru, если что.",
    ],
)
def test_email_is_detected(text: str) -> None:
    kinds = [match.kind for match in find_pii(text)]

    assert "email" in kinds


@pytest.mark.parametrize(
    "text",
    [
        "Позвоните +7 999 123-45-67",
        "Мой номер 8 (999) 123 45 67",
        "Телефон 89991234567",
        "Можно на +7(999)1234567",
    ],
)
def test_russian_phone_is_detected(text: str) -> None:
    kinds = [match.kind for match in find_pii(text)]

    assert "phone" in kinds


@pytest.mark.parametrize(
    "text",
    [
        "Меня зовут Анна, у кота рвота.",
        "Кличка собаки Рекс, он отказывается от еды.",
        "Это Анна, я уже писала вам вчера.",
        "Мария Петровна, это вы?",
        "Ивановна говорила, что коту плохо.",
    ],
)
def test_names_are_detected(text: str) -> None:
    kinds = [match.kind for match in find_pii(text)]

    assert "name" in kinds


@pytest.mark.parametrize(
    "text",
    [
        "У кота рвота второй день, он не ест.",
        "Парацетамол высокотоксичен для кошек даже в малых дозах.",
        "Собака породы чихуахуа чешет ухо и трясёт головой.",
        "В Москве сейчас жарко, кот лежит под кондиционером.",
        "Кот Барсик не ест второй день.",
        "Добрый вечер! Подскажите, пожалуйста, что делать.",
        "Кошка стерилизована, вакцинация по графику.",
        "Пришлите фото языка, пожалуйста.",
    ],
)
def test_clean_text_has_no_pii(text: str) -> None:
    assert find_pii(text) == []


def test_pii_matches_are_unique() -> None:
    matches = find_pii("Почта kot@example.com и снова kot@example.com")

    assert len(matches) == 1
    assert matches[0].kind == "email"


def test_name_list_contains_only_lowercase() -> None:
    """Список имён нормализован: сравнение идёт по casefold."""
    assert all(name == name.casefold() for name in COMMON_RU_NAMES)


# --- Дедупликация -----------------------------------------------------------


def test_dialogue_fingerprint_ignores_whitespace_and_case() -> None:
    first = [{"role": "user", "content": "  Кот  НЕ  ест "}]
    second = [{"role": "user", "content": "кот не ест"}]

    assert dialogue_fingerprint(first) == dialogue_fingerprint(second)


def test_first_user_fingerprint_uses_first_user_message() -> None:
    messages = [
        {"role": "assistant", "content": "Здравствуйте"},
        {"role": "user", "content": "Кот не ест"},
        {"role": "user", "content": "Второй день"},
    ]

    assert first_user_fingerprint(messages) == first_user_fingerprint(
        [{"role": "user", "content": " кот   не ест "}]
    )


def test_first_user_fingerprint_without_user() -> None:
    assert first_user_fingerprint([{"role": "assistant", "content": "…"}]) == ""


# --- filter_dataset ---------------------------------------------------------


def test_filter_dataset_on_empty_input() -> None:
    cleaned, report = filter_dataset([])

    assert cleaned == []
    assert report == FilterReport(
        total=0,
        pii_dropped=0,
        duplicates_dropped=0,
        remaining=0,
        pii_by_kind={"email": 0, "phone": 0, "name": 0},
    )


def test_filter_dataset_keeps_clean_dialogues() -> None:
    records = [
        _dialogue("Кот не ест второй день.", record_id="case-1"),
        _dialogue("Собака чешет ухо.", record_id="case-2", answer="Как давно?"),
    ]

    cleaned, report = filter_dataset(records)

    assert [record["id"] for record in cleaned] == ["case-1", "case-2"]
    assert report == FilterReport(
        total=2,
        pii_dropped=0,
        duplicates_dropped=0,
        remaining=2,
        pii_by_kind={"email": 0, "phone": 0, "name": 0},
    )


def test_filter_dataset_drops_email_and_counts_by_kind() -> None:
    records = [
        _dialogue("Кот не ест, пишите на kot@example.com", record_id="pii-1"),
        _dialogue("Собака чешет ухо.", record_id="clean-1", answer="Как давно?"),
    ]

    cleaned, report = filter_dataset(records)

    assert [record["id"] for record in cleaned] == ["clean-1"]
    assert report.total == 2
    assert report.pii_dropped == 1
    assert report.duplicates_dropped == 0
    assert report.remaining == 1
    assert report.pii_by_kind["email"] == 1


def test_filter_dataset_counts_phone_and_name_separately() -> None:
    records = [
        _dialogue("Позвоните +7 999 123-45-67", record_id="phone"),
        _dialogue("Меня зовут Анна, кот не ест", record_id="name"),
    ]

    cleaned, report = filter_dataset(records)

    assert cleaned == []
    assert report.pii_dropped == 2
    assert report.pii_by_kind == {"email": 0, "phone": 1, "name": 1}


def test_filter_dataset_drops_identical_dialogues() -> None:
    records = [
        _dialogue("Кот не ест второй день.", record_id="case-1"),
        _dialogue("Кот не ест второй день.", record_id="case-2"),
    ]

    cleaned, report = filter_dataset(records)

    assert [record["id"] for record in cleaned] == ["case-1"]
    assert report.total == 2
    assert report.pii_dropped == 0
    assert report.duplicates_dropped == 1
    assert report.remaining == 1


def test_filter_dataset_drops_same_first_question() -> None:
    """Пока дедуп по первому вопросу: разные продолжения не спасают запись."""
    records = [
        _dialogue("Кот не ест второй день.", record_id="case-1"),
        _dialogue(
            "Кот не ест второй день.",
            record_id="case-2",
            answer="Сколько коту лет?",
            tail="Срочно к врачу.",
        ),
    ]

    cleaned, report = filter_dataset(records)

    assert [record["id"] for record in cleaned] == ["case-1"]
    assert report.duplicates_dropped == 1


def test_filter_dataset_pii_checked_before_duplicates() -> None:
    records = [
        _dialogue("Кот не ест, звоните 89991234567", record_id="pii-1"),
        _dialogue("Кот не ест, звоните 89991234567", record_id="pii-2"),
    ]

    cleaned, report = filter_dataset(records)

    assert cleaned == []
    assert report.pii_dropped == 2
    assert report.duplicates_dropped == 0


def test_filter_dataset_survives_records_without_messages() -> None:
    records: list[dict[str, Any]] = [
        {"id": "broken", "messages": "не список"},
        {"id": "empty"},
    ]

    cleaned, report = filter_dataset(records)

    assert [record["id"] for record in cleaned] == ["broken", "empty"]
    assert report.remaining == 2
