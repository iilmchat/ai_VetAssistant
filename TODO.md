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

---

## Backlog

### [ ] T-013. Архитектура «Router & Triage»
- **Зависит от:** T-012
- **Что:** Микро-модели на входе: классифицировать экстренность обращения и детектировать prompt-инъекции до основного ассистента, маршрутизировать запросы в safety/emergency-ветку.
- **DoD:** Роутер с измеренными precision/recall на эталонной выборке и тестами на инъекции; интеграция в пайплайн ассистента.
- **Оценка:** 2
