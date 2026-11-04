# Production-деплой VetAssistant на VPS (T-040)

Пошаговая инструкция: от аренды Ubuntu-сервера до работающего
`https://vetassistant.ru` с JWT-авторизацией и PostgreSQL.

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
        └─────────────┘        └──────────────────┘
```

Наружу открыты только `80` и `443`. Порты `8000` (API), `5432`
(PostgreSQL) и `8501` (Streamlit) в production не публикуются.

> **Общий VPS с Caddy:** если 80/443 уже заняты другим проектом, не
> используйте `docker-compose.prod.yml`/`docker-compose.ssl.yml`. Для
> изолированного `/srv/vetassistant` есть `docker-compose.edge.yml`
> (внешняя сеть `edge`, без публикации портов), `deploy/Caddyfile` и
> `scripts/upload_model.py`. TLS завершает Caddy инфраструктурного агента.

Основные файлы:

| Файл | Назначение |
|---|---|
| `.env.production.example` | шаблон production-секретов и настроек |
| `docker-compose.prod.yml` | выделенный production-стек, публикует `frontend:80` |
| `docker-compose.ssl.yml` | HTTPS-overlay: `443`, Certbot и сертификаты |
| `docker-compose.edge.yml` | общий VPS: только сеть `edge`, без портов и бота |
| `frontend/nginx.conf` | HTTP-сервер, `/api`, SPA и ACME |
| `landing/` | публичная статика лендинга (web-root без служебных файлов) |
| `docs/landing/` | `nginx.conf`, Caddy-сниппет, `DEPLOY.md` и README лендинга |
| `deploy/nginx/ssl.conf` | HTTPS-сервер и редирект с HTTP |
| `deploy/Caddyfile` | Caddy-блок `ai-pets.ru` и `www` для edge-сети |
| `scripts/deploy.sh` | установка Docker, клонирование и запуск |
| `scripts/setup_ufw.sh` | настройка UFW: SSH, HTTP, HTTPS и deny incoming |
| `scripts/setup_deploy_user.sh` | пользователь `deployer` и SSH-каталог для CI/CD |
| `.github/workflows/deploy.yml` | автодеплой edge-стека по тегу `v*` |
| `scripts/renew_ssl.sh` | продление сертификата и reload Nginx |
| `scripts/upload_model.py` | SFTP-загрузка GGUF с проверкой SHA-256 |
| `scripts/check_ram.py` | проверка `/api/health`, GGUF и текущего `n_ctx` |
| `scripts/smoke_test.py` | проверка сайта, входа, чата и записей |

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

### Настройка Git на сервере

На сервере уже могут быть SSH-ключи других проектов. Чтобы не менять
глобальный конфиг GitHub и не конфликтовать с ними, доступ к репозиторию
VetAssistant идёт через SSH-алиас **`github.com-vetassistant`**, а не через
стандартный `github.com`.

Проверьте `~/.ssh/config` — инфраструктурный агент добавляет туда блок
вида:

```sshconfig
Host github.com-vetassistant
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_vetassistant
    IdentitiesOnly yes
```

`Host` — произвольное имя алиаса, `HostName` — реальный хост GitHub,
`IdentityFile` — ключ, у которого есть доступ к `iilmchat/ai_VetAssistant`.
`IdentitiesOnly yes` заставляет SSH использовать именно этот ключ, не
перебирая остальные. Права на файл:

```bash
chmod 600 ~/.ssh/config
```

Проверка алиаса:

```bash
ssh -T git@github.com-vetassistant
```

Ожидаемо сообщение `Hi <user>! You've successfully authenticated...`
(предупреждение об отсутствии shell-доступа — нормально).

Клонирование репозитория через алиас:

```bash
git clone git@github.com-vetassistant:iilmchat/ai_VetAssistant.git \
  /opt/vetassistant
```

Если репозиторий уже склонирован (например, в `/srv/vetassistant`) и нужно
переключить `origin` на алиас:

```bash
cd /opt/vetassistant
git remote add origin git@github.com-vetassistant:iilmchat/ai_VetAssistant.git
```

Если `origin` уже существует, замените URL:

```bash
git remote set-url origin git@github.com-vetassistant:iilmchat/ai_VetAssistant.git
```

Проверьте, что используется правильный remote, и обновите код:

```bash
git remote -v
git fetch origin
git pull --ff-only origin main
```

> Не заменяйте `github.com-vetassistant` на `github.com` в командах: без
> алиаса SSH может выбрать ключ другого проекта, и доступ к репозиторию
> завершится ошибкой `Permission denied (publickey)`.

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

