"""Быстрый роутер и триаж входящих сообщений (T-027).

Эвристики на регулярных выражениях выполняются до генерации ответа и решают
две задачи:

* найти сообщения с угрожающими жизни симптомами;
* заблокировать попытки prompt injection.

Роутер намеренно не использует LLM: проверка должна быть дешёвой и быстрой,
чтобы тяжёлая модель не тратила время на заведомо опасные или вредоносные
запросы.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TypedDict

#: Жёсткая инструкция, которая добавляется в system prompt при экстренном случае.
EMERGENCY_SYSTEM_INSTRUCTION = (
    "ВНИМАНИЕ: СИМПТОМЫ УГРОЖАЮТ ЖИЗНИ. Твой первый ответ должен начинаться "
    "со слов 'СРОЧНО ОБРАТИТЕСЬ В КЛИНИКУ' и не должен задавать уточняющих вопросов."
)


class TriageResult(TypedDict):
    """Результат быстрой классификации сообщения."""

    is_emergency: bool
    reason: str
    injection_detected: bool


#: Пары «человекочитаемая причина — регулярное выражение».
#: Регулярные выражения рассчитаны на нормализованный текст (нижний регистр,
#: одиночные пробелы), который готовит :func:`_normalize`.
_EMERGENCY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "кровотечение",
        re.compile(
            r"\b(?:кров(?:ь|и|ью|ян\w*|ав\w*|отеч\w*|оточащ\w*|оточи\w*|оточ\w*)"
            r"|окровавл\w*)\b"
        ),
    ),
    ("судороги", re.compile(r"\b(?:судорог\w*|судорожн\w*|конвульси\w*)\b")),
    ("отравление", re.compile(r"\b(?:яд(?:а|ы|ом|е|ов)?|ядовит\w*|отрав\w*)\b")),
    (
        "нарушение дыхания",
        re.compile(r"\b(?:не\s+дыш\w*|не\s+может\s+дышать|задыха\w*|удушь\w*)\b"),
    ),
    ("парацетамол", re.compile(r"\bпарацетамол\w*\b")),
    ("потеря сознания", re.compile(r"\b(?:без\s+сознания|потеря\w*\s+сознани\w*)\b")),
)

#: Контексты, где слово «кровь» не означает кровотечение. Вырезаются только
#: перед проверкой экстренности, чтобы «анализ крови» не считался аварией.
_NON_EMERGENCY_CONTEXTS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:общ\w*|биохимическ\w*|клиническ\w*|развернут\w*)?\s*"
        r"анализ\w*\s+кров\w*"
    ),
    re.compile(r"\bпоказател\w*\s+кров\w*"),
    re.compile(r"\bрезультат\w*\s+(?:анализ\w*\s+)?кров\w*"),
)

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "игнорирование предыдущих инструкций",
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass)\s+"
            r"(?:all\s+|any\s+|the\s+|your\s+)*"
            r"(?:previous|prior|above|earlier|system)\s+"
            r"(?:instructions?|prompts?|rules?)\b"
        ),
    ),
    (
        "игнорирование всего предыдущего текста",
        re.compile(r"\bignore\s+(?:everything|all)\s+(?:above|before)\b"),
    ),
    (
        "попытка получить системный промпт",
        re.compile(
            r"\b(?:reveal|show|print|display|output|repeat|tell\s+me)\s+"
            r"(?:me\s+)?(?:your|the)\s+(?:system\s+)?(?:prompt|instructions|rules)\b"
        ),
    ),
    (
        "повтор предыдущего текста",
        re.compile(r"\brepeat\s+(?:the\s+)?(?:text|everything|words)\s+(?:above|before)\b"),
    ),
    (
        "режим разработчика или jailbreak",
        re.compile(
            r"\b(?:jailbreak\w*|developer\s+mode|"
            r"(?:you\s+are|act\s+as|pretend\s+to\s+be)\s+(?:now\s+)?"
            r"(?:dan|an?\s+unrestricted|jailbroken))\b"
        ),
    ),
    (
        "отключение ограничений",
        re.compile(
            r"\b(?:bypass|disable|turn\s+off)\s+(?:your\s+|all\s+)?"
            r"(?:safety|restrictions?|filters?|guardrails?)\b"
        ),
    ),
    (
        "игнорирование инструкций (рус.)",
        re.compile(
            r"\b(?:игнорируй|игнорируйте|проигнорируй|проигнорируйте)\s+"
            r"(?:все\s+|любые\s+|эти\s+)?"
            r"(?:предыдущие\s+|прошлые\s+|вышеуказанные\s+|системные\s+)?"
            r"(?:инструкции|указания|правила|промпт\w*)\b"
        ),
    ),
    (
        "забывание инструкций (рус.)",
        re.compile(
            r"\b(?:забудь|забудьте|забыть)\s+(?:все\s+)?"
            r"(?:предыдущие\s+|прошлые\s+|старые\s+)?"
            r"(?:инструкции|указания|правила|промпт\w*)\b"
        ),
    ),
    (
        "вывод системного промпта (рус.)",
        re.compile(
            r"\b(?:покажи|покажите|выведи|выведите|раскрой|раскройте|"
            r"напечатай|напечатайте|повтори|повторите|скажи|скажите)\s+"
            r"(?:мне\s+)?(?:свой\s+|ваш\s+|системный\s+)*"
            r"(?:промпт\w*|системные\s+инструкции|системные\s+правила)\b"
        ),
    ),
    (
        "режим разработчика (рус.)",
        re.compile(r"\b(?:режим\s+разработчика|отвечай\s+без\s+(?:ограничений|правил|фильтров))\b"),
    ),
)


def _normalize(text: str) -> str:
    """Привести текст к нижнему регистру и схлопнуть пробелы."""
    return " ".join(text.casefold().replace("ё", "е").split())


def _matched_labels(text: str, patterns: Sequence[tuple[str, re.Pattern[str]]]) -> list[str]:
    """Вернуть причины, регулярные выражения которых сработали."""
    return [label for label, pattern in patterns if pattern.search(text)]


def _without_non_emergency_contexts(text: str) -> str:
    """Убрать словосочетания вроде «анализ крови» перед проверкой аварий."""
    for pattern in _NON_EMERGENCY_CONTEXTS:
        text = pattern.sub(" ", text)
    return text


def triage_message(user_message: str) -> TriageResult:
    """Быстро классифицировать сообщение пользователя.

    Проверка не вызывает LLM и работает за микросекунды. Инъекции и
    экстренные симптомы определяются независимо: сообщение может быть
    одновременно опасным по содержанию и содержать попытку взлома.

    Args:
        user_message: последнее сообщение пользователя.

    Returns:
        Словарь с ключами ``is_emergency``, ``reason`` и
        ``injection_detected``.
    """
    text = _normalize(user_message)
    if not text:
        return {"is_emergency": False, "reason": "", "injection_detected": False}

    emergency_labels = _matched_labels(
        _without_non_emergency_contexts(text),
        _EMERGENCY_PATTERNS,
    )
    injection_labels = _matched_labels(text, _INJECTION_PATTERNS)

    reasons: list[str] = []
    if emergency_labels:
        reasons.append(f"экстренные симптомы: {', '.join(emergency_labels)}")
    if injection_labels:
        reasons.append(f"попытка prompt injection: {', '.join(injection_labels)}")

    return {
        "is_emergency": bool(emergency_labels),
        "reason": "; ".join(reasons),
        "injection_detected": bool(injection_labels),
    }


def with_emergency_instruction(
    messages: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    """Добавить жёсткую инструкцию в system message.

    Исходный список не изменяется. Если system message отсутствует, он
    создаётся в начале списка.
    """
    result = [dict(message) for message in messages]
    for index, message in enumerate(result):
        if message.get("role") == "system":
            content = message.get("content", "").strip()
            result[index] = {
                **message,
                "content": f"{content}\n\n{EMERGENCY_SYSTEM_INSTRUCTION}".strip(),
            }
            return result

    return [{"role": "system", "content": EMERGENCY_SYSTEM_INSTRUCTION}, *result]
