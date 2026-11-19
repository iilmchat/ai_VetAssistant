# TODO — VetAssistant

Легенда: `[ ]` — не сделано, `[x]` — сделано, `[~]` — в работе.
Работай сверху вниз. Не перескакивай через зависимости.

---

## Фаза 0. Инфраструктура и пайплайн (Итерация 1)

### [x] T-001. Инициализация репозитория
- **Зависит от:** —
- **Что:** Создать структуру папок (`data_pipeline/`, `scripts/`, `configs/`, `data/`). Создать `pyproject.toml` с зависимостями (`openai`, `pydantic`, `tenacity`, `loguru`, `pytest`). Создать `.env.example` (ключи `TEACHER_API_KEY`, `TEACHER_BASE_URL`, `TEACHER_MODEL`). Настроить `.gitignore`.
- **DoD:** `pip install -e .` проходит без ошибок. Структура папок создана.
- **Оценка:** 0.5

### [x] T-002. Слой абстракции API учителя
- **Зависит от:** T-001
- **Что:** Написать `data_pipeline/llm_client.py`. Класс-обертка над `openai.AsyncOpenAI` с поддержкой `base_url`, ретраев (через `tenacity` при 429/500) и логированием токенов.
- **DoD:** Юнит-тест с моком, проверяющий, что ретраи работают. Скрипт `scripts/test_api.py`, который делает тестовый запрос к API и выводит "OK".
- **Оценка:** 1

### [x] T-003. Парсер промптов и генератор Шага A
- **Зависит от:** T-002
- **Что:** Создать `data_pipeline/generator.py`. Загрузить шаблоны из `synthetic_prompts.md` (хардкод или вынести в `configs/prompts.yaml`). Реализовать функцию генерации `user_query` из `seed_text` (Шаг A). Взять 5 тестовых фактов из MSD Vet Manual (вписать вручную в `data/seeds.jsonl`).
- **DoD:** Скрипт `scripts/run_stage_a.py` читает `seeds.jsonl`, генерирует 5 реалистичных вопросов от лица владельца и сохраняет в `data/stage_a_output.jsonl`.
- **Оценка:** 1.5

### [x] T-004. Генератор Шага B (Многотурный диалог)
- **Зависит от:** T-003
- **Что:** Реализовать в `generator.py` функцию Шага B. На вход подается `user_query` из Шага A. На выходе — JSON-массив сообщений (диалог). Добавить валидацию через Pydantic (роли user/assistant, четное/нечетное количество).
- **DoD:** Скрипт `scripts/run_stage_b.py` читает `stage_a_output.jsonl` и генерирует 5 полных диалогов в `data/dialogues_v1.jsonl`. Валидатор Pydantic не выдает ошибок.
- **Оценка:** 2

### [x] T-005. Safety-генератор и фильтры
- **Зависит от:** T-004
- **Что:** Реализовать генерацию Safety-кейсов (из `synthetic_prompts.md` п.3). Написать простой PII-фильтр (regex на телефоны, email, имена) в `data_pipeline/filter.py`, который прогоняет итоговый JSONL.
- **DoD:** Скрипт `scripts/run_safety.py` генерирует 3 safety-диалога. Скрипт `scripts/filter_data.py` успешно чистит объединенный датасет от PII.
- **Оценка:** 1.5

---

## Фаза 1. Eval Harness (Итерация 2)

### [x] T-006. Скелет оценивания
- **Зависит от:** T-001
- **Что:** Создать `evaluation/evaluate.py` по шаблону из `eval_harness.md`. Реализовать классы для парсинга JSONL и заглушки для метрик.
- **DoD:** Скрипт запускается, читает пустой `eval_dataset.jsonl` (создать тестовый с 1 MCQ) и выводит `{"mcq_accuracy": 1.0}`.
- **Оценка:** 1

### [x] T-007. LLM-Judge интеграция
- **Зависит от:** T-002, T-006
- **Что:** Написать промпт судьи (из `eval_harness.md` п.3) и реализовать асинхронный вызов судьи для оценки Reasoning Score и Safety.
- **DoD:** Скрипт `evaluate.py` умеет оценивать Safety-кейс через судью и выдавать оценку 1-5.
- **Оценка:** 1.5

---

## Фаза 1. Масштабирование данных (Итерация 3)

### [x] T-008. Мультипровайдерная конфигурация и пилот
- **Зависит от:** T-002, T-007
- **Что:** Primary/fallback провайдеры в `.env` (`TEACHER_{PRIMARY,FALLBACK}_*`), DI конфигурации в `TeacherClient`, генератор `data/seeds_bulk.jsonl` на 100 записей, пилотный прогон Шагов A+B с отчётом по токенам и ошибкам.
- **DoD:** `scripts/run_pilot.py --provider primary --limit 10` пишет `data/pilot_primary.jsonl` и печатает статистику; `--provider fallback` без настроек даёт понятную ошибку.
- **Оценка:** 1.5

### [x] T-009. Bulk-генерация с конкурентностью
- **Зависит от:** T-008
- **Что:** Перейти на non-reasoning модель `deepseek-chat`, добавить `scripts/run_bulk.py` с `asyncio.Semaphore`, `--resume`, `--limit`, устойчивостью к ошибкам отдельных кейсов и итоговой статистикой.
- **DoD:** Bulk-скрипт генерирует диалоги параллельно и пишет их инкрементально; `--resume` продолжает с места остановки; ошибка одного кейса не роняет прогон.
- **Оценка:** 1.5

### [x] T-010. Сборка датасета v1 (8000 диалогов)
- **Зависит от:** T-009
- **Что:** Thinking off для генерации (`extra_body`), 8000 сидов, `scripts/build_dataset.py`: bulk + 500 safety → PII-фильтр/дедуп → стратифицированный train/val 90/10 → JSON-отчёт.
- **DoD:** `data/train.jsonl` и `data/val.jsonl` на ~8000 диалогов, отчёт с распределением по темам; прогон идемпотентен через `--resume`.
- **Оценка:** 2
- **Статус:** выполнен: 8 120 bulk + 500 safety; после PII/дедупа 8 275; train 7 448 / val 827; отчёт `data/dataset_v1_report.json`.

### [x] T-011. Интеграция PetQA
- **Зависит от:** T-010
- **Что:** загрузка текстовой части PetQA, перевод вопросов на русский через учителя, `data/petqa_ru_questions.jsonl`, PetQA-Bench → `data/eval_dataset_petqa.jsonl`, `generate_seeds.py --source petqa`.
- **DoD:** реальные вопросы PetQA используются как сиды; бенчмарк переведён и валиден по нашим схемам; офлайновые тесты парсинга/конвертации.
- **Оценка:** 2
- **Статус:** выполнено: 10 076 сырых записей загружено; переведено 8 076 seed-вопросов и 2 000 PetQA-Bench (2 000 open-ended); `--source petqa` проверен.

### [x] T-012. Интеграция GigaChat API
- **Зависит от:** T-008
- **Что:** Провайдер GigaChat (`GIGACHAT_*`): OAuth 2.0 client_credentials, кеш и автообновление access_token, `extra_body.thinking` только для DeepSeek, `concurrency=1` для GigaChat в bulk/build_dataset.
- **DoD:** `--provider gigachat` работает через `TeacherClient`; OAuth-эндпоинт замокан в тестах; ограничение конкурентности проверено.
- **Оценка:** 1

### [x] T-014. DVC и S3-хранилище (Selectel)
- **Зависит от:** T-010, T-011
- **Что:** DVC с S3-remote Selectel, локальные ключи, `.dvc`-файлы в Git, скрипт `sync_data.py`, документация.
- **DoD:** `dvc push/pull` работают; тяжёлые данные не попадают в Git; `.dvc`-файлы и конфиги запушены.
- **Оценка:** 1
- **Статус:** выполнено: remote `selectel` (ru-7), 13 путей под DVC, `dvc push/pull/status --cloud` успешно; `sync_data.py` проверен.

### [x] T-015. Скрипты SFT/QLoRA-обучения
- **Зависит от:** T-010, T-014
- **Что:** `configs/train_sft.yaml`, `configs/training.py`, `scripts/train_sft.py`, `scripts/merge_lora.py`, локальный dry-run и тесты без GPU.
- **DoD:** dry-run проверяет конфиг/данные и показывает ChatML; обучение и merge запускаются на Unsloth VM; тесты не требуют GPU.
- **Оценка:** 2
- **Статус:** выполнено: 7448 train / 827 val, Qwen3-8B QLoRA; `train_sft.py --dry-run` и `merge_lora.py --dry-run` работают локально.

### [x] T-016. Скрипт развертывания на удаленном сервере
- **Зависит от:** T-014
- **Что:** bash-скрипт автоматического развертывания на Ubuntu/Unsloth VM: пакеты, репозиторий, venv, training-зависимости, DVC remote, `dvc pull`; документация `TRAINING.md`.
- **DoD:** `bash scripts/setup_remote.sh` разворачивает окружение с проверками; ключи S3 не попадают в Git; скрипт идемпотентен.
- **Оценка:** 1
- **Статус:** выполнено: `scripts/setup_remote.sh`, `requirements-train.txt`, `docs/development/TRAINING.md`; `bash -n` и `shellcheck` чисто. Доработано: `GITHUB_TOKEN` для приватного репозитория и пропуск клонирования, если каталог уже существует.

### [x] T-017. Исправление инфраструктурных скриптов по итогам запуска
- **Зависит от:** T-015, T-016
- **Что:** цели `train`/`merge` в Makefile, системные зависимости и Python headers для Triton, удаление xformers, фоновая инструкция `nohup`.
- **DoD:** `make -n train`/`make -n merge` корректны; `setup_remote.sh` проходит shellcheck; документация обновлена.
- **Оценка:** 1
- **Статус:** выполнено: Makefile, setup_remote.sh, TRAINING.md; добавлен системный `make`, build-essential, zlib1g-dev, libxml2-dev, динамические Python headers и `pip uninstall xformers`.

### [x] T-018. Конвертация модели в GGUF
- **Зависит от:** T-015
- **Что:** `scripts/convert_to_gguf.py`: llama.cpp, f16, Q4_K_M/Q5_K_M, `--dry-run`, тесты команд subprocess; раздел в TRAINING.md.
- **DoD:** скрипт проверяет merged-модель, клонирует/собирает llama.cpp, складывает GGUF в `models/gguf`; dry-run и тесты без тяжёлых процессов.
- **Оценка:** 1
- **Статус:** выполнено: команды проверены тестами, `--dry-run` работает без subprocess; реальная конвертация ожидает merged-модель.

---

## Фаза 2. Оценка GGUF-модели

### [x] T-020. Оценка дообученной GGUF-модели
- **Зависит от:** T-018
- **Что:** прогнать `evaluation/evaluate.py` на `data/eval_dataset_petqa.jsonl` (2000 open-ended вопросов PetQA-Bench) через LM Studio (`--base-url`, `--model-id`, `--limit`), с resume по уже сгенерированным ответам.
- **DoD:** 2000/2000 ответов без потерь; `eval_report.json` и лог прогона.
- **Оценка:** 2
- **Статус:** выполнено: 2000/2000 ответов, 0 missing; `reference_f1_avg=0.0836` (низкий из-за разницы длины ответов и эталонов); дважды потребовался resume после выгрузки модели в LM Studio (873 и 119 ошибок `No models loaded`).

### [x] T-021. Оценка качества ответов через LLM-Judge
- **Зависит от:** T-020
- **Что:** прогнать готовые ответы `data/eval_answers.jsonl` через локального LLM-Judge (LM Studio, `--judge-base-url`/`--judge-model-id`) без повторной генерации (`--skip-generation`); пилот на 10, затем все 2000.
- **DoD:** судья возвращает JSON `{"score": 1..5, "reason": ...}`; отчёт с `reasoning_score_avg` и `reasoning_above_4_ratio` на 2000 ответах.
- **Оценка:** 1.5
- **Статус:** выполнено: 2000/2000 вердиктов, `judge_errors=0`, `reasoning_score_avg=4.5185`, `reasoning_above_4_ratio=0.977`; кеш вердиктов `data/judge_verdicts.jsonl`.

### [x] T-022. FastAPI-обёртка для локальной GGUF-модели
- **Зависит от:** T-018, T-020
- **Что:** `app/main.py` — OpenAI-совместимый `POST /v1/chat/completions` на `llama-cpp-python`, системный ветеринарный промпт, SSE-стриминг, настройки модели через pydantic-settings; тесты с замоканной моделью.
- **DoD:** API принимает `messages` в формате OpenAI, возвращает полный ответ или SSE-поток; тесты не грузят GGUF; зависимости добавлены в `pyproject.toml`.
- **Оценка:** 2
- **Статус:** выполнено: `app/main.py`, `app/settings.py`, 7 API-тестов с моком; `pytest` 368 passed, `ruff`/`mypy` чисто.

### [x] T-023. Проверка безопасности и документация
- **Зависит от:** T-021, T-022
- **Что:** `scripts/test_safety.py` для Safety-кейсов из `data/eval_dataset.jsonl` через локальный API; режим `--local-api` в `evaluation/evaluate.py`; инструкция запуска FastAPI на Windows в `README.md`.
- **DoD:** скрипт находит Safety-кейсы, проверяет отказ/эскалацию и отсутствие назначения запрещённых препаратов; eval умеет работать с `http://127.0.0.1:8000/v1`; README содержит установку wheel и запуск.
- **Оценка:** 1.5
- **Статус:** выполнено: `scripts/test_safety.py` (dry-run находит 2 Safety-кейса), режим `--local-api`, инструкция в README; `pytest` 377 passed, `ruff`/`mypy` чисто.

### [x] T-024. Финальная документация и релиз v0.1.0
- **Зависит от:** T-021, T-022, T-023
- **Что:** внести результаты локального Safety-прогона в `EVAL_V1.md`, обновить `MODEL_CARD.md` и `README.md`, оформить `docs/CHANGELOG.md`, сделать релизный коммит и тег `v0.1.0`.
- **DoD:** документация отражает релиз, Safety 2/2, метрики 4.5185; коммит и тег запушены в GitHub.
- **Оценка:** 1
- **Статус:** выполнено: `MODEL_CARD.md`, `docs/CHANGELOG.md`, обновлены README и EVAL_V1; релизный коммит и тег `v0.1.0`.

### [x] T-025. Веб-интерфейс Streamlit
- **Зависит от:** T-022, T-024
- **Что:** `app/ui.py` — чат на Streamlit с историей в `st.session_state`, потоковым выводом через SSE, настройкой `temperature` и очисткой истории; HTTP-клиент `app/ui_client.py`; инструкции в README и TRAINING.md.
- **DoD:** `streamlit run app/ui.py` открывает чат, ответы приходят потоком, при выключенном API показывается «Сервер ветеринара спит, включите uvicorn».
- **Оценка:** 1.5
- **Статус:** выполнено: UI и клиент готовы, 11 тестов, Streamlit отвечает HTTP 200; `pytest` 388 passed, `ruff`/`mypy` чисто.

### [x] T-026. RAG: локальная база знаний
- **Зависит от:** T-022, T-025
- **Что:** `scripts/ingest_knowledge.py` читает `data/knowledge/*.txt`, режет на чанки по 500 символов, строит эмбеддинги и сохраняет в ChromaDB; FastAPI ищет контекст по последнему сообщению при `use_rag=true`; UI добавляет галочку RAG.
- **DoD:** скрипт индексирует 3 демо-файла, API добавляет «Справочная информация из MSD Vet Manual» в system prompt, при пустой/отсутствующей базе работает как раньше; тесты с замоканным поиском.
- **Оценка:** 2
- **Статус:** выполнено: ingest-скрипт (dry-run: 3 файла, 6 чанков), RAG-слой, API, UI-галочка, тесты; `pytest` 410 passed, `ruff`/`mypy` чисто.

### [x] T-027. Router & Triage: экстренность и prompt injection
- **Зависит от:** T-022, T-026
- **Что:** `app/router.py` — быстрые regex-эвристики: экстренные симптомы (кровь, судороги, яд, отравление, не дышит, парацетамол) и prompt injection. Интеграция в `/v1/chat/completions` до генерации: инъекции → `400 Bad Request`, экстренность → жёсткая инструкция в system prompt; тесты.
- **DoD:** аварийные фразы распознаются, инъекции блокируются без вызова LLM, экстренный system prompt содержит требование начать ответ с «СРОЧНО ОБРАТИТЕСЬ В КЛИНИКУ».
- **Оценка:** 1.5
- **Статус:** выполнено: `app/router.py`, интеграция в API, 30 тестов роутера и API; `pytest` 440 passed, `ruff`/`mypy` чисто.

### [x] T-027.1. Docker-стек и подготовка v0.2.0
- **Зависит от:** T-025, T-026, T-027
- **Что:** `Dockerfile`, `docker-compose.yml` и `.dockerignore`; контейнеры FastAPI (`:8000`) и Streamlit UI (`:8501`), volume `./data:/app/data`, переменные `VET_API_*`/`VET_UI_*`; настройка адреса API для UI; README и CHANGELOG v0.2.0.
- **DoD:** `docker compose config` валиден, UI внутри Compose обращается к API по имени сервиса, модель и ChromaDB доступны через volume, инструкция запуска добавлена в README.
- **Оценка:** 1
- **Статус:** выполнено: Docker-стек готов, `UISettings` для `VET_UI_*`, README и CHANGELOG обновлены; `docker compose config` — OK, образ собран (3.68 ГБ), smoke-тест API+UI в контейнерах пройден (API `/health` 200, UI `/_stcore/health` — `ok`).

### [x] T-028. CI/CD пайплайн (GitHub Actions)
- **Зависит от:** T-013, T-027
- **Что:** `.github/workflows/ci.yml` — push/PR в `main`, Python 3.12, установка зависимостей, `ruff check .`, `mypy app`, `pytest -q`, Docker Buildx и сборка образа без пуша; бейдж CI в README.
- **DoD:** workflow запускается на push и pull_request в `main`, все шаги зелёные, Docker-образ собирается, бейдж отображает статус.
- **Оценка:** 1
- **Статус:** выполнено: workflow и бейдж добавлены; актуальный статус прогонов — по бейджу CI в README.

