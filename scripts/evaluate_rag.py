#!/usr/bin/env python
"""Оценка hit rate RAG по новым статьям MSD Vet Manual (T-133).

Скрипт задаёт 12 вопросов по темам расширенной базы (ксилит, парвовирус,
эпилепсия, виноград, антифриз, панкреатит), отправляет их в
``POST /v1/chat/completions`` с ``use_rag: true`` и сохраняет ответы.

Проверка, что RAG-поиск реально сработал, делается по счётчику
``vet_rag_searches_total{result=...}``:

* ``--metrics-url`` — текстовый эндпоинт ``/metrics`` (например
  ``http://127.0.0.1:8000/metrics`` из контейнера API);
* ``--prometheus-url`` — HTTP API Prometheus (``http://vetassistant-prometheus:9090``).

Счётчик читается до и сразу после каждого запроса: прирост ``hit`` означает,
что RAG нашёл чанки. Без одного из этих флагов скрипт всё равно соберёт
ответы, но колонка hit будет ``n/a``.

Примеры::

    # внутри контейнера api на сервере
    python scripts/evaluate_rag.py --api-url http://127.0.0.1:8000 \\
        --email owner@example.com --metrics-url http://127.0.0.1:8000/metrics

    # снаружи, через Prometheus и предъявленный JWT
    python scripts/evaluate_rag.py --token "$VET_EVAL_TOKEN" \\
        --prometheus-url http://vetassistant-prometheus:9090

    # посмотреть вопросы без сетевых запросов
    python scripts/evaluate_rag.py --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from loguru import logger

DEFAULT_API_URL = "https://app.ai-pets.ru/api"
DEFAULT_TIMEOUT = 30.0
DEFAULT_CHAT_TIMEOUT = 600.0
DEFAULT_OUTPUT = Path("docs") / "development" / "reports" / "rag_eval_results.json"
METRICS_PATTERN = re.compile(
    r'^vet_rag_searches_total\{result="(?P<result>[a-z]+)"\}\s+(?P<value>[0-9.eE+-]+)\s*$',
)


@dataclass(frozen=True)
class RagQuestion:
    """Один проверочный вопрос по статье расширенной базы."""

    id: str
    topic: str
    question: str
    source: str
    keywords: tuple[str, ...]


#: 12 вопросов: по два на каждую новую тему T-133.
QUESTIONS: tuple[RagQuestion, ...] = (
    RagQuestion(
        id="xylitol-1",
        topic="Ксилит",
        question="Какие симптомы у собаки после отравления ксилитом и почему он опасен?",
        source="msd_xylitol_toxicosis_dogs.txt",
        keywords=("гипогли", "печен", "рвот"),
    ),
    RagQuestion(
        id="xylitol-2",
        topic="Ксилит",
        question="Что делать, если собака съела жвачку с ксилитом?",
        source="msd_xylitol_toxicosis_dogs.txt",
        keywords=("ветеринар", "рвот", "глюкоз"),
    ),
    RagQuestion(
        id="parvo-1",
        topic="Парвовирус",
        question="Какие симптомы парвовирусного энтерита у щенков?",
        source="msd_canine_parvovirus.txt",
        keywords=("рвот", "диаре", "вялост"),
    ),
    RagQuestion(
        id="parvo-2",
        topic="Парвовирус",
        question="Как лечат парвовирус у собак?",
        source="msd_canine_parvovirus.txt",
        keywords=("инфузи", "регидрат", "жидкост"),
    ),
    RagQuestion(
        id="epilepsy-1",
        topic="Эпилепсия",
        question="Что делать при эпилептическом приступе у собаки?",
        source="msd_epilepsy_seizures_small_animals.txt",
        keywords=("приступ", "ветеринар", "судорог"),
    ),
    RagQuestion(
        id="epilepsy-2",
        topic="Эпилепсия",
        question="Что такое эпилептический статус и чем он опасен?",
        source="msd_epilepsy_seizures_small_animals.txt",
        keywords=("статус", "судорог", "поврежден"),
    ),
    RagQuestion(
        id="grapes-1",
        topic="Виноград",
        question="Опасен ли виноград для собак и почему?",
        source="msd_grape_raisin_tamarind_toxicosis_dogs.txt",
        keywords=("почк", "токсич", "виноград"),
    ),
    RagQuestion(
        id="grapes-2",
        topic="Виноград",
        question="Сколько винограда или изюма опасно для собаки?",
        source="msd_grape_raisin_tamarind_toxicosis_dogs.txt",
        keywords=("доз", "изюм", "токсич"),
    ),
    RagQuestion(
        id="antifreeze-1",
        topic="Антифриз",
        question="Какие признаки отравления антифризом у кошки?",
        source="msd_ethylene_glycol_toxicosis_animals.txt",
        keywords=("этиленгликол", "почк", "рвот"),
    ),
    RagQuestion(
        id="antifreeze-2",
        topic="Антифриз",
        question="Чем лечат отравление этиленгликолем у животных?",
        source="msd_ethylene_glycol_toxicosis_animals.txt",
        keywords=("фомепизол", "этанол", "диализ"),
    ),
    RagQuestion(
        id="pancreatitis-1",
        topic="Панкреатит",
        question="Какие симптомы панкреатита у собак и кошек?",
        source="msd_pancreatitis_dogs_cats.txt",
        keywords=("рвот", "боль", "аппетит"),
    ),
    RagQuestion(
        id="pancreatitis-2",
        topic="Панкреатит",
        question="Какая диета и кормление показаны при панкреатите у собак?",
        source="msd_pancreatitis_dogs_cats.txt",
        keywords=("жир", "диет", "корм"),
    ),
)


@dataclass(frozen=True)
class RagCounters:
    """Значения счётчика ``vet_rag_searches_total`` по результатам."""

    hits: float = 0.0
    misses: float = 0.0
    errors: float = 0.0


@dataclass
class QuestionResult:
    """Результат одного вопроса: ответ модели и признаки RAG."""

    id: str
    topic: str
    question: str
    source: str
    answer: str = ""
    duration_s: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    rag_hits_delta: float | None = None
    rag_misses_delta: float | None = None
    rag_hit: bool | None = None
    keywords_found: list[str] = field(default_factory=list)
    error: str | None = None


def normalize_api_url(value: str) -> str:
    """Убрать завершающие слеши из URL API."""
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("URL API не задан")
    return normalized


def parse_metrics_text(text: str) -> RagCounters:
    """Разобрать Prometheus-текст и достать счётчик RAG-поисков."""
    hits = misses = errors = 0.0
    for line in text.splitlines():
        match = METRICS_PATTERN.match(line.strip())
        if match is None:
            continue
        value = float(match.group("value"))
        result = match.group("result")
        if result == "hit":
            hits += value
        elif result == "miss":
            misses += value
        elif result == "error":
            errors += value
    return RagCounters(hits=hits, misses=misses, errors=errors)


def _sum_prometheus_vector(payload: dict[str, Any], result_name: str) -> float:
    """Просуммировать instant-вектор Prometheus по метке ``result``."""
    data = payload.get("data") or {}
    items = data.get("result") or []
    total = 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        metric = item.get("metric") or {}
        if metric.get("result") != result_name:
            continue
        value = item.get("value") or [0, "0"]
        try:
            total += float(value[1])
        except (TypeError, ValueError, IndexError):
            continue
    return total


def read_counters(
    *,
    metrics_url: str | None,
    prometheus_url: str | None,
    timeout: float,
) -> RagCounters | None:
    """Прочитать счётчики RAG из /metrics или из Prometheus."""
    if metrics_url:
        response = requests.get(metrics_url, timeout=timeout)
        response.raise_for_status()
        return parse_metrics_text(response.text)
    if prometheus_url:
        url = f"{prometheus_url.rstrip('/')}/api/v1/query"
        response = requests.get(
            url,
            params={"query": "vet_rag_searches_total"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") != "success":
            raise ValueError("Prometheus вернул статус, отличный от success")
        return RagCounters(
            hits=_sum_prometheus_vector(payload, "hit"),
            misses=_sum_prometheus_vector(payload, "miss"),
            errors=_sum_prometheus_vector(payload, "error"),
        )
    return None


def login(
    session: requests.Session,
    api_url: str,
    *,
    email: str,
    password: str,
    timeout: float,
) -> str:
    """Получить JWT существующего пользователя."""
    response = session.post(
        f"{api_url}/v1/auth/login",
        json={"email": email, "password": password},
        timeout=timeout,
    )
    response.raise_for_status()
    payload: Any = response.json()
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("API не вернул access_token")
    return token


def ask_question(
    session: requests.Session,
    api_url: str,
    token: str,
    question: RagQuestion,
    *,
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> tuple[str, dict[str, int], float]:
    """Отправить вопрос с включённым RAG и вернуть (ответ, usage, секунды)."""
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": question.question}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "use_rag": True,
    }
    started = time.perf_counter()
    response = session.post(
        f"{api_url}/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=(30, timeout),
    )
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    data: Any = response.json()
    if not isinstance(data, dict):
        raise ValueError("API вернул не-JSON-объект")

    choices = data.get("choices") or []
    content = ""
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        if isinstance(message.get("content"), str):
            content = message["content"].strip()
    usage_payload = data.get("usage") or {}
    usage = {
        key: int(usage_payload.get(key, 0) or 0)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    return content, usage, elapsed


def match_keywords(answer: str, keywords: tuple[str, ...]) -> list[str]:
    """Найти ключевые основы в ответе (регистр не важен)."""
    lowered = answer.lower()
    return [keyword for keyword in keywords if keyword in lowered]


def evaluate(
    session: requests.Session,
    *,
    api_url: str,
    token: str,
    questions: tuple[RagQuestion, ...],
    timeout: float,
    chat_timeout: float,
    max_tokens: int,
    temperature: float,
    pause_s: float,
    metrics_url: str | None,
    prometheus_url: str | None,
) -> list[QuestionResult]:
    """Прогнать вопросы и собрать результаты с дельтами счётчиков RAG."""
    results: list[QuestionResult] = []
    for index, question in enumerate(questions, start=1):
        result = QuestionResult(
            id=question.id,
            topic=question.topic,
            question=question.question,
            source=question.source,
        )
        before: RagCounters | None = None
        try:
            before = read_counters(
                metrics_url=metrics_url,
                prometheus_url=prometheus_url,
                timeout=timeout,
            )
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Не удалось прочитать метрики до вопроса {}: {}", question.id, exc)

        logger.info("[{}/{}] {} — {}", index, len(questions), question.id, question.question)
        try:
            answer, usage, elapsed = ask_question(
                session,
                api_url,
                token,
                question,
                timeout=chat_timeout,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except (requests.RequestException, ValueError) as exc:
            result.error = str(exc)
            logger.error("Вопрос {} не выполнен: {}", question.id, exc)
            results.append(result)
            continue

        result.answer = answer
        result.usage = usage
        result.duration_s = elapsed
        result.keywords_found = match_keywords(answer, question.keywords)
        if not answer:
            result.error = "модель вернула пустой ответ"

        after: RagCounters | None = None
        try:
            after = read_counters(
                metrics_url=metrics_url,
                prometheus_url=prometheus_url,
                timeout=timeout,
            )
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Не удалось прочитать метрики после вопроса {}: {}", question.id, exc)

        if before is not None and after is not None:
            hits_delta = after.hits - before.hits
            misses_delta = after.misses - before.misses
            result.rag_hits_delta = hits_delta
            result.rag_misses_delta = misses_delta
            result.rag_hit = hits_delta >= 1
            if hits_delta + misses_delta > 1.5:
                logger.warning(
                    "Для {} счётчик RAG вырос больше чем на 1 (hit={}, miss={}); "
                    "возможен фоновый трафик",
                    question.id,
                    hits_delta,
                    misses_delta,
                )

        results.append(result)
        if pause_s > 0 and index < len(questions):
            time.sleep(pause_s)
    return results


def summarize(results: list[QuestionResult]) -> dict[str, Any]:
    """Посчитать агрегаты по результатам."""
    measured = [item for item in results if item.rag_hit is not None]
    hits = sum(1 for item in measured if item.rag_hit)
    keyword_total = sum(len(item.keywords_found) for item in results if not item.error)
    failed = sum(1 for item in results if item.error)
    return {
        "questions": len(results),
        "failed": failed,
        "measured": len(measured),
        "hits": hits,
        "hit_rate": (hits / len(measured)) if measured else None,
        "keyword_matches": keyword_total,
        "avg_duration_s": (
            sum(item.duration_s for item in results if not item.error)
            / max(len(results) - failed, 1)
        ),
    }


def render_markdown(results: list[QuestionResult], summary: dict[str, Any]) -> str:
    """Сгенерировать markdown-таблицу под шаблон RAG_EVAL.md."""
    lines = [
        "| # | Темы | Вопрос | RAG hit | Ключевые факты | Ответ (фрагмент) |",
        "|---|---|---|---|---|---|",
    ]
    for index, item in enumerate(results, start=1):
        hit = "—" if item.rag_hit is None else ("да" if item.rag_hit else "нет")
        keywords = ", ".join(item.keywords_found) or "—"
        quote = " ".join(item.answer.split())
        if len(quote) > 180:
            quote = f"{quote[:177]}…"
        quote = quote.replace("|", "\\|") or item.error or "—"
        lines.append(
            f"| {index} | {item.topic} | {item.question} | {hit} | {keywords} | {quote} |",
        )
    lines.append("")
    hit_rate = summary.get("hit_rate")
    hit_rate_text = f"{hit_rate:.1%}" if isinstance(hit_rate, float) else "n/a"
    lines.append(
        f"**Итого:** вопросов {summary['questions']}, "
        f"hit {summary['hits']}/{summary['measured']} ({hit_rate_text}), "
        f"ошибок {summary['failed']}, среднее время {summary['avg_duration_s']:.1f} с.",
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Оценить hit rate RAG по новым статьям MSD (T-133).",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"Корень API (по умолчанию {DEFAULT_API_URL})",
    )
    parser.add_argument("--email", default=None, help="Email существующего пользователя")
    parser.add_argument("--password", default=None, help="Пароль (иначе getpass)")
    parser.add_argument(
        "--token",
        default=None,
        help="Готовый JWT (альтернатива email/password; можно через VET_EVAL_TOKEN)",
    )
    parser.add_argument(
        "--metrics-url",
        default=None,
        help="Текстовый /metrics (например http://127.0.0.1:8000/metrics)",
    )
    parser.add_argument(
        "--prometheus-url",
        default=None,
        help="База Prometheus (http://vetassistant-prometheus:9090)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Таймаут запросов, с",
    )
    parser.add_argument(
        "--chat-timeout",
        type=float,
        default=DEFAULT_CHAT_TIMEOUT,
        help="Таймаут генерации ответа, с",
    )
    parser.add_argument("--max-tokens", type=int, default=600, help="max_tokens для ответа")
    parser.add_argument("--temperature", type=float, default=0.2, help="Температура генерации")
    parser.add_argument(
        "--pause",
        type=float,
        default=1.0,
        help="Пауза между вопросами, с (по умолчанию 1.0)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Ограничить число вопросов")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSON с результатами (по умолчанию {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=None,
        help="Дополнительно сохранить markdown-таблицу",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать вопросы и выйти без сетевых запросов",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    api_url = normalize_api_url(args.api_url)
    questions = QUESTIONS[: args.limit] if args.limit else QUESTIONS

    if args.dry_run:
        for index, question in enumerate(questions, start=1):
            print(f"{index:2d}. [{question.topic}] {question.question}  <{question.source}>")
        print(f"\nВсего вопросов: {len(questions)} (сетевые запросы не выполнялись)")
        return 0

    token = (args.token or "").strip() or None
    if token is None:
        email = (args.email or input("Email пользователя: ")).strip()
        if not email:
            print("Ошибка: не задан email", file=sys.stderr)
            return 2
        password = args.password or getpass.getpass(f"Пароль {email}: ")
        if not password:
            print("Ошибка: не задан пароль", file=sys.stderr)
            return 2

    session = requests.Session()
    session.headers["User-Agent"] = "VetAssistant-RagEval/1.0"
    if token is None:
        try:
            token = login(
                session,
                api_url,
                email=email,
                password=password,
                timeout=args.timeout,
            )
        except (requests.RequestException, ValueError) as exc:
            print(f"Ошибка входа: {exc}", file=sys.stderr)
            return 2
    session.headers["Authorization"] = f"Bearer {token}"

    if not args.metrics_url and not args.prometheus_url:
        print(
            "Предупреждение: не задан --metrics-url/--prometheus-url, "
            "колонка RAG hit будет n/a",
            file=sys.stderr,
        )

    results = evaluate(
        session,
        api_url=api_url,
        token=token,
        questions=questions,
        timeout=args.timeout,
        chat_timeout=args.chat_timeout,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        pause_s=max(args.pause, 0.0),
        metrics_url=args.metrics_url,
        prometheus_url=args.prometheus_url,
    )
    summary = summarize(results)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "api_url": api_url,
        "source": (
            "prometheus" if args.prometheus_url else ("metrics" if args.metrics_url else "none")
        ),
        "summary": summary,
        "results": [asdict(item) for item in results],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Результаты сохранены: {args.output}")

    if args.markdown_out is not None:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(render_markdown(results, summary) + "\n", encoding="utf-8")
        print(f"Markdown-таблица сохранена: {args.markdown_out}")

    print()
    print(render_markdown(results, summary))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
