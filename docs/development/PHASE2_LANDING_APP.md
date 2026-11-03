# Phase 2 — VetAssistant: лендинг и разделение приложения

**Статус:** черновик плана, не согласован. Production не меняется.
**Дата:** 2026-11-04.
**Текущая версия:** backend `1.1.2`, frontend `1.1.2`.
**Прогресс:** шаг B1 — статический лендинг подготовлен в `landing/`
(`index.html`, `privacy/`, `terms/`, OG 1200×630); шаг B2 — подготовлены
`landing/compose.edge.fragment.yml`, `landing/Caddyfile.edge.snippet`,
`landing/DEPLOY.md` и `deploy/landing/apply-package-b.sh`. Caddy, compose и DNS
не менялись. В v1.2.0 служебные файлы лежат в web-root `landing/`; Caddy
блокирует их по путям, вынос в `deploy/landing/` — следующий шаг.

## 1. Цель

Разделить один домен на две роли:

```text
ai-pets.ru              -> статический лендинг (индексируется)
ai-pets.ru/privacy/     -> политика конфиденциальности
ai-pets.ru/terms/       -> условия использования

app.ai-pets.ru          -> React SPA (noindex)
app.ai-pets.ru/api/*    -> FastAPI (существующий прокси)

www.ai-pets.ru          -> redirect на ai-pets.ru
```

Почему `app.ai-pets.ru`, а не `ai-pets.ru/app/`:

- не нужно менять `base` в Vite, router и `frontend/nginx.conf`;
- приложение остаётся в корне своего origin, API — тот же `/api`;
- лендинг и приложение не мешают друг другу в SEO и кеше;
- цена — одна A-запись и один сертификат, Caddy уже умеет автоматический ACME
  для `ai-pets.ru`.

Запасной вариант `/app/` оценивается отдельно: +0.5–1 день на Vite `base`,
nginx `location /app/`, Caddy `handle_path`.

## 2. Пакеты работ

| Пакет | Что входит | Оценка |
|---|---|---:|
| **A. Доступ** | Убрать мёртвую регистрацию, форма заявки, rate limiting, скрипты администратора | 2 дня |
| **B. Разделение** | Лендинг в корне, `app.` поддомен, Caddy/DNS, compose | 2 дня |
| **C. Доверие и SEO** | Политика/условия, robots/sitemap/OG, noindex приложения, аналитика | 1 день |
| **D. Полировка** | Закрыть OpenAPI, минимальный `/health`, CSP report-only, мониторинг | 0.5–1 день |

Итого: **5–6 рабочих дней**. Пакет A можно выпустить отдельно и раньше —
он не требует разделения домена.

---

## 3. Пакет A — доступ без публичной регистрации

### 3.1. Проблема

`VET_API_ALLOW_PUBLIC_REGISTRATION=false`, `POST /v1/auth/register` возвращает
`403`, но `frontend/src/components/AuthScreen.tsx` показывает вкладку
«Регистрация». Пользователь заполняет форму и получает отказ.

### 3.2. Backend

**Файлы:**

- `app/database.py` — новая таблица `access_requests`.
- `app/access.py` — новый модуль с моделями и эндпоинтом заявки.
- `app/rate_limit.py` — новый модуль, `slowapi` + лимиты.
- `app/main.py` — подключить роутер, добавить лимиты на login.
- `pyproject.toml` — зависимость `slowapi>=0.1.9`.
- `tests/test_access_requests.py`, `tests/test_rate_limit.py` — новые тесты.

**Таблица `access_requests`:**

| Поле | Тип | Комментарий |
|---|---|---|
| `id` | int PK | |
| `email` | varchar(320), index | нормализованный email |
| `comment` | text, nullable | «кошка, 3 года, вопрос по питанию» |
| `status` | varchar(20), default `new` | `new` / `contacted` / `closed` |
| `created_at` | timestamptz | |
| `ip_hash` | varchar(64), nullable | sha256(IP + JWT secret), не сырой IP |

