"""Prometheus-метрики инференса и RAG (T-117).

`llama-cpp-python` не умеет отдавать метрики llama.cpp server
(``llamacpp_prompt_tokens_seconds``, ``llamacpp_predicted_tokens_seconds``):
в Python-биндингах нет ни HTTP-эндпоинта, ни структурированного API таймингов.
Поэтому токены и латентность считаются в API по полю ``usage`` и времени
вызова модели, а метрики отдаются вместе со стандартными HTTP-метриками
instrumentator'а на ``/metrics``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from prometheus_client import REGISTRY, Counter, Gauge, Histogram

#: Момент старта процесса API: используется в fallback-режиме админской
#: аналитики, когда Prometheus недоступен (T-135).
PROCESS_STARTED_AT = datetime.now(UTC)

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

#: Запросы к инференс-бэкенду (T-144): backend=gpu|cpu, status=success|error.
BACKEND_REQUESTS = Counter(
    "vet_llm_backend_requests_total",
    "Запросы к GPU/CPU инференс-бэкенду по результату",
    ("backend", "status"),
)

#: Время до первого токена в разрезе бэкенда (T-144).
BACKEND_TTFT = Histogram(
    "vet_llm_backend_ttft_seconds",
    "Время до первого токена GPU/CPU-бэкенда, секунды",
    ("backend",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 8.0, 10.0, 30.0, 60.0),
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

#: Вызовы модели в разрезе пользователей (T-135). Метка — числовой user_id:
#: кардинальность ограничена числом пользователей, email в метрику не пишем.
USER_REQUESTS = Counter(
    "vet_llm_user_requests_total",
    "Вызовы модели по пользователям",
    ("user_id",),
)

#: Токены по пользователям и виду: ``kind`` = prompt|completion.
USER_TOKENS = Counter(
    "vet_llm_user_tokens_total",
    "Токены модели по пользователям и виду",
    ("user_id", "kind"),
)


@dataclass(frozen=True)
class UserUsage:
    """Накопленное использование модели одним пользователем."""

    requests: float = 0.0
    prompt_tokens: float = 0.0
    completion_tokens: float = 0.0

    @property
    def tokens(self) -> float:
        """Всего токенов (prompt + completion)."""
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class MetricsSnapshot:
    """Снимок метрик процесса — fallback, когда Prometheus недоступен."""

    requests: float = 0.0
    generation_errors: float = 0.0
    prompt_tokens: float = 0.0
    completion_tokens: float = 0.0
    rag_hits: float = 0.0
    rag_misses: float = 0.0
    rag_errors: float = 0.0
    http_errors: float = 0.0
    users: dict[int, UserUsage] = field(default_factory=dict)

    @property
    def tokens(self) -> float:
        """Всего токенов (prompt + completion)."""
        return self.prompt_tokens + self.completion_tokens


def record_user_usage(
    user_id: int,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """Учесть вызов модели и токены в разрезе пользователя (T-135)."""
    key = str(int(user_id))
    USER_REQUESTS.labels(user_id=key).inc()
    prompt = max(int(prompt_tokens), 0)
    completion = max(int(completion_tokens), 0)
    if prompt:
        USER_TOKENS.labels(user_id=key, kind="prompt").inc(prompt)
    if completion:
        USER_TOKENS.labels(user_id=key, kind="completion").inc(completion)


def snapshot() -> MetricsSnapshot:
    """Прочитать накопленные значения метрик из registry процесса.

    Нужен для fallback-режима админской аналитики: цифры «с момента запуска
    API», без истории по времени.
    """
    requests = 0.0
    generation_errors = 0.0
    prompt_tokens = 0.0
    completion_tokens = 0.0
    rag_hits = 0.0
    rag_misses = 0.0
    rag_errors = 0.0
    http_errors = 0.0
    users: dict[int, dict[str, float]] = {}

    for metric in REGISTRY.collect():
        for sample in metric.samples:
            name = sample.name
            value = float(sample.value)
            labels = sample.labels

            if name == "vet_llm_generation_requests_total":
                requests += value
                if labels.get("status") == "error":
                    generation_errors += value
            elif name == "vet_llm_prompt_tokens_total":
                prompt_tokens += value
            elif name == "vet_llm_completion_tokens_total":
                completion_tokens += value
            elif name == "vet_rag_searches_total":
                result = labels.get("result")
                if result == "hit":
                    rag_hits += value
                elif result == "miss":
                    rag_misses += value
                elif result == "error":
                    rag_errors += value
            elif name == "http_requests_total":
                if str(labels.get("status", "")).startswith("5"):
                    http_errors += value
            elif name in {"vet_llm_user_requests_total", "vet_llm_user_tokens_total"}:
                raw_user_id = labels.get("user_id", "")
                if not raw_user_id.isdigit():
                    continue
                usage = users.setdefault(
                    int(raw_user_id),
                    {"requests": 0.0, "prompt": 0.0, "completion": 0.0},
                )
                if name == "vet_llm_user_requests_total":
                    usage["requests"] += value
                else:
                    kind = labels.get("kind")
                    if kind == "prompt":
                        usage["prompt"] += value
                    elif kind == "completion":
                        usage["completion"] += value

    return MetricsSnapshot(
        requests=requests,
        generation_errors=generation_errors,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        rag_hits=rag_hits,
        rag_misses=rag_misses,
        rag_errors=rag_errors,
        http_errors=http_errors,
        users={
            user_id: UserUsage(
                requests=usage["requests"],
                prompt_tokens=usage["prompt"],
                completion_tokens=usage["completion"],
            )
            for user_id, usage in users.items()
        },
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


def record_backend_request(backend: str, status: str) -> None:
    """Учесть запрос к GPU/CPU-бэкенду (T-144)."""
    BACKEND_REQUESTS.labels(backend=backend, status=status).inc()


def record_backend_ttft(backend: str, seconds: float) -> None:
    """Записать время до первого токена бэкенда (T-144)."""
    BACKEND_TTFT.labels(backend=backend).observe(max(seconds, 0.0))