### [~] T-029. Релиз v0.2.0 и защита ветки `main`
- **Зависит от:** T-028
- **Что:** тег `v0.2.0`, финальная дата и статус в CHANGELOG, README со стабильным релизом, CI/CD и Docker-дистрибутивом; Branch Protection для `main` (только PR + обязательные `Lint & Test`/`Docker Build`).
- **DoD:** тег `v0.2.0` запушен, документация отражает стабильный релиз, прямые push в `main` запрещены, CI-проверки обязательны.
- **Оценка:** 1
- **Статус:** частично: тег, CHANGELOG, README и инструкция готовы; Branch Protection недоступен для private-репозитория на GitHub Free (API 403), требуется GitHub Pro/Team или публичный репозиторий — см. `docs/development/BRANCH_PROTECTION.md`.

### [x] T-030. Function Calling и реальный RAG (v0.3.0)
- **Зависит от:** T-022, T-026, T-027
- **Что:** `app/tools.py` — OpenAI JSON Schema для `book_appointment` и `set_reminder`, парсинг `tool_calls`; поддержка `tools` в API и заглушка `/v1/tools/execute`; UI-переключатель и бейджи инструментов. Реальный RAG: `scripts/download_msd.py` (2 статьи MSD), PDF-поддержка в `scripts/ingest_knowledge.py` через `pypdf`.
- **DoD:** модель возвращает `tool_calls` в OpenAI-формате, UI показывает вызов, заглушка исполнения отвечает `{"status":"success"}`, реальные статьи скачиваются и индексируются вместе с PDF; тесты парсинга и API.
- **Оценка:** 2
- **Статус:** выполнено: инструменты и API, UI-бейджи, загрузка 2 статей MSD, поддержка PDF/TXT и рекурсивная индексация; `pytest` 474 passed, `ruff`/`mypy` чисто.

### [x] T-031. GitHub Release и автоматизация релизов
- **Зависит от:** T-028, T-029
- **Что:** публикация GitHub Release `v0.2.0` через `gh`; workflow `.github/workflows/release.yml` на теги `v*` — сборка Docker-образа и создание релиза через `softprops/action-gh-release@v2`; бейдж последнего релиза в README.
- **DoD:** релиз `v0.2.0` виден в GitHub Releases, workflow готов к следующему тегу, бейдж добавлен.
- **Оценка:** 0.5
- **Статус:** выполнено: GitHub Release `v0.2.0 - VetAssistant MVP` опубликован; `release.yml` и бейдж добавлены.

### [x] T-032. Agentic Loop и реальное выполнение инструментов
- **Зависит от:** T-030
- **Что:** `app/database.py` (SQLite, `appointments`, `reminders`), реальное выполнение `book_appointment`/`set_reminder`, Agentic Loop в `/v1/chat/completions` с повторным вызовом LLM и ролью `tool`, UI-бейджи как индикация уже выполненных вызовов.
- **DoD:** инструмент сохраняет данные в SQLite, API автоматически выполняет `tool_calls` и возвращает финальный текст, тесты БД и agentic loop с замоканной LLM.
- **Оценка:** 2
- **Статус:** выполнено: SQLite, реальное выполнение, loop на 2+ вызова модели, изолированные тесты БД и API; `pytest` 484 passed, `ruff`/`mypy` чисто.

### [x] T-033. PostgreSQL, async SQLAlchemy и чтение записей
- **Зависит от:** T-032
- **Что:** PostgreSQL 16 в Docker Compose с volume; async SQLAlchemy 2.0 (`asyncpg`/`aiosqlite`), модели `Appointment`/`Reminder`, `create_all` в lifespan; `GET /v1/appointments`, `GET /v1/reminders`; Streamlit expander «Мои записи»; тесты на async SQLite.
- **DoD:** Docker-стек поднимает PostgreSQL, API создаёт таблицы при старте, записи сохраняются между перезапусками, read-эндпоинты и UI работают; тесты не требуют Postgres.
- **Оценка:** 2
- **Статус:** выполнено: PostgreSQL-сервис и volume, async SQLAlchemy, read-эндпоинты, UI «Мои записи», async-тесты; проверено на реальном PostgreSQL 16; `pytest` 487 passed, `ruff`/`mypy` чисто.

### [x] T-034. Подготовка и выпуск релиза v0.3.0
- **Зависит от:** T-030, T-031, T-032, T-033
- **Что:** версия `0.3.0` в `pyproject.toml`, FastAPI и Docker-образе; секция `[0.3.0]` в CHANGELOG с реальным RAG (PDF), Function Calling/Agentic Loop, PostgreSQL и расширением Streamlit UI; README со статусом релиза; релизный коммит, тег `v0.3.0` и GitHub Release через `release.yml`.
- **DoD:** версия и документация согласованы, тесты и линтеры зелёные, коммит и тег запушены, workflow Release успешно создал GitHub Release.
- **Оценка:** 1
- **Статус:** выполнено: версия `0.3.0`, CHANGELOG и README обновлены, `pytest` 487 passed, `ruff`/`mypy` чисто; коммит и тег `v0.3.0` запушены, GitHub Release создан workflow Release.

### [x] T-035. Telegram-бот
- **Зависит от:** T-022, T-030, T-033, T-034
- **Что:** пакет `bot/` на aiogram 3.x: отдельный процесс `python -m bot`, клиент FastAPI с историей диалога на пользователя, команды `/start` (дисклеймер), `/reset`, `/help`, Function Calling с подтверждениями записи и напоминаний; сервис `bot` в Docker Compose с `TELEGRAM_BOT_TOKEN`; README и тесты с фейковыми Telegram/FastAPI.
- **DoD:** бот принимает текст, помнит контекст, отвечает через локальный API, показывает вызовы инструментов, запускается локально и в Docker; тесты не обращаются к реальным Telegram и API.
- **Оценка:** 2
- **Статус:** выполнено: `bot/`, сервис `bot`, настройки `VET_BOT_*`, README; тесты клиента и логики; `pytest` 516 passed, `ruff`/`mypy` чисто.

### [x] T-036. Подготовка к релизу v0.4.0
- **Зависит от:** T-034, T-035
- **Что:** версия `0.4.0` в `pyproject.toml`, FastAPI и Docker-образе; секция `[0.4.0]` в CHANGELOG с Telegram-ботом, историей диалогов и Function Calling; README с разделом о боте, инструкцией @BotFather и бейджем `v0.4.0`; релизный коммит.
- **DoD:** версия и документация согласованы, тесты и линтеры зелёные; коммит запушен; тег `v0.4.0` создаётся после подтверждения, что бот работает в Telegram, и запускает GitHub Release.
- **Оценка:** 1
- **Статус:** выполнено: версия `0.4.0`, CHANGELOG и README обновлены, `pytest` 516 passed, `ruff`/`mypy` чисто; релизный коммит `72a9227`, тег `v0.4.0` запушен, workflow Release (run `41605144099`) успешно создал GitHub Release.

### [x] T-037. React-веб-интерфейс
- **Зависит от:** T-022, T-025, T-030, T-033
- **Что:** `frontend/` на React 19 + Vite + TypeScript + Tailwind CSS 4; SSE-стриминг, Markdown, бейджи Function Calling, настройки temperature/RAG/tools, «Мои записи»; CORS для Vite; multi-stage Dockerfile и сервис `frontend` в Compose; README и тесты.
- **DoD:** чат стримит ответы, показывает tool_calls, настройки и записи работают, `npm run build`/`npm test` зелёные, контейнер раздаёт UI через Nginx, документация обновлена.
- **Оценка:** 3
- **Статус:** выполнено: `frontend/` с SSE-чатом, Markdown, бейджами, настройками и «Моими записями»; CORS и `tests/test_cors.py`; multi-stage Dockerfile + Nginx и сервис `frontend`; README, CHANGELOG, CI. Проверено: `npm run lint`/`npm test` (22 passed)/`npm run build`, `pytest` 518 passed, `ruff`/`mypy` чисто, Docker-образ собирается и отдаёт `/healthz`; e2e с mock-API: стриминг, tool badge, автообновление записей, drawer.

### [x] T-038. Подготовка и выпуск релиза v0.5.0
- **Зависит от:** T-037
- **Что:** версия `0.5.0` в `pyproject.toml`, FastAPI, Docker Compose, `frontend/package.json` и lockfile; секция `[0.5.0]` в CHANGELOG; README со скриншотом, описанием веб-интерфейса и портами `3000`/`5173`; release-workflow собирает API и Frontend; релизный коммит и аннотированный тег.
- **DoD:** версии и документация согласованы, тесты и линтеры зелёные, Docker-образы API и Frontend собираются, тег `v0.5.0` опубликован, GitHub Release создан.
- **Оценка:** 1
- **Статус:** выполнено: версия `0.5.0` обновлена во всех конфигурациях, CHANGELOG и README дополнены скриншотом и портами, release-workflow собирает оба Docker-образа; релизный коммит `9f26e90`, тег `v0.5.0` запушен. Release workflow (run `41610500708`) собрал API и Frontend и опубликовал GitHub Release: https://github.com/iilmchat/ai_VetAssistant/releases/tag/v0.5.0. CI (run `41610495022`): Lint & Test, Docker Build, Frontend — success.

### [x] T-039. JWT-авторизация и мультитенантная изоляция данных
- **Зависит от:** T-033, T-035, T-037
- **Что:** таблица `users` (`id`, `email`, `hashed_password`, `created_at`) и `user_id` FK в `appointments`/`reminders`; bcrypt-хэши через `passlib[bcrypt]`; `/v1/auth/register`, `/v1/auth/login` и `/v1/auth/me`; зависимость `get_current_user` по `Authorization: Bearer <token>`; защита chat/appointments/reminders/tools и фильтрация по `user_id`; Agentic Loop пишет данные текущему пользователю; React-экран входа/регистрации с JWT в `localStorage` и кнопкой «Выйти»; Telegram-аккаунт на `/start`; тесты `401` и изоляции.
- **DoD:** без токена защищённые эндпоинты возвращают `401`, с токеном каждый пользователь видит только свои данные; пароли хэшированы; веб, Streamlit и Telegram передают JWT; тесты, линтеры и сборки зелёные; коммит запушен.
- **Оценка:** 3
- **Статус:** выполнено: `app/auth.py` (JWT HS256, bcrypt, `get_current_user`), таблица `users` и `user_id` FK с мягкой миграцией, защита API и Agentic Loop; React (`AuthScreen`, `lib/auth.ts`, logout, per-user история), Streamlit auth-gate и Telegram-авторизация через HMAC-аккаунт с кэшем JWT и повтором при `401`; `pytest` 537 passed, React-тесты 29 passed, `ruff`/`mypy` и `npm run build` чисто. Коммит `4117c2b`; CI (run `41617248540`): Lint & Test, Frontend и Docker Build — success.

### [x] T-040. Подготовка к production-деплою на VPS
- **Зависит от:** T-033, T-035, T-037, T-039
- **Что:** production-стек для одного домена: `docker-compose.prod.yml` с публикацией только `frontend:80`; `frontend/nginx.conf` с проксированием `/api/*` в `api:8000` и SPA fallback; `.env.production.example` со всеми обязательными секретами и инструкцией генерации через `openssl rand -hex 32`; bash-скрипт установки Docker/Compose, клонирования и запуска; HTTPS через Let's Encrypt/Certbot; пошаговый `DEPLOYMENT.md`.
- **DoD:** `.env` исключён из Git, production-шаблон закоммичен; приложение доступно на одном домене, API проксируется через Nginx, наружу открыты только `80`/`443`; скрипт деплоя запускает стек на чистом Ubuntu; документация описывает VPS, DNS, деплой и SSL; тесты и линтеры зелёные.
- **Оценка:** 3
- **Статус:** выполнено: `docker-compose.prod.yml` (только frontend `80:80`), `docker-compose.ssl.yml` (443, Certbot, HSTS и HTTP→HTTPS), Nginx-конфигурация с `/api/`, SSE, SPA и ACME; `.env.production.example`, `scripts/deploy.sh` (Docker, clone, secrets, `--ssl`), `scripts/renew_ssl.sh`, `DEPLOYMENT.md`, тесты `tests/test_deployment.py`; `pytest` 546 passed, React-тесты 29 passed, `ruff`/`mypy`, `npm run build`, `docker compose config` и `nginx -t` — успешно. Коммит `eee9ad9`; CI (run `41623545986`): Lint & Test, Frontend и Docker Build — success.

### [x] T-041. Финальный релиз v1.0.0 (Production Ready)
- **Зависит от:** T-039, T-040
- **Что:** версия `1.0.0` в `pyproject.toml`, FastAPI, Docker Compose (dev/prod), `frontend/package.json` и lockfile; `SECURITY.md` с политикой, порядком сообщения об уязвимостях и production-чеклистом; большая секция `[1.0.0]` в CHANGELOG с путём проекта; README со статусом Production Ready и ссылками на `SECURITY.md`/`DEPLOYMENT.md`; релизный коммит без тега.
- **DoD:** версии согласованы, документация и security-политика готовы, тесты/линтеры/сборки зелёные, коммит `chore: release v1.0.0 (Production Ready)` запушен; тег `v1.0.0` создаётся только после подтверждения работы HTTPS на боевом сервере.
- **Оценка:** 2
- **Статус:** выполнено: версия `1.0.0` синхронизирована, создан `SECURITY.md`, CHANGELOG дополнен полной историей 1.0.0, README переведён в Production Ready со ссылками на security/deployment; `pytest` 548 passed, React-тесты 29 passed, `ruff`/`mypy`, `npm run build` и `docker compose config` — успешно. Релизный коммит `b1d8cec`; CI (run `41627332784`): Lint & Test, Frontend и Docker Build — success. Тег **не создан** — ожидается сигнал «Сайт работает».

### [~] T-042. Автоматизация деплоя (отменена, заменена T-043)
- **Зависит от:** T-040, T-041
- **Что:** Изначально планировался SSH/SFTP-оркестратор `scripts/deploy_prod.py` с Paramiko.
- **DoD:** Не актуально: управление VPS передано инфраструктурному агенту с Caddy и edge-сетями.
- **Оценка:** 3
- **Статус:** отменена по требованию владельца проекта. `scripts/deploy_prod.py` удалён, `paramiko` и `types-paramiko` убраны из зависимостей/CI; безопасные артефакты выделены в T-043.

### [x] T-043. Артефакты Edge-деплоя для инфраструктурного агента
- **Зависит от:** T-040, T-041
- **Что:** `docker-compose.edge.yml` без публикации портов и бота, с внешней сетью `edge` и изолированной `internal`; `deploy/Caddyfile` для `ai-pets.ru`/`www`, `/api/*` → `api:8000`, SPA → `frontend:80`; `scripts/upload_model.py` — SFTP-загрузка в `/srv/vetassistant/data/gguf/` через `.part` с проверкой SHA-256; флаг `VET_API_ALLOW_PUBLIC_REGISTRATION` (по умолчанию `false` в production) и `403` на регистрацию; удаление бота из production-стека и токена из `deploy.sh`.
- **DoD:** edge-стек не публикует 80/443, Caddy получает доступ по сети `edge`, модель проверяется по размеру и SHA-256, регистрация закрывается флагом, тесты/линтеры зелёные.
- **Оценка:** 3
- **Статус:** выполнено: созданы `docker-compose.edge.yml`, `deploy/Caddyfile`, `scripts/upload_model.py`; добавлены `VET_API_ALLOW_PUBLIC_REGISTRATION`, тесты Edge/Caddy/загрузчика/регистрации; `pytest` 566 passed, React-тесты 29 passed, `ruff`/`mypy` и сборки — успешно.

### [x] T-044. Исправление порта SFTP в upload_model.py
- **Зависит от:** T-043
- **Что:** Для OpenSSH `ssh` использует `-p <port>`, а `sftp` — заглавную `-P <port>`; исправить формирование опций и добавить регрессионный тест.
- **DoD:** `_sftp_options` возвращает `-P`, `_ssh_options` — `-p`; тест покрывает оба случая; коммит `fix(deploy): correct sftp port flag in upload_model.py` запушен.
- **Оценка:** 0.5
- **Статус:** выполнено: `_sftp_options` явно заменяет порт на `-P`, `_ssh_options` сохраняет `-p`; регрессионный тест добавлен, `pytest` 566 passed, `ruff`/`mypy` чисто. Коммит `8e38305`; CI (run `41646806216`): Lint & Test, Frontend и Docker Build — success. Тег `v1.0.0` по-прежнему ожидает сигнала «Сайт работает».

### [x] T-045. Адаптация smoke-теста под закрытую регистрацию
- **Зависит от:** T-043
- **Что:** убрать регистрацию из `scripts/smoke_test.py`; запрашивать email/пароль через аргументы или `getpass`; логиниться через `/api/v1/auth/login`; проверять главную, чат с «Привет!» и `GET /api/v1/appointments`; красивый отчёт ✅/❌.
- **DoD:** скрипт запускается как `python scripts/smoke_test.py --base-url https://ai-pets.ru --email ...`, пароль запрашивает `getpass`, проверяет 200/чат/записи, не пытается регистрироваться; тесты/линтеры зелёные; коммит и push.
- **Оценка:** 1
- **Статус:** выполнено: smoke-тест переведён на вход существующим пользователем, добавлена проверка `/api/v1/appointments`, тесты обновлены; `pytest` 569 passed, `ruff`/`mypy` чисто. Тег `v1.0.0` ожидает сигнала «Сайт работает».

---

## Backlog

### [x] T-013. Архитектура «Router & Triage»
- **Зависит от:** T-012
- **Что:** Микро-модели на входе: классифицировать экстренность обращения и детектировать prompt-инъекции до основного ассистента, маршрутизировать запросы в safety/emergency-ветку.
- **DoD:** Роутер с измеренными precision/recall на эталонной выборке и тестами на инъекции; интеграция в пайплайн ассистента.
- **Оценка:** 2
- **Статус:** выполнено: роутер и интеграция в API (T-027); бенчмарк `data/router_benchmark.jsonl` (30 кейсов) и отчёт `docs/development/reports/EVAL_ROUTER.md`; Precision/Recall/F1 = 1.0000 для экстренности и инъекций; тесты на инъекции добавлены.

