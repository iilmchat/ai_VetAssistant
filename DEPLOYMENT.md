# Production-деплой VetAssistant на VPS (T-040)

Пошаговая инструкция: от аренды Ubuntu-сервера до работающего
`https://vetassistant.ru` с JWT-авторизацией, PostgreSQL и Telegram-ботом.

## Архитектура

```
Интернет
   │  :80 / :443
   ▼
┌──────────────────────────────┐
│ frontend (Nginx + React SPA) │
│  /       → index.html        │
│  /api/*  → api:8000          │
└──────────────┬───────────────┘
               │ внутренняя сеть Docker
               ▼
        ┌─────────────┐        ┌──────────────────┐
        │ api:8000    │───────▶│ PostgreSQL 16    │
        │ FastAPI     │        │ volume postgres  │
        └──────┬──────┘        └──────────────────┘
               │
        ┌──────▼──────┐
        │ bot         │  исходящие запросы к Telegram API
        └─────────────┘
```

Наружу открыты только `80` и `443`. Порты `8000` (API), `5432`
(PostgreSQL) и `8501` (Streamlit) в production не публикуются.

Основные файлы:

| Файл | Назначение |
|---|---|
| `.env.production.example` | шаблон production-секретов и настроек |
| `docker-compose.prod.yml` | production-стек, публикует только `frontend:80` |
| `docker-compose.ssl.yml` | HTTPS-overlay: `443`, Certbot и сертификаты |
| `frontend/nginx.conf` | HTTP-сервер, `/api`, SPA и ACME |
| `deploy/nginx/ssl.conf` | HTTPS-сервер и редирект с HTTP |
| `scripts/deploy.sh` | установка Docker, клонирование и запуск |
| `scripts/renew_ssl.sh` | продление сертификата и reload Nginx |

## 1. Требования к серверу

- Ubuntu 22.04/24.04 LTS (подойдёт Debian 12).
- **Минимум 4 vCPU, 8 ГБ RAM, 40 ГБ SSD.** Комфортно: 4–8 vCPU,
  16 ГБ RAM. Qwen3-8B в Q4_K_M занимает около 5–6 ГБ памяти, плюс
  PostgreSQL, ChromaDB и системные процессы.
- Публичный IPv4.
- Домен или поддомен, которым вы управляете.
- SSH-доступ с ключом.

> CPU-инференс 8B-модели работает, но отвечает медленно. Для нескольких
> одновременных пользователей лучше 8+ vCPU или GPU-сервер.

## 2. Аренда сервера

Подойдут Selectel, Reg.Cloud, Timeweb Cloud и другие провайдеры с
Ubuntu 24.04.

1. Создайте сервер с Ubuntu 24.04 LTS.
2. Добавьте SSH-ключ при создании (пароль root лучше отключить).
3. Запишите публичный IP, например `203.0.113.10`.
4. Проверьте вход:

   ```bash
   ssh root@203.0.113.10
   ```

5. Обновите систему:

   ```bash
   apt update && apt upgrade -y
   ```

## 3. DNS: A-запись на сервер

В панели домена создайте записи:

| Тип | Имя | Значение | TTL |
|---|---|---|---|
| `A` | `@` | `203.0.113.10` | 300 |
| `A` | `www` | `203.0.113.10` | 300 |

Проверьте распространение DNS:

```bash
dig +short vetassistant.ru
dig +short www.vetassistant.ru
```

Оба ответа должны совпадать с IP сервера. Обычно это занимает от
нескольких минут до часа. **Не выпускайте SSL, пока DNS не указывает
на сервер** — Let's Encrypt не сможет пройти проверку.

## 4. Firewall

Откройте только SSH, HTTP и HTTPS:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
ufw status
```

Не открывайте `8000`, `5432` и `8501`: в production они доступны только
внутри Docker-сети. Дополнительно можно включить firewall провайдера с
теми же правилами.

> Docker публикует порты в обход некоторых правил UFW. В нашем compose
> наружу публикуется только `frontend` (`80`/`443`), поэтому этого
> достаточно. Не добавляйте `ports` для `api` и `db`.

## 5. Быстрый деплой скриптом (рекомендуется)

Скрипт можно запустить прямо на чистом сервере — он сам установит Docker,
клонирует репозиторий в `/opt/vetassistant`, сгенерирует секреты и
поднимет стек.

```bash
curl -fsSL https://raw.githubusercontent.com/iilmchat/ai_VetAssistant/main/scripts/deploy.sh \
  -o /tmp/deploy.sh
