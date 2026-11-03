# VetAssistant: Русскоязычный ветеринарный ИИ-ассистент

[![CI](https://github.com/iilmchat/ai_VetAssistant/actions/workflows/ci.yml/badge.svg)](https://github.com/iilmchat/ai_VetAssistant/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/badge/latest_release-v0.5.0-blue)](https://github.com/iilmchat/ai_VetAssistant/releases/latest)

> Легковесный ассистент на базе Qwen3-8B (GGUF), работающий на CPU без GPU. Специализируется на многотурном диалоге с владельцами животных, соблюдает медицинские рамки безопасности, вызывает инструменты, сохраняет записи в базе данных и опирается на MSD Vet Manual.

**Статус:** ✅ Релиз **v0.5.0** (2026-11-03) — полноценное веб-приложение
**Новое в v0.5.0:** React 19 UI, SSE-стриминг, Function Calling в браузере, Docker/Nginx
**Telegram:** отдельный процесс/контейнер `bot`; запись питомца на приём и напоминания прямо из чата
**Web:** React 19 + Vite + TypeScript + Tailwind CSS — SSE-чат в стиле ChatGPT, настройки и «Мои записи»
**Auth:** JWT (HS256), bcrypt-пароли и изоляция записей по `user_id` в вебе, Streamlit и Telegram
**Production:** Ubuntu VPS, Docker Compose, единый домен и HTTPS через Let's Encrypt
**Порты:** `80`/`443` — production, `3000` — Docker dev/Nginx, `5173` — Vite dev server
**CI/CD:** GitHub Actions — линтеры, тесты, Docker-сборка и автоматические GitHub Releases по тегам
**Дистрибуция:** Docker Compose (`docker compose up --build`)
**Целевой инференс:** llama.cpp / `llama-cpp-python` (GGUF Q4_K_M, CPU, 8–16 ГБ RAM)
**API:** FastAPI, OpenAI-совместимый `POST /v1/chat/completions`
**Обучение:** Unsloth + QLoRA на арендованных GPU (Vast.ai / RunPod)
**Генерация данных:** Зарубежные LLM через API (слой абстракции)

## 🏁 Релиз v0.5.0 — полноценное веб-приложение

[![React-интерфейс VetAssistant](docs/assets/react-ui.png)](docs/assets/react-ui.png)

- **React 19 Frontend**: новый SPA в `frontend/` на Vite, TypeScript и
  Tailwind CSS 4 — чат в стиле ChatGPT с боковой панелью и адаптивной
  вёрсткой для телефона.
- **SSE-стриминг**: ответы `/v1/chat/completions` появляются постепенно;
  генерацию можно остановить, Markdown и таблицы рендерятся через
  `react-markdown`.
- **UI для Function Calling**: переключатели RAG и инструментов,
  `temperature`, зелёные/янтарные бейджи записей и напоминаний, блок
  **«Мои записи»**.
- **Docker/Nginx**: multi-stage `frontend/Dockerfile`, сервис `frontend` в
  Compose на порту **3000**; Nginx раздаёт SPA и проксирует `/api/*` в
  `api:8000` без буферизации SSE.
- **CORS и тесты**: FastAPI разрешает `localhost:5173` для Vite; **22**
  фронтенд-теста и **518** тестов проекта.
- Подробности: [CHANGELOG.md](docs/CHANGELOG.md).

## 🏁 Предыдущие релизы

### v0.4.0 — 2026-11-03 — Telegram-бот

- **Telegram-бот** на aiogram 3.x: отдельный процесс `python -m bot` и
  контейнер `bot`; команды `/start`, `/reset` и `/help`.
- **История диалогов** для каждого пользователя: бот передаёт предыдущие
  сообщения в API и помнит контекст беседы.
- **Function Calling**: запись питомца на приём и создание напоминаний с
  понятными подтверждениями прямо в чате.
- **Интеграция с API**: бот использует тот же локальный
  `POST /v1/chat/completions` с RAG и инструментами; ошибки API
  показываются пользователю человекочитаемо.
- **Docker Compose**: сервис `bot` зависит от здорового `api` и читает
  `TELEGRAM_BOT_TOKEN`; без токена API и Streamlit UI продолжают работать.
- **Тесты**: **516** тестов, включая клиент API и логику бота с фейковыми
  Telegram и FastAPI.
- Подробности: [CHANGELOG.md](docs/CHANGELOG.md).

### v0.3.0 — 2026-11-03 — Autonomous Agent

- **Agentic Loop**: модель вызывает `book_appointment` и `set_reminder`, API
  выполняет инструменты, передаёт результат обратно модели и возвращает
  финальный ответ.
- **База данных**: PostgreSQL 16 в Docker Compose и async SQLAlchemy 2.0;
  записи и напоминания сохраняются в volume и не теряются при перезапуске.
  Локально используется async SQLite.
- **Реальный RAG**: загрузка статей MSD Vet Manual, поддержка TXT/PDF,
  ChromaDB и мультиязычная модель эмбеддингов.
- **Streamlit UI**: потоковый чат, RAG, Function Calling, бейджи инструментов
  и раздел **«Мои записи»**.
- **CI/CD**: GitHub Actions проверяет `ruff`, `mypy`, `pytest` (**487 тестов**),
  собирает Docker-образ и публикует GitHub Release по тегу `v*`.
- Подробности: [CHANGELOG.md](docs/CHANGELOG.md),
  [EVAL_ROUTER.md](docs/development/reports/EVAL_ROUTER.md).

### v0.2.0 — 2026-11-03

- **Streamlit UI** с потоковым выводом, историей чата и настройкой RAG.
- **RAG на ChromaDB**: локальная база знаний MSD Vet Manual и
  мультиязычная модель эмбеддингов.
- **Router & Triage**: мгновенная детекция экстренных симптомов и
  prompt injection до вызова LLM; F1 = **1.0000** на бенчмарке.
- **Docker-дистрибутив**: FastAPI и Streamlit UI одной командой
  `docker compose up --build`.
- **CI/CD**: GitHub Actions проверяет `ruff`, `mypy`, `pytest` и собирает
  Docker-образ на каждый push/PR в `main`.
- Подробности: [CHANGELOG.md](docs/CHANGELOG.md),
  [EVAL_ROUTER.md](docs/development/reports/EVAL_ROUTER.md).

### v0.1.0 — 2026-11-02

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
| [**BRANCH_PROTECTION.md**](docs/development/BRANCH_PROTECTION.md) | Настройка защиты `main`: PR, обязательные CI-проверки. |
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
- переключатель Function Calling и бейджи вызова инструментов;
- раскрывающийся список **«Мои записи»** с приёмами и напоминаниями;
- кнопка «Очистить историю чата».

Если API выключен, UI покажет сообщение
**«Сервер ветеринара спит, включите uvicorn»**.

## ⚛️ React-веб-интерфейс

Современный чат в стиле ChatGPT: React 19, Vite, TypeScript и Tailwind CSS 4.
Ответы приходят через SSE и появляются постепенно, Markdown и таблицы
рендерятся через `react-markdown`, а вызовы `book_appointment` и
`set_reminder` показываются зелёными и янтарными бейджами.

В интерфейсе есть:

- экран входа и регистрации: без JWT показывается форма, после входа токен
  хранится в `localStorage`;
- кнопка **«Выйти»** и email текущего пользователя в сайдбаре;
- боковая панель с настройками `temperature`, RAG и Function Calling;
- блок **«Мои записи»** с приёмами (`/v1/appointments`) и напоминаниями;
- история диалога в `localStorage` отдельно для каждого пользователя,
  кнопка «Новый чат» и остановка генерации;
- индикатор доступности API и адаптивная вёрстка для телефона.

### Локальный запуск (порт 5173)

Нужен Node.js 20.19+ (или 22.12+) и запущенный FastAPI на
`http://127.0.0.1:8000`.

```powershell
cd frontend
npm install
npm run dev
```

Откройте `http://localhost:5173`. По умолчанию фронтенд обращается к
`http://127.0.0.1:8000`; адрес можно изменить в `frontend/.env`:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_MODEL_ID=qwen3-8b-vet
```

FastAPI разрешает CORS для `http://localhost:5173` и
`http://127.0.0.1:5173`. Проверка сборки и тестов:

```powershell
cd frontend
npm run build
npm test
npm run lint
```

### Запуск в Docker (порт 3000)

```powershell
docker compose up --build frontend
```

Фронтенд будет доступен на `http://localhost:3000`. Nginx раздаёт статику и
проксирует `/api/*` в сервис `api`, поэтому браузер не обращается к
`api:8000` напрямую, а SSE не буферизуется.

## 🤖 Telegram-бот

Бот работает отдельным процессом, хранит историю диалога для каждого
пользователя и обращается к тому же FastAPI. Поддерживаются команды
`/start`, `/reset`, `/help`, а также Function Calling: запись питомца на
приём и создание напоминания.

### 1. Получите токен у @BotFather

1. Откройте в Telegram бота **[@BotFather](https://t.me/BotFather)**.
2. Отправьте команду `/newbot`.
3. Задайте имя бота (например, `VetAssistant`) и username, который
   заканчивается на `bot` (например, `vet_assistant_bot`).
4. Скопируйте токен вида `123456789:AA...`.
5. Добавьте его в `.env` в корне проекта:

   ```dotenv
   TELEGRAM_BOT_TOKEN=123456789:AA...
   ```

   Токен — секрет. Не коммитьте `.env` и не публикуйте токен в чатах.

### 2. Локальный запуск

Сначала запустите FastAPI (см. раздел выше), затем в новом терминале:

```powershell
pip install -e .
$env:TELEGRAM_BOT_TOKEN="123456789:AA..."
python -m bot
```

Для локального запуска бот по умолчанию обращается к
`http://127.0.0.1:8000/v1/chat/completions`. Адрес можно переопределить:

```powershell
$env:VET_BOT_API_URL="http://127.0.0.1:8000/v1/chat/completions"
```

После запуска откройте своего бота в Telegram и отправьте `/start`.
При `/start` бот автоматически регистрирует или находит аккаунт
`telegram-<id>@bot.vetassistant.local` и получает JWT, поэтому все записи
привязаны к этому Telegram-пользователю и не пересекаются с веб-аккаунтами.
Пароль синтетического аккаунта вычисляется из `VET_BOT_AUTH_SECRET`
(или `TELEGRAM_BOT_TOKEN`) и в БД не хранится.

### 3. Запуск в Docker Compose

Добавьте `TELEGRAM_BOT_TOKEN` в `.env` и поднимите стек:

```powershell
docker compose up --build
```

Сервис `bot` зависит от здорового `api` и автоматически использует
`http://api:8000/v1/chat/completions`. Логи бота:

```powershell
docker compose logs -f bot
```

Если токен не задан, контейнер `bot` завершится с понятной ошибкой, а API и
Streamlit UI продолжат работать. После добавления токена перезапустите бота:

```powershell
docker compose up -d bot
```

### 4. Настройки бота

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Токен от @BotFather (обязателен) |
| `VET_BOT_API_URL` | `http://127.0.0.1:8000/v1/chat/completions` | URL API |
| `VET_BOT_MODEL_ID` | `qwen3-8b-vet` | Имя модели в запросах |
| `VET_BOT_TIMEOUT_S` | `300` | Таймаут запроса к API |
| `VET_BOT_TEMPERATURE` | `0.7` | Температура генерации |
| `VET_BOT_USE_RAG` | `true` | Использовать базу знаний |
| `VET_BOT_USE_TOOLS` | `true` | Разрешить Function Calling |
| `VET_BOT_MAX_HISTORY_MESSAGES` | `20` | Сколько сообщений помнить |
| `VET_BOT_AUTH_SECRET` | `TELEGRAM_BOT_TOKEN` | Секрет HMAC для аккаунтов Telegram |

История диалога хранится в памяти процесса: после перезапуска бота контекст
сбрасывается, а созданные приёмы и напоминания остаются в PostgreSQL.
Если модель вызывает `book_appointment` или `set_reminder`, API выполняет
инструмент, а бот показывает подтверждение вида
**«✅ Я записал вашего питомца на приём: Мурзик, 2026-11-04 в 10:00.»**
и финальный текст модели.

## 📚 RAG: база знаний MSD Vet Manual

Модель может дополнять ответы проверенными фрагментами локального
справочника. База хранится в `data/chroma_db/` и не коммитится в Git.

1. Установите зависимости (они уже входят в `pip install -e .`):
   `chromadb`, `sentence-transformers`. При первом инжесте скачается
   лёгкая мультиязычная модель эмбеддингов
   `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
2. Положите текстовые файлы в `data/knowledge/` (3 демо-файла уже есть).
   Поддерживаются `*.txt` и `*.pdf`, файлы читаются рекурсивно. Чтобы скачать
   реальные статьи MSD Vet Manual:

   ```powershell
   python scripts/download_msd.py --dry-run
   python scripts/download_msd.py
   ```

   Статьи сохраняются в `data/knowledge/real/`: отравление человеческими
   анальгетиками (включая парацетамол) и острый геморрагический диарейный
   синдром у собак.
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

## 🧰 Function Calling

Модель умеет вызывать два инструмента (схемы — `app/tools.py`):

- `book_appointment(date, time, pet_name)` — запись питомца на приём;
- `set_reminder(time, text)` — напоминание, например дать таблетку.

В Streamlit включите в сайдбаре
**«Разрешить модели использовать инструменты (Function Calling)»**. Если
модель вернула `tool_calls`, API автоматически выполнит инструмент, сохранит
результат в PostgreSQL (в Docker) или async SQLite (локально), отправит его
обратно модели и вернёт финальный текст. В чате останется бейдж
**🛠️ Вызван инструмент: …** с параметрами — как визуальная индикация.

Прямой запрос к API передаёт OpenAI-совместимый массив `tools` и требует
JWT (см. раздел «Аутентификация и изоляция данных»):

```json
{
  "messages": [{"role": "user", "content": "Запиши Мурзика на 4 ноября в 10:00"}],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "book_appointment",
        "parameters": {
          "type": "object",
          "properties": {
            "date": {"type": "string"},
            "time": {"type": "string"},
            "pet_name": {"type": "string"}
          },
          "required": ["date", "time", "pet_name"]
        }
      }
    }
  ]
}
```

Прямой вызов выполнения инструмента:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/v1/tools/execute `
  -Method Post -ContentType "application/json" -Headers $headers `
  -Body '{"name":"book_appointment","arguments":{"date":"2026-11-04","time":"10:00","pet_name":"Мурзик"}}'
```

