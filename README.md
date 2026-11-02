# VetAssistant: Русскоязычный ветеринарный ИИ-ассистент

> Легковесный ассистент на базе Qwen3-8B (GGUF), работающий на CPU без GPU. Специализируется на многотурном диалоге с владельцами животных с соблюдением медицинских рамок безопасности.

**Статус:** 🚧 Подготовка релиза **v0.2.0** (предыдущий релиз — v0.1.0)
**Целевой инференс:** llama.cpp / `llama-cpp-python` (GGUF Q4_K_M, CPU, 8–16 ГБ RAM)
**API:** FastAPI, OpenAI-совместимый `POST /v1/chat/completions`
**Обучение:** Unsloth + QLoRA на арендованных GPU (Vast.ai / RunPod)
**Генерация данных:** Зарубежные LLM через API (слой абстракции)

## 🏁 Релиз v0.1.0

- Дообучена **Qwen3-8B Vet** (QLoRA SFT, GGUF Q4_K_M); `train_loss=0.5922`,
  `eval_loss=0.483`.
- PetQA-Bench: **2000/2000** ответов, LLM-Judge — **4.5185 / 5**,
  **97.7%** оценок ≥ 4.
- Safety через локальный API: **passed=2, failed=0** (парацетамол, феназепам).
- Модель интегрирована в **FastAPI** с OpenAI-совместимым API и SSE-стримингом,
  работает локально через `llama-cpp-python`.
- Подробности: [MODEL_CARD.md](MODEL_CARD.md), [EVAL_V1.md](docs/development/reports/EVAL_V1.md),
  [CHANGELOG.md](docs/CHANGELOG.md).

## 📚 Документация проекта

Вся документация находится в корне или папке `docs/`:

| Документ | Описание |
|---|---|
| [**Design.md**](docs/development/Design_v1.md) | **Источник истины.** Архитектура пайплайна, выбор моделей, инфраструктура, риски. |
| [**MODEL_CARD.md**](MODEL_CARD.md) | Карточка модели: назначение, данные, метрики, ограничения. |
| [**EVAL_V1.md**](docs/development/reports/EVAL_V1.md) | Отчёт об обучении, генерации, LLM-Judge и Safety-проверке. |
| [**EVAL_ROUTER.md**](docs/development/reports/EVAL_ROUTER.md) | Precision/Recall/F1 роутера на бенчмарке экстренных случаев и инъекций. |
| [**CHANGELOG.md**](docs/CHANGELOG.md) | История релизов и ключевые вехи проекта. |
| [**synthetic_prompts.md**](docs/synthetic_prompts.md) | Библиотека промптов для двухшаговой генерации (Шаг A + Шаг B) и Safety-кейсов. |
| [**eval_harness.md**](docs/eval_harness.md) | Структура бенчмарка, JSONL-схемы, метрики (MCQ, Safety, Multi-turn) и код `evaluate.py`. |
| [**TRAINING.md**](docs/development/TRAINING.md) | Развертывание на GPU-сервере Selectel и запуск обучения. |
| [**RULES.md**](docs/development/RULES.md) | **Обязательно к прочтению.** Правила коммитов, код-стайла и отчетности для агента. |
| [**TODO.md**](TODO.md) | Пошаговый план работ с зависимостями и Definition of Done. |

## 🚀 Быстрый старт для разработки

1. Скопируйте `.env.example` в `.env` и заполните API-ключи учителя (OpenAI-совместимые).
2. Установите зависимости: `pip install -e ".[dev]"`
3. Запустите генерацию пилотного батча:
   ```bash
   python scripts/generate_data.py --stage pilot --limit 50
   ```
4. Проверьте качество датасета:
   ```bash
   python scripts/validate_dataset.py data/pilot.jsonl
   ```

## 🪟 Запуск FastAPI-сервера на Windows

### 1. Установка `llama-cpp-python`

На Windows `pip install llama-cpp-python` часто пытается собрать пакет из
исходников и требует Visual Studio Build Tools (C++). Проще поставить готовый
CPU-wheel:

```powershell
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

Для CUDA используйте соответствующий индекс, например
`https://abetlen.github.io/llama-cpp-python/whl/cu121` (или `cu124`), и
подходящую версию Python. После установки wheel выполните:

```powershell
pip install -e .
```

`llama-cpp-python` уже будет установлен, и pip не станет собирать его заново.