### [ ] T-105. Инвалидация JWT-токенов
- **Зависит от:** T-039, T-103
- **Что:** При смене или сбросе пароля все ранее выданные JWT-токены должны становиться невалидными. Сейчас после T-103 клиент разлогинивается, но старый JWT остаётся валидным до истечения срока.
- **Решение:** Добавить в таблицу `users` поле `token_version` (int). Встраивать его в JWT при выпуске. При проверке токена сверять версию из токена с версией в БД. При смене пароля инкрементировать `token_version`.
- **DoD:** старый токен после смены пароля получает `401`; новый токен, выданный после входа с новым паролем, работает; существующие пользователи получают начальную версию через мягкую миграцию; тесты на инвалидацию, повторный вход и параллельные сессии; `ruff`/`mypy`/`pytest` зелёные.
- **Оценка:** 2
- **Статус:** запланирована; не входит в релиз v1.1.0.

### [ ] T-166. Retention эпизодов памяти (180 дней)
- **Зависит от:** T-160, T-162 (v1.14.0)
- **Что:** `episodes.content` хранит краткие выжимки обсуждений. Добавить
  автоматическую очистку эпизодов старше 180 дней: скрипт
  `scripts/purge_episodes.py` (батч-удаление, `--dry-run`, `--days`,
  `--database-url`), настройку `VET_API_MEMORY_RETENTION_DAYS` (default 180)
  и запуск по cron/systemd-таймеру на сервере.
- **DoD:** скрипт идемпотентен, удаляет только `episodes` старше срока и не
  трогает карточки `patients`; `--dry-run` показывает количество без записи;
  тесты на границу срока и батчи; инструкция в `DEPLOYMENT.md`; метрика/лог
  `vet_memory_episodes_purged_total`; `ruff`/`mypy`/`pytest` зелёные.
- **Оценка:** 1
- **Статус:** запланирована на v1.15.0; в v1.14.0 действует ручное правило
  хранения ≤ 500 символов и каскадное удаление вместе с пользователем.

### [ ] T-167. Защита от «грязного» дерева на сервере
- **Зависит от:** T-108, T-165
- **Что:** deploy-пайплайн должен переживать локальные изменения в
  `/srv/vetassistant` или падать с понятной инструкцией. Инцидент v1.14.0:
  сисадмин вручную поменял образ БД на `pgvector/pgvector:pg16`, мы
  закоммитили то же изменение, и `git pull --ff-only` упал с «local changes
  would be overwritten»; деплой остановился до пересоздания контейнеров.
- **Почему:** ручные правки на сервере обходят CI/CD, расходятся с Git и
  ломают следующий деплой в самый неподходящий момент. Нужно либо
  автоматически сохранять их в stash, либо явно останавливать деплой с
  диагностикой.
- **Решение:**
  1. В `deploy.yml` (шаг `Pull and rebuild on server`) перед `git pull`
     выполнять `git status --porcelain`.
  2. Если дерево чистое — обычный `git pull --ff-only`.
  3. Если есть изменения — по умолчанию **не** затирать их: вывести список
     файлов, `git diff --stat` и ошибку с инструкцией
     (`git stash push -m "deploy-$(date +%F-%H%M)"`, затем повторить деплой).
  4. Опциональный режим `AUTO_STASH=true` (workflow input или переменная
     окружения): делать `git stash push --include-untracked` с меткой
     релиза, продолжать деплой; stash не удалять автоматически, чтобы
     изменения можно было восстановить.
  5. Логировать, что именно попало в stash, и добавить подсказку
     `git stash list` / `git stash show`; при конфликте pull — откатывать
     деплой и не пересоздавать контейнеры.
  6. Проверять, что после pull `git describe --tags` соответствует
     запрошенной версии; иначе падать с понятной ошибкой.
- **DoD:** деплой на чистом дереве работает как раньше; при локальных
  изменениях без `AUTO_STASH` падает до `docker compose up` с инструкцией и
  списком файлов; с `AUTO_STASH=true` изменения попадают в stash, деплой
  продолжается, stash виден в `git stash list`; тесты workflow/скрипта
  покрывают оба сценария; `DEPLOYMENT.md` описывает ручной и авто-режим и
  запрет правок на сервере; `bash -n`/`shellcheck` для скриптов чистые.
- **Оценка:** 1
- **Статус:** запланирована на v1.15.0; появилась после инцидента с Deploy
  v1.14.0 (локальные правки compose-файлов на сервере).

### [x] T-169. Явная просьба «создай карточку» не включает `create_patient`
- **Зависит от:** T-163 (v1.14.0)
- **Что:** в v1.14.0 инъекция `create_patient` срабатывала только на маркеры
  «у меня», «мой», «зовут». На «Создай карточку Мурзика» инструмент не
  добавлялся, и модель вызывала единственный доступный `book_appointment`.
- **Решение:** отдельная регулярка `_requests_patient_creation` для
  «создай карточку», «создать питомца», «добавь питомца», «заведи карточку»
  и их форм/перестановок; при явной просьбе инструмент добавляется даже при
  выбранной карточке и `use_patient_tools=false`; инструкция и описание
  инструмента явно запрещают `book_appointment` вместо создания карточки.
- **DoD:** тесты на фразы и отрицательные кейсы, приоритет над выбранной
  карточкой/флагом, API-тест с клиентским `book_appointment`; `ruff`/`mypy`/
  `pytest` зелёные.
- **Оценка:** 0.5
- **Статус:** выполнено в v1.14.1.

### [x] T-168. Вёрстка сайдбара и поля ввода
- **Зависит от:** T-164 (v1.14.0)
- **Что:** переключатели «База знаний (RAG)» и «Function Calling» выезжали
  за край карточки, у поля ввода чата появлялась красная обводка валидации.
- **Решение:** knob переключателя позиционируется flex-ом внутри трека, а не
  `absolute` + `translate` (static position добавлял лишние 18 px); у поля
  ввода зелёный `focus-within`-фокус, `noValidate` у формы и подавление
  браузерной `:invalid`-обводки.
- **DoD:** knob и текст в пределах карточки на 320/360 px, зелёный фокус,
  `npm run lint`/`test`/`build` зелёные, проверено скриншотом headless Edge.
- **Оценка:** 0.5
- **Статус:** выполнено в v1.14.1.

### [x] T-170. `'cosine_distance'` в семантическом поиске памяти
- **Зависит от:** T-162 (v1.14.0)
- **Что:** `Episode.embedding` объявлен как
  `JSON().with_variant(Vector(384), "postgresql")`; базовым типом оставался
  JSON, у колонки не было `cosine_distance`, и поиск падал с
  `AttributeError: 'cosine_distance'`.
- **Решение:** базовый тип — `Vector(384)`, JSON — только SQLite-вариант:
  `Vector(MEMORY_EMBEDDING_DIM).with_variant(JSON, "sqlite")`. Запросы
  используют pgvector `<=>`; SQLite-фолбэк сохранён.
- **DoD:** компаратор колонки имеет `cosine_distance`, SQL компилируется с
  `<=>` для PostgreSQL, SQLite-тесты и весь memory-suite зелёные.
- **Оценка:** 0.5
- **Статус:** выполнено в v1.14.2.

### [x] T-171. `create_patient` без лишних уточнений
- **Зависит от:** T-163 (v1.14.0)
- **Что:** описание инструмента требовало «не вызывай без имени и вида» и
  провоцировало уточняющие вопросы; модель откладывала создание карточки.
- **Решение:** описание — «Вызывай этот инструмент СРАЗУ, как только
  пользователь назвал кличку и вид. Не задавай вопросы про вес, вакцинацию,
  породу — они необязательны»; в системный промпт добавлено жёсткое
  правило вызывать `create_patient` немедленно по просьбе создать карточку.
- **DoD:** тесты инструкции и описания, agentic-сценарий создаёт карточку
  без вопросов о необязательных полях.
- **Оценка:** 0.5
- **Статус:** выполнено в v1.14.2.

### [x] T-172. Защита от ложного «Карточка создана»
- **Зависит от:** T-163 (v1.14.0)
- **Что:** модель могла написать «Карточка создана», не вызвав
  `create_patient`; пользователь получал ложное подтверждение.
- **Решение:** в agentic loop (`_complete`) финальный текст проверяется
  регуляркой; если утверждение о создании есть, а успешного
  `create_patient` (`success`/`exists`) не было — текст заменяется на
  «Извините, произошла ошибка при создании карточки, попробуйте еще раз».
  Отрицания и вопросы не считаются утверждением.
- **DoD:** тесты на положительные/отрицательные формулировки, ответ без
  вызова инструмента заменяется, ответ после успешного вызова — нет;
  streaming-агент использует тот же `_complete`.
- **Оценка:** 1
- **Статус:** выполнено в v1.14.2.

### [x] T-173. Запись на приём только к существующей карточке
- **Зависит от:** T-161, T-163 (v1.14.0)
- **Что:** `appointments` хранил только `pet_name`, поэтому можно было
  создать запись «в воздух» без карточки питомца.
- **Решение:** nullable `appointments.patient_id` (`ON DELETE SET NULL`) +
  индекс + миграция `2026-11-17_appointments_patient.sql`; `book_appointment`
  ищет карточку по `patient_id`, затем по кличке и виду, при отсутствии
  создаёт её по `species` или возвращает ошибку с требованием создать
  карточку. `AppointmentRead`/frontend-тип отдают `patient_id`.
- **DoD:** запись без карточки не создаётся; существующая карточка
  привязывается; автосоздание по `species`; чужая карточка отклоняется;
  тесты repository/tools/API зелёные.
- **Оценка:** 1.5
- **Статус:** выполнено в v1.14.2.

### [x] T-108. Автоматический деплой на сервер (CI/CD)
- **Зависит от:** T-104, T-106
- **Что:** Настроить безопасный автоматический деплой edge-стека по пушу тега. GitHub Actions должен запускать пересборку образов, заходить по SSH на VPS под отдельным пользователем `deployer` и обновлять `/srv/vetassistant` без использования root.
- **Решение:**
  1. На сервере создать отдельного пользователя `deployer` и добавить его в группу `docker`; убедиться, что у него есть доступ к `/srv/vetassistant` и Docker Compose.
  2. Сгенерировать новую SSH-пару специально для GitHub Actions. Публичный ключ добавить в `~/.ssh/authorized_keys` пользователя `deployer`; приватный — в GitHub Actions secret `SSH_KEY`, хост — в `SSH_HOST`, пользователя — в `SSH_USER`.
  3. Добавить `.github/workflows/deploy.yml`: по пушу тега `v*` вызвать `appleboy/ssh-action@v1.0.3` с `host: ${{ secrets.SSH_HOST }}`, `username: ${{ secrets.SSH_USER }}`, `key: ${{ secrets.SSH_KEY }}`; на сервере выполнить `cd /srv/vetassistant && git pull --ff-only && docker compose -f docker-compose.edge.yml up -d --build` (образы собираются на сервере).
  4. Обновить `DEPLOYMENT.md`: создание `deployer`, права Docker, генерация ключей, настройка secrets и проверка первого деплоя по тегу.
- **DoD:** пуш тега `v*` автоматически деплоит edge-стек; деплой идёт под `deployer`, не под root; приватный ключ не попадает в репозиторий и логи; `docker compose -f docker-compose.edge.yml config` проходит; документация позволяет повторить настройку с нуля; при ошибке деплоя workflow завершается с ненулевым кодом.
- **Оценка:** 3
- **Статус:** выполнено: `.github/workflows/deploy.yml` (тег `v*`, `appleboy/ssh-action@v1.0.3`, secrets `SSH_HOST`/`SSH_USER`/`SSH_KEY`, `script_stop`), `scripts/setup_deploy_user.sh` (`deployer`, группа `docker`, `.ssh` 700, `authorized_keys` 600), раздел «Настройка CI/CD» в `DEPLOYMENT.md`; тесты workflow/скрипта/документации добавлены.

### [x] T-114. Очистка web-root лендинга
- **Зависит от:** T-113 (v1.2.0)
- **Что:** Вынести служебные файлы (`README.md`, `DEPLOY.md`, `nginx.conf`, `compose.edge.fragment.yml`, `Caddyfile.edge.snippet`) из папки `landing/`, которая раздаётся как статика, в `landing/docs/` или корень проекта (по плану Phase 2 — `deploy/landing/`). Обновить пути в `docker-compose.landing.yml` (генерируется `deploy/landing/apply-package-b.sh`) и в самом скрипте: `LANDING_DIR`/`NGINX_CONF`, встроенный Caddy-сниппет и smoke-проверка служебных файлов. Убрать блок `@landing_private` из `landing/Caddyfile.edge.snippet` и из встроенного сниппета в скрипте — в web-root служебных файлов больше не будет. Обновить структуру в `landing/README.md` и `landing/DEPLOY.md`.
- **DoD:** в `landing/` остаются только публичные статики (`index.html`, `404.html`, `assets/`, `privacy/`, `terms/`, `robots.txt`, `sitemap.xml`); служебные файлы не попадают в web-root и недоступны по HTTP даже без Caddy-блока; `@landing_private` удалён из обоих Caddy-сниппетов; `docker compose -f docker-compose.landing.yml config` валиден, лендинг и `/healthz` отвечают; `pytest`/`ruff`/`mypy` зелёные, `bash -n`/`shellcheck` для скрипта чисто; коммит запушен.
- **Оценка:** 1
- **Статус:** выполнено: служебные файлы перенесены в `docs/landing/` (не `landing/docs/`, иначе они остались бы в web-root); `NGINX_CONF` в `apply-package-b.sh` указывает на `docs/landing/nginx.conf`; `@landing_private` удалён из сниппета и встроенного Caddy-блока; smoke-проверка 404 для служебных путей сохранена; обновлены `docs/landing/README.md`, `docs/landing/DEPLOY.md`, `DEPLOYMENT.md`, `README.md` и план Phase 2.

### [x] T-132. Персистентность версии образов и план Фазы 5
- **Зависит от:** T-131
- **Что:** `VETASSISTANT_VERSION` передавалась только через `env` шага деплоя и не сохранялась в `.env`, поэтому ручной `docker compose up -d` на сервере мог поднять образ `:latest`. Записывать версию в `.env` из workflow, добавить безопасный скрипт ручного перезапуска и задокументировать запрет прямого `docker compose` на проде; подготовить backlog Фазы 5.
- **DoD:** после деплоя по тегу `VETASSISTANT_VERSION=<версия>` есть в `/srv/vetassistant/.env` и не дублируется при повторных деплоях; `scripts/restart_prod.sh` сам определяет версию из git-тега (или аргумента), пишет её в `.env` и поднимает стек `up -d --no-build`; `DEPLOYMENT.md` предупреждает запускать только скрипт; `bash -n` чистый; тесты обновлены.
- **Оценка:** 0.5
- **Статус:** выполнено: в `deploy.yml` добавлен шаг `Persist image version to .env` (идемпотентные `sed`/`printf`), создан `scripts/restart_prod.sh` (версия из `git describe --tags`, проверка формата, обновление `.env`, `docker compose up -d --no-build`), переменная описана в `.env.production.example`, `DEPLOYMENT.md` §6.4 и новый §6.6; backlog Фазы 5 — T-133…T-136.

### [x] T-133. Расширение RAG: ещё 5–10 статей MSD Vet Manual
- **Зависит от:** T-124
- **Что:** Догрузить 5–10 статей (вакцинация, паразиты, экстренная помощь — отравления, травмы, тепловой удар), прогнать `scripts/ingest_knowledge.py` (upsert безопасен) и расширить индекс `msd_vet_manual` с текущих 204 чанков.
- **DoD:** статьи в Git и доступны после `git pull`; индекс — не меньше 230 чанков; hit rate на 10–20 вопросах измерен и не ниже текущего; тесты ingestion зелёные; обновлён раздел README про RAG.
- **Оценка:** 1
- **Статус:** выполнено: 10 статей MSD добавлены в `data/knowledge/real/` и проиндексированы — **766 чанков** (было 204, ×3.75) через `upsert` с логом «Новых чанков / будет обновлено / всего в коллекции»; `scripts/download_msd.py --url` умеет скачивать по прямым ссылкам; `scripts/create_telegram_user.py --reset-password` для сброса пароля после ротации `VET_BOT_AUTH_SECRET`; `scripts/evaluate_rag.py` + `docs/development/reports/RAG_EVAL.md` — прогон 12 вопросов дал **12/12 RAG hit (100 %), 0 miss, 0 ошибок, среднее 74.6 с**; регрессии на старых темах нет.