Ответ: `{"status": "success", "message": "Записали Мурзика на 2026-11-04 в 10:00"}`.
Записи и напоминания хранятся в таблицах `appointments` и `reminders` вместе
с `user_id` владельца. В Docker используется PostgreSQL 16, локально — async
SQLite (`data/vetassistant.db`).

Чтение данных (только записи текущего пользователя):

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/v1/appointments -Headers $headers
Invoke-RestMethod -Uri http://127.0.0.1:8000/v1/reminders -Headers $headers
```

В Streamlit откройте в сайдбаре **«Мои записи»** — там показываются карточки
ближайших приёмов и напоминаний.

> В финальном ответе agentic loop `tool_calls` остаются как визуальная
> индикация для UI. Они уже выполнены; `finish_reason` при наличии финального
> текста равен `stop`.

## 🔐 Аутентификация и изоляция данных (T-039)

Сервис теперь мультитенантный: каждый пользователь видит только своих
питомцев, записи на приём и напоминания.

- Пароли хранятся как bcrypt-хэши (`passlib[bcrypt]`).
- Access-токен — JWT HS256 со сроком 7 дней (настраивается
  `VET_API_ACCESS_TOKEN_EXPIRE_MINUTES`).
- Защищены `/v1/chat/completions`, `/v1/appointments`, `/v1/reminders`,
  `/v1/tools/execute` и `/v1/auth/me`; без токена они возвращают `401`.
- `user_id` берётся только из JWT и никогда из аргументов модели, поэтому
  Agentic Loop записывает приём владельцу текущей сессии.

### Регистрация и вход

```powershell
$auth = Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/v1/auth/register `
  -Method Post -ContentType "application/json" `
  -Body '{"email":"owner@example.com","password":"secret-pass-1"}'