sudo bash /tmp/deploy.sh --ssl
```

Скрипт интерактивно спросит:

- домен (например, `vetassistant.ru`);
- email для Let's Encrypt;
- токен Telegram-бота от @BotFather.

Для неинтерактивного запуска:

```bash
export DOMAIN=vetassistant.ru
export LETSENCRYPT_EMAIL=admin@vetassistant.ru
export TELEGRAM_BOT_TOKEN='123456789:AA...'
sudo -E bash /tmp/deploy.sh --ssl
```

Что делает `deploy.sh`:

1. Ставит `docker-ce`, `docker-compose-plugin`, `git`, `curl`, `openssl`.
2. Клонирует `main` в `/opt/vetassistant` (или обновляет существующий клон).
3. Если `.env` нет — копирует `.env.production.example` и генерирует
   `POSTGRES_PASSWORD`, `VET_API_JWT_SECRET`, `VET_BOT_AUTH_SECRET`
   через `openssl rand -hex 32`.
4. Собирает и запускает `docker-compose.prod.yml`.
5. Ждёт `http://127.0.0.1/healthz`.
6. С флагом `--ssl` выпускает сертификат и включает HTTPS-overlay.

Если бот не нужен, удалите сервис `bot` из `docker-compose.prod.yml` до
запуска: production compose требует `TELEGRAM_BOT_TOKEN`, когда сервис
включён.

Повторный запуск скрипта обновляет код и пересобирает контейнеры. Секреты
в существующем `.env` не перезаписываются.

### Windows: автоматизированный деплой через Python

Если SSH-сессии из терминала неудобны, используйте Paramiko-оркестратор:

```powershell
pip install -e .
python scripts/deploy_prod.py
```

Скрипт запросит пароль root и выполнит установку Docker, клонирование,
создание `.env`, сборку стека, SFTP-загрузку модели, перезапуск API и
выпуск SSL. Токен Telegram можно передать через
`$env:TELEGRAM_BOT_TOKEN`, email — через `--email`. После деплоя:

```powershell
python scripts/smoke_test.py
```

Подробнее — в разделе README «Автоматизированный деплой на VPS».

## 6. Ручной деплой (если не используете скрипт)

```bash
apt update
apt install -y git

git clone --branch main \
  https://github.com/iilmchat/ai_VetAssistant.git /opt/vetassistant
cd /opt/vetassistant

cp .env.production.example .env
chmod 600 .env
nano .env
```

Сгенерируйте три независимых секрета:

```bash
openssl rand -hex 32   # POSTGRES_PASSWORD
openssl rand -hex 32   # VET_API_JWT_SECRET
openssl rand -hex 32   # VET_BOT_AUTH_SECRET
```

Заполните в `.env`:

- `POSTGRES_PASSWORD`, `VET_API_JWT_SECRET`, `VET_BOT_AUTH_SECRET`;
- `TELEGRAM_BOT_TOKEN` — токен от @BotFather;
- `VET_DOMAIN` — домен без `https://`;
- `LETSENCRYPT_EMAIL` — email для Let's Encrypt.

> Используйте для пароля PostgreSQL hex-строку без спецсимволов. Если
> задать пароль со спецсимволами, его нужно percent-кодировать в
> `VET_API_DATABASE_URL`.

Затем:

```bash
bash scripts/deploy.sh --ssl
```

или вручную:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## 7. Модель GGUF и база знаний

Модель не хранится в Git. Загрузите её в `data/gguf/` на сервере:

```bash
# На локальной машине
scp data/gguf/qwen3-8b-vet-Q4_K_M.gguf \
  root@203.0.113.10:/opt/vetassistant/data/gguf/
```

Если SSH для root закрыт, скопируйте во временный каталог пользователя,
затем переместите через `sudo`.

Альтернатива — `dvc pull`, если на сервере настроены ключи S3 Selectel
(см. `scripts/setup_remote.sh` и README).

Без модели API запустится, но будет отвечать `503 Модель недоступна`.
Индекс ChromaDB опционален: без него RAG просто не добавляет контекст.
Построить индекс можно в контейнере:

```bash
docker compose -f docker-compose.prod.yml exec api \
  python scripts/ingest_knowledge.py
```

## 8. Проверка после запуска

```bash
docker compose -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1/healthz
curl -fsS http://vetassistant.ru/healthz
curl -fsS http://vetassistant.ru/api/health
```

`/api/health` проксируется в FastAPI `/health`. Затем откройте
`http://vetassistant.ru`, зарегистрируйте пользователя и проверьте чат,
записи и напоминания.

Полезные команды:

```bash
# Логи
docker compose -f docker-compose.prod.yml logs -f api frontend bot

# Статус и потребление ресурсов
docker compose -f docker-compose.prod.yml ps
docker stats

# Проверка конфигурации без запуска
docker compose -f docker-compose.prod.yml config
```

## 9. HTTPS через Let's Encrypt / Certbot

HTTPS использует **webroot-режим**: frontend на :80 отдаёт
`/.well-known/acme-challenge/`, Certbot кладёт туда файл, Let's Encrypt
проверяет домен. Сертификат имеет фиксированное имя `vetassistant`,
поэтому `deploy/nginx/ssl.conf` не зависит от домена.

Предварительно:

1. DNS A-запись уже указывает на сервер.
2. Порт `80` открыт.
3. HTTP-стек запущен (`docker compose -f docker-compose.prod.yml up -d`).

