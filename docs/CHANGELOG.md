# Changelog

Все заметные изменения проекта VetAssistant.
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/),
версии — по [Semantic Versioning](https://semver.org/lang/ru/).

## [1.3.0] — 2026-11-04

### Добавлено

#### Prometheus-метрики (T-117)

- `prometheus-fastapi-instrumentator`: `GET /metrics` со стандартными
  HTTP-метриками (`http_requests_total`, `http_request_duration_seconds`) и
  кастомными `vet_llm_*` / `vet_rag_*`.
- Метрики инференса: вызовы модели по режимам (`chat`/`stream`,
  `success`/`empty`/`error`), токены промпта и генерации, полное время
  генерации, время до первого токена SSE и скорость генерации токенов/с.
- Метрики RAG: поиски (`hit`/`miss`/`error`), число извлечённых чанков,
  длительность поиска и gauge `vet_rag_index_ready` (1/0).
- `llama-cpp-python` не поддерживает `--metrics` и не отдаёт тайминги
  llama.cpp server, поэтому `vet_llm_*` считаются в API по `usage` и времени
  вызова; для стриминговых ответов точны латентность и TTFT.
- В lifespan API добавлена проверка индекса ChromaDB: если его нет, API
  стартует без RAG и пишет предупреждение в лог.

#### RAG production readiness

- `scripts/ingest_knowledge.py` обновляет индекс инкрементально через
  `upsert`, не удаляя коллекцию: существующие чанки (77 в production)
  сохраняются, изменённые обновляются, новые добавляются. Полная пересборка
  — только с флагом `--rebuild`.
- Entrypoint по-прежнему собирает индекс до запуска API при
  `VET_API_AUTO_INGEST=1`; при ошибке API стартует без RAG, если
  `VET_API_INGEST_STRICT=0`.
- `DEPLOYMENT.md`: загрузка статей через `scp`, ручное обновление и полная
  пересборка индекса, проверка `/metrics`, список метрик и пример
  scrape-конфига Prometheus.

### Изменено

- Версия `1.3.0` в `pyproject.toml`, FastAPI, Docker Compose (dev/prod/edge)
  и `frontend/package.json`.

### Итоги Фазы 3 (production)

- **Prometheus** собирает `vetassistant-api:8000/metrics` по сети `edge`:
  стандартные HTTP-метрики и 10 кастомных `vet_llm_*` / `vet_rag_*`.
- **Grafana** развёрнута рядом с Prometheus; дашборды — RPS и p95
  HTTP-латентности, токены/с, p95 TTFT, доля RAG-hit и алерт
  `vet_rag_index_ready == 0`. Финальное подтверждение работы дашбордов — за
  сисадмином.
- **RAG в production:** коллекция `msd_vet_manual` содержит **77 чанков** из
  двух статей MSD Vet Manual и трёх демо-файлов; API отдаёт
  `vet_rag_index_ready 1.0`.
- Инкрементальный ingest через `upsert` сохраняет базу при обновлении статей;
  `--rebuild` — только осознанная полная пересборка.
- Публичный путь `/api/metrics` закрывается в Caddy; Prometheus ходит на
  внутренний адрес API.

## [1.2.1] — 2026-11-04

### Изменено

- **Split architecture:** landing page on `ai-pets.ru`, app on
  `app.ai-pets.ru`, fixed Caddy matchers.
- Лендинг и приложение разделены по доменам: `ai-pets.ru` отдаёт статический
  лендинг (`vetassistant-landing`), `app.ai-pets.ru` — React SPA и
  `/api/*` → `vetassistant-api:8000`, `www.ai-pets.ru` редиректит на apex.
  Caddy на edge-хосте переключён, сертификат поддомена выпущен автоматически,
  smoke-проверки (корень, app, API, `www`, `/privacy/`, `/terms/`) пройдены.
- **Caddy matchers:** служебные файлы лендинга (`README.md`, `DEPLOY.md`,
  `nginx.conf`, `compose.edge.fragment.yml`, `Caddyfile.edge.snippet`)
  возвращают 404 до проксирования. В исходной конфигурации
  `respond @landing_private 404` не срабатывал раньше `handle`; исправлено на
  `handle @landing_private { respond 404 }` (`f982cd0`).

### Документация

- `docs/development/PHASE2_LANDING_APP.md` — Пакеты A и B отмечены как
  реализованные и задеплоенные, добавлен итоговый статус доменов.
- `README.md` — архитектура двух доменов и актуальный smoke-тест.

## [1.2.0] — 2026-11-04

### Добавлено

#### Закрытый доступ (Access Requests)

- Таблица `access_requests` (`email`, `reason`, `status`, `created_at`) и
  публичный эндпоинт `POST /v1/access/request` с ответом `202 Accepted`.
- `slowapi` и лимит **3 заявки в час с одного IP**; повторная заявка с тем же
  email не создаёт дубликат и не раскрывает наличие аккаунта.
- Публичная регистрация закрыта: `POST /v1/auth/register` всегда возвращает
  `403 Регистрация только по заявкам`.
- React: вкладка регистрации убрана, добавлена кнопка «Запросить доступ» с
  модальной формой; `?mode=request` автоматически открывает её (deep-link с
  лендинга).
- Админские скрипты: `scripts/list_access_requests.py` и
  `scripts/create_user.py` для ручного создания аккаунта после одобрения.

#### Лендинг и Nginx

- Каталог `landing/`: статический лендинг `ai-pets.ru`, страницы
  `/privacy/`, `/terms/`, `404.html`, `robots.txt`, `sitemap.xml`, OG-карточка.
- `landing/nginx.conf`: кеширование статики, security-заголовки, `/healthz` и
  отдача юридических страниц.
- Фрагменты `landing/compose.edge.fragment.yml` и
  `landing/Caddyfile.edge.snippet` для последующего переключения Caddy и
  поддомена `app.ai-pets.ru` (в этом релизе не применяются).
- `landing/DEPLOY.md` с порядком выкладки, smoke-проверками и откатом.

## [1.1.3] — 2026-11-04

### Безопасность

- **Security key rotation.** SSH-ключ пользователя `deployer` перевыпущен,
  старый отозван; GitHub Secret `SSH_KEY` обновлён. Тег `v1.1.3` проверяет
  автоматический деплой с новым ключом.
- В релиз также входит T-110: автоматическая сборка ChromaDB перед стартом
  API и кеширование модели эмбеддингов в volume `hf_cache`.

## [1.1.2] (Unreleased)

### Исправлено

- **Fix deploy timeout.** Полная Docker-сборка edge-стека на сервере занимает
  около 50 минут, поэтому лимиты workflow увеличены: `timeout-minutes` с
  `30` до `90`, `command_timeout` с `20m` до `80m`.
- Версия поднята до `1.1.2`; тег `v1.1.2` проверяет автоматический деплой
  с новыми таймаутами.

## [1.1.1] (Unreleased)

### Тестовый релиз

- Тег `v1.1.1` создан для проверки нового CI/CD-пайплайна: сборки образов
  и автоматического деплоя edge-стека через `.github/workflows/deploy.yml`.
- Версия поднята до `1.1.1`; функциональных изменений относительно `1.1.0`
  нет.

## [1.1.0] — 2026-11-04

### Добавлено

#### Безопасность и память

- **Смена пароля (T-103).** Эндпоинт `POST /v1/auth/change-password`
  принимает `old_password`, `new_password` и необязательный
  `new_password_confirm`, проверяет старый bcrypt-хэш и сохраняет новый.
  В React-сайдбаре добавлена кнопка-шестерёнка «Настройки» с модальной
  формой смены пароля; после успеха показывается уведомление
  «Пароль изменен» и выполняется разлогин. Добавлены тесты на успешную
  смену, неверный старый пароль и несовпадение подтверждения.
- **Конфигурация памяти (T-101).** `VET_API_N_CTX` по умолчанию снижен с
  `8192` до `4096` в `app/settings.py`, Docker Compose и
  `.env.production.example`; при OOM рекомендуется `2048`. `/health`
  теперь возвращает `n_ctx`, `n_threads` и `n_gpu_layers`, добавлен
  `scripts/check_ram.py` для мониторинга конфигурации и памяти хоста.
- **Защита сервера (T-104).** Добавлен `scripts/setup_ufw.sh`:
  разрешает SSH (`22`), HTTP (`80`) и HTTPS (`443`), запрещает входящие
  по умолчанию и включает UFW; в `DEPLOYMENT.md` добавлен раздел
  «Безопасность сервера» с инструкцией запуска.

### Планируется

- Расширенный Safety-бенчмарк и независимые модели-судьи.
- Расширение базы знаний и оценка качества RAG-ответов.
- Rate limiting на `/v1/auth/login` и публичных эндпоинтах.
- Инвалидация ранее выданных JWT при смене пароля (T-105, backlog).

## [1.0.0] — 2026-11-03

> **Первый production-ready релиз VetAssistant.** Тег: `v1.0.0`
> (публикуется после боевой проверки HTTPS на VPS).

VetAssistant прошёл путь от идеи и синтетических данных до полноценного
multi-tenant SaaS: локальная LLM-модель, RAG по MSD Vet Manual, Agentic
Loop с записью к ветеринару, React-интерфейс, Telegram-бот, JWT-авторизация
и production-деплой на одном домене с HTTPS.

### Путь к 1.0.0

| Этап | Что появилось |
|---|---|
| v0.1.0 | Пайплайн генерации данных, первые промпты, RAG-заготовка |
| v0.2.0 | FastAPI, Streamlit UI, живая GGUF-модель, MSD Vet Manual |
| v0.3.0 | Autonomous Agent: `book_appointment`, `set_reminder`, PostgreSQL |
| v0.4.0 | Telegram-бот на aiogram 3.x, история диалогов, Function Calling |
| v0.5.0 | React 19 SPA: SSE-стриминг, Markdown, «Мои записи», Docker/Nginx |
| T-039 | JWT Auth, bcrypt, `user_id` FK и мультитенантная изоляция |
| T-040 | Production Docker, единый домен, Let's Encrypt/Certbot, deploy.sh |
| **v1.0.0** | **Production Ready: безопасность, HTTPS, эксплуатационная документация** |

### Добавлено в 1.0.0

#### Multi-tenant SaaS и безопасность

- JWT-аутентификация (`PyJWT`, HS256) и bcrypt-хэширование паролей через
  `passlib[bcrypt]`; эндпоинты `/v1/auth/register`, `/v1/auth/login` и
  `/v1/auth/me` (T-039).
- Таблица `users` и `user_id` с внешним ключом в `appointments` и
  `reminders`; мягкая миграция старых таблиц без потери строк (T-039).
- Мультитенантная изоляция: `/v1/chat/completions`, `/v1/appointments`,
  `/v1/reminders` и `/v1/tools/execute` требуют Bearer-токен и работают
  только с данными текущего пользователя; Agentic Loop берёт `user_id` из
  JWT (T-039).
- React: экран входа/регистрации, JWT в `localStorage`, заголовок
  `Authorization` во всех запросах, кнопка «Выйти» и раздельная история чата
  по `user_id` (T-039).
- Streamlit: формы входа/регистрации, токен в `session_state`, кнопка
  «Выйти» и авторизованные запросы (T-039).
- Telegram: синтетический аккаунт `telegram-<id>@bot.vetassistant.local`,
  детерминированный HMAC-пароль, кэш JWT и повторная авторизация при `401`
  (T-039).

#### Production-инфраструктура

- `docker-compose.prod.yml`: публикация только `frontend:80`; API и
  PostgreSQL доступны только внутри Docker-сети; сервис бота удалён из
  production (T-040, T-043).
- `docker-compose.ssl.yml`: `443`, Certbot, Let's Encrypt, HSTS и
  HTTP→HTTPS-редирект; единый домен через Nginx (T-040).
- `frontend/nginx.conf`: проксирование `/api/*` в `api:8000`, SSE без
  буферизации, SPA fallback, ACME webroot и security-заголовки (T-040).
- `.env.production.example` с обязательными секретами и инструкцией
  `openssl rand -hex 32`; `.env` и каталоги Certbot исключены из Git (T-040).
- `scripts/deploy.sh`: установка Docker/Compose на Ubuntu, клонирование,
  генерация секретов, запуск production-стека и опциональный `--ssl`;
  `scripts/renew_ssl.sh` для автопродления сертификата (T-040).
- `docker-compose.edge.yml`: edge-стек для общего VPS с Caddy — `api`,
  `db`, `frontend`, внешняя сеть `edge`, изолированная `internal`, без
  публикации 80/443, бота и Streamlit (T-043).
- `deploy/Caddyfile`: `ai-pets.ru`, редирект `www`, `/api/*` → `api:8000`
  со снятием префикса и SPA через `frontend:80` (T-043).
- `scripts/upload_model.py`: SFTP-загрузка GGUF в
  `/srv/vetassistant/data/gguf/` через `.part`, проверка размера и
  SHA-256 (`45cccc...b10b`) и атомарное переименование (T-043).
- `VET_API_ALLOW_PUBLIC_REGISTRATION`: production-флаг закрытия публичной
  регистрации; при `false` `/v1/auth/register` возвращает `403`
  «Регистрация временно закрыта» (T-043).
- `DEPLOYMENT.md`: аренда VPS, DNS A-запись, firewall, модель GGUF, Certbot,
  HTTPS-редирект, обновления, бэкапы и диагностика (T-040).
- `SECURITY.md`: политика безопасности, порядок сообщения об уязвимостях,
  модель угроз, известные ограничения и обязательный production-чеклист
  (T-041).

#### Качество и релизная инженерия

- Тесты авторизации: `401` без токена, `409` при дубле email, изоляция
  записей между пользователями (T-039).
- Тесты production-конфигурации: compose, HTTPS-overlay, Nginx, шаблон
  секретов и скрипты деплоя (T-040).
- Тесты edge-конфигурации, Caddyfile, SFTP-загрузчика и smoke-теста;
  проверка закрытия регистрации (T-043).
- Smoke-тест адаптирован под закрытую регистрацию: вход существующим
  пользователем, проверка `/api/v1/appointments` (T-045).
- CI: `ruff`, `mypy`, `pytest`, frontend lint/tests/build и Docker-сборка
  API + Frontend.
- Версия `1.0.0` синхронизирована в `pyproject.toml`, FastAPI,
  `docker-compose.yml`, `docker-compose.prod.yml`, `frontend/package.json`
  и lockfile (T-041).

### Изменено

- `VET_API_JWT_SECRET` и `VET_API_ACCESS_TOKEN_EXPIRE_MINUTES` добавлены в
  настройки, `.env.example` и Docker Compose; `VET_BOT_AUTH_SECRET` — в
  настройки бота и Compose (T-039).
- README дополнен разделами об аутентификации, production-деплое и
  финальным статусом **Production Ready** со ссылками на `SECURITY.md` и
  `DEPLOYMENT.md` (T-039, T-040, T-041).
- README дополнен разделом Edge-деплоя для инфраструктурного агента (T-043).
- SSH-оркестратор `deploy_prod.py` и зависимость `paramiko` удалены:
  управление VPS передано инфраструктурному агенту (T-043).
- `deploy.sh` больше не запрашивает `TELEGRAM_BOT_TOKEN`; сервис `bot`
  удалён из production-стека (T-043).
- Dockerfile фронтенда копирует Nginx-конфигурацию с правилами `/api`, SPA
  и ACME для HTTP (T-040).

### Безопасность

- Пароли не хранятся в открытом виде; JWT подписывается секретом и имеет
  срок действия 7 дней по умолчанию (T-039).
- Данные питомцев, записи и напоминания недоступны другим пользователям,
  включая Telegram-аккаунты (T-039).
- Production-стек не публикует API и PostgreSQL наружу; наружу открыты
  только `80`/`443`, а HTTPS включается с HSTS и редиректом с HTTP (T-040).
- Добавлена публичная политика безопасности и обязательный чеклист смены
  `VET_API_JWT_SECRET`, `POSTGRES_PASSWORD` и `VET_BOT_AUTH_SECRET` перед
  публикацией сервиса (T-041).
- Публичная регистрация в production закрывается флагом
  `VET_API_ALLOW_PUBLIC_REGISTRATION=false`; API отвечает `403`
  «Регистрация временно закрыта» (T-043).

### Результаты 1.0.0

| Метрика | Значение |
|---|---|
| Python-тесты | **569 passed** |
| Frontend-тесты | **29 passed** |
| Python-линтеры | `ruff check .`, `mypy app bot` — чисто |
| Frontend | `oxlint`, `npm run build` — успешно |
| Docker Compose | dev, prod и SSL-overlay — валидны |
| Nginx | `nginx -t` для HTTP и HTTPS — успешно |
| Production-проверки | HTTP→HTTPS, HSTS, `/healthz`, SPA fallback |
| CI | Lint & Test, Frontend, Docker Build — success |

### Известные ограничения

- Нет rate limiting, подтверждения email, восстановления пароля и 2FA.
- JWT хранится в `localStorage`; требуется защита от XSS.
- История Telegram-диалога хранится в памяти процесса.
- Модель не заменяет ветеринарного врача; медицинские ограничения описаны
  в README и системном промпте.

## [0.5.0] — 2026-11-03

> Релиз «React web interface». Тег: `v0.5.0`.

Пятый релиз: у VetAssistant появился полноценный веб-интерфейс. React-SPA
работает с тем же FastAPI, стримит ответы через SSE, показывает вызовы
инструментов и объединяет чат, настройки и записи питомцев в одном окне.

### Добавлено

#### React 19 Frontend

- Новый фронтенд `frontend/` на React 19 + Vite + TypeScript + Tailwind CSS 4:
  чат в стиле ChatGPT с боковой панелью и адаптивной вёрсткой (T-037).
- SSE-стриминг ответов `/v1/chat/completions`: текст появляется по мере
  генерации, поддерживается остановка запроса (T-037).
- Markdown и GFM-таблицы через `react-markdown`; вызовы `book_appointment` и
  `set_reminder` отображаются цветными бейджами (T-037).
- Настройки `temperature`, RAG и Function Calling; блок «Мои записи» с
  приёмами (`/v1/appointments`) и напоминаниями (`/v1/reminders`) (T-037).
- История диалога в `localStorage`, индикатор доступности API и кнопка
  «Новый чат» (T-037).

#### Инфраструктура

- `frontend/Dockerfile`: multi-stage сборка Node.js → Nginx, healthcheck
  `/healthz` (T-037).
- Сервис `frontend` в Docker Compose на порту `3000`; Nginx проксирует
  `/api/*` в `api:8000` без буферизации SSE (T-037).
- CORS в FastAPI для Vite (`http://localhost:5173`,
  `http://127.0.0.1:5173`) и Docker-фронтенда на порту `3000` (T-037).
- README: скриншот интерфейса, локальный запуск `npm run dev`, сборка, тесты и
  запуск через Docker на порту `3000` (T-037, T-038).
- CI и Release: отдельная проверка фронтенда (`npm ci`, lint, tests, build)
  и сборка Docker-образов API и Frontend (T-037, T-038).

### Изменено

- Версия проекта, FastAPI-приложения, Docker-образов и `frontend/package.json`
  поднята до `0.5.0`.
- README дополнен разделом о React-интерфейсе, скриншотом и бейджем версии
  `v0.5.0`; зафиксированы порты `3000` (Docker) и `5173` (Vite dev).
- Release-workflow собирает оба Docker-образа — `vetassistant` и
  `vetassistant-frontend` — перед публикацией GitHub Release.

### Результаты v0.5.0

| Метрика | Значение |
|---|---|
| Python-тесты | **518 passed** |
| Frontend-тесты | **22 passed** |
| Python-линтеры | `ruff check .`, `mypy app bot` — чисто |
| Frontend-линтер | `oxlint` — чисто |
| Сборка фронтенда | `npm run build` — успешно |
| Docker Compose | `docker compose config` — валиден |
| Docker-образы | API и Frontend собираются, `/healthz` отвечает 200 |
| E2E | SSE-стриминг, tool badge, «Мои записи», мобильный drawer |

### Известные ограничения

- История чата хранится в `localStorage` браузера и не синхронизируется между
  устройствами.
- Веб-интерфейс не содержит аутентификации и рассчитан на локальный запуск.
- Возможны галлюцинации; ассистент не заменяет ветеринарного врача.

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
