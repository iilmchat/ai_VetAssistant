# Changelog

Все заметные изменения проекта VetAssistant.
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/),
версии — по [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Добавлено

- GitHub Release `v0.2.0 - VetAssistant MVP` с описанием из CHANGELOG (T-031).
- Workflow `.github/workflows/release.yml`: на пуш тега `v*` собирает
  Docker-образ и создаёт GitHub Release через `softprops/action-gh-release@v2`
  (T-031).
- Бейдж последнего релиза в README (T-031).

## [0.2.0] — 2026-11-03

> Официальный стабильный релиз. Тег: `v0.2.0`.
> CI: GitHub Actions, прогон `41527072842` — success.

Второй релиз: Streamlit UI, локальная RAG-база знаний, Router & Triage,
Docker-стек для запуска всего приложения одной командой и CI/CD-пайплайн.

### Добавлено

- Streamlit-интерфейс `app/ui.py`: чат с историей в `st.session_state`,
  потоковый вывод SSE, слайдер `temperature`, очистка истории и понятная
  ошибка при выключенном FastAPI (T-025).
- HTTP-клиент UI `app/ui_client.py` с тестами парсинга SSE (T-025).
- RAG-слой: `scripts/ingest_knowledge.py`, ChromaDB + sentence-transformers,
  поиск по `data/knowledge/` и контекст «Справочная информация из MSD Vet
  Manual» в system prompt при `use_rag=true` (T-026).
- Галочка «Использовать базу знаний (RAG)» в Streamlit-сайдбаре (T-026).
- Router & Triage: `app/router.py` с быстрыми эвристиками экстренных
  симптомов и prompt injection. API отклоняет инъекции с `400 Bad Request`
  и добавляет жёсткую инструкцию «СРОЧНО ОБРАТИТЕСЬ В КЛИНИКУ» при
  угрожающих жизни симптомах до вызова LLM (T-027).
- Бенчмарк роутера `data/router_benchmark.jsonl` (30 кейсов: экстренные,
  обычные, инъекции) и `scripts/evaluate_router.py` с Precision/Recall/F1;
  отчёт `docs/development/reports/EVAL_ROUTER.md` (T-013).
- `UISettings` (`VET_UI_API_URL`, `VET_UI_MODEL_ID`, `VET_UI_TIMEOUT_S`) —
  адрес API можно переопределить для Docker и других окружений.
- Docker-стек: `Dockerfile`, `docker-compose.yml`, `.dockerignore`.
  Контейнеры FastAPI (`:8000`) и Streamlit UI (`:8501`), общий volume
  `./data:/app/data` для GGUF-модели и ChromaDB.
- CI/CD: GitHub Actions workflow `.github/workflows/ci.yml` на push/PR в
  `main` — `ruff check .`, `mypy app`, `pytest -q` и сборка Docker-образа;
  бейдж статуса CI в README (T-028).
- README: инструкция запуска через `docker compose up --build`.

### Результаты v0.2.0

| Метрика | Значение |
|---|---|
| Router: экстренность F1 | **1.0000** |
| Router: prompt injection F1 | **1.0000** |
| Бенчмарк роутера | 30 кейсов, 0 ошибок |
| Проверка Docker Compose | `docker compose config` — OK |
| Сборка Docker-образа | `docker compose build api` — OK (3.68 ГБ) |
| Smoke-тест контейнеров | API `/health` 200, UI `/_stcore/health` — `ok` |
| Тесты | **447 passed** |
| CI (GitHub Actions) | **Lint & Test + Docker Build — success** |

### Планируется

- Function Calling для ассистента.
- Расширение RAG реальными ветеринарными справочниками.
- Расширенный Safety-бенчмарк и независимые модели-судьи.
- Интеграция с внешним веб-приложением.

## [0.1.0] — 2026-11-02

Первый публичный релиз: данные, обученная GGUF-модель, оценка качества,
Safety-проверка и локальный OpenAI-совместимый API.

### Добавлено

- **Инфраструктура и пайплайн данных:** `pyproject.toml`, настройки через
  `pydantic-settings`, клиент учителя с ретраями и логированием токенов
  (T-001, T-002).
- **Генерация синтетических данных:** Шаг A (вопросы владельцев), Шаг B
  (многотурные диалоги), Safety-кейсы, PII-фильтр и дедупликация
  (T-003, T-004, T-005).
- **Масштабирование:** мультипровайдерная конфигурация, bulk-генерация с
  конкурентностью и resume, датасет v1 — 8 120 bulk + 500 safety, после
  PII/дедупа 8 275; train 7 448 / val 827 (T-008, T-009, T-010).
- **PetQA:** загрузка и перевод 10 076 сырых записей, 8 076 seed-вопросов,
  PetQA-Bench на 2 000 open-ended вопросов (T-011).
- **GigaChat:** OAuth 2.0, кеш токена, ограничение конкурентности (T-012).
- **DVC/S3 Selectel:** 13 путей под DVC, `dvc push/pull`, `scripts/sync_data.py`
  (T-014).
- **Обучение:** QLoRA SFT Qwen3-8B, `scripts/train_sft.py`, merge LoRA,
  dry-run и тесты без GPU (T-015).
- **GGUF:** конвертация в f16/Q4_K_M/Q5_K_M, `scripts/convert_to_gguf.py`
  (T-018).
- **Eval harness:** `evaluation/evaluate.py`, MCQ/Reasoning/Safety-метрики,
  LLM-Judge, OpenAI-совместимые endpoint'ы, resume и инкрементальный кеш
  ответов и вердиктов (T-006, T-007, T-020, T-021).
- **FastAPI-обёртка:** `app/main.py`, `POST /v1/chat/completions` в формате
  OpenAI, SSE-стриминг, ветеринарный system prompt, `GET /health`,
  `llama-cpp-python` (T-022).
- **Safety-проверка:** `scripts/test_safety.py` — Safety-кейсы из
  `data/eval_dataset.jsonl` через локальный API (T-023).
- **Документация:** `README.md` с инструкцией для Windows, `MODEL_CARD.md`,
  `docs/development/reports/EVAL_V1.md`, этот CHANGELOG (T-023, T-024).

### Изменено

- `evaluation/evaluate.py`: добавлены `--skip-generation`, `--judge-output`,
  `--local-api` и метаданные судьи в отчёте.
- `evaluation/judge.py`: structured output `json_schema` для LM Studio,
  `CachingJudge` для resume длинных прогонов.
- Ошибки API судьи по отдельным записям больше не прерывают весь прогон.

### Исправлено

- Падения прогона из-за выгрузки модели в LM Studio: ответы и вердикты
  сохраняются инкрементально и переиспользуются при resume.
- Невалидный JSON судьи при обычном текстовом ответе: включён строгий
  `response_format: json_schema`.
- Отсутствующий файл ответов теперь даёт понятную ошибку вместо traceback.

### Результаты релиза

| Метрика | Значение |
|---|---|
| `train_loss` | 0.5922 |
| `eval_loss` | 0.483 |
| Ответов сгенерировано (PetQA) | 2000 / 2000 |
| `reasoning_score_avg` (LLM-Judge) | **4.5185** |
| `reasoning_above_4_ratio` | **0.977** |
| Safety через локальный API | **passed=2, failed=0** |
| Тесты | 377 passed |

### Известные ограничения

- Safety-набор мал (2 кейса); нужен расширенный бенчмарк.
- LLM-Judge — та же модель, что и оцениваемая (self-evaluation bias).
- `reference_f1_avg` не показательна из-за разницы длины ответов и эталонов.
- Возможны галлюцинации; модель не заменяет ветеринарного врача.