## 4. Безопасность сервера

### Firewall (UFW)

Наружу должны быть открыты только SSH, HTTP и HTTPS. На чистом Ubuntu
настройте firewall готовым скриптом:

```bash
cd /opt/vetassistant
sudo bash scripts/setup_ufw.sh
```

Что делает скрипт:

1. устанавливает `ufw`, если он отсутствует;
2. разрешает SSH (`22/tcp`), HTTP (`80/tcp`) и HTTPS (`443/tcp`);
3. запрещает входящие соединения по умолчанию и разрешает исходящие;
4. включает firewall и печатает итоговые правила.

Скрипт идемпотентен: повторный запуск не сбрасывает существующие правила.
Если SSH работает на нестандартном порту, укажите его через переменную
окружения — порт `22` всё равно останется открытым как страховка:

```bash
sudo SSH_PORT=2222 bash scripts/setup_ufw.sh
```

Проверьте результат:

```bash
sudo ufw status verbose
```

Ожидаемо `Status: active` и разрешающие правила для `22`, `80` и `443`.
Те же действия вручную:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw default deny incoming
ufw default allow outgoing
ufw enable
ufw status
```

Не открывайте `8000`, `5432` и `8501`: в production они доступны только
внутри Docker-сети. Дополнительно можно включить firewall провайдера с
теми же правилами.

> Docker публикует порты в обход некоторых правил UFW. В нашем compose
> наружу публикуется только `frontend` (`80`/`443`), поэтому этого
> достаточно. Не добавляйте `ports` для `api` и `db`.

> Перед включением UFW убедитесь, что SSH-порт доступен и порт `22` не
> закрыт firewall провайдера: иначе можно потерять доступ к серверу.

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
sudo -E bash /tmp/deploy.sh --ssl
```

Если на сервере настроен SSH-алиас `github.com-vetassistant` (см. раздел
«Настройка Git на сервере»), передайте его в `REPO_URL`:

```bash
export REPO_URL=git@github.com-vetassistant:iilmchat/ai_VetAssistant.git
sudo -E bash /tmp/deploy.sh --ssl
```

Что делает `deploy.sh`:

1. Ставит `docker-ce`, `docker-compose-plugin`, `git`, `curl`, `openssl`.
2. Клонирует `main` в `/opt/vetassistant` (или обновляет существующий клон).
3. Если `.env` нет — копирует `.env.production.example` и генерирует
   `POSTGRES_PASSWORD`, `VET_API_JWT_SECRET` через `openssl rand -hex 32`.
4. Собирает и запускает `docker-compose.prod.yml`.
5. Ждёт `http://127.0.0.1/healthz`.
6. С флагом `--ssl` выпускает сертификат и включает HTTPS-overlay.

Повторный запуск скрипта обновляет код и пересобирает контейнеры. Секреты
в существующем `.env` не перезаписываются.

### Edge-деплой на общем VPS (T-043)

Если 80/443 уже заняты Caddy инфраструктурного агента, используйте
`docker-compose.edge.yml`, `deploy/Caddyfile` и `scripts/upload_model.py`.
Стек не публикует порты, подключается к внешней сети `edge`, содержит API,
frontend и Telegram-бота с allowlist; Streamlit в него не входит. Регистрация
в production закрыта флагом `VET_API_ALLOW_PUBLIC_REGISTRATION=false`.

```bash
docker network inspect edge
docker compose -f docker-compose.edge.yml up -d --build
python scripts/upload_model.py --host 62.109.1.230
```

После подключения Caddy-блока:

```powershell
python scripts/smoke_test.py --base-url https://ai-pets.ru --email owner@example.com
```

Пароль будет запрошен через `getpass`. Скрипт входит существующим
пользователем, проверяет главную, чат и `/api/v1/appointments`.

Подробнее — в разделе README «Edge-деплой для инфраструктурного агента».

#### Telegram-бот в edge-стеке (T-121)

Бот работает в том же образе (`python -m bot`), не публикует порты и ходит к
API по сети `edge`. В `.env` на сервере добавьте:

```dotenv
TELEGRAM_BOT_TOKEN=123456789:AA...
# Только эти Telegram ID могут пользоваться ботом (через запятую).
VET_BOT_ALLOWED_TELEGRAM_IDS=111111111,222222222
# Если с VPS заблокирован api.telegram.org — URL Cloudflare Worker.
# По умолчанию https://api.telegram.org
VET_BOT_TELEGRAM_API_BASE=https://tg.example.workers.dev
```

