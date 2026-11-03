# Changelog

Все заметные изменения проекта VetAssistant.
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/),
версии — по [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

### Планируется

- Полноценный React-фронтенд.
- Расширенный Safety-бенчмарк и независимые модели-судьи.
- Расширение базы знаний и оценка качества RAG-ответов.

## [0.4.0] — 2026-11-03

> Релиз «Telegram-бот». Тег: `v0.4.0`.
> Тег создаётся после проверки бота в Telegram.

Четвёртый релиз: у VetAssistant появился полноценный интерфейс для
владельцев животных в Telegram. Бот работает отдельным процессом, помнит
контекст диалога и использует тот же локальный API с RAG и Function Calling.

### Добавлено

#### Telegram-бот

- Пакет `bot/` на aiogram 3.x: отдельный процесс `python -m bot` и
  отдельный контейнер `bot` (T-035).
- Команды `/start` (приветствие и дисклеймер «ИИ, а не живой врач»),
  `/reset` (очистка истории) и `/help` (справка) (T-035).
- История диалога для каждого Telegram `user_id`: бот передаёт предыдущие
  сообщения в FastAPI, поэтому помнит контекст беседы (T-035).
- Обработка ошибок API: недоступный сервер, таймаут, `503` и отклонение
  запроса системой безопасности показываются пользователю понятным текстом
  (T-035).
- Автоматическое разбиение длинных ответов на части в пределах лимита
  сообщения Telegram (T-035).

#### Function Calling в Telegram

- Бот передаёт `tools` в `POST /v1/chat/completions` и поддерживает
  `book_appointment` и `set_reminder` (T-035).
- Подтверждения выполнения инструментов отображаются человекочитаемо:
  «✅ Я записал вашего питомца на приём…» и «⏰ Напоминание создано…»,
  после чего показывается финальный текст модели (T-035).

#### Инфраструктура и документация

- Docker Compose сервис `bot` с зависимостью от здорового `api`,
  переменной `TELEGRAM_BOT_TOKEN` и настройками `VET_BOT_*` (T-035).
- `Dockerfile` включает пакет `bot`; wheel также содержит `bot/` (T-035).
- README: получение токена у @BotFather, локальный запуск, запуск в Docker
  Compose и таблица настроек бота (T-035).

#### Тесты

- Юнит-тесты HTTP-клиента FastAPI: нормализация URL, сборка payload,
  парсинг ответа и `tool_calls`, маппинг ошибок (T-035).
- Юнит-тесты логики бота с фейковыми Telegram и FastAPI: команды, история
  по пользователям, Function Calling, разбиение длинных ответов (T-035).
- Всего в проекте **516 тестов**.

### Изменено

- Версия проекта, FastAPI-приложения и Docker-образа поднята до `0.4.0`.
- README дополнен разделом о Telegram-боте и бейджем версии `v0.4.0`.

### Результаты v0.4.0

| Метрика | Значение |
|---|---|
| Тесты | **516 passed** |
| Линтеры | `ruff check .`, `mypy app bot` — чисто |
| Docker Compose | `docker compose config` — валиден |
| Сборка wheel | пакет `bot/` включён |
| Запуск без токена | код 1 и понятная ошибка про `TELEGRAM_BOT_TOKEN` |

### Известные ограничения

- История диалога хранится в памяти процесса бота и сбрасывается после его
  перезапуска; приёмы и напоминания при этом остаются в PostgreSQL.
- Бот рассчитан на один экземпляр и не содержит rate limiting.
- Function Calling зависит от способности модели сформировать корректный
  JSON; при ошибке пользователь получает понятное сообщение.
- Возможны галлюцинации; ассистент не заменяет ветеринарного врача.

## [0.3.0] — 2026-11-03

> Стабильный релиз «Autonomous Agent». Тег: `v0.3.0`.

Третий релиз: ассистент стал автономным агентом — вызывает инструменты,
сохраняет записи в базе данных и опирается на реальные статьи MSD Vet Manual.

### Добавлено

#### Function Calling и Agentic Loop

- Function Calling: `app/tools.py` со схемами `book_appointment` и
  `set_reminder`, парсинг нативных и текстовых `tool_calls`, поддержка
  параметра `tools` в `/v1/chat/completions` (T-030).
- Agentic Loop: API выполняет `tool_calls`, передаёт результат обратно модели
  и возвращает финальный текст; в ответе вызовы остаются как индикация для UI
  (T-032).
- Прямой эндпоинт `POST /v1/tools/execute` для выполнения инструментов (T-030).
- Streamlit UI: переключатель Function Calling и бейджи
  «🛠️ Вызван инструмент: …» с параметрами (T-030, T-032).

#### База данных

- PostgreSQL 16 в Docker Compose (`db`), volume `postgres_data`,
  healthcheck и переменные `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`
  (T-033).
- Async SQLAlchemy 2.0: модели `Appointment`/`Reminder`, `asyncpg` для
  PostgreSQL и `aiosqlite` для локальных тестов; создание таблиц в lifespan
  FastAPI (T-033).
- Реальное сохранение приёмов и напоминаний; read-эндпоинты
  `GET /v1/appointments` и `GET /v1/reminders` (T-033).
- Streamlit: expander **«Мои записи»** с карточками приёмов и напоминаний
  (T-033).

#### Реальный RAG

- `scripts/download_msd.py` скачивает статьи MSD Vet Manual в
  `data/knowledge/real/` (T-030).
- `scripts/ingest_knowledge.py` рекурсивно читает TXT и PDF через `pypdf`,
  режет текст на чанки и строит эмбеддинги в ChromaDB (T-030).
- API добавляет найденные фрагменты в system prompt как «Справочная информация
  из MSD Vet Manual» при `use_rag=true` (T-026, T-030).

#### UI и релизная инфраструктура

- Streamlit UI: потоковый чат, история, `temperature`, RAG, Function Calling
  и «Мои записи» (T-025, T-030, T-033).
- GitHub Release `v0.2.0 - VetAssistant MVP` с описанием из CHANGELOG (T-031).
- Workflow `.github/workflows/release.yml`: на пуш тега `v*` собирает
  Docker-образ и создаёт GitHub Release через `softprops/action-gh-release@v2`
  (T-031).
- Бейдж последнего релиза в README (T-031).

### Изменено

- SQLite-хранилище T-032 заменено на async SQLAlchemy/PostgreSQL (T-033).
- README дополнен разделами о Function Calling, базе данных и реальном RAG.
- Версия проекта и Docker-образа поднята до `0.3.0`.

### Результаты v0.3.0

| Метрика | Значение |
|---|---|
| Тесты | **487 passed** |
| Линтеры | `ruff check .`, `mypy app` — чисто |
| PostgreSQL 16 | проверено на реальном контейнере, данные сохраняются в volume |
| RAG | 2 статьи MSD Vet Manual, поддержка TXT/PDF |
| Инструменты | `book_appointment`, `set_reminder` + Agentic Loop |
| CI (GitHub Actions) | Lint & Test + Docker Build — success |

### Известные ограничения

- База знаний пока небольшая (2 реальные статьи MSD + демо-файлы); качество
  RAG-ответов отдельно не измерялось.
- Function Calling зависит от способности модели формировать корректный JSON;
  при ошибке API возвращает понятную ошибку выполнения инструмента.
- Safety-набор по-прежнему мал, а LLM-Judge — та же модель, что и оцениваемая.
- Возможны галлюцинации; ассистент не заменяет ветеринарного врача.

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