### [x] T-134. Привязка Telegram к веб-аккаунту
- **Зависит от:** T-121, T-039
- **Что:** Сейчас Telegram-пользователь создаётся скриптом `scripts/create_telegram_user.py` с synthetic email и живёт отдельным аккаунтом: записи и напоминания, сделанные на сайте, в боте не видны. Добавить `telegram_id` в `users`, привязку существующего аккаунта по одноразовому коду и уведомления в чат о записях и напоминаниях. Вход на сайт через Telegram Login Widget — отдельный этап (T-134.7), в эту итерацию не входит.
- **Решение:** привязка инициируется на сайте, подтверждается в боте. Сайт выпускает одноразовый код и показывает «отправьте боту `/link КОД`»; бот вызывает `POST /v1/telegram/confirm` под своим synthetic-JWT, а API проверяет, что email из токена соответствует `telegram-<id>@bot.vetassistant.local` для переданного `telegram_id`. Пароль synthetic-аккаунта выводится из `VET_BOT_AUTH_SECRET` (HMAC), поэтому такой JWT может получить только бот — отдельный shared secret для внутреннего эндпоинта не нужен. Коды хранятся только как HMAC-SHA256 от `VET_API_JWT_SECRET`.
- **Безопасность:** код — 8 символов Crockford base32 (без `0/O/1/I`), TTL 10 минут, одноразовый, максимум 3 активных кода на пользователя, лимит 5 запросов/час; `users.telegram_id UNIQUE`; коды не пишутся в логи; synthetic-JWT с чужим `telegram_id` → 403. Автоматического слияния аккаунтов в эндпоинте нет: конфликт `telegram_id` → 409, слияние — только вручную скриптом с `--merge-user`.
- **DoD:** привязка и отвязка работают без смены пароля; старые synthetic-аккаунты продолжают работать (JWT-remap на привязанный веб-аккаунт); уведомления приходят только привязанным; миграция идемпотентна на SQLite и PostgreSQL; тесты на код/истечение/повтор/чужой ID/отвязку/уведомления; `ruff`/`mypy`/`pytest` и frontend-проверки зелёные; `DEPLOYMENT.md` описывает миграцию, команды и откат.
- **Оценка:** 3
- **Статус:** выполнено в v1.6.0. Отличие от первоначального плана: **backfill `telegram_id` для synthetic-аккаунтов не выполняется** — он занял бы `telegram_id` и сделал бы привязку веб-аккаунта невозможной (409). Вместо удаления synthetic-аккаунта при `--merge-user` он сохраняется (иначе бот теряет пароль для входа), а записи/напоминания переносятся; вход бота после привязки отдаёт JWT веб-пользователя. SQL прогнан на PostgreSQL 16 дважды, полный `pytest`/`ruff`/`mypy` и frontend-проверки зелёные.

#### Подзадачи T-134

- [x] **T-134.1. Схема БД и миграции (0.5).**
  - `users.telegram_id BIGINT NULL` + `UNIQUE`-индекс `ix_users_telegram_id`; поле в модели `User`.
  - Новая таблица `telegram_link_codes`: `id`, `user_id` (FK `ON DELETE CASCADE`), `code_hash CHAR(64)`, `expires_at`, `used_at`, `created_at`; индексы по `user_id` и `expires_at`.
  - Мягкая миграция `_migrate_telegram_link(connection)` в `app/database.py` по образцу `_migrate_admin_panel` (ALTER TABLE + `CREATE UNIQUE INDEX IF NOT EXISTS`, совместимо с SQLite и Postgres) и вызов из `create_tables`.
  - `scripts/migrate_telegram_link.py`: отчёт по synthetic-аккаунтам, `--dry-run`, `--merge-user EMAIL TELEGRAM_ID` (перенос `appointments`/`reminders`, привязка `telegram_id`; synthetic-аккаунт сохраняется для входа бота).
  - DoD: повторный запуск миграции не меняет данные и не падает; `--merge-user` переносит записи без потерь и идемпотентен; тесты миграции на временной SQLite.

- [x] **T-134.2. API: коды, привязка и отвязка (1).**
  - `app/telegram_link.py`: генерация кода (Crockford base32), HMAC-хеширование, TTL, лимиты, проверки.
  - `POST /v1/telegram/link-code` (JWT пользователя) → `{code, expires_at, bot_username, instructions}`; не более 3 активных кодов, лимит 5 запросов/час.
  - `GET /v1/telegram/link` (JWT) → `{linked, telegram_id, linked_at, email}`.
  - `POST /v1/telegram/confirm` (JWT бота + `{code, telegram_id}`): проверка связки email↔telegram_id, TTL, одноразовость, уникальность; запись `users.telegram_id`, `used_at`, ревокация остальных кодов.
  - `DELETE /v1/telegram/link` (JWT пользователя) и `POST /v1/telegram/unlink` (JWT бота) — отвязка.
  - DoD: код живёт 10 минут; повторное использование → 400; занятый `telegram_id` → 409; без токена → 401; synthetic-JWT с чужим ID → 403; в БД только HMAC кода; тесты всех веток и лимитов.

- [x] **T-134.3. Бот: `/link`, `/unlink`, `/status` (0.5).**
  - `bot/handlers.py` + `bot/service.py`: команды привязки, человеческие сообщения об ошибках (код истёк, неверный, занят другим аккаунтом), обновлённые `/help` и `/start`.
  - `bot/client.py`: методы `confirm_link`, `unlink`, `link_status` с JWT (код выпускает только сайт).
  - Вход бота: synthetic-JWT обменивается на JWT привязанного веб-пользователя (`resolve_bot_login_user`), иначе записи из бота остались бы в отдельном аккаунте.
  - Allowlist `VET_BOT_ALLOWED_TELEGRAM_IDS` проверяется до любых действий (fail closed).
  - DoD: `/link КОД` привязывает и отвечает «Аккаунт привязан: <email>»; неверный код не раскрывает лишних деталей; `/unlink` отвязывает; тесты хендлеров на фейковом API.

- [x] **T-134.4. Уведомления API → Telegram (0.5).**
  - `app/telegram_notify.py`: `send_telegram_message(chat_id, text)` через Bot API (`VET_API_TELEGRAM_API_BASE`), timeout 5 с, ошибки только в лог; флаг `VET_API_TELEGRAM_NOTIFY` (по умолчанию включён).
  - `api` получает `TELEGRAM_BOT_TOKEN` в edge-compose (бот уже получает).
  - Триггеры: после успешных `book_appointment`/`set_reminder` в `_execute_tool_calls`, если у пользователя есть `telegram_id`; запросы бота помечаются заголовком `X-Vet-Client` и не дублируются.
  - DoD: уведомление о записи и напоминании приходит в чат; ошибка Telegram не ломает ответ API; при выключенном флаге отправки нет; тест с моком httpx.

- [x] **T-134.5. Frontend: блок «Telegram» в настройках (1).**
  - `types.ts`/`lib/api.ts`: `TelegramLinkStatus`, `fetchTelegramLink`, `createTelegramLinkCode`, `unlinkTelegram`.
  - UI в настройках: статус, кнопка «Привязать» → код + инструкция + обратный отсчёт, «Отвязать» с подтверждением, состояния loading/error.
  - DoD: привязка и отвязка из UI; код не сохраняется в `localStorage`; `npm run build`/`npm test`/`oxlint` зелёные; тесты клиента и логики таймера.

- [x] **T-134.6. Документация, релиз и откат (0.5).**
  - `DEPLOYMENT.md`: миграция (`scripts/migrate_telegram_link.py`), команды бота, переменные `VET_BOT_USERNAME`, `TELEGRAM_BOT_TOKEN` в `api`, `VET_API_TELEGRAM_NOTIFY`; откат — `UPDATE users SET telegram_id = NULL`.
  - `.env.production.example`, README, CHANGELOG; версия `v1.6.0`.
  - DoD: инструкция позволяет повторить настройку с нуля; `pytest`/`ruff`/`mypy` и frontend-проверки зелёные; релиз по обычной схеме CI → тег → деплой.

- [ ] **T-134.7. (опционально, отдельная итерация) Вход на сайт через Telegram Login Widget.** Проверка подписи `hash` от Telegram, выдача обычного JWT, привязка при первом входе. Требует подтверждённого домена и HTTPS; в оценку T-134 не входит.

### [x] T-135. Аналитика в админ-панели на метриках Prometheus
- **Зависит от:** T-122 (перенесена в v1.6.0), T-117
- **Что:** Метрики уже собираются в `app/metrics.py` (`vet_llm_generation_requests_total`, `vet_llm_prompt_tokens_total`, `vet_llm_completion_tokens_total`, `vet_llm_generation_seconds`, `vet_rag_searches_total`), но админка их не показывает, а `/metrics` закрыт наружу. Вывести графики прямо в `AdminDashboard`: запросы по времени, сожжённые токены, латентность (TTFT, токенов/с), RAG hit rate и топ пользователей. Для топа нужна новая размерность: сейчас в метриках нет `user_id`.
- **Решение:** агрегаты отдаёт **API** (`GET /v1/admin/metrics`, за `get_current_admin`), а не iframe Grafana. Причины: (1) админка должна работать и без Grafana — локально, в dev и до развёртывания мониторинга; (2) Grafana потребовала бы анонимного доступа/embed-токена и правки Caddy + CSP `frame-ancestors`, то есть отдельного контура авторизации; (3) продукту нужны агрегаты («токены за 24 ч», «топ пользователей»), а не произвольный PromQL. История берётся из Prometheus, если задан `VET_API_PROMETHEUS_URL` (allowlist запросов на сервере), иначе — из in-process registry `prometheus_client` с пометкой «с момента запуска API». Встраивание Grafana остаётся опцией для ops, но не в UI пользователей.
- **DoD:** админка показывает графики за 24 часа и 7 дней; API отдаёт агрегаты через админский эндпоинт с проверкой `is_admin`; `/metrics` остаётся недоступным снаружи; высококардинальные метки не появляются; тесты агрегации и прав доступа.
- **Оценка:** 2.5
- **Статус:** выполнено в v1.5.6: вкладка «Аналитика» в `AdminDashboard` (KPI-карточки, SVG-графики `Sparkline`, топ-5 пользователей по запросам и токенам, окна 24 ч/7 д, автообновление раз в минуту); `GET /v1/admin/metrics` с режимами `prometheus` и `in_process` (`degraded` вместо 500); счётчики `vet_llm_user_requests_total{user_id}` и `vet_llm_user_tokens_total{user_id,kind}`; настройки `VET_API_PROMETHEUS_URL`/`VET_API_PROMETHEUS_TIMEOUT_S`; `DEPLOYMENT.md` §«Админская аналитика» и `.env.production.example`. Тесты: `tests/test_admin_metrics.py` — 12 passed, frontend — 59 passed, `ruff`/`mypy`/`oxlint`/`tsc` чисто.

#### Подзадачи T-135

- [x] **T-135.1. Метрики: размерность пользователя и снимок в процессе.**
  - В `app/metrics.py` добавить `USER_REQUESTS = Counter("vet_llm_user_requests_total", ..., ("user_id",))` и вызывать её из `chat_completions`/стриминга (`app/main.py`, там уже есть `current_user`); кардинальность ограничена числом пользователей, email в метку не пишем.
  - Добавить `snapshot()`: прочитать `prometheus_client.REGISTRY` и вернуть суммы по `vet_llm_*`, `vet_rag_*` и `http_requests_total{status}` + `started_at` процесса.
  - DoD: счётчик растёт на каждый чат-запрос; `snapshot()` покрыт тестом с подменённым registry; `ruff`/`mypy` зелёные.

- [x] **T-135.2. API: `GET /v1/admin/metrics`.**
  - Новый эндпоинт в `app/admin.py` (`Annotated[User, Depends(get_current_admin)]`, query `window=24h|7d`).
  - Модель ответа: `source: "prometheus" | "in_process"`, `degraded: bool`, `generated_at`, `totals` (запросы, prompt/completion токены, RAG hit/miss/error, доля ошибок), `series: [{ts, requests, tokens}]`, `top_users: [{user_id, email, requests}]`.
  - Запросы к Prometheus — фиксированный allowlist PromQL-выражений (`sum(rate(...))`, `topk`), URL из нового поля `prometheus_url` в `AppSettings` (`VET_API_PROMETHEUS_URL`, `VET_API_PROMETHEUS_TIMEOUT_S`); таймаут 2–3 с; при ошибке — fallback на `snapshot()` и `degraded=true`.
  - DoD: без Prometheus эндпоинт отвечает 200 в режиме `in_process`; с недоступным URL — `degraded=true`, без 500; не-админ получает 401/403; произвольный PromQL с клиента не принимается; тесты на оба режима и на allowlist.

- [x] **T-135.3. Frontend: вкладка «Аналитика» в `AdminDashboard`.**
  - Разделить экран на две вкладки: «Заявки» (текущий список, поведение не меняется) и «Аналитика»; состояние вкладки — локальное, без роутера.
  - `frontend/src/components/AdminAnalytics.tsx`: 4 KPI-карточки (запросы, токены, RAG hit rate, средняя латентность), график запросов/токенов по времени, таблица топ-5 пользователей; переключатель 24 ч / 7 д; обновление раз в 60 с по кнопке/таймеру.
  - Графики — собственный SVG-компонент (`frontend/src/components/charts/Sparkline.tsx`), без новой зависимости: в проекте нет chart-библиотеки, а тянуть recharts ради двух линий не нужно.
  - DoD: вкладка не ломает текущий approve/reject-флоу; состояния loading/empty/error/degraded отображаются честно (badge «с момента запуска API»); `npm run build`/`npm test`/`oxlint` зелёные.

- [x] **T-135.4. Клиент API и типы.**
  - `frontend/src/types.ts`: `AdminMetrics`, `AdminMetricsPoint`, `AdminTopUser`, `AdminMetricsSource`.
  - `frontend/src/lib/api.ts`: `fetchAdminMetrics(window, baseUrl)` рядом с существующими admin-функциями.
  - DoD: типы экспортируются и используются в `AdminAnalytics`; тест на маппинг серий и на пустой ответ.

- [x] **T-135.5. Тесты, конфиг и документация.**
  - `tests/test_admin_metrics.py`: доступ только админу, режим `in_process`, `degraded=true` при недоступном Prometheus, топ пользователей с email.
  - `DEPLOYMENT.md` §«Метрики Prometheus»: переменные `VET_API_PROMETHEUS_URL`/`VET_API_PROMETHEUS_TIMEOUT_S`, что показывает админка, почему не iframe Grafana; обновить `.env.production.example`.
  - DoD: `pytest`/`ruff`/`mypy` зелёные; в документации есть пример URL (`http://prometheus:9090`) и объяснение fallback-режима.

### [ ] T-136. Докачка прерванного ответа вместо потери текста
- **Зависит от:** T-037
- **Что:** При обрыве сети `streamChat` в `App.tsx` падает: частичный ответ остаётся в чате со статусом ошибки, продолжить генерацию нельзя, пользователь повторяет вопрос. Добавить идемпотентный `request_id` и повтор запроса, чтобы ответ доезжал после кратковременного обрыва, либо докачку по `stream_id`.
- **DoD:** обрыв на середине ответа не теряет уже сгенерированный текст; повтор не дублирует сообщения в истории; есть тест на обрыв и повтор; поведение описано в README.
- **Оценка:** 2
- **Статус:** запланирована.

---

## Фаза 5 (v1.5.0) — экспорт истории и Telegram-бот

Утверждено: **T-123 + T-121**. T-122 (аналитика) перенесена в v1.6.0.
Расширение RAG (больше статей MSD) — контентная задача без релиза, см.
примечание в конце.

### [x] T-121. Telegram-бот в production edge-стеке
- **Зависит от:** T-035, T-043, T-117
- **Что:** Вернуть `bot` в production: сервис в `docker-compose.edge.yml` без публикации портов, `TELEGRAM_BOT_TOKEN` из `.env`, `VET_BOT_API_URL=http://api:8000/v1/chat/completions`, `VET_BOT_USE_RAG=true`, `depends_on` на здоровый `api`. Так как доступ в сервис закрытый — добавить allowlist `VET_BOT_ALLOWED_TELEGRAM_IDS`: посторонним бот отказывает и не создаёт аккаунт. Обновить `DEPLOYMENT.md` (BotFather, секрет, проверка) и `README.md`; тесты конфигурации и allowlist.
- **DoD:** `docker compose -f docker-compose.edge.yml config` валиден; контейнер `bot` работает и не публикует порты; `/start`, вопрос по MSD Vet Manual и запись питомца работают с RAG; Telegram-ID вне allowlist получает отказ; токен не попадает в Git и логи; тесты allowlist/конфигурации зелёные; деплой по тегу не ломает API и frontend.
- **Оценка:** 2
- **Статус:** выполнено: сервис `bot` в `docker-compose.edge.yml` (edge, без портов, зависит от healthy `api`); allowlist `VET_BOT_ALLOWED_TELEGRAM_IDS` с fail closed; бот больше не регистрирует пользователей (только login), остальным — сообщение об ограничении; тесты allowlist/отказа/клиента и edge-конфигурации; обновлены `.env.example`, `.env.production.example`, `README.md`, `DEPLOYMENT.md`.

### [ ] T-122. Аналитика использования в админ-панели
- **Зависит от:** T-120, T-117
- **Что:** Хранить использование модели в БД: таблица `llm_usage` (`user_id`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `stream`, `created_at`), запись в `_generate_once`/`_stream` при наличии `usage`. Эндпоинт `GET /v1/admin/stats?days=7` — totals, разбивка по дням и топ пользователей. В `AdminDashboard` — вкладка «Статистика» с карточками (запросы, токены, средняя латентность) и графиком. Учесть ограничение: llama.cpp в стриме не отдаёт `usage`, поэтому запросы считаются всегда, а токены — где `usage` доступен (для стрима можно добавить оценку через `tokenize`).
- **DoD:** миграция идемпотентна; агрегаты за 7/30 дней корректны; не-админ получает `403`; UI показывает данные и пустое состояние; `ruff`/`mypy`/`pytest`/frontend-тесты зелёные; секреты и тексты сообщений в статистику не попадают.
- **Оценка:** 2
- **Статус:** перенесена в v1.6.0 (решение после теста админ-панели).

### [x] T-123. Экспорт истории диалогов
- **Зависит от:** T-037
- **Что:** Кнопка «Экспорт» в сайдбаре: скачивать историю текущего пользователя в Markdown и JSON (роль, текст, tool calls, дата), без обращения к серверу. Добавить `created_at` в `UiMessage` при отправке/загрузке, имя файла `vetassistant-<user-id>-<date>.md`. Учесть, что история хранится только в `localStorage` и очищается кнопкой «Новый чат».
- **DoD:** экспорт работает офлайн и не отправляет данные на сервер; старые сообщения без даты не ломают файл; кнопка недоступна при пустой истории; есть тест утилиты экспорта и типов; `npm run build`/`npm test`/`oxlint` зелёные.
- **Оценка:** 0.5
- **Статус:** выполнено: `frontend/src/lib/export.ts` (Markdown/JSON, имя файла, Blob + object URL), кнопка «Скачать историю» в сайдбаре, `createdAt` в `UiMessage`; 6 тестов экспорта, `npm run build`/`npm test`/`oxlint` чисто.