**Эндпоинт:**

```http
POST /api/v1/access/request
Content-Type: application/json

{
  "email": "owner@example.com",
  "comment": "Кошка 3 года, беспокоит аппетит"
}
```

Ответ всегда `202 Accepted`:

```json
{ "status": "received" }
```

Правила:

- email валидируется, приводится к нижнему регистру;
- комментарий — до 1000 символов, обрезается;
- повторная заявка с тем же email не раскрывает, есть ли аккаунт;
- лимит: **3 заявки в час с IP**;
- после записи — уведомление в Telegram (если настроено), ошибка уведомления
  не ломает ответ пользователю;
- в логах не пишем email и текст заявки целиком.

Alembic в проекте нет: таблица создастся через `Base.metadata.create_all`
при старте API. После выкладки проверить `\d access_requests` в PostgreSQL;
для будущих изменений схемы завести Alembic отдельной задачей.

**Уведомление:**

- `TELEGRAM_BOT_TOKEN` уже используется ботом;
- добавить `VET_API_ADMIN_TELEGRAM_CHAT_ID`;
- отправка через Bot API в `BackgroundTasks`, без блокировки запроса;
- если chat_id пуст — только запись в БД и запись в лог;
- в `docker-compose.edge.yml` добавить API-сервису:
  `TELEGRAM_BOT_TOKEN`, `VET_API_ADMIN_TELEGRAM_CHAT_ID`,
  `VET_API_RATE_LIMIT_ENABLED=true`, `VET_API_ENABLE_DOCS=false`;
- те же переменные добавить в `.env.production.example` (без значений).

**Администрирование (MVP, без админ-UI):**

- `scripts/list_access_requests.py` — показать новые заявки, `--mark-contacted ID`;
- `scripts/create_user.py` — создать пользователя после одобрения:
  `--email`, сгенерировать пароль через `secrets.token_urlsafe(12)`,
  вывести его один раз, записать `bcrypt`-хеш;
- пароль отправляется заявителю вручную (почта/Telegram).
- Одноразовые invite-ссылки — следующая итерация, не в этом этапе.

**Rate limiting:**

- `POST /v1/auth/login` — 10 попыток/минуту с IP, 100/час;
- `POST /v1/access/request` — 3/час с IP;
- `POST /v1/auth/register` — оставить `403`, лимит не нужен;
- `slowapi` in-memory, одного uvicorn-процесса достаточно; при масштабировании
  перейти на Redis;
- ответ `429` с понятным русским текстом;
- в тестах лимитер отключается через настройку
  `VET_API_RATE_LIMIT_ENABLED=false`.

### 3.3. Frontend

**Файлы:**

- `frontend/src/components/AuthScreen.tsx` — убрать вкладку «Регистрация»,
  добавить ссылку/кнопку «Запросить доступ».
- `frontend/src/components/AccessRequestForm.tsx` — новая форма:
  email, комментарий, чекбокс согласия, ссылки на политику/условия.
- `frontend/src/lib/api.ts` — `requestAccess(email, comment)`.
- `frontend/src/lib/api.test.ts` — тест запроса и разбора `202`.
- `frontend/index.html` — `noindex` для приложения (дублируется заголовком Caddy).

Поведение:

- по умолчанию — только вход;
- «Запросить доступ» открывает форму (или `?mode=request` в URL);
- после отправки — «Заявка отправлена. Ответим на email»;
- при `429` — «Слишком много заявок, попробуйте позже»;
- внизу экрана — ссылки на политику и условия. Если пакет A выкатывается
  раньше пакета B, временно используется действующая политика
  `https://iiruchating.ru/privacy/`, а условия публикуются вместе с лендингом.

### 3.4. Юридические страницы

**Файлы (лендинг):**

- `landing/privacy/index.html` — какие данные собираем (email, сообщения,
  данные питомца), зачем, где храним, сроки, права, удаление, контакт;
