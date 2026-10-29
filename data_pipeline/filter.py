"""Фильтрация датасета: PII и дедупликация (T-005).

Фильтр работает с «сырыми» JSON-объектами (как их читает `read_jsonl`),
поэтому его можно прогонять и на `dialogues_v1.jsonl`, и на
`safety_dialogues.jsonl`, не завязываясь на конкретную Pydantic-модель.

PII-политика:

* e-mail и российские телефоны (`+7…`, `8…`) — жёсткий отсев;
* имена — эвристика по списку распространённых русских имён, отчествам
  и конструкциям «меня зовут …», «кличка …». Список (а не «любое слово
  с заглавной буквы») выбран осознанно: иначе фильтр резал бы названия
  препаратов, пород и городов, которые в ветеринарных диалогах
  встречаются постоянно.

Дедупликация пока точная: совпадение хэша всего диалога или первого
сообщения `user`. В будущем заменим на MinHash/embeddings.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from loguru import logger

PIIKind = Literal["email", "phone", "name"]

#: Простой, но достаточный для синтетики e-mail.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

#: Российский номер: префикс +7/8 и ровно 10 цифр с любыми разделителями.
PHONE_RE = re.compile(r"(?<![\d+])(?:\+7|8)[\s\-()]*(?:\d[\s\-()]*){10}(?!\d)")

#: Явные конструкции представления: «меня зовут Анна», «кличка Рекс».
NAME_INTRO_RE = re.compile(
    r"(?i)\b(?:меня\s+зовут|моё\s+имя|мое\s+имя|зовут|кличка|по\s+имени)\s+([А-ЯЁ][а-яё\-]+)"
)

#: Отчества — почти всегда персональные данные.
PATRONYMIC_RE = re.compile(r"\b[А-ЯЁ][а-яё]+(?:ович|евич|овна|евна|инична|ична)\b")

CAPITALIZED_RE = re.compile(r"\b[А-ЯЁ][а-яё\-]+\b")

#: Распространённые русские имена (в нижнем регистре, ё приводится к е).
COMMON_RU_NAMES: frozenset[str] = frozenset(
    {
        # женские
        "александра",
        "алина",
        "алиса",
        "алла",
        "анастасия",
        "ангелина",
        "анна",
        "антонина",
        "валентина",
        "валерия",
        "варвара",
        "василиса",
        "вера",
        "виктория",
        "галина",
        "дарья",
        "диана",
        "евгения",
        "екатерина",
        "елена",
        "елизавета",
        "жанна",
        "зоя",
        "инна",
        "ирина",
        "карина",
        "кристина",
        "ксения",
        "лариса",
        "лидия",
        "любовь",
        "людмила",
        "маргарита",
        "марина",
        "мария",
        "милана",
        "надежда",
        "наталия",
        "наталья",
        "нина",
        "оксана",
        "олеся",
        "ольга",
        "полина",
        "раиса",
        "светлана",
        "снежана",
        "софия",
        "софья",
        "тамара",
        "татьяна",
        "ульяна",
        "эльвира",
        "юлия",
        "яна",
        # мужские
        "александр",
        "алексей",
        "анатолий",
        "андрей",
        "антон",
        "аркадий",
        "артем",
        "артём",
        "борис",
        "вадим",
        "валентин",
        "валерий",
        "василий",
        "виктор",
        "виталий",
        "владимир",
        "владислав",
        "вячеслав",
        "геннадий",
        "георгий",
        "григорий",
        "даниил",
        "денис",
        "дмитрий",
        "евгений",
        "егор",
        "иван",
        "игорь",
        "илья",
        "кирилл",
        "константин",
        "лев",
        "леонид",
        "максим",
        "марат",
        "михаил",
        "никита",
        "николай",
        "олег",
        "павел",
        "петр",
        "пётр",
        "роман",
        "руслан",
        "сергей",
        "станислав",
        "степан",
        "тимур",
        "федор",
        "фёдор",
        "эдуард",
        "юрий",
        "ярослав",
    }
)

#: Порядок ключей в отчёте — стабильный, чтобы логи не «прыгали».
PII_KINDS: tuple[PIIKind, ...] = ("email", "phone", "name")


@dataclass(frozen=True, slots=True)
class PIIMatch:
    """Найденный фрагмент персональных данных."""

    kind: PIIKind
    value: str


@dataclass(frozen=True, slots=True)
class FilterReport:
    """Итоги фильтрации датасета."""

    total: int
    pii_dropped: int
    duplicates_dropped: int
    remaining: int
    pii_by_kind: Mapping[str, int] = field(default_factory=dict)


def find_pii(text: str) -> list[PIIMatch]:
    """Найти e-mail, телефоны и имена в тексте.

    Возвращает уникальные совпадения (без повторов одинаковых значений).
    """
    matches: list[PIIMatch] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: PIIKind, value: str) -> None:
        key = (kind, value.casefold())
        if key in seen:
            return
        seen.add(key)
        matches.append(PIIMatch(kind=kind, value=value))

    for match in EMAIL_RE.finditer(text):
        add("email", match.group(0))
    for match in PHONE_RE.finditer(text):
        add("phone", match.group(0))
    for match in NAME_INTRO_RE.finditer(text):
        add("name", match.group(1))
    for match in PATRONYMIC_RE.finditer(text):
        add("name", match.group(0))
    for match in CAPITALIZED_RE.finditer(text):
        if match.group(0).casefold() in COMMON_RU_NAMES:
            add("name", match.group(0))

    return matches


def _extract_messages(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Достать реплики диалога, игнорируя строки неверного типа."""
    raw = record.get("messages")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _normalize_text(value: str) -> str:
    """Схлопнуть пробелы и регистр — база для точного сравнения."""
    return " ".join(value.split()).casefold()


