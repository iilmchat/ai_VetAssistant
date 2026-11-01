#!/usr/bin/env bash
# =============================================================================
# T-016: автоматическое развертывание VetAssistant на GPU-сервере Selectel.
#
# Скрипт рассчитан на Ubuntu 24.04 / образ «Unsloth VM» с CUDA и PyTorch.
# Запуск (из любого каталога):
#   bash setup_remote.sh
#   GITHUB_TOKEN=github_pat_... bash setup_remote.sh
#   REPO_URL=https://github.com/iilmchat/ai_VetAssistant.git bash setup_remote.sh
#
# Для приватного GitHub-репозитория задайте GITHUB_TOKEN (Personal Access
# Token с правом чтения репозитория). Токен не печатается в логах; после
# клонирования origin сбрасывается на URL без токена.
#
# S3-ключи Selectel передаются через переменные окружения S3_ACCESS_KEY_ID и
# S3_SECRET_ACCESS_KEY. Если они не заданы, скрипт запросит их интерактивно.
# Ключи сохраняются только в .dvc/config.local (chmod 600), который
# игнорируется Git. В командной строке и логах ключи не печатаются.
# =============================================================================
set -euo pipefail

DEFAULT_REPO_URL="https://github.com/iilmchat/ai_VetAssistant.git"
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    CLONE_URL="https://${GITHUB_TOKEN}@github.com/iilmchat/ai_VetAssistant.git"
else
    CLONE_URL="${REPO_URL:-$DEFAULT_REPO_URL}"
fi
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PROJECT_DIR="$HOME/ai_VetAssistant"
# Если скрипт запущен из уже склонированного репозитория, не клонируем второй раз.
if [[ -d "$SCRIPT_DIR/../.git" && -f "$SCRIPT_DIR/../pyproject.toml" ]]; then
    DEFAULT_PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
fi
PROJECT_DIR="${PROJECT_DIR:-$DEFAULT_PROJECT_DIR}"
DVC_REMOTE_NAME="selectel"
DVC_REMOTE_URL="${DVC_REMOTE_URL:-s3://vetassistant-data/dvc}"
DVC_ENDPOINT_URL="${DVC_ENDPOINT_URL:-https://s3.ru-7.storage.selcloud.ru}"
DVC_REGION="${DVC_REGION:-ru-7}"

log() {
    printf '\n[setup_remote] %s\n' "$*"
}

die() {
    printf '\n[setup_remote] ОШИБКА: %s\n' "$*" >&2
    exit 1
}

on_error() {
    local exit_code=$?
    printf '\n[setup_remote] Ошибка на строке %s (код %s). Развертывание остановлено.\n' \
        "${BASH_LINENO[0]:-?}" "$exit_code" >&2
    exit "$exit_code"
}
trap on_error ERR

if [[ "${EUID}" -eq 0 ]]; then
    SUDO=()
else
    command -v sudo >/dev/null 2>&1 || die "нужен root или sudo"
    SUDO=(sudo)
fi

log "1/8. Установка системных пакетов"
export DEBIAN_FRONTEND=noninteractive
"${SUDO[@]}" apt-get update
"${SUDO[@]}" apt-get install -y --no-install-recommends \
    git python3-pip python3-venv ca-certificates curl make

log "2/8. Получение репозитория"
if [[ -d "$PROJECT_DIR" ]]; then
    # Сценарий scp/rsync: каталог уже доставлен на сервер, клонирование не нужно.
    log "Папка уже существует: $PROJECT_DIR; пропускаю git clone"
elif [[ -e "$PROJECT_DIR" ]]; then
    die "путь $PROJECT_DIR существует, но это не каталог"
else
    log "Клонирую репозиторий в $PROJECT_DIR"
    if ! GIT_TERMINAL_PROMPT=0 git clone "$CLONE_URL" "$PROJECT_DIR"; then
        die "не удалось клонировать репозиторий; проверьте GITHUB_TOKEN и доступ к $DEFAULT_REPO_URL"
    fi
    # Не оставляем токен в .git/config на сервере.
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        git -C "$PROJECT_DIR" remote set-url origin "$DEFAULT_REPO_URL"
    fi
fi

cd "$PROJECT_DIR"
[[ -f pyproject.toml ]] || die "в $PROJECT_DIR нет pyproject.toml — это не проект VetAssistant"
[[ -f requirements-train.txt ]] || die "не найден requirements-train.txt"

log "3/8. Создание виртуального окружения"
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
else
    log "Виртуальное окружение уже существует: $PROJECT_DIR/.venv"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

log "4/8. Установка зависимостей обучения"
pip install -r requirements-train.txt

log "5/8. Установка DVC с поддержкой S3"
pip install "dvc[s3]"

log "6/8. Настройка DVC-remote ${DVC_REMOTE_NAME}"
if dvc remote list | grep -qE "^${DVC_REMOTE_NAME}[[:space:]]"; then
    dvc remote modify "$DVC_REMOTE_NAME" url "$DVC_REMOTE_URL"
else
    dvc remote add -d "$DVC_REMOTE_NAME" "$DVC_REMOTE_URL"
fi
dvc remote modify "$DVC_REMOTE_NAME" endpointurl "$DVC_ENDPOINT_URL"
dvc remote modify "$DVC_REMOTE_NAME" region "$DVC_REGION"
dvc remote default "$DVC_REMOTE_NAME"

log "7/8. Настройка S3-ключей (локально, без попадания в Git)"
if [[ -f .dvc/config.local ]] \
    && grep -q "access_key_id" .dvc/config.local \
    && grep -q "secret_access_key" .dvc/config.local; then
    log "Найден .dvc/config.local — использую сохраненные ключи"
else
    ACCESS_KEY="${S3_ACCESS_KEY_ID:-${AWS_ACCESS_KEY_ID:-}}"
    SECRET_KEY="${S3_SECRET_ACCESS_KEY:-${AWS_SECRET_ACCESS_KEY:-}}"
    if [[ -z "$ACCESS_KEY" || -z "$SECRET_KEY" ]]; then
        if [[ ! -t 0 ]]; then
            die "задайте S3_ACCESS_KEY_ID и S3_SECRET_ACCESS_KEY (или создайте .dvc/config.local)"
        fi
        read -r -p "S3 access_key_id: " ACCESS_KEY
        read -r -s -p "S3 secret_access_key: " SECRET_KEY
        printf '\n'
    fi
    [[ -n "$ACCESS_KEY" && -n "$SECRET_KEY" ]] || die "S3-ключи пустые"
    dvc remote modify --local "$DVC_REMOTE_NAME" access_key_id "$ACCESS_KEY"
    dvc remote modify --local "$DVC_REMOTE_NAME" secret_access_key "$SECRET_KEY"
    chmod 600 .dvc/config.local
fi

log "8/8. Загрузка данных из S3 (dvc pull)"
dvc pull

log "Проверка окружения"
python - <<'PY'
import torch

print(f"Python: {__import__('sys').version.split()[0]}")
print(f"PyTorch: {torch.__version__}")
print(f"CUDA доступна: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
PY

log "Готово."
printf 'Активируйте окружение в новой SSH-сессии:\n  source %s/.venv/bin/activate\n' "$PROJECT_DIR"
printf 'Каталог проекта: %s\n' "$PROJECT_DIR"