### [x] T-124. Финализация v1.5.0: статьи MSD и фикс админки
- **Зависит от:** T-120, T-121, T-123
- **Что:** Добавить в Git пять новых статей MSD Vet Manual (шоколад, блохи, клещи кошек/собак, вакцинация), обновить индекс до 204 чанков; исправить появление вкладки «Администрирование» у пользователей со старой сессией: применять ответ `GET /v1/auth/me` к текущей сессии и сохранять в `localStorage`.
- **DoD:** статьи в Git и доступны после `git pull`; индекс `msd_vet_manual` — 204 чанка; `is_admin=true` из `/auth/me` доезжает до `Sidebar` без повторного логина; тесты и сборки зелёные; тег `v1.5.0` запушен.
- **Оценка:** 0.5
- **Статус:** выполнено: 5 статей добавлены, RAG обновлён до 204 чанков (upsert), `App.tsx` применяет `/auth/me` к сессии и `localStorage`, версия `1.5.0`.

### [x] T-130. Оптимизация CI/CD: убрать двойную сборку образов
- **Зависит от:** T-128
- **Что:** Сейчас `release.yml` собирает Docker-образы `api` и `frontend`, а затем `deploy.yml` собирает их **заново** на том же VPS. Это двойная нагрузка на сервер и лишние 20–30 минут на каждый тег. Убрать сборку из `release.yml` (оставить только создание GitHub Release) и переложить её полностью на `deploy.yml`; либо объединить workflows в один, если так проще сохранить атомарность «сборка → релиз → деплой».
- **DoD:** тег `v*` запускает сборку образов ровно один раз; `release.yml` не делает `docker build`; GitHub Release создаётся; `deploy.yml` собирает `api`/`frontend` и поднимает стек; время тега сокращено; workflow-тесты обновлены; деплой остаётся зелёным.
- **Оценка:** 0.5
- **Статус:** выполнено: из `.github/workflows/release.yml` удалены `setup-buildx-action` и обе сборки (`docker build` для `api` и `frontend`); job переименован в `create-release` (таймаут 10 минут), остались `actions/checkout` и `softprops/action-gh-release@v2`; единственная сборка production-образов — `deploy.yml` (`docker compose … build api frontend` + `up -d --no-build`). Добавлены workflow-тесты `test_release_workflow_only_creates_github_release` и `test_docker_images_built_only_by_deploy_workflow`; `tests/test_deployment.py` — 21 passed, `ruff`/`mypy` чисто. Запись `v1.5.3` в `docs/CHANGELOG.md` дополнена (T-130, синтетические email, гонки CI/CD), `DEPLOYMENT.md` §6 обновлён; тег `v1.5.4` — контрольный прогон CI/CD с новыми правилами.

### [x] T-131. Динамические версии Docker-образов и фиксация v1.5.5
- **Зависит от:** T-130
- **Что:** В `docker-compose.edge.yml` и `docker-compose.prod.yml` тег образа был захардкожен (`vetassistant:1.5.3`), поэтому в `docker ps` не было видно, что на проде запущена сборка хотфикса из тега `v1.5.4`. Заменить тег на `vetassistant:${VETASSISTANT_VERSION:-latest}`, научить `deploy.yml` брать версию из тега (`VETASSISTANT_VERSION=${GITHUB_REF_NAME#v}`) и передавать её в `docker compose` через `env`. Поднять версию проекта до `1.5.5` и зафиксировать процесс «сначала зелёный CI, потом тег».
- **DoD:** ни в одном compose-файле нет захардкоженной версии; деплой по тегу `v1.5.5` собирает образы `vetassistant:1.5.5` и `vetassistant-frontend:1.5.5`; версия `1.5.5` согласована в `pyproject.toml`, FastAPI, `package.json`, `package-lock.json`, README и CHANGELOG; `DEPLOYMENT.md` описывает порядок «CI → тег»; тесты обновлены; CI зелёный, затем ставится тег `v1.5.5`.
- **Оценка:** 0.5
- **Статус:** выполнено: compose-файлы (edge/prod/dev) используют `${VETASSISTANT_VERSION:-latest}`; в `deploy.yml` добавлен шаг `Resolve image version from tag` (output `version`, `env: VETASSISTANT_VERSION` на шаге деплоя); версия `1.5.5` в `pyproject.toml`, `app/main.py`, `frontend/package.json`, `package-lock.json`, README и записи `[1.5.5]` CHANGELOG; `DEPLOYMENT.md` §6.4–6.5 — версия из тега и порядок «сначала CI, потом тег»; тесты `test_docker_compose_uses_dynamic_image_version` и `test_deploy_workflow_passes_image_version_from_tag` добавлены, `tests/test_deployment.py` — 23 passed, `ruff`/`mypy` чисто. Тег `v1.5.5` ставится только после зелёного CI на `main`.

> **Расширение RAG (вне релиза):** скачать дополнительные статьи MSD Vet
> Manual, прогнать `scripts/ingest_knowledge.py` (upsert безопасен для текущих
> 77 чанков) и замерить hit rate на 10–20 вопросах. Оценка 0.5–1 день, зависит
> от прав на использование текстов; код-изменений не требует.

---

## Стабилизация v1.6.1 (T-143–T-145)

Hotfix по итогам аудита падений и глюков после v1.6.0. Приёмочная
тест-матрица v1.6.1 пройдена на production edge-стеке 2026-11-06.

### [x] T-143. Hotfix падений и глюков (H-1…H-5)
- **Зависит от:** T-134, T-121
- **Что:** Закрыть пять дефектов, найденных при аудите: H-1 — segfault
  `llama.cpp` при параллельных запросах; H-2 — повторный `/link` в боте;
  H-3 — устаревшая дата в ответах; H-4 — `<think>` в ответах Qwen3; H-5 —
  дубли уведомлений в Telegram.
- **DoD:** стресс-тест H-1 без `exit 139`; `<think>` не просачивается в
  нестриминговые ответы и SSE; дата в промпте актуальна; повторный `/link`
  даёт понятную ошибку; уведомление приходит только после `book_appointment`.
- **Оценка:** 1
- **Статус:** выполнено: общий `threading.Lock` вокруг вызовов
  `llama-cpp-python`, потоковый фильтр `think`-тегов, строка
  `Сегодня/Завтра` в системном промпте, сообщение при 403 в боте,
  уведомления только для записи. Детали — `docs/CHANGELOG.md` §1.6.1.

### [x] T-144. GPU-бэкенд с fallback на CPU
- **Зависит от:** T-143
- **Что:** Добавить GPU-инференс через LM Studio (OpenAI-протокол, обратный
  SSH-туннель) и автоматический fallback на CPU: probe раз в 15 с,
  circuit breaker (3 ошибки → cooldown 180 с), fallback стрима до первого
  чанка, `/health` с активным бэкендом и метрики `vet_llm_backend_*`.
- **DoD:** переключение GPU→CPU и CPU→GPU без рестарта API; при недоступном
  GPU запросы обслуживает CPU; в `/health` виден `backend`; тесты роутера и
  бэкендов зелёные.
- **Оценка:** 1.5
- **Статус:** выполнено: `app/backends.py` (`GpuHttpBackend`,
  `CpuLlamaBackend`), `app/router.py` (`BackendRouter`), настройки
  `VET_API_GPU_BACKEND_*`. Приёмка: Function Calling на GPU — **3.4 с**
  вместо **75 с** на CPU (ускорение ≈20×).

### [x] T-145. Очистка осиротевших контейнеров
- **Зависит от:** T-143, T-144
- **Что:** При деплое v1.6.1 на сервере остался осиротевший контейнер
  `60577ee94155_vetassistant-api`: он держал имя `vetassistant-api` и мешал
  пересозданию сервиса. Сисадмин предложил добавить
  `docker compose up -d --remove-orphans` в пайплайн.
- **Решение:** Флаг добавлен в оба места, где стек поднимается без сборки:
  1. `.github/workflows/deploy.yml` — шаг «Pull and rebuild on server»:
     `docker compose -f docker-compose.edge.yml up -d --no-build --remove-orphans`.
  2. `scripts/restart_prod.sh` — ручной перезапуск с той же командой, чтобы
     поведение пайплайна и ручного деплоя не расходилось.
  `--remove-orphans` удаляет только контейнеры того же compose-проекта,
  которых нет в актуальном compose-файле; Caddy, Prometheus и Grafana живут
  в других проектах и не затрагиваются. Сборка образов остаётся в
  `deploy.yml` — флаг не влияет на теги `VETASSISTANT_VERSION`.
- **DoD:** в `deploy.yml` и `restart_prod.sh` есть `--remove-orphans`;
  повторный деплой не падает на конфликте имён; тесты workflow и скрипта
  обновлены; `DEPLOYMENT.md` §6.6 описывает поведение; `pytest`/`ruff` зелёные.
- **Оценка:** 0.25
- **Статус:** выполнено: флаг добавлен в `deploy.yml` и
  `scripts/restart_prod.sh`, тесты `test_remove_orphans_is_used_by_deploy_and_restart`
  и проверки строк обновлены, `DEPLOYMENT.md` §6.6 дополнен. Проверка на
  сервере — при следующем деплое: `docker ps -a --filter name=vetassistant`
  не должен показывать контейнеров с hash-префиксом.

---

## Фаза 6 (v1.7.0) — масштабирование и удобство

**Статус:** ✅ закрыта 2026-11-08 релизом v1.7.0: hybrid RAG (Hit@3
70.6 % → 100 %, MRR 0.912) и 85 с полного E2E на GPU (≈10× быстрее CPU).
Патч v1.7.1 — T-147 (прямой запуск скриптов).

Базовый функционал закрыт в v1.6.0: привязка Telegram, общие записи и
уведомления работают. Следующая итерация — про качество ответов, наблюдаемость
и удобство эксплуатации, а не про новые крупные подсистемы.

### [x] T-137. Планирование v1.7.0
- **Зависит от:** T-134
- **Что:** Собрать backlog версии v1.7.0: 3–4 задачи, которые дают наибольший эффект при умеренном риске, с оценками, зависимостями и критериями готовности. Выбор задачи — после подтверждения сисадмином, что привязка Telegram на проде работает.
- **Решение:** В backlog добавлены четыре кандидата: T-138 (токены в стриме), T-139 (обратная связь), T-140 (управление пользователями), T-141 (hybrid search). Приоритет — по пользе для пользователя и эксплуатации, а не по размеру оценки:

  | Задача | Польза | Риск | Оценка | Приоритет |
  |---|---|---|---|---|
  | T-141 Hybrid Search | точность RAG на названиях препаратов | средний: новая зависимость и качество поиска надо доказать замером | 1.5 | 1 |
  | T-140 Управление пользователями | безопасность и поддержка | средний: миграция и защита от блокировки последнего админа | 2 | 2 |
  | T-138 Токены в стриме | полные метрики и аналитика | низкий: счётчики модели вместо `usage` | 1 | 3 |
  | T-139 Feedback | датасет для DPO/SFT | высокий: в БД попадают тексты диалогов (ПДн) | 2 | 4 |
- **DoD:** в `TODO.md` есть четыре задачи с «Что/Решение/DoD/Оценка/Статус»; у каждой указаны зависимости и риск; рекомендация по порядку обоснована; коммит `docs: prepare v1.7.0 backlog` запушен в `main`; реализация не начата до отдельного сигнала.
- **Оценка:** 0.5
- **Статус:** выполнено: backlog v1.7.0 ниже; T-138–T-141 — кандидаты, ожидают выбора. Версия `v1.7.0` будет присвоена выбранной итерации; T-134.7 (Telegram Login Widget) остаётся опциональным и в план не входит.

### [x] T-141. Hybrid Search в RAG (BM25 + векторы)
- **Зависит от:** T-026, T-124, T-133, T-145
- **Что:** `app/knowledge.py` ищет только по эмбеддингам ChromaDB (`top_k=3`).
  Точные названия препаратов, дозировки и редкие термины векторный поиск
  иногда «размывает»; BM25 по тем же чанкам должен вытаскивать буквальные
  совпадения. Нужен гибридный поиск с замером hit rate до/после.
- **Важное открытие:** корпус MSD Vet Manual **англоязычный** (17 статей,
  `data/knowledge/real/*.txt`), а вопросы — русские; три демо-файла русские,
  но маленькие. «Чистый» BM25 по русскому запросу находит **0/17** нужных
  статей: слова «ксилит» в английском тексте нет. Поэтому лексический канал
  работает только вместе с русско-английским глоссарием и понижением веса
  русских токенов — иначе BM25 выбирает русские демо-файлы вместо профильной
  статьи и тянет гибрид вниз.
- **Подтверждено на сервере (2026-11-08):** Hit@3 **70.6 % → 100 %**
  (vector 12/17 → hybrid 17/17), MRR **0.912** против 0.676, p95 140.3 мс
  против 54.5 мс (+85.8 мс в бюджете +100 мс). Вес
  `VET_API_RAG_BM25_WEIGHT=1.0` утверждён.
- **Решение:**
  1. **BM25 без новой зависимости.** Свой Okapi BM25 в `app/rag_hybrid.py`
     (~60 строк): `k1=1.5`, `b=0.75`, токенизация `[а-яёa-z0-9]+`, лёгкое
     снятие английского `-s` (`grapes`→`grape`). `rank-bm25` не тянем:
     production-образ не пересобирается ради пакета, тесты идут без сети.
  2. **Глоссарий RU→EN** (`RU_EN_TERMS`, ~110 основ): ксилит→xylitol,
     фомепизол→fomepizole, фенобарбитал→phenobarbital, ацетилцистеин→
     acetylcysteine и т. д. Совпадение по префиксу с окончанием ≤3 символов
     (`ксилитом`→`ксилит`); короткие ключи (`кот`, `узи`, `шок`) — только
     точно. Если перевод найден, вес русских токенов запроса понижается до
     `0.25` (`DEFAULT_RU_FALLBACK_WEIGHT`), чтобы английские статьи выигрывали
     у русских демо-файлов.
  3. **Заголовок чанка как отдельное поле.** `scripts/ingest_knowledge.py`
     теперь пишет в metadata `title` (строка `Title:` у MSD-статей, иначе
     первая содержательная строка). BM25 повторяет токены заголовка
     `title_weight=2` — заголовок весомее тела.
  4. **Слияние RRF.** Вектор top-`candidates` + BM25 top-`candidates`,
     `score = Σ weight_i / (k + rank_i)`, `k=60`; вес вектора 1.0, вес BM25 —
     настройка. Результат — top_k=3.
  5. **Настройки:** `VET_API_RAG_MODE=vector|hybrid` (default `hybrid`),
     `VET_API_RAG_CANDIDATES=10`, `VET_API_RAG_BM25_WEIGHT=1.0`; прокинуты в
     три compose-файла и оба `.env*.example`.
  6. **Деградация:** если BM25/коллекция недоступны — прозрачный fallback на
     vector с warning в лог; `vector` остаётся доступен флагом. Индекс BM25
     строится при старте API, поэтому после `ingest_knowledge.py` API нужно
     перезапустить (описано в `DEPLOYMENT.md`).
  7. **Замер:** `scripts/evaluate_hybrid_rag.py` проверяет не ответ модели, а
     **поиск**: попал ли ожидаемый источник в top_k. Режимы `bm25` (офлайн,
     без Chroma), `vector`, `hybrid`, `both` (на сервере); считает hit rate,
     MRR, среднее и p95 времени.
- **Подзадачи:**
  - [x] **T-141.1. BM25, токенизация, RRF.** `app/rag_hybrid.py`:
    `tokenize`, `BM25Index`, `reciprocal_rank_fusion`; параметры проверяются,
    RRF детерминирован при равных score.
  - [x] **T-141.2. Глоссарий и веса.** `RU_EN_TERMS`, `weight_query_terms`;
    русские токены при наличии перевода весят 0.25.
  - [x] **T-141.3. Hybrid-режим в `ChromaKnowledgeBase`.** `search_details`
    с источниками, `mode`, `bm25_size`, fallback на vector, ленивое чтение
    чанков через `collection.get`.
  - [x] **T-141.4. Заголовки чанков в ingest.** `document_title`, metadata
    `title`, тесты на MSD-заголовок и fallback.
  - [x] **T-141.5. Настройки, compose, env.** `AppSettings`, три compose,
    `.env.example`, `.env.production.example`, тесты конфигурации.
  - [x] **T-141.6. Скрипт замера и офлайн-прогон.** 17 вопросов (12 из T-133
    + 5 с названиями препаратов). Офлайн на 766 чанках: BM25 без глоссария —
    **0/17 (0 %)**, BM25 с глоссарием и весами — **17/17 (100 %)**, MRR 0.931,
    p95 поиска 3.6 мс. Все пять «препаратных» вопросов — rank 1.
  - [x] **T-141.7. Замер vector vs hybrid на сервере.** 2026-11-08,
    production-индекс, 17 вопросов: vector — 12/17 (70.6 %), MRR 0.676,
    p95 54.5 мс; hybrid — **17/17 (100 %)**, MRR 0.912, p95 140.3 мс.
    Критерии выполнены: hit rate выше, все вопросы в top-3, p95 в бюджете
    (+85.8 мс из 100). Вес `VET_API_RAG_BM25_WEIGHT=1.0` утверждён.
  - [x] **T-141.8. Документация.** README (раздел RAG), `DEPLOYMENT.md`
    (режимы, пересборка индекса, откат на vector, §6.7 — запуск новых
    скриптов на старом образе), отчёт
    `docs/development/reports/RAG_EVAL.md` §8.
  - [x] **T-141.9. Релиз v1.7.0.** Версия поднята в `pyproject.toml`,
    `app/main.py`, `frontend/package.json`, `frontend/package-lock.json` и
    README; CHANGELOG получил дату и серверную таблицу; тег `v1.7.0`
    ставится только после зелёного CI на `main`.
- **DoD:** hybrid не ухудшает hit rate и заметно улучшает точные названия
  препаратов на контрольной выборке; vector-only остаётся доступен флагом;
  тесты токенизации, BM25, RRF, fallback и настроек; `pytest`/`ruff`/`mypy`
  зелёные; README/DEPLOYMENT описывают режимы и пересборку индекса;
  серверный замер зафиксирован в RAG_EVAL.md.