def _dialogue_text(messages: Sequence[Mapping[str, Any]]) -> str:
    """Склеить все `content` в один текст для PII-сканирования."""
    return "\n".join(str(item.get("content", "")) for item in messages)


def dialogue_fingerprint(messages: Sequence[Mapping[str, Any]]) -> str:
    """SHA-256 от нормализованного диалога целиком."""
    canonical = "\n".join(
        f"{item.get('role', '')}:{_normalize_text(str(item.get('content', '')))}"
        for item in messages
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def first_user_fingerprint(messages: Sequence[Mapping[str, Any]]) -> str:
    """SHA-256 от первого сообщения `user` (пустая строка, если его нет)."""
    for item in messages:
        if item.get("role") == "user":
            content = _normalize_text(str(item.get("content", "")))
            return hashlib.sha256(content.encode("utf-8")).hexdigest()
    return ""


def filter_dataset(
    records: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], FilterReport]:
    """Отсеять PII и дубликаты.

    Сначала отбрасываются записи с PII, затем — дубликаты среди оставшихся
    (совпадение хэша всего диалога или первого вопроса `user`).

    Returns:
        Кортеж ``(очищенные_записи, отчёт)``.
    """
    kept: list[dict[str, Any]] = []
    total = 0
    pii_dropped = 0
    duplicates_dropped = 0
    pii_by_kind: dict[str, int] = dict.fromkeys(PII_KINDS, 0)
    seen_dialogues: set[str] = set()
    seen_first_questions: set[str] = set()

    for record in records:
        total += 1
        messages = _extract_messages(record)

        matches = find_pii(_dialogue_text(messages))
        if matches:
            pii_dropped += 1
            for match in matches:
                pii_by_kind[match.kind] += 1
            logger.debug(
                "PII: запись {} отсеяна ({}); значения в лог не пишем",
                record.get("id", "?"),
                ", ".join(sorted({match.kind for match in matches})),
            )
            continue

        if messages:
            dialogue_key = dialogue_fingerprint(messages)
            first_key = first_user_fingerprint(messages)
            if dialogue_key in seen_dialogues or (first_key and first_key in seen_first_questions):
                duplicates_dropped += 1
                logger.debug("Дубликат: запись {} отсеяна", record.get("id", "?"))
                continue
            seen_dialogues.add(dialogue_key)
            if first_key:
                seen_first_questions.add(first_key)
        else:
            logger.warning("Запись {} без messages — сохранена как есть", record.get("id", "?"))

        kept.append(dict(record))

    report = FilterReport(
        total=total,
        pii_dropped=pii_dropped,
        duplicates_dropped=duplicates_dropped,
        remaining=len(kept),
        pii_by_kind=pii_by_kind,
    )
    return kept, report