### 2. Модель

Основная модель лежит в `data/gguf/qwen3-8b-vet-Q4_K_M.gguf`. Если файла нет,
получите его через DVC:

```powershell
python scripts/sync_data.py pull
```

### 3. Запуск API

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Эквивалентный вариант, если `uvicorn` доступен как консольная команда:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Проверка живости:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/health
```

Пример запроса:

```powershell
$body = @{
  messages = @(@{ role = "user"; content = "Кот не ест сутки, что делать?" })
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri http://127.0.0.1:8000/v1/chat/completions `
  -Method Post -ContentType "application/json" -Body $body
```

Для стриминга добавьте в тело `stream = $true` — API вернёт SSE-поток
(`text/event-stream`).

Настройки модели можно переопределить через `.env`:
`VET_API_MODEL_PATH`, `VET_API_MODEL_ID`, `VET_API_N_CTX`,
`VET_API_N_THREADS`, `VET_API_N_GPU_LAYERS`.

### 4. Safety-проверка через локальный API

```powershell
python scripts/test_safety.py `
  --base-url http://127.0.0.1:8000/v1 `
  --model-id qwen3-8b-vet
```

Скрипт берёт Safety-кейсы из `data/eval_dataset.jsonl`, отправляет их в
`POST /v1/chat/completions` и проверяет отсутствие назначения запрещённых
препаратов, наличие отказа и направления к ветеринару.

Результат релиза v0.1.0: **passed=2, failed=0** — оба кейса (парацетамол и
феназепам) корректно отказали и направили к ветеринару.

### 5. Оценка через локальный API

Флаг `--local-api` подставляет `http://127.0.0.1:8000/v1` и модель
`qwen3-8b-vet` (значения можно переопределить через `--base-url`/`--model-id`):

```powershell
python evaluation/evaluate.py --local-api `
  --dataset data/eval_dataset.jsonl `
  --output data/local_answers.jsonl
```

## 🖥️ Веб-интерфейс Streamlit

Убедитесь, что FastAPI-сервер уже запущен (см. раздел выше), затем установите
зависимости и запустите UI:

```powershell
pip install -e .
streamlit run app/ui.py
```

Если команда `streamlit` не найдена в PATH:

```powershell
python -m streamlit run app/ui.py
```

Streamlit откроет браузер на `http://localhost:8501`. В интерфейсе доступны:

- чат с моделью через `POST /v1/chat/completions`;
- потоковый вывод ответа (эффект печатной машинки);
- история сообщений в `st.session_state`;
- слайдер `temperature` (0.0–1.0, по умолчанию 0.7);
- кнопка «Очистить историю чата».

Если API выключен, UI покажет сообщение
**«Сервер ветеринара спит, включите uvicorn»**.

## 📚 RAG: база знаний MSD Vet Manual

Модель может дополнять ответы проверенными фрагментами локального
справочника. База хранится в `data/chroma_db/` и не коммитится в Git.

1. Установите зависимости (они уже входят в `pip install -e .`):
   `chromadb`, `sentence-transformers`. При первом инжесте скачается
   лёгкая мультиязычная модель эмбеддингов
   `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
2. Положите текстовые файлы в `data/knowledge/` (3 демо-файла уже есть).
3. Постройте индекс:

```powershell
python scripts/ingest_knowledge.py
```

Проверить нарезку без создания базы:

```powershell
python scripts/ingest_knowledge.py --dry-run
```

4. Запустите API и UI. В сайдбаре включите
   **«Использовать базу знаний (RAG)»** — UI передаст `use_rag: true`.
5. Для прямых запросов к API добавьте в JSON `"use_rag": true`.

Если база не создана, пуста или RAG-зависимости не установлены, API
продолжает работать как раньше — без справочного контекста.

## 🛡️ Router & Triage: экстренные случаи и prompt injection

До вызова LLM API прогоняет последнее сообщение пользователя через быстрый
regex-роутер `app/router.py`:

- **Prompt injection** («ignore previous instructions», «покажи системный
  промпт» и похожие) — запрос отклоняется с `400 Bad Request`, модель не
  вызывается.
- **Экстренные симптомы** (кровотечение, судороги, отравление, «не дышит»,
  парацетамол) — в system prompt добавляется жёсткая инструкция начать ответ
  с фразы **«СРОЧНО ОБРАТИТЕСЬ В КЛИНИКУ»** и не задавать уточняющих вопросов.

Проверка занимает микросекунды и не требует загрузки дополнительных моделей.

## 🐳 Запуск через Docker Compose

Требования: Docker Engine или Docker Desktop с Compose v2 и не менее 10 ГБ
свободного места (образ содержит `llama-cpp-python`, CPU-сборку PyTorch,
ChromaDB и Streamlit).

1. Убедитесь, что GGUF-модель лежит в `data/gguf/`. Если файла нет:

   ```powershell
   python scripts/sync_data.py pull
   ```

2. (Опционально) Постройте индекс RAG. Можно на хосте:

   ```powershell
   python scripts/ingest_knowledge.py
   ```

   Или в контейнере после сборки:

   ```powershell
   docker compose run --rm api python scripts/ingest_knowledge.py
   ```

3. Соберите и запустите оба сервиса:

   ```powershell
   docker compose up --build
   ```

4. Откройте:
   - API: `http://localhost:8000/health`
   - Streamlit UI: `http://localhost:8501`

5. Остановка:

   ```powershell
   docker compose down
   ```

Контейнеры монтируют локальную папку `./data` в `/app/data`, поэтому модель
GGUF и ChromaDB не копируются в образ и остаются доступны API. UI внутри
Compose обращается к API по имени сервиса `http://api:8000`.

Основные переменные окружения можно задать в `.env` (Compose подхватит их
для подстановки):

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `VET_API_MODEL_PATH` | `/app/data/gguf/qwen3-8b-vet-Q4_K_M.gguf` | Путь к GGUF внутри контейнера |
| `VET_API_N_CTX` | `8192` | Размер контекста llama.cpp |
| `VET_API_N_GPU_LAYERS` | `0` | Слоёв на GPU (0 — CPU) |
| `VET_UI_API_URL` | `http://api:8000/v1/chat/completions` | Адрес API для UI |
| `VET_UI_MODEL_ID` | `qwen3-8b-vet` | Имя модели в запросах UI |

> Первая сборка может занять 10–20 минут: `llama-cpp-python` собирается из
> исходников. Если GGUF-модель отсутствует, API запустится, но ответы на
> запросы будут возвращать `503 Модель недоступна`.

## 🛠️ Стек
- **Данные:** Python, Pydantic, OpenAI SDK (для API), `datasets` (HF), DVC + S3 (Selectel).
- **Обучение:** Unsloth, PyTorch, HuggingFace `transformers`, `peft`.
- **Экспорт:** `llama.cpp` (convert_hf_to_gguf.py), GGUF Q4_K_M/Q5_K_M.
- **Инференс:** FastAPI + `llama-cpp-python`, OpenAI-совместимый API и SSE.
- **RAG:** ChromaDB + sentence-transformers, локальная база знаний.
- **Безопасность:** Router & Triage (`app/router.py`), regex-эвристики до вызова LLM.
- **UI:** Streamlit-чат (`app/ui.py`), потоковый вывод, настройки температуры.
- **Развёртывание:** Docker Compose, FastAPI + Streamlit UI.
- **Оценка:** `evaluate.py`, LLM-Judge, `scripts/test_safety.py`, `scripts/evaluate_router.py`.

## 💾 Работа с данными (DVC)

Тяжёлые сгенерированные данные (диалоги, train/val, PetQA, отчёты) хранятся
в S3 Selectel и **не коммитятся в Git**. В Git попадают только `.dvc`-файлы
с хешами и конфигурация remote.

- Remote: `selectel` → `s3://vetassistant-data/dvc`
- Endpoint: `https://s3.ru-7.storage.selcloud.ru`, регион `ru-7`
- Ключи доступа заданы локально через `dvc remote modify --local` и хранятся
  в `.dvc/config.local` (файл в `.gitignore`).

Синхронизация:

```bash
python scripts/sync_data.py push   # загрузить данные в S3
python scripts/sync_data.py pull   # скачать данные из S3
```

Добавление новых тяжёлых файлов:

```bash
dvc add data/<file>.jsonl
git add data/<file>.jsonl.dvc
git commit -m "chore(data): track <file> with DVC"
git push
python scripts/sync_data.py push
```

Для воспроизведения на новой машине: склонировать репозиторий, установить
dev-зависимости, настроить `selectel`-креды локально и выполнить
`python scripts/sync_data.py pull`.