- **Оценка:** 1.5
- **Статус:** выполнено: код, тесты, офлайн-замер (17/17) и серверный замер
  (hybrid 17/17 против vector 12/17) закрыты; вес BM25 = 1.0; входит в
  v1.7.0.

### [x] T-146. Фикс зависания CI на self-hosted runner
- **Зависит от:** T-145
- **Что:** Прогон CI для v1.7.0 завис на шаге `Post Set up Python 3.12`
  больше чем на 18 минут: `actions/setup-python@v5` с `cache: pip`
  синхронизировал кэш с GitHub Cache Service, что в российских сетях
  приводит к зависанию. Раннер пришлось перезапускать вручную.
- **Решение:** убрать `cache: pip` и `cache-dependency-path` у
  `actions/setup-python@v5` — на self-hosted раннере pip-кэш лежит локально
  и переживает прогоны; ограничить job `lint-and-test` 20 минутами, чтобы
  зависший job убивался автоматически; закрепить оба правила тестом.
- **DoD:** в `ci.yml` нет cache-параметров у setup-python; у job
  `lint-and-test` стоит `timeout-minutes: 20`; тест зелёный; CI на v1.7.0
  проходит без зависаний.
- **Оценка:** 0.25
- **Статус:** выполнено: `ci.yml` обновлён, добавлен
  `test_ci_has_no_pip_cache_and_job_timeout`; CI на `a4fc3d3` зелёный
  (Frontend, Docker Build, Lint & Test), релиз v1.7.0 выпущен.

### [x] T-147. Прямой запуск скриптов оценки RAG
- **Зависит от:** T-141
- **Что:** `python scripts/evaluate_hybrid_rag.py` внутри контейнера падал с
  `ModuleNotFoundError: No module named 'scripts'`: при прямом запуске в
  `sys.path[0]` попадает только `scripts/`, а импорт
  `from scripts.evaluate_rag import ...` требует корень репозитория в пути.
- **Решение:** bootstrap в начале `scripts/evaluate_hybrid_rag.py` и
  `scripts/evaluate_rag.py`:
  `sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`.
  Работают оба варианта — `python scripts/...` и `python -m scripts....` —
  из корня репозитория и из `/app` внутри контейнера; `DEPLOYMENT.md` §6.7
  описывает оба.
- **DoD:** `--dry-run` проходит обоими способами; `ruff`/`mypy` зелёные;
  документация обновлена; патч входит в v1.7.1.
- **Оценка:** 0.25
- **Статус:** выполнено: bootstrap добавлен в оба скрипта, проверены
  `python scripts/evaluate_hybrid_rag.py --dry-run`,
  `python -m scripts.evaluate_hybrid_rag --dry-run` и
  `python scripts/evaluate_rag.py --dry-run`; входит в v1.7.1.

---

## Фаза 7 (v1.8.0) — безопасность, наблюдаемость и обратная связь

**Статус:** запланирована. Фаза 6 закрыта 2026-11-08 релизом v1.7.0
(hybrid RAG, Hit@3 100 %); патч v1.7.1 — T-147.

В релиз выбраны три задачи. Порядок — по риску и зависимостям: сначала
безопасность (T-140), затем наблюдаемость (T-138), затем обратная связь
(T-139 — только после решения по хранению текстов диалогов).

| Задача | Польза | Риск | Оценка | Приоритет |
|---|---|---|---|---|
| T-140 Управление пользователями | безопасность и поддержка | средний: миграция `users.is_active` | 2 | 1 |
| T-138 Токены в стриме | полная аналитика Grafana | низкий: счётчики модели вместо `usage` | 1 | 2 |
| T-139 Feedback 👍/👎 | датасет для DPO/SFT | высокий: тексты диалогов (ПДн) | 2 | 3 (stretch) |

### [x] T-140. Управление пользователями в админке
- **Зависит от:** T-120, T-039
- **Что:** В админ-панели есть только заявки на доступ: нельзя увидеть всех
  пользователей, заблокировать нарушителя или удалить аккаунт. Блокировка
  должна мгновенно закрывать доступ по уже выданному JWT.
- **Решение:**
  - `users.is_active BOOLEAN NOT NULL DEFAULT TRUE` (миграция + SQL);
    `POST /v1/auth/login` для заблокированного → `403`, `get_current_user`
    проверяет `is_active` (действующие токены перестают работать без T-105).
  - API `GET /v1/admin/users?query=&status=&limit=&offset=` (без
    `hashed_password`), `POST /v1/admin/users/{id}/block` и `/unblock` с
    причиной, `DELETE /v1/admin/users/{id}` — каскад
    `appointments`/`reminders`/`telegram_link_codes`,
    `access_requests.reviewed_by/approved_user_id → NULL`; запись в
    `admin_actions` (actor_id, action, target_id, reason, created_at).
  - Защита: нельзя блокировать/удалять себя и последнего активного админа;
    удаление только с подтверждением по email; все действия — в лог без
    паролей и токенов.
  - UI: третья вкладка «Пользователи» в `AdminDashboard` — поиск, фильтр
    all/active/blocked, пагинация, бейджи, block/unblock, delete с
    подтверждением.
- **Подзадачи:**
  - [x] **T-140.1. Схема и миграция.** `users.is_active`,
    `admin_actions`, идемпотентная миграция в `create_tables` + SQL для
    прода (`scripts/migrations/2026-11-08_user_management.sql`).
  - [x] **T-140.2. API модерации.** Список с пагинацией и фильтрами,
    block/unblock/delete, защита себя и последнего админа, запись в
    `admin_actions`; `get_current_user` возвращает 403 заблокированному.
  - [x] **T-140.3. Действующие JWT.** Проверка `is_active` в login (в
    `get_current_user` уже есть, T-140.2); заблокированный получает 403/401.
  - [x] **T-140.4. Frontend.** Вкладка «Пользователи» с поиском, фильтром,
    пагинацией и подтверждениями.
  - [x] **T-140.5. Тесты и документация.** Каскады, защита, 403 не-админу;
    `DEPLOYMENT.md` — миграция и откат.
- **DoD:** заблокированный не входит (403), его старый JWT получает 401/403;
  каскадное удаление не оставляет осиротевших записей; нельзя
  заблокировать/удалить себя и последнего админа; не-админ получает 403; UI
  и тесты зелёные; `DEPLOYMENT.md` описывает миграцию и откат.
- **Оценка:** 2
- **Статус:** выполнено в v1.8.0: миграция, список с пагинацией,
  block/unblock/delete, аудит `admin_actions`, 403 по действующему JWT и при
  входе, вкладка «Пользователи»; тесты и документация обновлены.

### [x] T-138. Точные токены и usage в стриминге
- **Зависит от:** T-117, T-135
- **Что:** React-UI по умолчанию использует `stream: true`, а
  `llama-cpp-python` в стриме не отдаёт `usage`: в `app/main.py::_stream`
  счётчики `prompt_tokens`/`completion_tokens` остаются нулями. Из-за этого
  `vet_llm_prompt_tokens_total`, `vet_llm_completion_tokens_total`,
  `vet_llm_completion_tokens_per_second`, `vet_llm_user_tokens_total{kind}`
  и админская аналитика (T-135) видят только нестриминговые запросы.
- **Решение:**
  1. Не пытаться получить `stream_options.include_usage` у
     `create_chat_completion`: в актуальной `llama-cpp-python` такого
     параметра нет. Считать токены в API.
  2. Ввести `app/inference_usage.py` (или расширить `ChatModel`): точный
     prompt — `Llama.n_tokens` после префилла (снять при первом чанке),
     completion — дельта `n_tokens` в конце либо число сгенерированных
     чанков; для моделей без `n_tokens` — fallback на `model.tokenize()` и
     пометку «оценка» в логах.
  3. В `_stream`/`_stream_with_tools` передавать usage в `record_generation`
     и `record_user_usage` в `finally`/`else`; не считать токены при отмене
     стрима как успешные (status отдельно).
  4. Сверить на 20 промптах (короткие/длинные/RAG/tools) с нестриминговым
     `usage`; расхождение ≤1 % — принять, иначе оставить fallback и
     задокументировать.
- **Подзадачи:**
  - [x] **T-138.1. Счётчик usage.** `app/inference_usage.py` + тест с
    фейковой моделью, отдающей `n_tokens`.
  - [x] **T-138.2. Интеграция в стрим.** `_stream` и `_stream_with_tools`:
    usage в метрики и финальный SSE-чанк.
  - [x] **T-138.5. Usage в GPU-стриме (v1.8.2).** `GpuHttpBackend` передаёт
    в LM Studio `stream_options: {"include_usage": true}` — без этого параметра
    `usage` в GPU-стриме не приходил; тест на payload запроса.
  - [x] **T-138.3. Сверка.** 20 промптов, расхождение с не-стрим ≤1 %,
    отчёт в `docs/development/reports/`.
  - [x] **T-138.4. Аналитика.** Проверить Grafana и вкладку «Аналитика»
    админки на токенах стрима.
- **DoD:** стриминговые запросы дают ненулевые prompt/completion в метриках;
  расхождение с не-стрим ≤1 % на контрольной выборке; Grafana-панели и
  вкладка «Аналитика» показывают токены стрима; тест с фейковой моделью,
  отдающей `n_tokens` и чанки; `ruff`/`mypy`/`pytest` зелёные.
- **Оценка:** 1
- **Статус:** завершено. T-138.1–T-138.2 в v1.8.1, T-138.5 (usage в
  GPU-стриме) в v1.8.2. По итогам эксплуатации расхождений токенов нет,
  счётчики Prometheus растут (подтверждено сисадмином, 2026-11-09).

### [x] T-139. Обратная связь по ответам (👍/👎)
- **Зависит от:** T-037, T-039
- **Что:** Под ответами ИИ в React нет кнопок оценки, поэтому нельзя собрать
  датасет для будущего DPO/RLHF и понять, какие ответы плохи. История чата
  живёт только в `localStorage`, на сервере пар «вопрос-ответ» нет.
- **Решение (принято):** сырые тексты диалогов в БД не храним (152-ФЗ).
  Таблица `feedback` содержит только `id`, `user_id` (FK `ON DELETE
  CASCADE`), `message_id VARCHAR(128)` (непрозрачный id сообщения на
  клиенте), `rating SMALLINT CHECK (rating IN (-1, 1))`, `created_at`;
  `UNIQUE (user_id, message_id)` — одна оценка на сообщение, повторная
  перезаписывает (upsert). Комментарии, `prompt`/`answer` и экспорт JSONL
  в этот релиз не входят: для DPO потребуется отдельное согласование ПДн.
- **Подзадачи:**
  - [x] **T-139.1. База данных.** Модель `Feedback` в `app/database.py` и
    идемпотентная миграция `scripts/migrations/2026-11-09_feedback.sql`
    (таблица, индексы по `user_id`/`message_id`, уникальность, CHECK);
    оценки удаляются каскадом вместе с аккаунтом.
  - [x] **T-139.2. API.** `POST /v1/feedback` (JWT) с `{message_id, rating}` —
    upsert без дублей; `GET /v1/admin/feedback/stats` — общее число оценок,
    👍/👎 и доля положительных.
  - [x] **T-139.3. Frontend.** Кнопки 👍/👎 в `MessageBubble` для
    завершённых ответов, активное состояние выбранной оценки, отправка
    `POST /api/v1/feedback`, неблокирующие ошибки.
  - [x] **T-139.4. Админка.** KPI-карточка «Рейтинг ответов» (доля 👍) на
    вкладке «Аналитика» в `AdminDashboard`/`AdminAnalytics`.
  - [x] **T-139.5. Тесты.** Валидация, 401/403, upsert и права, изоляция
    пользователей, каскад при удалении, ограничения схемы БД, наличие
    миграции; frontend-тесты API-клиента.
- **DoD:** одна оценка на сообщение без дублей; не-админ не получает сводку;
  оценки удаляются вместе с аккаунтом; текстов диалогов в БД нет; UI
  показывает выбранное состояние; `pytest`/`ruff`/`mypy` и frontend-проверки
  зелёные.
- **Оценка:** 2
- **Статус:** выполнено в v1.9.0.

### Порядок работ и DoD релиза v1.8.0

1. T-140.1–T-140.2: схема, миграция и API модерации → ревью.
2. T-140.3–T-140.5: блокировка JWT, UI, тесты, документация.
3. T-138.1–T-138.4: usage в стриме, сверка, аналитика.
4. T-139.1 — решение по ПДн; если «нет» — T-139 переносится в v1.9.0, релиз
   выпускается с T-140 + T-138.

- **DoD релиза:** выбранные задачи закрыты; миграции идемпотентны на SQLite и
  PostgreSQL; `pytest`/`ruff`/`mypy`/frontend-проверки зелёные;
  CHANGELOG/README/DEPLOYMENT обновлены; тег `v1.8.0` — только после
  зелёного CI.
- **Оценка:** 4–5 (T-140 — 2, T-138 — 1, T-139 — 2 при включении).

## Бэклог v1.11.0 и далее

В v1.10.0 вошли T-150 (экспорт оценок) и T-151 (активность DAU/WAU).
T-152 (автобэкап) закрыт сисадмином: бэкапы в S3 настроены, restore
проверен. В v1.11.0 вошла T-153 (i18n, RU/EN).

### [x] T-150. Экспорт оценок для DPO/SFT
- **Зависит от:** T-139
- **Что:** Оценки 👍/👎 лежат в `feedback`, но выгрузить их нельзя: нельзя
  собрать датасет для будущего DPO/SFT и проанализировать оценки вне
  админки. Сейчас доступна только агрегированная сводка
  `GET /v1/admin/feedback/stats`.
- **Решение:**
  1. `scripts/export_feedback.py` (запуск и как `python -m
     scripts.export_feedback`, и напрямую): JSONL, одна запись —
     `{"message_id", "rating", "created_at"}`. Тексты диалогов не выгружаются
     (152-ФЗ): только id и оценка; `user_id` по умолчанию не пишется
     (при необходимости — флаг `--include-user-id` с псевдонимизацией).
  2. Фильтры `--since`/`--until`, `--rating 1|-1`, `--limit`; вывод в stdout
     или `--output FILE`; коды выхода 0/1/2 как у остальных скриптов.
  3. Документация: `DEPLOYMENT.md` (запуск в контейнере) и `README.md`
     (как связать `message_id` с текстом на клиенте).
- **DoD:** валидный JSONL со стабильным порядком; фильтры и пустая БД
  покрыты тестами; в выгрузке нет текстов сообщений; `ruff`/`mypy`/`pytest`
  зелёные.
- **Оценка:** 1
- **Статус:** выполнено в v1.10.0: `scripts/export_feedback.py` (JSONL
  `message_id`/`rating`/`created_at`, фильтры `--since/--until/--rating/--limit`,
  stdout или `--output`, `user_id` — только по флагу и как HMAC-псевдоним с
  солью `VET_EXPORT_PSEUDONYM_SALT`); 21 тест, документация в
  `DEPLOYMENT.md` §8.

### [x] T-151. Активность пользователей в админке (DAU/WAU)
- **Зависит от:** T-135, T-139
- **Что:** На вкладке «Аналитика» есть KPI, ряды запросов/токенов и таблица
  топ-пользователей, но нет динамики по дням: нельзя увидеть, сколько
  уникальных пользователей приходит каждый день (DAU/WAU) и кто активнее
  всех за окно.
- **Решение:**
  1. `GET /v1/admin/activity?window=7d|30d`: по Prometheus
     `vet_llm_user_requests_total` — DAU по дням (уникальные `user_id` с
     приростом за сутки) и WAU (уникальные за 7 дней); топ-5 по числу
     запросов за окно с email из БД (переиспользовать `_resolve_top_users`).
  2. Fallback без Prometheus — пустые ряды и «история недоступна» без
     ошибок, как в `/v1/admin/metrics`.
  3. Frontend: в `AdminAnalytics` — график DAU/WAU (столбцы или Sparkline) и
     компактный топ-5 за окно; существующую таблицу топ-пользователей
     дополнить запросами за окно, чтобы не дублировать данные.
- **DoD:** эндпоинт и UI-карточка с графиком и топ-5; тесты расчёта
  DAU/WAU и fallback-режима; обновлены `DEPLOYMENT.md`/README-раздел
  админки; frontend — lint/test/build зелёные.
- **Оценка:** 2
- **Статус:** выполнено в v1.10.0: `GET /v1/admin/activity?window=7d|30d`
  (DAU по дням и WAU из `vet_llm_user_requests_total`, graceful fallback
  `source="unavailable"`), панель «Активность пользователей» в
  `AdminAnalytics` с переключателем 7/30 дней, графиком и карточками DAU/WAU;
  8 тестов. Топ-5 не дублировался — он уже есть в `/v1/admin/metrics`.

### [x] T-152. Автоматический бэкап PostgreSQL и `data/` в S3 (Selectel)
- **Зависит от:** нет (инфраструктурная задача)
- **Что:** Бэкапы PostgreSQL делаются вручную по `DEPLOYMENT.md` §12, папка
  `data/` (ChromaDB, база знаний) не резервируется вовсе, off-site копии
  нет. Потеря диска или ошибочная миграция уносит данные и индекс RAG.
- **Решение:**
  1. `scripts/backup_prod.sh`: `pg_dump` через
     `docker compose -f docker-compose.edge.yml exec -T db`, архив
     `data/chroma_db` и `data/knowledge` (`tar.gz`; GGUF-модели не включать —
     они воспроизводятся из DVC), sha256-чексуммы, дата в имени.
  2. Выгрузка в S3 Selectel (`aws s3 cp --endpoint-url` или `rclone`),
     бакет и ключи — в `.env`/секретах, не в Git; retention 7 daily + 4
     weekly.
  3. Расписание: cron или systemd timer (03:00 MSK), уведомление в Telegram
     при ошибке, лог в `/var/log/vetassistant-backup.log`.
  4. `DEPLOYMENT.md` §12: ежедневный бэкап, ротация, восстановление
     (`restore`-инструкция) и проверка на тестовой БД.
