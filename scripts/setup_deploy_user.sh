#!/usr/bin/env bash
# =============================================================================
# T-108: подготовка пользователя deployer для CI/CD GitHub Actions.
#
# Что делает скрипт:
#   1. создаёт пользователя deployer (если его ещё нет);
#   2. добавляет его в группу docker;
#   3. создаёт ~/.ssh с правами 700 и authorized_keys с правами 600;
#   4. печатает инструкцию, как добавить публичный SSH-ключ GitHub Actions.
#
# Использование (от root):
#   sudo bash scripts/setup_deploy_user.sh
#   sudo DEPLOY_USER=deployer PROJECT_DIR=/srv/vetassistant \
#       bash scripts/setup_deploy_user.sh
#
# ВАЖНО: группа docker даёт доступ к Docker-сокету, то есть фактически
# root-эквивалентные права на хосте. Приватный ключ deployer храните только
# в GitHub Actions secrets.
# =============================================================================
set -Eeuo pipefail

DEPLOY_USER="${DEPLOY_USER:-deployer}"
PROJECT_DIR="${PROJECT_DIR:-/srv/vetassistant}"

log() {
    printf '[deploy-user] %s\n' "$*"
}

warn() {
    printf '[deploy-user] ВНИМАНИЕ: %s\n' "$*" >&2
}

die() {
    printf '[deploy-user] ОШИБКА: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Использование: sudo bash scripts/setup_deploy_user.sh

Переменные окружения:
  DEPLOY_USER  имя пользователя для деплоя (по умолчанию deployer)
  PROJECT_DIR  каталог репозитория (по умолчанию /srv/vetassistant)
EOF
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

if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
    log "Создаю пользователя ${DEPLOY_USER}..."
    useradd \
        --create-home \
        --shell /bin/bash \
        --comment "GitHub Actions deploy user" \
        "${DEPLOY_USER}"
else
    log "Пользователь ${DEPLOY_USER} уже существует."
fi

if ! getent group docker >/dev/null 2>&1; then
    die "группа docker не найдена. Сначала установите Docker Engine."
fi

log "Добавляю ${DEPLOY_USER} в группу docker..."
usermod -aG docker "${DEPLOY_USER}"

HOME_DIR="$(getent passwd "${DEPLOY_USER}" | cut -d: -f6)"
if [[ -z "${HOME_DIR}" || ! -d "${HOME_DIR}" ]]; then
    die "не удалось определить домашний каталог ${DEPLOY_USER}"
fi

SSH_DIR="${HOME_DIR}/.ssh"
AUTHORIZED_KEYS="${SSH_DIR}/authorized_keys"

log "Готовлю ${SSH_DIR} (700) и authorized_keys (600)..."
install -d -m 700 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "${SSH_DIR}"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${SSH_DIR}"
chmod 700 "${SSH_DIR}"

touch "${AUTHORIZED_KEYS}"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${AUTHORIZED_KEYS}"
chmod 600 "${AUTHORIZED_KEYS}"

if [[ -d "${PROJECT_DIR}" ]]; then
    if ! runuser -u "${DEPLOY_USER}" -- test -w "${PROJECT_DIR}"; then
        warn "у ${DEPLOY_USER} нет прав на запись в ${PROJECT_DIR}."
        warn "git pull не сработает. Выдайте права, если каталог принадлежит root:"
        warn "  sudo chown -R ${DEPLOY_USER}:${DEPLOY_USER} ${PROJECT_DIR}"
    fi
else
    warn "каталог ${PROJECT_DIR} не найден. Склонируйте репозиторий до первого деплоя."
fi

log "Проверка пользователя:"
id "${DEPLOY_USER}"

cat <<EOF

Пользователь ${DEPLOY_USER} создан и добавлен в группу docker.
SSH-каталог:      ${SSH_DIR} (700)
authorized_keys:  ${AUTHORIZED_KEYS} (600)

Дальнейшие шаги:

1. Сгенерируйте отдельную SSH-пару на машине, где настроен GitHub Actions:
   ssh-keygen -t ed25519 -C "github-actions-vetassistant" -f ~/.ssh/vetassistant_deploy -N ""

2. Добавьте публичный ключ пользователю ${DEPLOY_USER}:
   ssh-copy-id -i ~/.ssh/vetassistant_deploy.pub ${DEPLOY_USER}@<SERVER_IP>

   Если вход по паролю закрыт, выполните с root-доступа:
   sudo -u ${DEPLOY_USER} tee -a ${AUTHORIZED_KEYS} < vetassistant_deploy.pub

3. Проверьте вход и доступ к Docker (новую сессию SSH):
   ssh -i ~/.ssh/vetassistant_deploy ${DEPLOY_USER}@<SERVER_IP> 'docker ps'

4. Приватный ключ добавьте в GitHub Secrets как SSH_KEY, а также задайте
   SSH_HOST (IP или домен сервера) и SSH_USER=${DEPLOY_USER}.
   Подробности — раздел «Настройка CI/CD» в DEPLOYMENT.md.

EOF

log "Готово."