$headers = @{ Authorization = "Bearer $($auth.access_token)" }

# Повторный вход в другом клиенте
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/v1/auth/login `
  -Method Post -ContentType "application/json" `
  -Body '{"email":"owner@example.com","password":"secret-pass-1"}'
```

`register` и `login` возвращают `access_token`, `token_type` и публичные
данные пользователя. `GET /v1/auth/me` проверяет токен и возвращает текущего
пользователя.

### Клиенты

- **React:** при отсутствии токена показывается экран входа/регистрации;
  JWT сохраняется в `localStorage` и передаётся в `Authorization`. История
  чата хранится отдельно для каждого `user_id`, в сайдбаре есть кнопка
  «Выйти».
- **Streamlit:** формы входа и регистрации, токен хранится в `session_state`,
  кнопка выхода в сайдбаре.
- **Telegram:** на `/start` бот создаёт или переиспользует синтетический
  аккаунт `telegram-<id>@bot.vetassistant.local`. Пароль детерминированно
  вычисляется через HMAC-SHA256 из Telegram ID и `VET_BOT_AUTH_SECRET`
  (fallback — `TELEGRAM_BOT_TOKEN`), поэтому пароли не хранятся в открытом
  виде. Бот кэширует JWT и при `401` автоматически входит повторно.

### Настройки

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `VET_API_JWT_SECRET` | `dev-insecure-jwt-secret-change-me` | Секрет подписи JWT (замените в production) |
| `VET_API_ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` | Срок жизни токена (7 дней) |
| `VET_BOT_AUTH_SECRET` | `TELEGRAM_BOT_TOKEN` | Секрет HMAC для аккаунтов Telegram |

> Для существующих баз `create_tables` мягко добавляет `user_id` в старые
> таблицы `appointments`/`reminders`. Строки, созданные до T-039, остаются в
> БД с `NULL` и не видны пользователям — при необходимости привяжите их к
> владельцу вручную.

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

3. Соберите и запустите весь стек (`db` + `api` + `ui` + `frontend` + `bot`):

   ```powershell
   docker compose up --build
   ```

4. Откройте:
   - API: `http://localhost:8000/health`
   - React UI: `http://localhost:3000`
   - Streamlit UI: `http://localhost:8501`