Публичная регистрация закрыта, поэтому бот **не создаёт** аккаунты: для
разрешённого ID аккаунт создаёт администратор после одобрения заявки.

```bash
docker compose -f docker-compose.edge.yml exec api \
  python scripts/create_telegram_user.py --telegram-id 111111111

docker compose -f docker-compose.edge.yml up -d bot
docker compose -f docker-compose.edge.yml logs -f bot
```

`create_telegram_user.py` сам вычисляет synthetic email и пароль из
`VET_BOT_AUTH_SECRET` (fallback — `TELEGRAM_BOT_TOKEN`) и не печатает пароль.

Проверка:
- `/start` и вопрос по базе знаний от ID из allowlist работают, RAG включён;
- ID вне списка получает «Доступ к боту ограничен…», аккаунт не создаётся;
- без `VET_BOT_ALLOWED_TELEGRAM_IDS` контейнер завершается с ошибкой
  (fail closed), остальной стек продолжает работать.

## 6. Настройка CI/CD

Автодеплой edge-стека по тегу `v*` выполняет
`.github/workflows/deploy.yml` на **self-hosted runner**, установленном на
том же VPS. Workflow заходит в `/srv/vetassistant`, делает
`git pull --ff-only`, затем:

```bash
docker compose -f docker-compose.edge.yml build api frontend
docker compose -f docker-compose.edge.yml up -d --no-build
```

Раздельная сборка убирает гонку Docker за общий image tag между api и bot.
SSH-секреты и внешние SSH-экшены больше не используются.

Сборка образов выполняется **только** в `deploy.yml`. `.github/workflows/release.yml`
по тому же тегу `v*` создаёт GitHub Release и больше не делает `docker build`:
раньше оба workflow собирали `api`/`frontend` на одном VPS, и каждый тег тратил
на это лишние 20–30 минут (T-130).

### 6.1. Self-hosted runner на VPS

В GitHub откройте **Settings → Actions → Runners → New self-hosted runner**
(Linux x64) и выполните команды из инструкции. Пример для пользователя
`runner` и каталога `/opt/actions-runner`:

```bash
sudo useradd -m -s /bin/bash runner
sudo usermod -aG docker runner
sudo mkdir -p /opt/actions-runner
sudo chown -R runner:runner /opt/actions-runner

sudo -u runner bash -c '
  cd /opt/actions-runner
  curl -fsSL -o runner.tar.gz <URL_ИЗ_ИНСТРУКЦИИ_GITHUB>
  tar xzf runner.tar.gz
  ./config.sh --url https://github.com/iilmchat/ai_VetAssistant \
    --token <TOKEN_ИЗ_GITHUB> --name vetassistant-vps \
    --labels vps --unattended --replace
'
```

Метки `self-hosted`, `linux`, `x64` GitHub добавляет автоматически, `vps` —
наша метка; workflow требует весь набор `[self-hosted, linux, x64, vps]`.

Установите runner как сервис, чтобы он переживал перезагрузку:

```bash
cd /opt/actions-runner
sudo ./svc.sh install runner
sudo ./svc.sh start
sudo ./svc.sh status
```

Runner должен иметь право писать в `/srv/vetassistant` и доступ к Docker:

```bash
sudo chown -R runner:runner /srv/vetassistant
sudo -u runner docker ps
```

> **Безопасность:** self-hosted runner имеет доступ к Docker и production-
> каталогу. В `ci.yml` у всех джобов стоит условие
> `github.event_name == 'push' || github.event.pull_request.head.repo.full_name == github.repository`,
> поэтому код из форков на VPS не выполняется. Не снимайте это условие.

### 6.2. Проверка регистрации runner

```bash
gh api repos/iilmchat/ai_VetAssistant/actions/runners \
  --jq '.runners[] | {name, status, labels: [.labels[].name]}'
```

Ожидаем `status=online` и метки `self-hosted`, `linux`, `x64`, `vps`.
Если джобы висят в `queued`, почти всегда не хватает метки `vps` или runner
офлайн.

### 6.3. Секреты GitHub Actions

Для деплоя SSH-секреты больше не нужны: workflow выполняется локально на
сервере. Секреты `SSH_HOST`, `SSH_USER`, `SSH_KEY` можно удалить из
**Settings → Secrets and variables → Actions**. `GITHUB_TOKEN` workflow
получает автоматически.

### 6.4. Проверка автоматического деплоя

Workflow запускается при пуше тега `v*`:

