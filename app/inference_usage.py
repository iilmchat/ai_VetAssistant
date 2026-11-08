"""Точный ``usage`` для потоковой генерации (T-138).

``llama-cpp-python`` не отдаёт ``usage`` при ``stream=True``. Для CPU-модели
токены считаются по ``Llama.n_tokens`` (сколько токенов прошло через контекст)
и ``Llama.tokenize`` (сколько токенов в сгенерированном тексте). Если модель
не предоставляет ни того, ни другого (тестовые заглушки), используется
лексический fallback — он даёт ненулевые, но приблизительные значения.

GPU-бэкенд (LM Studio) обычно присылает ``usage`` в последнем SSE-чанке;
такой ``usage`` имеет приоритет над локальным подсчётом.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: Fallback-токенизация: слова, числа и отдельные знаки препинания.
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def _fallback_token_count(text: str) -> int:
    """Приблизительно посчитать токены без доступа к tokenizer модели."""
    return len(_TOKEN_RE.findall(text))


def count_tokens(model: Any, text: str) -> int:
    """Посчитать токены текста через tokenizer модели или fallback.

    ``llama-cpp-python`` принимает в ``tokenize`` байты; некоторые обёртки —
    строку. Пробуем оба варианта, чтобы не зависеть от версии библиотеки.
    """
    if not text:
        return 0

    tokenize = getattr(model, "tokenize", None)
    if callable(tokenize):
        for candidate in (text, text.encode("utf-8")):
            try:
                tokens = tokenize(candidate, add_bos=False)
            except TypeError:
                try:
                    tokens = tokenize(candidate)
                except Exception:
                    continue
            except Exception:
                continue
            try:
                return len(tokens)
            except TypeError:
                continue

    return _fallback_token_count(text)


def count_message_tokens(model: Any, messages: Sequence[Mapping[str, Any]]) -> int:
    """Приблизительно посчитать prompt по сообщениям чата.

    К каждому сообщению добавляются служебные токены шаблона чата. Это
    резервный путь: при наличии ``n_tokens`` prompt считается точнее.
    """
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += count_tokens(model, content)
        total += 4
    return total


@dataclass(frozen=True)
class TokenUsage:
    """Счётчики токенов одного вызова модели."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def normalized(self) -> TokenUsage:
        """Привести значения к неотрицательным и согласовать total."""
        prompt = max(int(self.prompt_tokens), 0)
        completion = max(int(self.completion_tokens), 0)
        total = max(int(self.total_tokens), prompt + completion)
        return TokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )

    def as_dict(self) -> dict[str, int]:
        """Представить usage в JSON-совместимом виде."""
        usage = self.normalized()
        return {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> TokenUsage | None:
        """Разобрать ``usage`` из чанка; ``None`` для пустого словаря."""
        if not payload:
            return None
        try:
            prompt = int(payload.get("prompt_tokens") or 0)
            completion = int(payload.get("completion_tokens") or 0)
            total = int(payload.get("total_tokens") or 0)
        except (TypeError, ValueError):
            return None
        if prompt == 0 and completion == 0 and total == 0:
            return None
        return cls(prompt, completion, total).normalized()


class StreamUsageTracker:
    """Собирает usage из чанков CPU-стрима.

    Наблюдает за чанками и моделью, а в конце выбирает лучший доступный
    источник: ``usage`` из чанка (GPU/LM Studio) → ``n_tokens`` модели →
    лексический fallback.
    """

    def __init__(
        self,
        model: Any,
        messages: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self._model = model
        self._messages = list(messages or [])
        self._parts: list[str] = []
        self._chunk_usage: TokenUsage | None = None
        self._last_n_tokens: int | None = None

    def observe(self, chunk: Mapping[str, Any]) -> None:
        """Учесть один SSE-чанк модели."""
        raw_usage = chunk.get("usage")
        if isinstance(raw_usage, Mapping):
            parsed = TokenUsage.from_mapping(raw_usage)
            if parsed is not None:
                self._chunk_usage = parsed

        choices = chunk.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, Mapping):
                    continue
                delta = choice.get("delta")
                if isinstance(delta, Mapping):
                    content = delta.get("content")
                    if isinstance(content, str):
                        self._parts.append(content)

        n_tokens = getattr(self._model, "n_tokens", None)
        if callable(n_tokens):
            try:
                n_tokens = n_tokens()
            except Exception:
                n_tokens = None
        if isinstance(n_tokens, int) and n_tokens > 0:
            self._last_n_tokens = n_tokens

    def finalize(self) -> TokenUsage:
        """Посчитать итоговый usage после завершения стрима."""
        generated = "".join(self._parts)
        completion = count_tokens(self._model, generated)

        if self._chunk_usage is not None:
            usage = self._chunk_usage
            prompt = usage.prompt_tokens
            if usage.completion_tokens > 0:
                completion = usage.completion_tokens
            if prompt == 0:
                prompt = self._prompt_fallback()
            total = max(usage.total_tokens, prompt + completion)
            return TokenUsage(prompt, completion, total).normalized()

        if self._last_n_tokens is not None and self._last_n_tokens >= completion:
            # n_tokens — весь контекст: prompt + уже сгенерированные токены.
            prompt = self._last_n_tokens - completion
            return TokenUsage(prompt, completion, self._last_n_tokens).normalized()

        prompt = self._prompt_fallback()
        return TokenUsage(prompt, completion, prompt + completion).normalized()

    def _prompt_fallback(self) -> int:
        return count_message_tokens(self._model, self._messages)