5. Остановка:

   ```powershell
   docker compose down
   ```

Контейнеры монтируют локальную папку `./data` в `/app/data`, поэтому модель
GGUF и ChromaDB не копируются в образ и остаются доступны API. PostgreSQL
хранит данные в именованном volume `postgres_data`, поэтому записи и
напоминания сохраняются между перезапусками. Streamlit UI внутри Compose
обращается к API по имени сервиса `http://api:8000`. React-фронтенд раздаётся
Nginx, который проксирует `/api/*` в `api:8000` — для браузера это тот же
origin.

Основные переменные окружения можно задать в `.env` (Compose подхватит их
для подстановки):

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `POSTGRES_USER` | `vetassistant` | Пользователь PostgreSQL |
| `POSTGRES_PASSWORD` | `vetassistant` | Пароль PostgreSQL |
| `POSTGRES_DB` | `vetassistant` | Имя базы данных |
| `VET_API_DATABASE_URL` | `postgresql+asyncpg://...@db:5432/...` | URL БД для SQLAlchemy |
| `VET_API_JWT_SECRET` | `dev-insecure-jwt-secret-change-me` | Секрет подписи JWT (замените в production) |
| `VET_API_ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` | Срок жизни access-токена |
| `VET_BOT_AUTH_SECRET` | `TELEGRAM_BOT_TOKEN` | Секрет HMAC для аккаунтов Telegram |
| `VET_API_MODEL_PATH` | `/app/data/gguf/qwen3-8b-vet-Q4_K_M.gguf` | Путь к GGUF внутри контейнера |
| `VET_API_N_CTX` | `8192` | Размер контекста llama.cpp |
| `VET_API_N_GPU_LAYERS` | `0` | Слоёв на GPU (0 — CPU) |
| `VET_UI_API_URL` | `http://api:8000/v1/chat/completions` | Адрес API для Streamlit UI |
| `VET_UI_MODEL_ID` | `qwen3-8b-vet` | Имя модели в запросах UI |
| `FRONTEND_PORT` | `3000` | Порт React-фронтенда на хосте |
| `VITE_FRONTEND_API_BASE_URL` | `/api` | Базовый URL API при сборке фронтенда |