```bash
git tag -a v1.5.5 -m "Deploy test"
git push origin v1.5.5
```

Ход выполнения: вкладка **Actions → Deploy**, либо:

```bash
gh run list --workflow=deploy.yml
```

Проверьте на сервере:

```bash
cd /srv/vetassistant
git log -1 --oneline
docker compose -f docker-compose.edge.yml ps --format '{{.Service}} {{.Image}}'
```

> Важно: тег — только триггер workflow. На сервере выполняется
> `git pull --ff-only` текущей ветки `main`, поэтому тег должен указывать
> на коммит, который уже есть в `main`.

Версия образа подтягивается из тега (T-131): шаг `Resolve image version from
tag` берёт `GITHUB_REF_NAME` без префикса `v` (`v1.5.5` → `1.5.5`) и передаёт
её в `docker compose` через `env` как `VETASSISTANT_VERSION`. В compose-файлах
образы описаны как `vetassistant:${VETASSISTANT_VERSION:-latest}` и
`vetassistant-frontend:${VETASSISTANT_VERSION:-latest}`, поэтому вывод `ps`
показывает запущенную сборку, а без переменной (локальный запуск) используется
`latest`.

Шаг `Persist image version to .env` (T-132) дополнительно записывает версию в
`/srv/vetassistant/.env` — идемпотентно, без дубликатов строк:

```bash
# как это выглядит на сервере после деплоя
grep '^VETASSISTANT_VERSION=' /srv/vetassistant/.env
# VETASSISTANT_VERSION=1.5.6
```

Файл должен принадлежать пользователю runner (`deployer`). Если `.env`
редактировали через `sudo` и он стал root-only, шаг выведет warning с готовой
командой и продолжит деплой — версия всё равно уйдёт в compose через `env`,
но персистентность для ручных перезапусков не заработает. Исправляется один
раз:

```bash
sudo chown deployer:deployer /srv/vetassistant/.env
sudo chmod 600 /srv/vetassistant/.env
```

Перезапустить деплой без нового тега можно вручную (версия передаётся
входным параметром):

```bash
gh workflow run deploy.yml --ref main -f version=1.5.6
```

Благодаря этому версия переживает ручной `docker compose up -d` и перезагрузку
сервера: compose читает `.env` сам и не откатывается на `latest`.

### 6.5. Порядок релиза: сначала зелёный CI, потом тег

Тег и CI используют один self-hosted runner с одним слотом, поэтому теговые
workflow стоят в очереди за CI: на `v1.5.4` ожидание составило 35 минут при
16 минутах самого деплоя. Чтобы не терять это время, соблюдайте порядок:

1. Запушьте коммит в `main`.
2. Дождитесь зелёного CI: вкладка **Actions** или `gh run list --limit 3`.
3. Только после этого ставьте тег и пушьте его — `release.yml` и `deploy.yml`
   сразу получат свободный runner.

```bash
git tag -a v1.5.5 -m "VetAssistant v1.5.5"
git push origin v1.5.5
```

### 6.6. Ручной перезапуск: только `scripts/restart_prod.sh`

> **Не запускайте `docker compose up -d` на сервере вручную.** Если
> `VETASSISTANT_VERSION` не задана в текущей оболочке и отсутствует в `.env`,
> compose возьмёт тег `latest`, и на проде окажется не тот образ. Для ручного
> перезапуска есть скрипт, который сам подставляет версию.

```bash
cd /srv/vetassistant
./scripts/restart_prod.sh                # версия из ближайшего git-тега
./scripts/restart_prod.sh 1.5.5          # явная версия
COMPOSE_FILE=docker-compose.prod.yml ./scripts/restart_prod.sh   # другой стек
```

Что делает скрипт:

1. определяет версию: `git describe --tags --exact-match`, иначе ближайший тег
   (с предупреждением в stderr), либо берёт аргумент командной строки;
2. проверяет формат версии (`^[0-9A-Za-z._-]+$`) и наличие `.env` и
   compose-файла;
3. идемпотентно обновляет `VETASSISTANT_VERSION` в `.env` и экспортирует её;
4. поднимает стек **без сборки**: `docker compose up -d --no-build`;
5. печатает таблицу `service / image / status`, чтобы сразу видеть теги.

Сборка образов остаётся за `deploy.yml` и тегом — скрипт ничего не пересобирает,
поэтому не может подменить версию «на лету».

Если деплой не прошёл, проверьте:

| Симптом | Что проверить |
|---|---|
| Джоба висит в `queued` | runner `online`, метки `self-hosted, linux, x64, vps` |
| `permission denied` на Docker | `groups runner`, `sudo usermod -aG docker runner` |
| `dubious ownership` в Git | владельца `/srv/vetassistant` и права `runner` |
| `git pull` не обновляет код | ветку `main`, `--ff-only` и наличие коммита на сервере |
| `docker compose` падает на переменных | `.env` в `/srv/vetassistant` (JWT, PostgreSQL, Telegram) |
| В `docker ps` тег `latest` | `VETASSISTANT_VERSION` в `.env`; запускать `scripts/restart_prod.sh` |
| В `docker ps` старый тег образа | `VETASSISTANT_VERSION` в логе шага, тег `v*` и `git pull` на сервере |

## 7. Ручной деплой (если не используете скрипт)

```bash
apt update
apt install -y git

git clone --branch main \
  git@github.com-vetassistant:iilmchat/ai_VetAssistant.git /opt/vetassistant
cd /opt/vetassistant

cp .env.production.example .env
chmod 600 .env
nano .env
```

Сгенерируйте два независимых секрета:

```bash
openssl rand -hex 32   # POSTGRES_PASSWORD
openssl rand -hex 32   # VET_API_JWT_SECRET
```

Заполните в `.env`:

- `POSTGRES_PASSWORD`, `VET_API_JWT_SECRET`;
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

## 8. Модель GGUF и база знаний

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

### RAG: ChromaDB в production (T-110)

Статьи лежат в `data/knowledge/` и хранятся в Git (TXT/PDF, включая
`data/knowledge/real/`). На сервере каталог монтируется в API как
`/app/data/knowledge`, поэтому отдельная DVC-загрузка не нужна: достаточно
`git pull`. В репозитории уже есть 3 демо-файла и 2 реальные статьи MSD Vet
Manual (`real/msd_toxicoses_from_human_analgesics.txt`,
`real/msd_acute_hemorrhagic_diarrhea_dogs.txt`); после `git pull` они
оказываются на сервере автоматически.

Edge-стек автоматически строит индекс при старте API:

- entrypoint проверяет коллекцию `msd_vet_manual` в `data/chroma_db`;
- если коллекции нет или она пуста, запускается
  `scripts/ingest_knowledge.py` **до** старта `uvicorn`;
- модель эмбеддингов
  `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` скачивается
  из HuggingFace при первом ingest (нужен исходящий доступ в интернет) и
  кешируется в volume `hf_cache` (`/root/.cache/huggingface`), а не в
  контейнере;
- после ingest процесс завершается, и только затем загружается API — это
  важно на сервере с 6 ГБ RAM;
- если индекс собрать не удалось, API всё равно стартует без RAG и пишет
  предупреждение `RAG: индекс ChromaDB не найден ...` в лог; при
  `VET_API_INGEST_STRICT=1` деплой падает.

Управление поведением в `.env`:

```bash
VET_API_AUTO_INGEST=1       # 0 — отключить автоматический ingest
VET_API_INGEST_STRICT=0     # 1 — падать деплоем при ошибке ingest
```

Ручное обновление индекса в контейнере (по умолчанию `upsert`: коллекция
сохраняется, существующие чанки обновляются, новые добавляются). Пути по
умолчанию берутся от рабочей директории `/app`, поэтому флаги не нужны:

```bash
docker compose -f docker-compose.edge.yml exec api \
  python scripts/ingest_knowledge.py
```

`--knowledge-dir`/`--chroma-dir` нужны только для нестандартных путей
(по умолчанию `/app/data/knowledge` и `/app/data/chroma_db`).

Полная пересборка с удалением коллекции — только с флагом `--rebuild`
(например, после массового удаления статей):

```bash
docker compose -f docker-compose.edge.yml exec api \
  python scripts/ingest_knowledge.py --rebuild
```

> На 6 ГБ RAM запуск ingest внутри уже работающего API может привести к
> OOM: embedding-модель загрузится рядом с 8B-моделью. Безопасный вариант —
> остановить API, собрать индекс отдельным одноразовым контейнером и
> поднять API снова:

```bash
docker compose -f docker-compose.edge.yml stop api
docker compose -f docker-compose.edge.yml run --rm --no-deps \
  --entrypoint python api scripts/ingest_knowledge.py
docker compose -f docker-compose.edge.yml up -d api
```

Существующий индекс при этом не теряется: 77 чанков из текущих статей
останутся, если не передан `--rebuild`.

Проверить, что индекс собран:

```bash
docker compose -f docker-compose.edge.yml exec api python -c \
  "from chromadb import PersistentClient; print(PersistentClient(path='/app/data/chroma_db').get_collection('msd_vet_manual').count())"
```

Число должно быть больше нуля. Логи ingest и RAG:

```bash
docker compose -f docker-compose.edge.yml logs api | grep -E "RAG|чанк"
```

Проверка в UI:

1. Войдите на сайт и откройте сайдбар.
2. Включите **«База знаний (RAG)»**.
3. Задайте вопрос по статье, например: «Какие симптомы отравления
   парацетамолом у кошек?» или «Что делать при геморрагической диарее у
   собаки?».
4. В логах API появится строка вида `RAG: добавлено чанков: N`; ответ
   должен опираться на факты из статьи.

Если RAG не отвечает, проверьте, что `data/knowledge/*.txt` есть на сервере
и индекс пересобран после `git pull`.

### Как добавить новые статьи в RAG (T-133)

Индекс `msd_vet_manual` обновляется через `upsert`: новые чанки добавляются,
существующие обновляются на месте, старые не удаляются. Для расширения базы
`--rebuild` не нужен — он пересобирает индекс с нуля.

**1. Скачать статью по прямой ссылке.** Возьмите URL со страницы
msdvetmanual.com и передайте его скрипту (`--url` можно повторять):

```bash
python scripts/download_msd.py \
  --url https://www.msdvetmanual.com/dog-owners/lung-and-airway-disorders-of-dogs/bronchitis-in-dogs
```

Файл появится в `data/knowledge/real/msd_bronchitis_in_dogs.txt`: имя выводится
из последнего сегмента URL, поэтому повторная загрузка перезапишет тот же файл,
а не создаст дубль. Скрипт сначала идёт напрямую на msdvetmanual.com, а при
ошибке или неполном HTML повторяет запрос через translate-прокси. План загрузки
без обращения к сети — `--dry-run`.

**2. Проверить, что текст извлёкся.** Быстрая проверка без ChromaDB:

```bash
python scripts/ingest_knowledge.py --dry-run | grep -c "DRY-RUN"
head -3 data/knowledge/real/msd_bronchitis_in_dogs.txt
```

В файле должны быть строки `Source:`, `Title:`, `Downloaded:` и осмысленный
текст статьи (скрипт отбрасывает страницы короче 500 символов).

**3. Проиндексировать на сервере.** На 6 ГБ RAM ingest рядом с работающим API
может уронить контейнер по OOM, поэтому API останавливается:

```bash
cd /srv/vetassistant
# файлы должны быть на сервере: git pull (если статьи в Git) или scp/rsync
docker compose -f docker-compose.edge.yml stop api
docker compose -f docker-compose.edge.yml run --rm --no-deps \
  --entrypoint python api scripts/ingest_knowledge.py
docker compose -f docker-compose.edge.yml up -d api
```

В логе будет видно, сколько чанков новых, сколько обновлено и сколько стало
всего:

```
Новых чанков: 37 | будет обновлено: 204 | к записи: 241
Записано чанков: 241/241
В коллекции msd_vet_manual теперь 241 чанков
```

Если в строке `Новых чанков` стоит 0, значит имена файлов совпали с уже
проиндексированными и чанки просто обновились.

**4. Проверить ответ.** Задайте в UI вопрос по новой статье с включённой
«Базой знаний (RAG)» и посмотрите логи API:

```bash
docker compose -f docker-compose.edge.yml logs api | grep -E "RAG|чанк"
```

Файл, скопированный только через `scp`, не попадёт в Git: если статья нужна
на всех окружениях, положите её в `data/knowledge/` локально и закоммитьте.

### Миграции админ-панели (T-120)

Схема админ-панели добавляет в `users` поля `is_admin` и
`must_change_password`, а в `access_requests` — `reviewed_at`, `reviewed_by`,
`approved_user_id`, `rejection_reason`. Применить миграцию к существующей БД:

```bash
docker compose -f docker-compose.edge.yml exec api \
  python scripts/migrate_admin_panel.py
```

Скрипт идемпотентен (`create_all` + `ALTER TABLE ... ADD COLUMN` только для
отсутствующих полей) и не удаляет данные. Выдать права администратора:

```bash
docker compose -f docker-compose.edge.yml exec db \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "UPDATE users SET is_admin = true WHERE email = 'admin@example.com';"
```

## 9. Проверка после запуска

```bash
docker compose -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1/healthz
curl -fsS http://vetassistant.ru/healthz
curl -fsS http://vetassistant.ru/api/health
```