- `landing/terms/index.html` — сервис не заменяет ветеринара, экстренные
  случаи, ограничения ответственности, правила использования.

Это черновики: перед публикацией нужна юридическая проверка. В политике
явно указать, что модель локальная, а данные не уходят во внешние LLM-API.

### 3.5. Критерии приёмки A

- в UI нет вкладки «Регистрация»;
- форма заявки сохраняет запись и показывает успех;
- повторная заявка не раскрывает существование аккаунта;
- 4-я заявка за час с IP даёт `429`;
- 11-я попытка входа за минуту даёт `429`;
- Telegram-уведомление приходит при настроенном chat_id;
- `scripts/create_user.py` создаёт пользователя, вход работает;
- тесты backend/frontend зелёные.

---

## 4. Пакет B — лендинг и `app.ai-pets.ru`

### 4.1. Лендинг

**Публичная статика и служебные файлы — `landing/`:**

```text
landing/
├── index.html          # hero, возможности, безопасность, скриншот, CTA
├── privacy/index.html
├── terms/index.html
├── assets/
│   ├── styles.css
│   ├── app.png         # реальный скриншот из docs/assets/react-ui.png
│   └── og.png          # 1200×630
├── robots.txt
├── sitemap.xml
├── nginx.conf          # конфиг контейнера; Caddy блокирует /nginx.conf
├── compose.edge.fragment.yml
├── Caddyfile.edge.snippet
└── DEPLOY.md
```

Служебные файлы в web-root блокируются Caddy (`@landing_private`).
Целевая чистка — вынести их в `deploy/landing/` и не держать в web-root.

Контент:

- «AI-ветеринарный ассистент для владельцев кошек и собак»;
- ответы по MSD Vet Manual, память диалога, записи и напоминания;
- безопасность: не ставит диагноз, не назначает дозировки, при тревожных
  симптомах направляет в клинику;
- CTA: **«Открыть приложение»** → `https://app.ai-pets.ru/`,
  **«Запросить доступ»** → `https://app.ai-pets.ru/?mode=request`;
- блок «как устроено»: Qwen3-8B, CPU, RAG, без внешних LLM-API;
- футер: политика, условия, контакт.

SEO:

- `title`, `description`, canonical `https://ai-pets.ru/`;
- OG/Twitter 1200×630;
- JSON-LD `SoftwareApplication`;
- `robots.txt` + `sitemap.xml` с лендингом и юридическими страницами;
- приложение `app.ai-pets.ru` — `X-Robots-Tag: noindex, nofollow`.

### 4.2. Compose

Добавить в `docker-compose.edge.yml` отдельный статический сервис, чтобы
Caddy не зависел от файлов продукта:

```yaml
  landing:
    image: nginx:stable-alpine
    container_name: vetassistant-landing
    restart: unless-stopped
    logging: *default-logging
    volumes:
      - ./landing:/usr/share/nginx/html:ro
      - ./landing/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://127.0.0.1/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - edge
```

Порты не публикуются. Caddy ходит на `vetassistant-landing:80` по сети `edge`.

### 4.3. Caddy

**Файлы:**

- `ai-infra/Caddyfile.manual` — источник истины на резерве;
- `ai_VetAssistant/deploy/Caddyfile` — standalone-вариант, синхронизировать.

Было: `ai-pets.ru` целиком уходил в `vetassistant-frontend:80`.
Стало:

```caddyfile
ai-pets.ru {
	encode zstd gzip
	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options "nosniff"
		X-Frame-Options "SAMEORIGIN"
		Referrer-Policy "strict-origin-when-cross-origin"
		Permissions-Policy "geolocation=(), microphone=(), camera=()"
	}
	handle {
		reverse_proxy vetassistant-landing:80
	}
}

app.ai-pets.ru {
	encode zstd gzip
	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options "nosniff"
		X-Frame-Options "SAMEORIGIN"
		Referrer-Policy "strict-origin-when-cross-origin"
		Permissions-Policy "geolocation=(), microphone=(), camera=()"
		X-Robots-Tag "noindex, nofollow"
	}
	handle_path /api/* {
		reverse_proxy vetassistant-api:8000 {
			flush_interval -1
		}
	}
	handle {
		reverse_proxy vetassistant-frontend:80
	}
}

www.ai-pets.ru {
	redir https://ai-pets.ru{uri} permanent
}
```