- **DoD:** ежедневный бэкап без ручных действий; копии в S3 и ротация;
  уведомление о сбое; `bash -n`/тесты парсинга имени и retention зелёные;
  восстановление описано и проверено; секреты не в Git.
- **Оценка:** 3
- **Статус:** выполнено (сисадмин): ежедневные бэкапы PostgreSQL и `data/`
  выгружаются в S3, retention настроен, restore проверен на тестовой БД.

### [x] T-153. Мультиязычность интерфейса (i18n, EN)
- **Зависит от:** T-037
- **Что:** React-интерфейс полностью на русском, хотя API и часть контента
  допускают английский. Для международных пользователей нужен переключатель
  RU/EN без перезагрузки и без дублирования строк по компонентам.
- **Решение:**
  1. Лёгкий i18n-слой (React-контекст + типизированные словари
     `locales/ru.ts`, `locales/en.ts`) или `i18next`, если понадобятся
     плюрализация/интерполяция. Все пользовательские строки вынести из
     компонентов: чат, авторизация, настройки, «Мои записи», ошибки.
     Админка — вторая итерация (может остаться RU в первом шаге).
  2. Переключатель RU/EN в настройках и на экране входа, выбор в
     `localStorage`, `document.documentElement.lang`, форматирование
     дат/чисел через `Intl`.
  3. Ошибки API маппить по HTTP-статусу/коду, а не по русскому тексту.
- **DoD:** переключение языка без перезагрузки; в пользовательских
  компонентах нет захардкоженных строк (тест на полноту словарей);
  `npm run lint`/`npm test`/`npm run build` зелёные; README описывает, как
  добавить новый язык.
- **Оценка:** 3
- **Статус:** выполнено в v1.11.0: `react-i18next` + словари
  `locales/ru.json`/`en.json`, переключатель RU/EN в сайдбаре, на экране
  входа и в настройках; выбор в `localStorage`, мгновенное переключение,
  `document.documentElement.lang`, даты/числа через `Intl`. Админка
  переведена полностью. Добавлены `i18n.test.ts` и проверка полноты
  словарей; README описывает добавление нового языка.

## Релиз v1.12.0

**Статус:** ✅ T-154 официально закрыта (2026-11-16): сисадмин подтвердил,
что независимый язык админки работает, чат не переключается, настройки
сохраняются. v1.12.0 и v1.12.1 задеплоены на прод (`https://app.ai-pets.ru`).
T-155 (датасет для DPO) и T-156 (расширение RAG) вошли в v1.13.0.

### [x] T-154. UI/UX: светлая тема, горячие клавиши и мобильная вёрстка
- **Зависит от:** T-037
- **Что:** Интерфейс сейчас только тёмный (`color-scheme: dark` в
  `frontend/src/index.css`), из горячих клавиш — только Enter/Shift+Enter в
  composer. Добавить светлую тему и переключатель «светлая / тёмная /
  системная» с сохранением в `localStorage`; вынести палитру в CSS-переменные
  и проверить контраст всех экранов, включая админку. Добавить `Ctrl/Cmd+K`
  для фокуса на поле поиска (поиск пользователей в админке; в чате — поиск по
  истории, если он появится) и не перехватывать хоткей во время ввода в
  textarea. Проверить и поправить мобильную вёрстку на 320–768 px: сайдбар
  как drawer, composer, сообщения, таблицы и диалоги админки.
- **DoD:** тема переключается без перезагрузки, выбор сохраняется, системная
  тема подхватывается через `prefers-color-scheme`; `Ctrl/Cmd+K` ставит
  курсор в поиск и не конфликтует с вводом; на 360/768 px нет
  горизонтального скролла и перекрытий; есть тесты на применение/сохранение
  темы и на хоткей; `npm run lint`/`npm test`/`npm run build` зелёные;
  README/CHANGELOG обновлены.
- **Оценка:** 2
- **Статус:** выполнено в v1.12.0: темы Light / Dark / System
  (`frontend/src/lib/theme.ts`, `ThemeSwitcher`, ключ `vetassistant.theme`,
  CSS-переменные и Tailwind-токены в `index.css`), тема применяется до
  первого рендера; хоткеи `Ctrl/Cmd+K`, `Ctrl/Cmd+Enter`, `Esc`
  (`lib/hotkeys.ts`, модалки и drawer); сайдбар-drawer до 768 px,
  увеличенные touch-цели, safe-area, прокрутка вкладок админки; RU/EN в
  шапке админки и spinner при отправке. Добавлены `theme.test.ts` и
  `hotkeys.test.ts`; `npm run lint`/`npm test` (95)/`npm run build` зелёные.

#### [x] T-154.5. Независимый язык админ-панели (v1.12.1)
- **Что:** переключатель RU/EN в админке менял глобальный язык и переводил
  чат; требовался отдельный язык только для админки.
- **Статус:** выполнено в v1.12.1: ключ `vetassistant.admin.language`,
  отдельный i18n-инстанс (`lib/adminI18n.ts`, `AdminI18nProvider`),
  `AdminLanguageSwitcher`, fallback на глобальный язык и кнопка «Как в чате»;
  даты и метрики админки форматируются по её языку. Тесты независимости
  языков добавлены в `i18n.test.ts` (100 тестов).

### [x] T-155. Сбор данных для DPO: пары оценок и `message_id`
- **Зависит от:** T-139, T-150
- **Что:** Оценки 👍/👎 лежат в `feedback` (`message_id`, `rating`,
  `created_at`), а `scripts/export_feedback.py` (T-150) отдаёт их плоским
  JSONL. Для будущего DPO/SFT нужен воспроизводимый датасет: собрать пары
  «оценка ↔ `message_id`», нормализовать и провалидировать их, разделить на
  train/val и посчитать сводку (число 👍/👎, покрытие, период). Пока **без
  текстов** (152-ФЗ): только `message_id`, `rating`, `created_at` и, по
  флагу, псевдоним пользователя; формат — JSONL + JSON-отчёт.
- **Решение:** переиспользовать `select_feedback_rows`/`build_records` из
  T-150, не дублировать доступ к БД; новый `scripts/build_dpo_dataset.py`
  читает БД или готовый JSONL и кладёт `data/dpo/…` и манифест для будущей
  привязки текстов на клиенте. Честные пары «prompt → chosen/rejected» без
  текстов и `conversation_id` не строятся — это отдельный этап после
  согласования ПДн.
- **DoD:** датасет и отчёт детерминированы; пустая БД, фильтры по периоду и
  рейтингу, повторные оценки покрыты тестами; в выгрузке нет текстов
  сообщений и реальных `user_id`; `ruff`/`mypy`/`pytest` зелёные;
  документация в `DEPLOYMENT.md`/README.
- **Оценка:** 1.5
- **Статус:** выполнено в v1.13.0: `scripts/build_dpo_dataset.py` строит
  `data/dpo/train.jsonl`, `val.jsonl` и `manifest.json` (80/20, seed 42);
  в строках только `message_id`, `rating`, `split`. Источник — таблица
  `feedback` или готовый JSONL (`--input`); фильтры `--since/--until/
  --rating/--limit`, дедупликация по `message_id` (остаётся свежая оценка),
  `--dry-run`. Тексты и `user_id` не выгружаются (152-ФЗ).

#### Подзадачи T-155

- [x] **T-155.1. Скрипт `scripts/build_dpo_dataset.py`.**
  - Чтение `feedback` через `fetch_feedback_rows` из T-150 или JSONL через
    `--input`; `--database-url`, `--output-dir`, `--train-ratio`, `--seed`,
    `--since`, `--until`, `--rating`, `--limit`, `--dry-run`.
  - Дедупликация по `message_id`, детерминированный train/val-сплит,
    `train.jsonl`/`val.jsonl`/`manifest.json` с периодами, счётчиками 👍/👎
    и пометкой об отсутствии текстов.
  - DoD: пустая БД даёт пустые файлы и валидный манифест; повторный запуск
    побайтово воспроизводим; тексты и `user_id` не попадают в выгрузку.

- [x] **T-155.2. Тесты `tests/test_build_dpo_dataset.py`.**
  - 80/20, детерминированность, дедупликация повторных оценок, фильтры,
    режим JSONL без БД, пустая БД, битый JSONL, неверный `--train-ratio`,
    взаимоисключающие `--input`/`--database-url`, отсутствие текстов.
  - DoD: 25 тестов зелёные; `ruff`/`mypy` чисто.

### [x] T-156. Расширение RAG: ещё 5–10 статей MSD по узким темам
- **Зависит от:** T-133, T-141
- **Что:** T-133 закрыл базовое расширение (10 статей, 766 чанков).
  Догрузить ещё 5–10 статей MSD Vet Manual по узким темам, которых нет в
  индексе: стоматология, офтальмология, дерматология, ортопедия и т. п.
  Скачать через `scripts/download_msd.py --url`, положить в
  `data/knowledge/real/`, проиндексировать `scripts/ingest_knowledge.py`
  (upsert безопасен) и проверить, что hybrid-поиск не деградировал.
- **DoD:** 5–10 новых статей в Git и доступны после `git pull`; индекс вырос
  с 766 чанков; `scripts/evaluate_hybrid_rag.py` на 15–20 вопросах по новым
  темам даёт hit rate не ниже текущего, регрессии на старых 17 вопросах нет;
  тесты ingestion и `pytest`/`ruff`/`mypy` зелёные; README и
  `docs/development/reports/RAG_EVAL.md` обновлены.
- **Оценка:** 1.5
- **Статус:** выполнено в v1.13.0: добавлены 10 статей MSD по стоматологии,
  офтальмологии, эндокринологии, дерматологии, ортопедии, нефрологии и
  респираторным болезням (`scripts/download_msd.py --batch expansion`);
  в `evaluate_hybrid_rag.py` — 10 новых вопросов (всего 27), офлайн-BM25
  с глоссарием даёт 27/27; инструкция по скачиванию и переиндексации —
  `DEPLOYMENT.md` §«Как добавить новые статьи в RAG».

## Релиз v1.14.0 (Фаза 8) — память и карточки пациентов

**Статус:** 📋 план на согласовании. Код ещё не пишется: сначала сисадмин
применяет SQL-миграцию `scripts/migrations/2026-11-16_patients.sql`
(и переводит БД на образ с pgvector), затем начинаем T-160…T-165.
**Цель:** ассистент перестаёт быть stateless-ботом: помнит питомцев
пользователя, историю эпизодов и релевантные прошлые обсуждения, умеет
сам предложить создать карточку питомца.
**Оценка:** 10 (T-160 — 2, T-161 — 1.5, T-162 — 2, T-163 — 1.5,
T-164 — 2, T-165 — 1).

### Архитектурные решения и ограничения