`/api/health` проксируется в FastAPI `/health`. Затем откройте
`http://vetassistant.ru`, зарегистрируйте пользователя и проверьте чат,
записи и напоминания.

### Лендинг `ai-pets.ru` и web-root

Лендинг раздаётся контейнером `vetassistant-landing`, web-root — только
каталог `landing/` (HTML, `assets/`, `privacy/`, `terms/`, `robots.txt`,
`sitemap.xml`). Служебные файлы (`nginx.conf`, `compose.edge.fragment.yml`,
`Caddyfile.edge.snippet`, `DEPLOY.md`, `README.md`) вынесены в
`docs/landing/` и в web-root отсутствуют; `nginx.conf` монтируется из
`docs/landing/nginx.conf`. Caddy-матчер `@landing_private` удалён как
ненужный.

Проверка после деплоя лендинга:

```bash
curl -sI https://ai-pets.ru/ | head -n 1
for p in README.md DEPLOY.md nginx.conf compose.edge.fragment.yml Caddyfile.edge.snippet; do
  curl -s -o /dev/null -w "$p -> %{http_code}\n" "https://ai-pets.ru/$p"
done
```

Ожидаем `200` для корня и `404` для всех служебных путей. Подробный
чек-лист выкладки и отката — `docs/landing/DEPLOY.md`.

Проверить наличие модели и текущий размер контекста (удобно для
мониторинга памяти):

```bash
python scripts/check_ram.py --base-url https://vetassistant.ru
```

Скрипт печатает `model_path_exists`, `n_ctx`, `n_threads` и
`n_gpu_layers`. Если `n_ctx` слишком велик и серверу не хватает RAM,
снизьте `VET_API_N_CTX` до `2048` в `.env` и перезапустите стек.

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

### Метрики Prometheus (T-117)

API отдаёт метрики на `GET /metrics` (порт `8000`). Наружу эндпоинт не
публикуется: Caddy проксирует только `/api/*`, а сам API доступен лишь во
внутренних сетях Docker. Prometheus должен ходить на
`vetassistant-api:8000` по сети `edge`.

Проверка из контейнера:

```bash
docker compose -f docker-compose.edge.yml exec api python -c \
  "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').read().decode()[:800])"
```

Ожидаемо: HTTP `200`, `Content-Type: text/plain; version=0.0.4`, строки
`# HELP`/`# TYPE` и метрики из таблицы ниже.

| Метрика | Тип | Что показывает |
|---|---|---|
| `http_requests_total{handler,method,status}` | counter | Запросы к API по эндпоинту и коду ответа |
| `http_request_duration_seconds` | histogram | Латентность HTTP-запросов |
| `vet_llm_generation_requests_total{mode,status}` | counter | Вызовы модели: `chat`/`stream`, `success`/`empty`/`error` |
| `vet_llm_prompt_tokens_total` | counter | Токены промпта, обработанные моделью |
| `vet_llm_completion_tokens_total` | counter | Сгенерированные токены |
| `vet_llm_generation_seconds{mode}` | histogram | Полное время генерации |
| `vet_llm_time_to_first_token_seconds{mode}` | histogram | Время до первого токена SSE |
| `vet_llm_completion_tokens_per_second` | histogram | Скорость генерации, токенов/с |
| `vet_rag_searches_total{result}` | counter | RAG-поиски: `hit`/`miss`/`error` |
| `vet_rag_chunks_retrieved` | histogram | Сколько чанков вернул поиск |
| `vet_rag_search_seconds` | histogram | Длительность RAG-поиска |
| `vet_rag_index_ready` | gauge | `1` — индекс ChromaDB найден при старте, `0` — RAG нет |

`llama-cpp-python` не поддерживает флаг `--metrics` и не отдаёт тайминги
llama.cpp server, поэтому `vet_llm_*` считаются в API по `usage` и времени
вызова. В стриминговых ответах `usage` недоступен: для них точны латентность
и TTFT, а счётчики токенов растут только если провайдер прислал `usage` в
чанке. Нестриминговые запросы и agentic loop дают точные токены.

Пример scrape-конфига Prometheus (Prometheus подключён к сети `edge`):

```yaml
scrape_configs:
  - job_name: vetassistant-api
    metrics_path: /metrics
    scrape_interval: 15s
    static_configs:
      - targets: ["vetassistant-api:8000"]
```

