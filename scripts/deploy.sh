#!/usr/bin/env bash
# =============================================================================
# T-040: production-развёртывание VetAssistant на Ubuntu/Debian VPS.
#
# Что делает скрипт:
#   1. устанавливает Docker Engine и Compose plugin (если их нет);
#   2. клонирует репозиторий (или обновляет существующий);
#   3. создаёт .env с автоматически сгенерированными секретами;
#   4. собирает и запускает docker-compose.prod.yml;
#   5. по флагу --ssl выпускает сертификат Let's Encrypt и включает HTTPS.
#
# Использование:
#   sudo bash scripts/deploy.sh
#   sudo bash scripts/deploy.sh --ssl
#   DOMAIN=vetassistant.ru LETSENCRYPT_EMAIL=admin@vetassistant.ru \
#     TELEGRAM_BOT_TOKEN=123:AA... sudo -E bash scripts/deploy.sh --ssl
#
# Переменные: REPO_URL, BRANCH, PROJECT_DIR, DOMAIN/VET_DOMAIN,
# LETSENCRYPT_EMAIL, TELEGRAM_BOT_TOKEN, GITHUB_TOKEN, ENABLE_SSL.
# =============================================================================
set -Eeuo pipefail

REPO_URL="${REPO_URL:-https://github.com/iilmchat/ai_VetAssistant.git}"
BRANCH="${BRANCH:-main}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENABLE_SSL="${ENABLE_SSL:-0}"

log() {
    printf '\n[deploy] %s\n' "$*"
}

warn() {
    printf '\n[deploy] ВНИМАНИЕ: %s\n' "$*" >&2
}

die() {
    printf '\n[deploy] ОШИБКА: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Использование: sudo bash scripts/deploy.sh [--ssl|--no-ssl]

  --ssl      после запуска выпустить сертификат Let's Encrypt и включить HTTPS
  --no-ssl   только HTTP (:80), без Certbot (по умолчанию)

Скрипт можно запускать из клонированного репозитория или отдельным файлом:
во втором случае он сам клонирует проект в /opt/vetassistant.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ssl) ENABLE_SSL=1 ;;
        --no-ssl) ENABLE_SSL=0 ;;
        -h|--help) usage; exit 0 ;;
        *) die "неизвестный аргумент: $1 (см. --help)" ;;
    esac
    shift
done

on_error() {
    local exit_code=$?
    printf '\n[deploy] Ошибка на строке %s (код %s).\n' \
        "${BASH_LINENO[0]:-?}" "$exit_code" >&2
    if [[ -n "${PROJECT_DIR:-}" && -f "${PROJECT_DIR}/docker-compose.prod.yml" ]]; then
        printf '[deploy] Последние логи контейнеров:\n' >&2
        (cd "$PROJECT_DIR" && "${DOCKER[@]}" compose -f docker-compose.prod.yml logs --tail=40) >&2 || true
    fi
    exit "$exit_code"
}

if [[ "${EUID}" -eq 0 ]]; then
    SUDO=()
    DEPLOY_USER="${SUDO_USER:-root}"
else
    command -v sudo >/dev/null 2>&1 || { printf '[deploy] ОШИБКА: нужен root или sudo\n' >&2; exit 1; }
    SUDO=(sudo)
    DEPLOY_USER="$(id -un)"
fi

DOCKER=("${SUDO[@]}" docker)
trap on_error ERR

run_as_user() {
    if [[ "${EUID}" -eq 0 && "${DEPLOY_USER}" != "root" ]]; then
        sudo -u "$DEPLOY_USER" -- "$@"
    else
        "$@"
    fi
}

# --- 1. Проверка ОС и системные пакеты -------------------------------------
log "1/7. Проверка ОС и системных пакетов"
# shellcheck disable=SC1091
. /etc/os-release
DOCKER_DISTRO="${ID:-}"
case "$DOCKER_DISTRO" in
    ubuntu|debian) ;;
    *) die "поддерживаются Ubuntu/Debian, обнаружено: ${PRETTY_NAME:-unknown}" ;;
esac
[[ -n "${VERSION_CODENAME:-}" ]] || die "не удалось определить VERSION_CODENAME"

export DEBIAN_FRONTEND=noninteractive
"${SUDO[@]}" apt-get update
"${SUDO[@]}" apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg git openssl