`handle_path /api/*` по-прежнему срезает `/api`; frontend собирается с
`VITE_API_BASE_URL=/api`, менять не нужно.

### 4.4. Nginx

- `frontend/nginx.conf` — **не меняется** при выборе поддомена.
- `landing/nginx.conf` — SPA/статика: `try_files $uri $uri/ =404`,
  кеш для assets, `X-Content-Type-Options`, без лишних директив.
- Если всё же выбран `/app/`: дополнительно
  `base: '/app/'` в `frontend/vite.config.ts`,
  `location /app/` в `frontend/nginx.conf`,
  `handle_path /app/*` в Caddy, ссылки в лендинге на `/app/`.

### 4.5. DNS и TLS

1. В reg.ru добавить A-запись `app.ai-pets.ru -> 62.109.1.230`, TTL 300.
2. Проверить `dig app.ai-pets.ru` с внешней сети.
3. Caddy сам выпустит сертификат для `app.ai-pets.ru` (HTTP-01/TLS-ALPN).
4. Если ACME не проходит — выпустить сертификат в панели reg.ru и добавить
   `tls /etc/caddy/certs/...`; это резервный путь, не основной.

Важно: HSTS уже стоит с `includeSubDomains`. Поддомен нельзя анонсировать,
пока TLS не готов, иначе браузеры будут ломаться на HTTPS.

### 4.6. Порядок выкладки (когда дойдём до production)

1. Собрать `landing` и новый frontend, поднять `landing` и `frontend` в compose.
2. Добавить DNS `app`, дождаться сертификата.
3. Проверить `https://app.ai-pets.ru/` и `https://app.ai-pets.ru/api/health`
   **до** переключения корня.
4. Сделать backup `Caddyfile`, выполнить `caddy validate`, затем `caddy reload`.
5. Переключить `ai-pets.ru` на лендинг.
6. Прогнать smoke: корень, app, API, форма заявки, 429, редирект www.
7. Откат: вернуть backup Caddyfile и `reverse_proxy vetassistant-frontend:80`
   для корня; DNS `app` можно оставить.

### 4.7. Критерии приёмки B

- `https://ai-pets.ru/` — лендинг, 200, корректные title/OG;
- `https://app.ai-pets.ru/` — приложение, 200;
- `https://app.ai-pets.ru/api/health` — 200;
- `https://www.ai-pets.ru/` — 301 на apex;
- `app.ai-pets.ru` отдаёт `X-Robots-Tag: noindex`;
- `ai-pets.ru/robots.txt` и `/sitemap.xml` — реальные файлы, не HTML;
- HTTPS-сертификат валиден, HSTS не ломает поддомен;
- лендинг и приложение открываются на мобильном.

---

## 5. Пакет C — доверие, SEO и аналитика

- Политика/условия: черновики + юридическая проверка.
- OG-карточка лендинга 1200×630.
- `sitemap.xml`: лендинг, privacy, terms.
- Яндекс.Метрика на лендинге: отдельный счётчик, согласие на cookie;
  цели: клик «Открыть приложение», клик «Запросить доступ».
- UTM-метки на ссылках в приложение (`?utm_source=landing&utm_medium=cta`).
- Проверить, что в приложении нет ссылок на старый корень.
- Мониторинг: uptime на `ai-pets.ru` и `app.ai-pets.ru`, алерт в Telegram.
- Проверка битых ссылок в CI для лендинга.

## 6. Пакет D — безопасность и гигиена