Выпуск сертификата:

```bash
cd /opt/vetassistant

docker compose \
  -f docker-compose.prod.yml \
  -f docker-compose.ssl.yml \
  --profile tools run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  -d vetassistant.ru \
  --cert-name vetassistant \
  --email admin@vetassistant.ru \
  --agree-tos --no-eff-email --non-interactive
```

Включение HTTPS (порт 443 и редирект с HTTP):

```bash
docker compose \
  -f docker-compose.prod.yml \
  -f docker-compose.ssl.yml up -d
```

Проверка:

```bash
curl -I https://vetassistant.ru
curl -fsS https://vetassistant.ru/healthz
```

Ожидаемо: `HTTP/2 200`, заголовок `strict-transport-security` и
редирект `http://` → `https://`.

> Если сайт должен открываться и по `www`, добавьте `-d www.vetassistant.ru`
> к команде Certbot и создайте для `www` отдельную A-запись. Nginx в этом
> проекте настроен на один домен; при необходимости добавьте `www` в
> `server_name` конфигураций.

### Автопродление

Certbot продлевает сертификат за 30 дней до истечения. Добавьте cron от
root:

```bash
crontab -e
```

```cron
0 3 * * * /opt/vetassistant/scripts/renew_ssl.sh >> /var/log/vetassistant-ssl.log 2>&1
```

`renew_ssl.sh` выполняет `certbot renew`, затем `nginx -s reload` в
контейнере frontend. Проверить продление без реального запроса:

```bash
docker compose \
  -f docker-compose.prod.yml \
  -f docker-compose.ssl.yml \
  --profile tools run --rm certbot renew --dry-run
```

## 10. Обновление приложения

```bash
cd /opt/vetassistant
sudo bash scripts/deploy.sh
```

Скрипт делает `git pull --ff-only`, пересобирает образы и перезапускает
контейнеры. Если сертификат уже выпущен, HTTPS-overlay подключается
автоматически. `.env` и `postgres_data` сохраняются.

Перед обновлением рекомендуется сделать бэкап БД.

## 11. Бэкап PostgreSQL

Создать дамп:

```bash
cd /opt/vetassistant
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -U vetassistant vetassistant > "backup-$(date +%F).sql"
```

Восстановить:

```bash
cat backup-2026-11-03.sql | \
  docker compose -f docker-compose.prod.yml exec -T db \
  psql -U vetassistant -d vetassistant
```

Храните дампы вне сервера (S3 Selectel и т.п.). Отдельно сохраните `.env`
в менеджере секретов: без `VET_API_JWT_SECRET` старые токены станут
недействительны, а без `VET_BOT_AUTH_SECRET` бот не сможет войти в
существующие Telegram-аккаунты.

## 12. Диагностика

| Симптом | Что проверить |
|---|---|
| `502 Bad Gateway` | `docker compose ... logs api`; API healthy; модель в `data/gguf` |
| `503 Модель недоступна` | файл GGUF отсутствует или путь в `VET_API_MODEL_PATH` неверен |
| `port is already allocated` | на хосте уже занят `80`/`443` (nginx/apache); остановите его |
| Certbot: `unauthorized` | DNS ещё не обновился, закрыт `80`, неверный домен |
| Certbot: `connection refused` | frontend не запущен или ACME-каталог не смонтирован |
| Сайт открывается, API — нет | `docker compose ... logs frontend`; проверьте `/api/health` |
| Telegram-бот молчит | `docker compose ... logs bot`; проверьте токен и `VET_BOT_AUTH_SECRET` |
| После перезагрузки сервера ничего не работает | `systemctl status docker`; `docker compose ... up -d` |

Проверка ACME-каталога вручную:

```bash
curl -i http://vetassistant.ru/.well-known/acme-challenge/test
```

Ожидаемо `404` (файла нет), но не `301`/`502`. Если `301` — HTTPS-overlay
уже включён, и запрос уходит на HTTPS; для диагностики временно
используйте `curl -I` с `--resolve`.

## 13. Security checklist

- [ ] `.env` имеет права `600` и не попал в Git.
- [ ] `POSTGRES_PASSWORD`, `VET_API_JWT_SECRET`, `VET_BOT_AUTH_SECRET`
      сгенерированы независимо через `openssl rand -hex 32`.
- [ ] Наружу открыты только `22`, `80`, `443`.
- [ ] API и PostgreSQL не опубликованы на хост.
- [ ] HTTPS работает, HTTP редиректит на HTTPS.
- [ ] Автопродление сертификата добавлено в cron и проверено `--dry-run`.
- [ ] Настроены бэкапы PostgreSQL и `.env`.
- [ ] Включены обновления безопасности Ubuntu (`unattended-upgrades`).
- [ ] Токен Telegram-бота и пароли не публиковались в чатах и issue.
- [ ] Для SSH отключён вход по паролю, используется ключ.
