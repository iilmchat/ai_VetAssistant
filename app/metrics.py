"""Prometheus-метрики инференса и RAG (T-117).

`llama-cpp-python` не умеет отдавать метрики llama.cpp server
(``llamacpp_prompt_tokens_seconds``, ``llamacpp_predicted_tokens_seconds``):
в Python-биндингах нет ни HTTP-эндпоинта, ни структурированного API таймингов.
Поэтому токены и латентность считаются в API по полю ``usage`` и времени
вызова модели, а метрики отдаются вместе со стандартными HTTP-метриками
instrumentator'а на ``/metrics``.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

#: Вызовы модели. ``mode`` — chat|stream, ``status`` — success|empty|error.
GENERATION_REQUESTS = Counter(
    "vet_llm_generation_requests_total",
    "Вызовы llama-cpp-python по режиму и результату",
    ("mode", "status"),
)

#: Токены промпта, обработанные моделью (только когда ``usage`` доступен).
PROMPT_TOKENS_TOTAL = Counter(
    "vet_llm_prompt_tokens_total",
    "Суммарное число токенов промпта, обработанных моделью",
)

#: Сгенерированные токены (только когда ``usage`` доступен).
COMPLETION_TOKENS_TOTAL = Counter(
    "vet_llm_completion_tokens_total",
    "Суммарное число сгенерированных токенов",
)

#: Полное время генерации от вызова модели до последнего токена.
GENERATION_SECONDS = Histogram(
    "vet_llm_generation_seconds",
    "Время генерации ответа, секунды",
    ("mode",),
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0, 300.0),
)

#: Время до первого токена для стриминговых ответов.
TIME_TO_FIRST_TOKEN = Histogram(
    "vet_llm_time_to_first_token_seconds",
    "Время до первого токена SSE-ответа, секунды",
    ("mode",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

#: Скорость генерации, токенов в секунду (когда известны токены).
TOKENS_PER_SECOND = Histogram(
    "vet_llm_completion_tokens_per_second",
    "Скорость генерации, токенов в секунду",
    buckets=(1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0),
)

#: Поиски по ChromaDB: hit|miss|error.
RAG_SEARCHES = Counter(
    "vet_rag_searches_total",
    "Поиски по базе знаний по результату",
    ("result",),
)

RAG_CHUNKS_RETRIEVED = Histogram(
    "vet_rag_chunks_retrieved",
    "Сколько чанков вернул RAG-поиск",
    buckets=(0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 10.0),
)

RAG_SEARCH_SECONDS = Histogram(
    "vet_rag_search_seconds",
    "Длительность RAG-поиска, секунды",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
)

#: 1 — индекс ChromaDB найден при старте API, 0 — API работает без RAG.
RAG_INDEX_READY = Gauge(
    "vet_rag_index_ready",
    "Найден ли индекс ChromaDB при старте API (1/0)",
)


def record_generation(
    mode: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    duration_s: float,
    status: str = "success",
    ttft_s: float | None = None,
) -> None:
    """Записать метрики одного вызова модели."""
    GENERATION_REQUESTS.labels(mode=mode, status=status).inc()
    GENERATION_SECONDS.labels(mode=mode).observe(max(duration_s, 0.0))

    prompt = max(int(prompt_tokens), 0)
    completion = max(int(completion_tokens), 0)
    PROMPT_TOKENS_TOTAL.inc(prompt)
    COMPLETION_TOKENS_TOTAL.inc(completion)

    if ttft_s is not None:
        TIME_TO_FIRST_TOKEN.labels(mode=mode).observe(max(ttft_s, 0.0))
    if completion > 0 and duration_s > 0:
        TOKENS_PER_SECOND.observe(completion / duration_s)


def record_rag_search(
    *,
    result: str,
    chunks: int,
    duration_s: float,
) -> None:
    """Записать метрики одного RAG-поиска (``result``: hit|miss|error)."""
    RAG_SEARCHES.labels(result=result).inc()
    RAG_CHUNKS_RETRIEVED.observe(float(max(chunks, 0)))
    RAG_SEARCH_SECONDS.observe(max(duration_s, 0.0))


def set_rag_index_ready(ready: bool) -> None:
    """Выставить gauge готовности RAG-индекса."""
    RAG_INDEX_READY.set(1.0 if ready else 0.0)