# --- 2. Docker Engine + Compose plugin --------------------------------------
log "2/7. Установка Docker Engine и Compose plugin"
if command -v docker >/dev/null 2>&1 && "${DOCKER[@]}" compose version >/dev/null 2>&1; then
    log "Docker и Compose уже установлены: $(docker --version)"
else
    "${SUDO[@]}" install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/${DOCKER_DISTRO}/gpg" \
        | "${SUDO[@]}" tee /etc/apt/keyrings/docker.asc >/dev/null
    "${SUDO[@]}" chmod a+r /etc/apt/keyrings/docker.asc
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
        "$(dpkg --print-architecture)" "$DOCKER_DISTRO" "$VERSION_CODENAME" \
        | "${SUDO[@]}" tee /etc/apt/sources.list.d/docker.list >/dev/null

    "${SUDO[@]}" apt-get update
    "${SUDO[@]}" apt-get install -y --no-install-recommends \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    "${SUDO[@]}" systemctl enable --now docker
fi

if [[ "${DEPLOY_USER}" != "root" ]]; then
    "${SUDO[@]}" usermod -aG docker "$DEPLOY_USER" || true
fi
"${DOCKER[@]}" compose version >/dev/null 2>&1 \
    || die "Docker Compose plugin недоступен"

# --- 3. Каталог проекта и репозиторий ---------------------------------------
log "3/7. Получение репозитория"
if [[ -f "${SCRIPT_DIR}/../docker-compose.prod.yml" ]]; then
    PROJECT_DIR="${PROJECT_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
    log "Использую существующий репозиторий: $PROJECT_DIR"
else
    PROJECT_DIR="${PROJECT_DIR:-/opt/vetassistant}"
    if [[ ! -d "$PROJECT_DIR" ]]; then
        "${SUDO[@]}" mkdir -p "$PROJECT_DIR"
        "${SUDO[@]}" chown "${DEPLOY_USER}:${DEPLOY_USER}" "$PROJECT_DIR"
    fi

    if [[ -d "$PROJECT_DIR/.git" ]]; then
        log "Обновляю существующий репозиторий: $PROJECT_DIR"
        run_as_user git -C "$PROJECT_DIR" fetch --prune origin
        run_as_user git -C "$PROJECT_DIR" checkout "$BRANCH"
        run_as_user git -C "$PROJECT_DIR" pull --ff-only origin "$BRANCH"
    elif [[ -n "$(ls -A "$PROJECT_DIR" 2>/dev/null)" ]]; then
        die "каталог $PROJECT_DIR не пуст и не является git-репозиторием"
    else
        if [[ -n "${GITHUB_TOKEN:-}" ]]; then
            CLONE_URL="https://${GITHUB_TOKEN}@github.com/iilmchat/ai_VetAssistant.git"
        else
            CLONE_URL="$REPO_URL"
        fi
        run_as_user git clone --branch "$BRANCH" "$CLONE_URL" "$PROJECT_DIR"
        if [[ -n "${GITHUB_TOKEN:-}" ]]; then
            run_as_user git -C "$PROJECT_DIR" remote set-url origin "$REPO_URL"
        fi
    fi
fi

cd "$PROJECT_DIR"
[[ -f docker-compose.prod.yml ]] || die "в $PROJECT_DIR нет docker-compose.prod.yml"
[[ -f .env.production.example ]] || die "в $PROJECT_DIR нет .env.production.example"

# --- 4. .env и секреты ------------------------------------------------------
log "4/7. Настройка .env"
read_env() {
    local key="$1"
    [[ -f .env ]] || return 0
    grep -E "^${key}=" .env | tail -n 1 | cut -d= -f2- || true
}

set_env() {
    local key="$1" value="$2" tmp
    tmp="$(mktemp)"
    awk -v key="$key" -v value="$value" '
        BEGIN { done = 0 }
        $0 ~ "^" key "=" { print key "=" value; done = 1; next }
        { print }
        END { if (!done) print key "=" value }
    ' .env > "$tmp"
    mv "$tmp" .env
}

