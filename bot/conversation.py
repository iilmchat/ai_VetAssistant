"""История диалогов Telegram-бота (T-035).

История хранится в памяти процесса и привязана к Telegram user_id. Этого
достаточно для MVP: после перезапуска бота контекст сбрасывается, а сами
приёмы и напоминания остаются в PostgreSQL.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

Message = dict[str, str]


@dataclass
class ConversationStore:
    """Ограниченная история сообщений для каждого пользователя."""

    max_messages: int = 20
    _histories: dict[int, deque[Message]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.max_messages < 2:
            raise ValueError("max_messages должен быть >= 2")

    def history(self, user_id: int) -> list[Message]:
        """Вернуть копию истории пользователя."""
        return [dict(message) for message in self._histories.get(user_id, ())]

    def save(self, user_id: int, messages: Sequence[Message]) -> None:
        """Сохранить историю, обрезав её до ``max_messages``.

        Обрезка выполняется по целым парам «пользователь — ассистент»,
        чтобы диалог не начинался с ответа без вопроса.
        """
        trimmed = [dict(message) for message in messages][-self.max_messages :]
        if len(trimmed) % 2 == 1:
            trimmed = trimmed[1:]
        self._histories[user_id] = deque(trimmed, maxlen=self.max_messages)

    def clear(self, user_id: int) -> None:
        """Забыть историю пользователя."""
        self._histories.pop(user_id, None)

    def clear_all(self) -> None:
        """Забыть историю всех пользователей."""
        self._histories.clear()