- `app/main.py`: в production отключить `/docs`, `/redoc`, `/openapi.json`
  через `VET_API_ENABLE_DOCS=false`.
- `/health` оставить публичным, но убрать `model_path` и внутренние настройки;
  детальную проверку RAM/модели перевести в локальный `scripts/check_ram.py`
  или защищённый endpoint.
- CORS: в production оставить только `https://app.ai-pets.ru` (или вообще
  не нужен при same-origin).
- CSP в `Report-Only` на лендинге и приложении, затем ужесточить.
- Проверить, что `VET_API_ALLOW_PUBLIC_REGISTRATION=false` остаётся в `.env`.
- Добавить в `DEPLOYMENT.md` и `ai-infra/docs/PRODUCTION.md` новые URL,
  DNS-запись и порядок отката.

---

## 7. Оценка по шагам

| Шаг | Результат | Часы |
|---|---|---:|
| A1. Модель `access_requests` + эндпоинт + тесты | заявки сохраняются | 4 |
| A2. Rate limiting login/access + тесты | 429 работает | 2 |
| A3. Форма в AuthScreen + запрос из UI | нет мёртвой регистрации | 4 |
| A4. Telegram-уведомление + скрипты list/create | заявку видно, аккаунт создаётся | 3 |
| A5. Политика/условия (черновик) | ссылки и тексты | 3 |
| **A итого** | | **16 ч (~2 дня)** |
| B1. Статический лендинг + контент + OG | лендинг готов | 6 |
| B2. `landing` сервис + compose | контейнер поднимается | 2 |
| B3. Caddy + DNS + TLS | app и корень разведены | 3 |
| B4. Smoke, откат, документация | выкладка безопасна | 3 |
| **B итого** | | **14 ч (~2 дня)** |
| C1. SEO/аналитика/OG | лендинг индексируется | 4 |
| C2. Мониторинг и ссылки | алерты | 2 |
| **C итого** | | **6 ч (~1 день)** |
| D1. OpenAPI/health/CSP | меньше поверхности атаки | 3–4 |
| **Всего** | | **~5–6 дней** |

Пакет A можно сделать и выкатить первым, не трогая домен: он сразу убирает
тупик с регистрацией. Если A выходит раньше B, в интерфейсе временно
используется действующая политика `https://iiruchating.ru/privacy/`,
а условия и лендинг публикуются в пакете B.

---

## 8. Риски

| Риск | Митигация |
|---|---|
| ACME не выпустит сертификат для `app` | проверить DNS заранее; резервный сертификат из reg.ru |
| HSTS `includeSubDomains` сломает app при ошибке TLS | не анонсировать app до успешной проверки сертификата |
| Telegram-уведомления не настроены | заявки всё равно в БД; скрипт list работает |
| Юридические тексты не проверены | не публиковать без ревью; черновики в `landing/` |
| Модель на 4 vCPU/8 ГБ | не менять `n_ctx=4096`, `n_threads=3`, `mem_limit=6g`; следить за OOM |
| Спам в форме заявок | rate limit + honeypot + комментарий до 1000 символов |
| Потеря заявок при рестарте | PostgreSQL, не in-memory очередь |

## 9. Что не входит в этап

- админ-UI для заявок;
- одноразовые invite-ссылки и самостоятельная регистрация;
- самостоятельное удаление аккаунта из UI;
- смена модели, RAG или промптов;
- платёжный/подписочный контур;
- мобильное приложение;
- перенос на другой хостинг.

## 10. Открытые решения

1. Подтверждаем `app.ai-pets.ru` или всё же `/app/`?
2. Уведомления только в Telegram или ещё email через SMTP reg.ru?
3. Кто делает юридическую проверку политики/условий?
4. Нужен ли отдельный счётчик Метрики для `ai-pets.ru` или используем
   существующий IIRuChating?
5. Нужны ли invite-ссылки вместо ручного создания аккаунта уже в этой фазе?