> Первая сборка может занять 10–20 минут: `llama-cpp-python` собирается из
> исходников. Если GGUF-модель отсутствует, API запустится, но ответы на
> запросы будут возвращать `503 Модель недоступна`.

## 🚀 Production-деплой на VPS (T-040)

Для боевого запуска на Ubuntu-сервере есть отдельная конфигурация:

- `docker-compose.prod.yml` — публикует только `frontend:80`; API,
  PostgreSQL и бот доступны только внутри Docker-сети;
- `docker-compose.ssl.yml` — включает `443`, Certbot и HTTPS;
- `frontend/nginx.conf` — раздаёт SPA и проксирует `/api/*` в `api:8000`;
- `.env.production.example` — шаблон секретов и production-настроек;
- `scripts/deploy.sh` — установка Docker, клонирование, генерация секретов
  и запуск стека (опционально с `--ssl`);
- `scripts/renew_ssl.sh` — автопродление Let's Encrypt.

Быстрый старт на чистом сервере:

```bash
curl -fsSL https://raw.githubusercontent.com/iilmchat/ai_VetAssistant/main/scripts/deploy.sh \
  -o /tmp/deploy.sh
sudo bash /tmp/deploy.sh --ssl
```

Пошаговая инструкция: аренда VPS, DNS A-запись, firewall, модель GGUF,
Certbot, автопродление, бэкапы и диагностика — в
[DEPLOYMENT.md](DEPLOYMENT.md).