if [[ ! -f .env ]]; then
    log "Создаю .env из .env.production.example"
    cp .env.production.example .env

    BOT_ENABLED=0
    if grep -qE '^  bot:' docker-compose.prod.yml; then
        BOT_ENABLED=1
    fi

    if [[ -z "${DOMAIN:-}" ]]; then
        DOMAIN="${VET_DOMAIN:-}"
    fi
    if [[ -z "${DOMAIN}" && -t 0 ]]; then
        read -r -p "Домен (например, vetassistant.ru): " DOMAIN
    fi
    DOMAIN="${DOMAIN#http://}"
    DOMAIN="${DOMAIN#https://}"
    DOMAIN="${DOMAIN%/}"
    if [[ -z "${LETSENCRYPT_EMAIL:-}" && -t 0 ]]; then
        read -r -p "Email для Let's Encrypt: " LETSENCRYPT_EMAIL
    fi
    if [[ "$BOT_ENABLED" -eq 1 && -z "${TELEGRAM_BOT_TOKEN:-}" && -t 0 ]]; then
        read -r -s -p "Telegram bot token от @BotFather: " TELEGRAM_BOT_TOKEN
        printf '\n'
    fi

    [[ -n "${DOMAIN:-}" ]] || die "задайте DOMAIN (или VET_DOMAIN) для production"
    [[ -n "${LETSENCRYPT_EMAIL:-}" ]] || warn "LETSENCRYPT_EMAIL не задан — SSL можно настроить позже"
    if [[ "$BOT_ENABLED" -eq 1 && -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
        die "задайте TELEGRAM_BOT_TOKEN или удалите сервис bot из docker-compose.prod.yml"
    fi

    set_env "POSTGRES_PASSWORD" "$(openssl rand -hex 32)"
    set_env "VET_API_JWT_SECRET" "$(openssl rand -hex 32)"
    set_env "VET_BOT_AUTH_SECRET" "$(openssl rand -hex 32)"
    set_env "VET_DOMAIN" "$DOMAIN"
    set_env "LETSENCRYPT_EMAIL" "${LETSENCRYPT_EMAIL:-}"
    if [[ "$BOT_ENABLED" -eq 1 ]]; then
        set_env "TELEGRAM_BOT_TOKEN" "$TELEGRAM_BOT_TOKEN"
    fi
    log "Секреты сгенерированы. Файл .env не попадёт в Git."
else
    log ".env уже существует — секреты не перезаписываю"
fi

chmod 600 .env 2>/dev/null || "${SUDO[@]}" chmod 600 .env

BOT_ENABLED=0
if grep -qE '^  bot:' docker-compose.prod.yml; then
    BOT_ENABLED=1
fi
REQUIRED_ENV=(POSTGRES_PASSWORD VET_API_JWT_SECRET)
if [[ "$BOT_ENABLED" -eq 1 ]]; then
    REQUIRED_ENV+=(VET_BOT_AUTH_SECRET TELEGRAM_BOT_TOKEN)
fi
for key in "${REQUIRED_ENV[@]}"; do
    [[ -n "$(read_env "$key")" ]] || die "в .env не заполнено: $key"
done

DOMAIN="${DOMAIN:-$(read_env VET_DOMAIN)}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-$(read_env LETSENCRYPT_EMAIL)}"
DOMAIN="${DOMAIN#http://}"
DOMAIN="${DOMAIN#https://}"
DOMAIN="${DOMAIN%/}"
if [[ "$ENABLE_SSL" -eq 1 ]]; then
    [[ -n "$DOMAIN" && "$DOMAIN" != "vetassistant.example.com" ]] \
        || die "для --ssl задайте реальный VET_DOMAIN в .env или DOMAIN в окружении"
    [[ -n "$LETSENCRYPT_EMAIL" && "$LETSENCRYPT_EMAIL" != "admin@example.com" ]] \
        || die "для --ssl задайте реальный LETSENCRYPT_EMAIL"
fi

# Каталоги для данных, модели и ACME.
mkdir -p data/gguf data/chroma_db deploy/certbot/www deploy/certbot/conf 2>/dev/null \
    || "${SUDO[@]}" mkdir -p data/gguf data/chroma_db deploy/certbot/www deploy/certbot/conf

MODEL_PATH="$(read_env VET_API_MODEL_PATH)"
MODEL_PATH="${MODEL_PATH:-/app/data/gguf/qwen3-8b-vet-Q4_K_M.gguf}"
case "$MODEL_PATH" in
    /app/*)
        HOST_MODEL_PATH="${MODEL_PATH#/app/}"
        if [[ ! -f "$HOST_MODEL_PATH" ]]; then
            warn "модель не найдена: $HOST_MODEL_PATH. API запустится, но будет отвечать 503. Загрузите GGUF в data/gguf/."
        fi
        ;;
    *)
        warn "VET_API_MODEL_PATH=$MODEL_PATH не в /app/data; проверьте, что файл доступен внутри контейнера."
        ;;
esac

# --- 5. Запуск HTTP/HTTPS ---------------------------------------------------
log "5/7. Сборка и запуск production-стека"
COMPOSE_BASE=(-f docker-compose.prod.yml)
COMPOSE_SSL=(-f docker-compose.prod.yml -f docker-compose.ssl.yml)
CERT_FILE="deploy/certbot/conf/live/vetassistant/fullchain.pem"
SSL_ACTIVE=0
if [[ -f "$CERT_FILE" ]]; then
    SSL_ACTIVE=1
    log "Найден сертификат — включаю HTTPS overlay"
fi

COMPOSE_FILES=("${COMPOSE_BASE[@]}")
if [[ "$SSL_ACTIVE" -eq 1 ]]; then
    COMPOSE_FILES=("${COMPOSE_SSL[@]}")
fi

compose() {
    "${DOCKER[@]}" compose "${COMPOSE_FILES[@]}" "$@"
}

compose up -d --build

log "Ожидаю готовности frontend..."
READY=0
for _ in $(seq 1 45); do
    if curl -fsS --max-time 3 http://127.0.0.1/healthz >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 2
done
if [[ "$READY" -ne 1 ]]; then
    compose ps || true
    compose logs --tail=80 || true
    die "frontend не ответил на http://127.0.0.1/healthz"
fi

# --- 6. HTTPS (опционально) -------------------------------------------------
if [[ "$ENABLE_SSL" -eq 1 ]]; then
    log "6/7. Выпуск сертификата Let's Encrypt"
    [[ -n "$DOMAIN" ]] || die "для --ssl задайте DOMAIN"
    [[ -n "$LETSENCRYPT_EMAIL" ]] || die "для --ssl задайте LETSENCRYPT_EMAIL"

    if [[ ! -f "$CERT_FILE" ]]; then
        "${DOCKER[@]}" compose "${COMPOSE_SSL[@]}" --profile tools run --rm certbot \
            certonly --webroot -w /var/www/certbot \
            -d "$DOMAIN" --cert-name vetassistant \
            --email "$LETSENCRYPT_EMAIL" --agree-tos --no-eff-email --non-interactive
    else
        log "Сертификат уже существует: $CERT_FILE"
    fi

    COMPOSE_FILES=("${COMPOSE_SSL[@]}")
    SSL_ACTIVE=1
    compose up -d
    if ! curl -fsS --max-time 10 --resolve "${DOMAIN}:443:127.0.0.1" \
        "https://${DOMAIN}/healthz" >/dev/null 2>&1; then
        warn "HTTPS-проверка не прошла. Проверьте DNS, порт 443 и логи frontend."
    fi
else
    log "6/7. HTTPS не включён (запустите с --ssl или см. DEPLOYMENT.md)"
    if [[ "$SSL_ACTIVE" -eq 1 ]]; then
        log "HTTPS уже настроен ранее — overlay сохранён"
    fi
fi

# --- 7. Итог ----------------------------------------------------------------
log "7/7. Готово"
compose ps || true
printf '\nПроверьте:\n'
printf '  http://%s/healthz\n' "${DOMAIN:-<домен>}"
if [[ "$SSL_ACTIVE" -eq 1 ]]; then
    printf '  https://%s\n' "$DOMAIN"
else
    printf '  HTTPS: sudo bash scripts/deploy.sh --ssl\n'
fi
printf '\nПолезные команды (из %s):\n' "$PROJECT_DIR"
printf '  sudo docker compose -f docker-compose.prod.yml ps\n'
printf '  sudo docker compose -f docker-compose.prod.yml logs -f api frontend\n'
printf '  sudo docker compose -f docker-compose.prod.yml up -d --build\n'
