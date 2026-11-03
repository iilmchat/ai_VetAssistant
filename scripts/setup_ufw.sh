#!/usr/bin/env bash
# =============================================================================
# T-104: базовая настройка UFW (Uncomplicated Firewall) на Ubuntu.
#
# Что делает скрипт:
#   1. устанавливает ufw, если его нет в системе;
#   2. разрешает SSH (22/tcp; порт можно переопределить через SSH_PORT);
#   3. разрешает HTTP (80/tcp) и HTTPS (443/tcp);
#   4. запрещает входящие соединения по умолчанию, разрешает исходящие;
#   5. включает firewall и печатает итоговые правила.
#
# Использование:
#   sudo bash scripts/setup_ufw.sh
#   sudo SSH_PORT=2222 bash scripts/setup_ufw.sh
#
# ВАЖНО:
#   * запускайте скрипт только по SSH, убедившись, что порт SSH доступен;
#   * Docker публикует порты в обход UFW — не публикуйте api/db наружу;
#   * firewall провайдера (security group) настраивается отдельно.
# =============================================================================
set -Eeuo pipefail

SSH_PORT="${SSH_PORT:-22}"
HTTP_PORT="${HTTP_PORT:-80}"
HTTPS_PORT="${HTTPS_PORT:-443}"

log() {
    printf '[ufw] %s\n' "$*"
}

warn() {
    printf '[ufw] ВНИМАНИЕ: %s\n' "$*" >&2
}

die() {
    printf '[ufw] ОШИБКА: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Использование: sudo bash scripts/setup_ufw.sh

Переменные окружения:
  SSH_PORT    порт SSH (по умолчанию 22; порт 22 разрешается всегда)
  HTTP_PORT   порт HTTP (по умолчанию 80)
  HTTPS_PORT  порт HTTPS (по умолчанию 443)
EOF
}

validate_port() {
    local name="$1"
    local value="$2"
    [[ "${value}" =~ ^[0-9]+$ ]] || die "${name} должен быть числом: ${value}"
    (( 10#${value} >= 1 && 10#${value} <= 65535 )) \
        || die "${name} вне диапазона 1..65535: ${value}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        *) die "неизвестный аргумент: $1 (см. --help)" ;;
    esac
done

if [[ "${EUID}" -ne 0 ]]; then
    die "нужны права root, запустите: sudo bash $0"
fi

validate_port SSH_PORT "${SSH_PORT}"
validate_port HTTP_PORT "${HTTP_PORT}"
validate_port HTTPS_PORT "${HTTPS_PORT}"

if ! command -v ufw >/dev/null 2>&1; then
    log "UFW не установлен — устанавливаю..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y ufw
fi

log "Проверьте, что SSH слушает порт ${SSH_PORT}: ss -ltnp | grep ':${SSH_PORT}'"
log "Разрешаю SSH (${SSH_PORT}/tcp)..."
ufw allow "${SSH_PORT}/tcp" comment 'SSH'
if [[ "${SSH_PORT}" != "22" ]]; then
    # Страховка от блокировки: стандартный порт тоже остаётся открытым.
    ufw allow 22/tcp comment 'SSH (default)'
fi

log "Разрешаю HTTP (${HTTP_PORT}/tcp) и HTTPS (${HTTPS_PORT}/tcp)..."
ufw allow "${HTTP_PORT}/tcp" comment 'HTTP'
ufw allow "${HTTPS_PORT}/tcp" comment 'HTTPS'

log "Запрещаю входящие по умолчанию, разрешаю исходящие..."
ufw default deny incoming
ufw default allow outgoing

log "Включаю UFW..."
ufw --force enable

log "Итоговые правила:"
ufw status verbose

warn "Docker публикует порты в обход UFW. Убедитесь, что 8000/5432/8501 не опубликованы на хост."
log "Готово."
