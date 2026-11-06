#!/usr/bin/env bash
# =============================================================================
# T-132: безопасный ручной перезапуск production-стека.
#
# Зачем скрипт: образы тегируются версией из git-тега (VETASSISTANT_VERSION,
# T-131). Если запустить `docker compose up -d` руками, а переменная не
# задана, compose возьмёт тег `latest` — на проде может оказаться не тот
# образ. Скрипт сам вычисляет текущую версию, фиксирует её в `.env` и
# поднимает стек без сборки.
#
# Использование:
#   ./scripts/restart_prod.sh                  # версия из git-тега
#   ./scripts/restart_prod.sh 1.5.5            # явная версия
#   COMPOSE_FILE=docker-compose.prod.yml ./scripts/restart_prod.sh
#
# Перезапуск не собирает образы: сборка остаётся за `deploy.yml` и тегом.
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.edge.yml}"
ENV_FILE="${ENV_FILE:-.env}"

version="${1:-}"
if [[ -z "${version}" ]]; then
    if tag="$(git describe --tags --exact-match 2>/dev/null)"; then
        version="${tag#v}"
    else
        tag="$(git describe --tags --abbrev=0 2>/dev/null || true)"
        if [[ -z "${tag}" ]]; then
            echo "[restart_prod] Не удалось определить версию: в репозитории нет git-тега." >&2
            echo "[restart_prod] Укажите версию явно: $0 1.5.5" >&2
            exit 1
        fi
        version="${tag#v}"
        echo "[restart_prod] HEAD не указывает на тег, беру ближайший: ${version}" >&2
    fi
fi

if [[ ! "${version}" =~ ^[0-9A-Za-z._-]+$ ]]; then
    echo "[restart_prod] Некорректная версия: '${version}'" >&2
    exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
    echo "[restart_prod] Не найден compose-файл: ${COMPOSE_FILE}" >&2
    exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "[restart_prod] Не найден ${ENV_FILE}: скопируйте .env.production.example" >&2
    exit 1
fi

# Идемпотентно фиксируем версию в .env: ручной compose и ребут увидят её же.
if grep -q '^VETASSISTANT_VERSION=' "${ENV_FILE}"; then
    sed -i "s|^VETASSISTANT_VERSION=.*|VETASSISTANT_VERSION=${version}|" "${ENV_FILE}"
else
    printf 'VETASSISTANT_VERSION=%s\n' "${version}" >> "${ENV_FILE}"
fi
export VETASSISTANT_VERSION="${version}"

echo "[restart_prod] $(date -Is) версия ${version}, compose ${COMPOSE_FILE}"
# T-145: --remove-orphans удаляет контейнеры прошлых релизов, которые держат
# имя (например, 60577ee94155_vetassistant-api) и мешают пересозданию.
docker compose -f "${COMPOSE_FILE}" up -d --no-build --remove-orphans

echo "[restart_prod] Контейнеры:"
docker compose -f "${COMPOSE_FILE}" ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}'
echo "[restart_prod] Готово."
