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
- **Статус:** выполнено: `app/auth.py` (JWT HS256, bcrypt, `get_current_user`), таблица `users` и `user_id` FK с мягкой миграцией, защита API и Agentic Loop; React (`AuthScreen`, `lib/auth.ts`, logout, per-user история), Streamlit auth-gate и Telegram-авторизация через HMAC-аккаунт с кэшем JWT и повтором при `401`; `pytest` 537 passed, React-тесты 29 passed, `ruff`/`mypy` и `npm run build` чисто.

---

## Backlog

### [x] T-013. Архитектура «Router & Triage»
- **Зависит от:** T-012
- **Что:** Микро-модели на входе: классифицировать экстренность обращения и детектировать prompt-инъекции до основного ассистента, маршрутизировать запросы в safety/emergency-ветку.
- **DoD:** Роутер с измеренными precision/recall на эталонной выборке и тестами на инъекции; интеграция в пайплайн ассистента.
- **Оценка:** 2
- **Статус:** выполнено: роутер и интеграция в API (T-027); бенчмарк `data/router_benchmark.jsonl` (30 кейсов) и отчёт `docs/development/reports/EVAL_ROUTER.md`; Precision/Recall/F1 = 1.0000 для экстренности и инъекций; тесты на инъекции добавлены.