Для Grafana полезны панели: RPS и p95 `http_request_duration_seconds`,
`rate(vet_llm_completion_tokens_total[5m])`, p95
`vet_llm_time_to_first_token_seconds`, доля `vet_rag_searches_total{result="hit"}`
и алерт на `vet_rag_index_ready == 0` после деплоя.

### Админская аналитика (T-135)

Вкладка «Аналитика» в админ-панели берёт данные из
`GET /v1/admin/metrics?window=24h|7d` (только администратор). Эндпоинт сам
ходит в Prometheus, поэтому Grafana для продукта не требуется.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `VET_API_PROMETHEUS_URL` | `http://prometheus:9090` | Базовый URL Prometheus в сети `edge`; пусто — только локальный снимок |
| `VET_API_PROMETHEUS_TIMEOUT_S` | `2` | Таймаут одного запроса к Prometheus |

Два режима работы:

- **`source: prometheus`** — суммы и графики за окно 24 часа / 7 дней,
  топ пользователей по запросам и токенам. Запросы (PromQL) формирует только
  API: клиент выбирает лишь окно, произвольный запрос выполнить нельзя.
- **`source: in_process`** — fallback на снимок `prometheus_client` в процессе
  API («с момента запуска API»). Включается, если URL пуст или Prometheus
  не ответил за таймаут; в ответе будет `degraded: true`, а в UI — жёлтый
  бейдж. Графики по времени в этом режиме недоступны, KPI и топ работают.

Проверка из контейнера:

```bash
docker compose -f docker-compose.edge.yml exec api python -c \
  "import urllib.request, json; r=json.load(urllib.request.urlopen('http://prometheus:9090/api/v1/query?query=up')); print(r['status'])"
```

Если видите `degraded` на проде — проверьте, что Prometheus подключён к сети
`edge` и его имя в DNS совпадает с `VET_API_PROMETHEUS_URL`. Метрика
`vet_llm_user_requests_total{user_id}` хранит только числовой id: email
подставляется из БД при выдаче ответа, в Prometheus персональные данные
не попадают.

## 10. HTTPS через Let's Encrypt / Certbot

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

## 11. Обновление приложения

```bash
cd /opt/vetassistant
sudo bash scripts/deploy.sh
```

Скрипт делает `git pull --ff-only`, пересобирает образы и перезапускает
контейнеры. Если сертификат уже выпущен, HTTPS-overlay подключается
автоматически. `.env` и `postgres_data` сохраняются.

Перед обновлением рекомендуется сделать бэкап БД.

## 12. Бэкап PostgreSQL

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
недействительны.

## 13. Диагностика

| Симптом | Что проверить |
|---|---|
| `502 Bad Gateway` | `docker compose ... logs api`; API healthy; модель в `data/gguf` |
| `503 Модель недоступна` | файл GGUF отсутствует или путь в `VET_API_MODEL_PATH` неверен |
| `port is already allocated` | на хосте уже занят `80`/`443` (nginx/apache); остановите его |
| Certbot: `unauthorized` | DNS ещё не обновился, закрыт `80`, неверный домен |
| Certbot: `connection refused` | frontend не запущен или ACME-каталог не смонтирован |
| Сайт открывается, API — нет | `docker compose ... logs frontend`; проверьте `/api/health` |
| После перезагрузки сервера ничего не работает | `systemctl status docker`; `docker compose ... up -d` |

Проверка ACME-каталога вручную:

```bash
curl -i http://vetassistant.ru/.well-known/acme-challenge/test
```

Ожидаемо `404` (файла нет), но не `301`/`502`. Если `301` — HTTPS-overlay
уже включён, и запрос уходит на HTTPS; для диагностики временно
используйте `curl -I` с `--resolve`.

## 14. Security checklist

- [ ] `.env` имеет права `600` и не попал в Git.
- [ ] `POSTGRES_PASSWORD` и `VET_API_JWT_SECRET` сгенерированы независимо
      через `openssl rand -hex 32`.
- [ ] `VET_API_ALLOW_PUBLIC_REGISTRATION=false` для production.
- [ ] Наружу открыты только `22`, `80`, `443`.
- [ ] API и PostgreSQL не опубликованы на хост.
- [ ] HTTPS работает, HTTP редиректит на HTTPS.
- [ ] Автопродление сертификата добавлено в cron и проверено `--dry-run`.
- [ ] Настроены бэкапы PostgreSQL и `.env`.
- [ ] Включены обновления безопасности Ubuntu (`unattended-upgrades`).
- [ ] Пароли и токены не публиковались в чатах и issue.
- [ ] Для SSH отключён вход по паролю, используется ключ.