## 🛠️ Стек
- **Данные:** Python, Pydantic, OpenAI SDK (для API), `datasets` (HF), DVC + S3 (Selectel).
- **Обучение:** Unsloth, PyTorch, HuggingFace `transformers`, `peft`.
- **Экспорт:** `llama.cpp` (convert_hf_to_gguf.py), GGUF Q4_K_M/Q5_K_M.
- **Инференс:** FastAPI + `llama-cpp-python`, OpenAI-совместимый API и SSE.
- **RAG:** ChromaDB + sentence-transformers, TXT/PDF, реальные статьи MSD Vet Manual.
- **Function Calling:** `book_appointment`, `set_reminder`, OpenAI-совместимые `tools`.
- **База данных:** PostgreSQL 16 + async SQLAlchemy 2.0/asyncpg; SQLite/aiosqlite для локальных тестов.
- **Аутентификация:** JWT HS256 (`PyJWT`), bcrypt (`passlib[bcrypt]`), изоляция данных по `user_id`.
- **Безопасность:** Router & Triage (`app/router.py`), regex-эвристики до вызова LLM.
- **UI:** React 19 + Vite + TypeScript + Tailwind CSS 4 (`frontend/`): SSE-стриминг, Markdown, бейджи инструментов, настройки и «Мои записи».
- **Streamlit:** резервный UI (`app/ui.py`) с потоковым выводом и настройками температуры.
- **Telegram:** aiogram 3.x, отдельный процесс/контейнер `bot`, история диалога на пользователя.
- **Развёртывание:** Docker Compose, FastAPI + React/Streamlit UI + PostgreSQL + Telegram-бот; Nginx для фронтенда.
- **Production:** `docker-compose.prod.yml` + `docker-compose.ssl.yml`, единый домен, Let's Encrypt/Certbot, `scripts/deploy.sh`.
- **CI/CD:** GitHub Actions — ruff, mypy, pytest, тесты и сборка React, Docker-образы.
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