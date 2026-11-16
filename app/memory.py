"""Слой памяти ассистента: контекст пациента и эпизоды (T-162).

Модуль отвечает за две вещи:

1. ``build_context`` — перед вызовом LLM собирает компактный блок
   (профиль питомца + последние эпизоды + семантически близкие факты),
   который добавляется в system prompt.
2. ``save_episode`` — после ответа сохраняет краткую выжимку обсуждения
   в ``episodes`` (без полных диалогов, 152-ФЗ).

Семантический поиск использует ту же RAG-модель
``paraphrase-multilingual-MiniLM-L12-v2`` (384 измерения). Если
sentence-transformers недоступен, память деградирует до хронологической:
профиль и последние эпизоды остаются, семантические факты пропускаются.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import date
from functools import lru_cache
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import (
    MEMORY_EMBEDDING_DIM,
    MEMORY_MIN_SIMILARITY,
    Episode,
    Patient,
    add_episode,
    get_patient,
    list_episodes,
    search_similar_episodes,
)
from app.metrics import record_memory_context, record_memory_episode
from app.settings import get_app_settings

#: Функция «текст → вектор»; в тестах подменяется детерминированной.
Embedder = Callable[[str], Sequence[float]]

#: Максимальный размер блока памяти в символах (влезает в n_ctx=4096).
DEFAULT_MAX_CONTEXT_CHARS = 1200

#: Сколько последних эпизодов добавлять в контекст.
DEFAULT_RECENT_EPISODES = 5

#: Сколько семантически близких эпизодов добавлять в контекст.
DEFAULT_SIMILAR_EPISODES = 3

#: Ограничения выжимки: вопрос и ответ обрезаются отдельно.
SUMMARY_QUESTION_LIMIT = 300
SUMMARY_ANSWER_LIMIT = 200

#: Жёсткий лимит content в БД (совпадает с CHECK в миграции).
SUMMARY_MAX_LENGTH = 500

SPECIES_RU: dict[str, str] = {"dog": "собака", "cat": "кошка"}


@lru_cache(maxsize=1)
def _load_encoder() -> Any:
    """Загрузить sentence-transformers один раз на процесс (лениво)."""
    from sentence_transformers import SentenceTransformer

    settings = get_app_settings()
    logger.info("Memory: загружаю эмбеддер {}", settings.embedding_model)
    return SentenceTransformer(settings.embedding_model)


def _default_embedder(text: str) -> list[float]:
    """Эмбеддинг текста RAG-моделью (384 измерения, L2-нормализация)."""
    model = _load_encoder()
    vector = model.encode(text, normalize_embeddings=True)
    return [float(value) for value in vector]


def _encode(embedder: Embedder, text: str) -> list[float]:
    """Получить вектор и проверить размерность до записи в pgvector."""
    vector = [float(value) for value in embedder(text)]
    if len(vector) != MEMORY_EMBEDDING_DIM:
        raise ValueError(
            f"эмбеддер вернул {len(vector)} измерений, "
            f"ожидалось {MEMORY_EMBEDDING_DIM}"
        )
    return vector


def _age_years(birth_date: date | None) -> int | None:
    """Полных лет по дате рождения."""
    if birth_date is None:
        return None
    today = date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return max(0, years)


def _one_line(text: str | None, limit: int) -> str | None:
    """Схлопнуть пробелы и обрезать длинный текст до ``limit`` символов."""
    if text is None:
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: max(limit - 1, 0)].rstrip()}…"


def _profile_lines(patient: Patient) -> list[str]:
    """Строки профиля: имя, вид, порода, возраст, вес, аллергии, хроника."""
    details: list[str] = []
    species = SPECIES_RU.get(patient.species)
    if species:
        details.append(species)
    if patient.breed:
        details.append(_one_line(patient.breed, 60) or "")
    age = _age_years(patient.birth_date)
    if age is not None:
        details.append(f"{age} лет" if age else "младше года")
    if patient.weight is not None:
        details.append(f"{float(patient.weight):g} кг")
    details = [item for item in details if item]

    head = f"Профиль пациента: {_one_line(patient.name, 60) or 'без имени'}"
    if details:
        head = f"{head}, {', '.join(details)}"
    lines = [f"{head}."]

    extras: list[str] = []
    allergies = _one_line(patient.known_allergies, 180)
    if allergies:
        extras.append(f"Аллергии: {allergies}.")
    chronic = _one_line(patient.chronic_conditions, 180)
    if chronic:
        extras.append(f"Хронические болезни: {chronic}.")
    if extras:
        lines.append(" ".join(extras))
    return lines


def _episode_line(episode: Episode, content_limit: int) -> str:
    """Строка эпизода с датой и обрезанным описанием."""
    moment = episode.created_at.strftime("%Y-%m-%d")
    content = _one_line(episode.content, content_limit) or ""
    return f"- {moment}: {content}"


def _truncate_block(text: str, limit: int) -> str:
    """Обрезать блок по границе строки и добавить многоточие."""
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    cut = text[: limit - 1]
    newline = cut.rfind("\n")
    if newline > limit // 2:
        cut = cut[:newline]
    return f"{cut.rstrip()}…"


def format_memory_context(
    patient: Patient,
    recent: Sequence[Episode],
    similar: Sequence[Episode],
    *,
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> str:
    """Собрать текстовый блок памяти в пределах ``max_chars`` символов."""
    lines = _profile_lines(patient)

    if recent:
        lines.append("История:")
        lines.extend(_episode_line(episode, 100) for episode in recent)

    if similar:
        lines.append("Релевантные факты:")
        lines.extend(_episode_line(episode, 180) for episode in similar)

    return _truncate_block("\n".join(lines), max_chars)


def with_patient_context(
    messages: Sequence[dict[str, Any]],
    context: str,
) -> list[dict[str, Any]]:
    """Добавить контекст памяти в system message (или создать его)."""
    result = [dict(message) for message in messages]
    if not context:
        return result

    for index, message in enumerate(result):
        if message.get("role") == "system":
            content = str(message.get("content") or "").strip()
            result[index] = {
                **message,
                "content": f"{content}\n\n{context}".strip(),
            }
            return result

    return [{"role": "system", "content": context}, *result]


def summarize_episode(question: str, answer: str) -> str:
    """Краткая выжимка обсуждения: вопрос до 300, ответ до 200 символов."""
    question = _one_line(question, SUMMARY_QUESTION_LIMIT) or ""
    answer = _one_line(answer, SUMMARY_ANSWER_LIMIT) or ""

    if question and answer:
        summary = f"Вопрос: {question} Ответ: {answer}"
    elif question:
        summary = f"Вопрос: {question}"
    elif answer:
        summary = f"Ответ: {answer}"
    else:
        return ""
    return summary[:SUMMARY_MAX_LENGTH]


class PatientMemory:
    """Сборка контекста питомца и сохранение эпизодов памяти (T-162)."""

    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
        recent_limit: int = DEFAULT_RECENT_EPISODES,
        similar_limit: int = DEFAULT_SIMILAR_EPISODES,
        min_similarity: float = MEMORY_MIN_SIMILARITY,
    ) -> None:
        self._embedder = embedder or _default_embedder
        self.max_context_chars = max_context_chars
        self.recent_limit = recent_limit
        self.similar_limit = similar_limit
        self.min_similarity = min_similarity

    def _embed(self, text: str) -> list[float]:
        return _encode(self._embedder, text)

    async def build_context(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        patient_id: int,
        query: str = "",
    ) -> str:
        """Собрать профиль, последние и семантически близкие эпизоды.

        Raises:
            LookupError: карточка не найдена или принадлежит другому
                пользователю.
        """
        started = time.perf_counter()
        patient = await get_patient(
            session,
            user_id=user_id,
            patient_id=patient_id,
        )
        if patient is None:
            raise LookupError("питомец не найден")

        recent = await list_episodes(
            session,
            user_id=user_id,
            patient_id=patient_id,
            limit=self.recent_limit,
        )

        similar: list[Episode] = []
        semantic_failed = False
        if query.strip():
            try:
                vector = self._embed(query)
                similar = await search_similar_episodes(
                    session,
                    user_id=user_id,
                    patient_id=patient_id,
                    embedding=vector,
                    limit=self.similar_limit,
                    exclude_ids=[episode.id for episode in recent],
                    min_similarity=self.min_similarity,
                )
            except Exception as exc:
                semantic_failed = True
                logger.warning("Memory: семантический поиск не удался — {}", exc)

        context = format_memory_context(
            patient,
            recent,
            similar,
            max_chars=self.max_context_chars,
        )
        if semantic_failed:
            result = "error"
        elif recent or similar:
            result = "hit"
        else:
            result = "miss"
        record_memory_context(
            result=result,
            duration_s=time.perf_counter() - started,
        )
        return context

    async def save_episode(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        patient_id: int,
        question: str,
        answer: str,
        episode_type: str = "chat",
    ) -> Episode | None:
        """Сохранить выжимку обсуждения; без ответа ничего не пишем.

        Ошибка эмбеддера не мешает сохранить эпизод: он останется без
        вектора и будет доступен только в хронологической истории.
        """
        summary = summarize_episode(question, answer)
        if not question.strip() or not answer.strip() or not summary:
            return None

        vector: list[float] | None = None
        try:
            vector = self._embed(summary)
        except Exception as exc:
            logger.warning("Memory: эмбеддинг эпизода не удался — {}", exc)

        try:
            episode = await add_episode(
                session,
                user_id=user_id,
                patient_id=patient_id,
                content=summary,
                episode_type=episode_type,
                embedding=vector,
            )
        except Exception:
            record_memory_episode(result="error")
            raise
        record_memory_episode(result="ok")
        return episode


@lru_cache(maxsize=1)
def get_patient_memory() -> PatientMemory:
    """FastAPI-зависимость: процессный экземпляр памяти с общим эмбеддером."""
    return PatientMemory()