- **Два диалекта БД.** Прод — PostgreSQL 16 (`asyncpg`), локально и в
  тестах — SQLite (`aiosqlite`). Модель `Episode.embedding` объявляется как
  `Vector(384)` для PostgreSQL и как `JSON` для SQLite
  (`JSON().with_variant(Vector(384), "postgresql")`). Размерность 384 —
  это `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
  (`VET_API_EMBEDDING_MODEL`), та же модель, что у RAG. Константа
  `MEMORY_EMBEDDING_DIM = 384` выносится в `app/memory.py`; смена модели —
  отдельная миграция.
- **⚠ Блокер для сисадмина: в проде нет pgvector.** Сейчас БД поднимается
  образом `postgres:16-alpine` (`docker-compose.edge.yml`), а в нём нет
  расширения `vector`. Нужно одно из двух:
  1. **Рекомендуется:** заменить образ на `pgvector/pgvector:pg16`
     (тот же major PostgreSQL 16, существующий volume
     `postgres_data` совместим; остановить `db`, обновить образ,
     `up -d db`, затем применить миграцию);
  2. либо установить пакет `postgresql-16-pgvector` внутри контейнера —
     менее воспроизводимо, теряется при пересоздании контейнера.
  Без этого миграция упадёт на `CREATE EXTENSION vector`, а API будет
  работать в degraded-режиме (память без семантического поиска).
- **Совместимость и безопасный rollout.** Миграция применяется **до**
  деплоя v1.14.0. При этом API обязан не падать, если таблиц ещё нет:
  чтение/запись эпизодов оборачивается в try/except с warning, чат
  продолжает работать без памяти. Старые клиенты не ломаются:
  `patient_id` опционален, `ChatCompletionRequest` уже игнорирует лишние
  поля.
- **152-ФЗ.** `episodes.content` — только краткое описание (≤ 500
  символов), без телефонов, email, адресов и полных диалогов; тексты
  сообщений целиком не дублируются. Удаление пользователя каскадно
  удаляет пациентов и эпизоды (`ON DELETE CASCADE`). Retention-политика
  (автоочистка, например 180 дней) — отдельная задача T-166, в v1.14.0
  фиксируем правило в SECURITY/README и не выгружаем эпизоды в DPO.
- **Порядок вставки в промпт:** базовый system prompt → контекст пациента
  (профиль + эпизоды) → RAG-контекст → инструкция инструментов →
  экстренная инструкция. Бюджет памяти — не более 1200 символов, чтобы
  не вытеснить RAG и историю диалога из `n_ctx=4096`.
- **Эпизоды не заменяют историю чата.** `messages` по-прежнему передаёт
  клиент; память добавляет только профиль и выжимки прошлых эпизодов.

### [x] T-160. Схема БД и модели пациентов/эпизодов
- **Зависит от:** —
- **Что:** модели `Patient` и `Episode`, repository-функции, SQL-миграция
  для PostgreSQL, совместимость со SQLite и `create_all`.

#### Подзадачи T-160
- [x] **T-160.1. Модели и repository в `app/database.py`.**
  - `Patient`: `id`, `user_id` FK → `users.id` (`ON DELETE CASCADE`,
    индекс), `name` (≤ 120, trim), `species` (`dog`/`cat`, CHECK),
    `breed` (≤ 120, nullable), `birth_date` (Date, nullable, не в
    будущем), `weight` (Numeric(6,2), nullable, > 0), `known_allergies`
    (Text, nullable), `chronic_conditions` (Text, nullable),
    `created_at`, `updated_at` (обновляется в ORM через `onupdate`).
  - `Episode`: `id` (BigInteger), `patient_id` FK → `patients.id`
    (`ON DELETE CASCADE`, индекс), `user_id` FK → `users.id`
    (`ON DELETE CASCADE`), `type` (`chat`/`appointment`/`reminder`/
    `manual`, CHECK), `content` (Text, ≤ 500), `embedding` (Vector(384)
    / JSON-вариант), `created_at`. Составной индекс
    `(patient_id, created_at DESC)`.
  - Функции: `create_patient`, `list_patients`, `get_patient`
    (с проверкой владельца), `update_patient`, `add_episode`,
    `list_episodes(limit/offset)`, `count_episodes`,
    `search_similar_episodes` (PG: `embedding <=> :vec` + `LIMIT`;
    SQLite: косинус в Python по последним 200 эпизодам, чтобы тесты
    шли без pgvector).
  - DoD: `create_all` создаёт таблицы на SQLite; для PostgreSQL
    `create_tables` дополнительно выполняет
    `CREATE EXTENSION IF NOT EXISTS vector`; типы/mypy чистые.

- [x] **T-160.2. SQL-миграция `scripts/migrations/2026-11-16_patients.sql`.**
  - `BEGIN; CREATE EXTENSION IF NOT EXISTS vector;` → `patients` →
    `episodes` → индексы (`ix_patients_user_id`,
    `ix_episodes_patient_created`, `ix_episodes_user_id`,
    HNSW `ix_episodes_embedding_hnsw USING hnsw (embedding
    vector_cosine_ops)`) → `COMMIT;`.
  - Идемпотентность: `CREATE TABLE IF NOT EXISTS`,
    `CREATE INDEX IF NOT EXISTS`; комментарии в шапке — назначение,
    порядок применения, проверка (`\d patients`, `\dx vector`),
    откат (`DROP TABLE episodes, patients`), оценка времени.
  - В шапке — явное требование к образу БД с pgvector и команда
    применения через `docker compose ... exec -T db psql < ...`.
  - DoD: миграция проверена на копии прод-БД (или чистом
    `pgvector/pgvector:pg16`), повторный запуск не падает; файл
    передан сисадмину.

- [x] **T-160.3. Тесты схемы и repository (`tests/test_patients_repository.py`).**
  - CRUD, каскадное удаление пользователя, `species`/`weight`/`birth_date`
    ограничения, ownership (чужой пациент не читается и не правится),
    пагинация истории, дедупликация/сортировка эпизодов, семантический
    поиск на SQLite-фолбэке с детерминированным fake-embedder,
    отсутствие embedding не ломает поиск.
  - DoD: тесты зелёные на SQLite; `ruff`/`mypy` чисто.

### [x] T-161. API карточек пациентов (CRUD)
- **Зависит от:** T-160
- **Что:** четыре эндпоинта в `app/main.py` и Pydantic-схемы; все
  запросы скоупятся `current_user.id`.

#### Подзадачи T-161
- [x] **T-161.1. Схемы и эндпоинты.**
  - `PatientCreate` (`name`, `species`, `breed`, `birth_date`, `weight`,
    `known_allergies`, `chronic_conditions`), `PatientUpdate` (все поля
    optional, PATCH-семантика, явный `null` очищает поле),
    `PatientRead` (+ `age_years` из `birth_date`), `EpisodeRead`,
    `PatientHistory` (`items`, `total`, `limit`, `offset`).
  - `GET /v1/patients` — только свои, сортировка по `created_at`.
  - `POST /v1/patients` — 201, валидация species/weight/дат.
  - `PATCH /v1/patients/{id}` — 404 для чужого (не раскрываем
    существование), обновляет `updated_at`.
  - `GET /v1/patients/{id}/history?limit=20&offset=0` — limit 1…100,
    новые сверху, `total` для UI.
  - DoD: OpenAPI отражает схемы; ошибки 401/404/422 единообразны.

- [x] **T-161.2. Тесты API (`tests/test_patients_api.py`).**
  - Изоляция пользователей (A не видит и не правит пациента B),
    пагинация и границы `limit`, пустая история, невалидные поля,
    PATCH дозаполнения, каскад после удаления пользователя.
  - DoD: тесты зелёные; покрыты 401 без токена и 404 на чужие id.

### [x] T-162. Слой памяти (Memory Router)
- **Зависит от:** T-160, T-161
- **Что:** `app/memory.py` — сборка контекста перед LLM и сохранение
  эпизода после ответа; graceful degradation без эмбеддингов.

#### Подзадачи T-162
- [x] **T-162.1. `PatientMemory` и провайдер эмбеддингов.**
  - Ленивая загрузка `SentenceTransformer` (та же модель, что RAG),
    инъекция fake-embedder в тестах; кэш модели на процесс.
  - `build_context(session, user_id, patient_id, query)`:
    профиль (имя, вид, порода, возраст, вес, аллергии, хроника) +
    последние 5 эпизодов + семантически близкие 3 эпизода
    (`<=>`/косинус), дедупликация, обрезка до 1200 символов,
    формат с заголовком «Карточка питомца и история».
  - Нет пациента → пустая строка (поведение v1.13.0 не меняется).
  - DoD: профиль и эпизоды попадают в промпт; лимит соблюдается.

- [x] **T-162.2. Интеграция до вызова LLM.**
  - В `ChatCompletionRequest` добавить `patient_id: int | None`.
  - В `chat_completions` проверить владельца пациента (404/403),
    вставить контекст памяти после базового system prompt и до RAG,
    для streaming и non-streaming одинаково.
  - DoD: при `patient_id` системный промпт содержит карточку; без него
    запросы побайтово эквивалентны прежним (кроме даты).

- [x] **T-162.3. Сохранение эпизода после генерации.**
  - `type="chat"`, `content` — краткая выжимка (вопрос ≤ 300 символов +
    ключевой вывод ≤ 200), без полного диалога и контактов.
  - Non-stream: после `_complete`; stream: в `finally` генератора
    `_stream`/`_stream_with_tools` (накапливать текст ответа).
  - Best-effort: ошибка БД/эмбеддинга логируется и не ломает ответ;
    эпизод без embedding допустим.
  - DoD: после ответа появляется ровно один эпизод; повторный запрос
    находит его семантически («та же сыпь»).

- [x] **T-162.4. Метрики и логи.**
  - `vet_memory_context_total{result="hit|miss|error"}`,
    `vet_memory_episode_saved_total{result="ok|error"}`, длительность
    поиска; без кардинальности по пользователю.
  - DoD: `/metrics` отдаёт новые счётчики; ошибки не шумят в проде.

- [x] **T-162.5. Тесты (`tests/test_memory.py`).**
  - Профиль в промпте, последние 5 эпизодов, семантический hit,
    дедупликация, лимит 1200 символов, отсутствие пациента, чужой
    пациент, сохранение в stream/non-stream, падение эмбеддера не
    ломает чат, отсутствие таблиц (degraded).
  - DoD: тесты зелёные, fake-embedder детерминирован.

### [x] T-163. Проактивное создание карточки (agentic behavior)
- **Зависит от:** T-161, T-162
- **Что:** инструмент `create_patient` и инструкция предлагать карточку,
  если питомец упомянут, а карточки нет.

#### Подзадачи T-163
- [x] **T-163.1. Инструмент `create_patient`.**
  - JSON-schema: `name` (required), `species` (`dog`/`cat`),
    `breed` (optional), `age` (целые годы, 0…40, optional).
  - `execute_tool` создаёт пациента от имени `user_id` из JWT,
    `age` → приблизительная `birth_date`; повторное создание с тем же
    именем и видом возвращает существующего (`status="exists"`) вместо
    дубликата; возвращает `patient_id` и человекочитаемое сообщение.
  - Добавить инструмент в `AVAILABLE_TOOLS` (`app/tools.py`) и
    `frontend/src/lib/tools.ts`; `ToolName` расширить.
  - DoD: вызов создаёт запись; аргументы валидируются; чужие данные
    недоступны.

- [x] **T-163.2. Проактивная инструкция.**
  - В системный промпт (когда `patient_id` не передан) добавить:
    «Если пользователь упоминает питомца, а карточки нет — предложи
    создать её и спроси имя, вид и возраст; не выдумывай данные».
  - Инструкция вставляется рядом с инструкцией инструментов, не
    перекрывает правила безопасности и RAG.
  - DoD: на «у меня собака Бобик, чешется» модель предлагает карточку
    и/или вызывает инструмент, а не молча ставит диагноз.

- [x] **T-163.3. Серверная инъекция инструмента.**
  - Если `patient_id` не передан и `use_patient_tools=true` (новое поле,
    default true), сервер сам добавляет `create_patient` в эффективный
    список инструментов; клиенту не нужно включать Debug-тумблер
    «Инструменты».
  - Эффективный список используется в `_generation_kwargs`,
    `_tool_names`, `with_tools_instruction`, `_complete` и `_stream`.
  - DoD: старые клиенты получают agentic-поведение; при
    `use_patient_tools=false` ответы прежние.

- [x] **T-163.4. Тесты (`tests/test_patient_tools.py`).**
  - Создание, `age`→`birth_date`, дубликат, невалидные аргументы,
    изоляция пользователей, инъекция инструмента в промпт, отключение
    флагом, agentic loop (tool → ответ модели).
  - DoD: тесты зелёные.

### [x] T-164. UI: выбор питомца и карточка (React)
- **Зависит от:** T-161
- **Что:** селектор «Мой питомец» в сайдбаре, модалка карточки,
  передача `patient_id` во всех запросах чата.

#### Подзадачи T-164
- [x] **T-164.1. Типы и API-клиент.**
  - `Patient`, `PatientHistory`, `PatientCreate/Update` в `types.ts`;
    `fetchPatients`, `createPatient`, `updatePatient`,
    `fetchPatientHistory` в `lib/api.ts`; `buildChatPayload` принимает
    `patientId` и кладёт `patient_id` в payload.
  - DoD: unit-тесты payload/URL/ошибок в `lib/api.test.ts`.

- [x] **T-164.2. Селектор «Мой питомец» в `Sidebar.tsx`.**
  - Dropdown: «Без питомца», список питомцев (имя + вид), пункт
    «＋ Добавить питомца»; выбранный id хранится per-user в
    `localStorage`, сбрасывается, если питомца удалили/нет в списке.
  - Загрузка/ошибка списка не блокируют чат; пустой список показывает
    CTA «Создать карточку».
  - DoD: выбор питомца виден в чате и переживает перезагрузку.

- [x] **T-164.3. Модалка «Карточка питомца» (`PatientCardDialog.tsx`).**
  - Просмотр/редактирование: имя, вид, порода, дата рождения или
    возраст, вес, аллергии, хронические болезни; создание новой карточки
    из селектора и из ответа агента.
  - Валидация на клиенте (обязательные имя/вид, вес > 0), состояния
    loading/error, оптимистичное обновление списка.
  - История эпизодов с пагинацией («Показать ещё»), тип и дата.
  - DoD: создание/редактирование отражаются в селекторе без перезагрузки.

- [x] **T-164.4. Чат и agentic-сценарий.**
  - Все запросы `streamChat` отправляют `patient_id` активного питомца.
  - После tool-call `create_patient` — `loadPatients()` и автовыбор
    созданного питомца (по имени из аргументов), открытие карточки по
    клику на бейдж.
  - i18n RU/EN для всех новых строк; мобильная вёрстка drawer.
  - DoD: Vitest-тесты хелперов/парсинга + `npm run build`; ручной
    сценарий: нет карточки → агент спрашивает данные → карточка
    создана → следующий вопрос уже с памятью.

### [x] T-165. Релиз v1.14.0
- **Зависит от:** T-160…T-164, миграция применена сисадмином
- **Что:** версия, документация, зелёный CI, тег.

#### Подзадачи T-165
- [x] **T-165.1. Версия `1.14.0`** в `pyproject.toml`, `app/main.py`,
  `frontend/package.json`, `frontend/package-lock.json`, README,
  `tests/test_deployment.py`.
- [x] **T-165.2. Документация.**
  - `docs/CHANGELOG.md` — раздел `[1.14.0]` (T-160…T-164, миграция,
    pgvector, приватность).
  - `DEPLOYMENT.md` — раздел «Память и карточки пациентов»: образ
    `pgvector/pgvector:pg16`, применение миграции до деплоя, проверка
    `\dx vector`, откат, smoke-тест чата с `patient_id`.
  - README — возможности, схема API, скриншот/описание селектора,
    ограничения памяти и 152-ФЗ; `SECURITY.md` — что хранится в
    `episodes` и срок хранения.
  - TODO — статусы T-160…T-165 и заметка о T-166 (retention).
- [x] **T-165.3. Локальная проверка:** `pytest` (все тесты),
  `ruff check .`, `mypy app`, `npm run test`, `npm run build`.
- [x] **T-165.4. Релиз:** коммит
  `feat: v1.14.0 - patient cards and memory layer`, push в `main`,
  дождаться зелёного CI, затем тег `v1.14.0` и push тега; проверить
  Deploy workflow и `/api/health`.
- DoD: прод отвечает, `patients`/`episodes` созданы, чат с выбранным
  питомцем использует память, откат описан.
- **Статус:** релиз v1.14.0 опубликован 2026-11-16 (тег `v1.14.0`,
  GitHub Release, CI/Release/Deploy зелёные). Пост-релизный аудит выявил
  T-168/T-169 — исправлены в v1.14.1 (T-169.1).

### [x] T-169.1. Релиз v1.14.1 (хотфикс)
- **Зависит от:** T-168, T-169
- **Что:** версия `1.14.1`, CHANGELOG, отчёт по v1.14.0, коммит
  `fix: tool injection for create_patient and UI CSS bugs (T-168, T-169)`,
  push, зелёный CI, тег `v1.14.1`.
- **DoD:** тег `v1.14.1` опубликован, Release и Deploy зелёные,
  `/api/health` отдаёт версию; отчёты по T-168/T-169 и v1.14.0 в
  `docs/development/reports/`.
- **Оценка:** 1
- **Статус:** выполнено в v1.14.1.

### [x] T-174. Релиз v1.14.2 (патч памяти и записей)
- **Зависит от:** T-170…T-173
- **Что:** версия `1.14.2`, CHANGELOG, README, TODO, отчёт, коммит
  `fix(core): fix pgvector import, create_patient triggers, and hallucination guard (T-170-T-173)`,
  push, зелёный CI, тег `v1.14.2`.
- **DoD:** тег `v1.14.2` опубликован, Release и Deploy зелёные, прод
  отдаёт `1.14.2`; отчёт — `docs/development/reports/RELEASE_v1.14.2.md`.
- **Оценка:** 1
- **Статус:** выполнено в v1.14.2.

### Что нужно от сисадмина до старта T-160

1. Подтвердить переход БД на `pgvector/pgvector:pg16` (рекомендуется)
   либо установку расширения в текущий контейнер.
2. Применить `scripts/migrations/2026-11-16_patients.sql` на проде
   **до** деплоя v1.14.0.
3. Прислать вывод проверки:
   `\dx vector`, `\d patients`, `\d episodes`,
   `SELECT count(*) FROM pg_extension WHERE extname = 'vector';`.
4. Согласовать политику хранения `episodes.content` (краткие выжимки,
   ≤ 500 символов) и срок retention; по умолчанию предлагаем 180 дней
   и отдельную задачу T-166.

### Порядок работ

1. T-160.1 → T-160.2 (миграция сисадмину) → T-160.3.
2. T-161 (API) параллельно с T-164.1 (типы/клиент).
3. T-162 (память) → T-163 (агентное создание).
4. T-164.2–T-164.4 (UI) после стабильного API.
5. T-165: версия/доки → полный прогон → commit → CI → tag.

## Мобильное приложение Android и RuStore — Roadmap (2026-11-19)

**Статус:** 📋 планирование; код Android-приложения не начат. Полный анализ,
сравнение вариантов, требования RuStore, риски и Definition of Done —
в [ANDROID_RUSTORE_ROADMAP.md](docs/development/ANDROID_RUSTORE_ROADMAP.md).
**Текущее состояние:** адаптивный веб (T-154), SSE-чат, карточки пациентов,
память, Telegram-бот. Нет PWA-манифеста, Android-проекта, подписи, push в
RuStore, CI-сборки APK/AAB. **Аккаунт RuStore уже есть:** Андрей Н.
(Андрей Никифоров), VK ID, физическое лицо, права владельца. Документация
RuStore проверена 2026-11-19 по официальным страницам и консоли.
**Рекомендуемый путь:** PWA-база → Capacitor MVP → RuStore; TWA — fallback.
**Зависимости из бэклога:** T-105 (инвалидация JWT), T-136 (докачка SSE),
T-166 (retention 180 дней), T-167 (грязное дерево на сервере).
**Решения (согласовано 2026-11-19):** keystore храните вы (Андрей Н.); push
в MVP не входит — in-app + Telegram, RuStore Push SDK (T-183) в Android v1.1;
ассеты и краш-аналитика — zero-budget, подробности в roadmap §7.

### Спринт 0 (1 неделя) — решение и фундамент

- [x] **T-175. Аудит RuStore и выбор модели доставки.** Утверждены Capacitor
      (TWA — fallback), требования APK/AAB ≤ 5 ГБ, подпись, 14 дней на
      модерацию, лимиты витрины, §2.9/§2.14 правил, 152-ФЗ. Владелец —
      Андрей Н. (VK ID, физлицо). DoD: roadmap §3 проверен 2026-11-19.
- [x] **T-176. PWA-база.** `manifest.webmanifest` (standalone, иконки
      192/512), `sw.js` с кэшем оболочки и без кэша API, мета в `index.html`,
      кнопка «Установить». DoD: тесты `tests/test_pwa.py` и `pwa.test.ts`.
- [x] **T-177. Мобильная готовность API.** Добавлены Origin’ы
      `https://app.ai-pets.ru` и `https://ai-pets.ru` в
      `CORS_ALLOWED_ORIGINS`; прокси `/api` и `VITE_API_BASE_URL` описаны
      в DEPLOYMENT. `android-app://...` — при реализации TWA (T-191).
- [x] **T-178. QA-база в мобильных браузерах.** Чек-лист 12 сценариев,
      матрица устройств и шаблон результатов —
      `docs/development/MOBILE_QA_CHECKLIST.md`. Прогон на реальных
      устройствах — T-188.

### Спринт 1 (2 недели) — MVP Android-обёртки

- [x] **T-179. Capacitor-проект.** `capacitor.config.ts`, `frontend/android/`
      (Capacitor 8), скрипты `android:add/sync/build/open`, документ
      `docs/development/ANDROID_LOCAL_BUILD.md`.
- [x] **T-180. Нативная оболочка.** Лапа в splash/launcher, статус-бар под
      тему, `overlay` + `viewport-fit=cover` safe-area, `touch-action:
      manipulation` и `user-scalable=no`, системная «Назад» закрывает
      модалки/drawer.
- [x] **T-181. Сессия и данные.** `Preferences` на Android вместо
      `localStorage` для JWT; восстановление до рендера через `bootstrap()`;
      in-app SSE/patient picker/карточки работают в той же React-кодовой базе.
      Зависит от T-105 (оставлено в бэклоге).
- [x] **T-182. Подпись и сборка.** `signingConfigs.release` в `build.gradle`
      читает keystore из env, `versionCode/versionName` из CI; job
      `android-build` (debug всегда, release при секретах) и `android-release`
      с прикреплением AAB/APK к GitHub Release. Фактический подписанный
      артефакт появится после того, как владелец добавит 4 GitHub Secret.

### Спринт 2 (2 недели) — ссылки и офлайн

- [ ] **T-184. In-app-уведомления и deep links.** `vetassistant://patient/{id}`
      и/или App Links `https://app.ai-pets.ru/...`, `assetlinks.json` при
      TWA/App Links; переход из уведомления в карточку/приём; тесты внешнего
      перехода. Системный push в MVP не входит (решение п. 7.3 roadmap).
- [ ] **T-185. Офлайн-деградация.** Кэш последних диалогов/карточек,
      состояния «нет сети», очередь повтора фидбека. Частично зависит
      от T-136.

### Спринт 3 (2 недели) — подготовка к RuStore

- [ ] **T-186. Юридическое и приватность.** Обновлённые privacy/terms,
      согласие 152-ФЗ, удаление данных, возрастной рейтинг, дисклеймеры;
      анкета «Безопасность данных пользователя»; соответствие §2.9 и §2.14
      правил модерации (без гарантий излечения и debug-признаков).
- [ ] **T-187. Витрина.** Название ≤ 30 симв., категория, краткое описание
      ≤ 80 и полное ≤ 4000 симв., иконка 512×512 ≤ 3 МБ с заливкой,
      минимум 3 скриншота на тип устройства, RU/EN-описания, контакт
      (Email/сайт/ВК/МАКС), age rating, release notes. Ассеты — zero-budget
      по умолчанию (иконка из SVG + скриншоты с рабочего приложения).
- [ ] **T-188. RC-тестирование.** Матрица из п. 7.4 roadmap (Android 10–15,
      Samsung/Xiaomi/Honor/чистый Android, 3 размера экрана, RU/EN и тёмная
      тема), доступность, обрывы сети, чек-лист модерации. Краш-аналитика —
      self-hosted Sentry плюс отзывы RuStore.
- [ ] **T-189. Публикация.** Первая загрузка, отправка на модерацию в течение
      14 дней после обработки файла, тестовый/открытый track, мониторинг
      отзывов и метрик, план отката.

### Спринт 4 (Android v1.1 и далее) — развитие после первой публикации

- [ ] **T-183. RuStore Push SDK.** Системные уведомления внутри приложения,
      регистрация токена, разрешения, сервер отправки, deep link из
      уведомления. Вынесен из MVP по согласованному решению (п. 7.3 roadmap).
- [ ] **T-190. Нативные возможности.** Биометрия, камера (фото питомца),
      геолокация клиник, виджет напоминания.
- [ ] **T-191. TWA-fallback.** Сборка Trusted Web Activity по PWA-базе,
      если Capacitor не проходит модерацию или срываются сроки.
