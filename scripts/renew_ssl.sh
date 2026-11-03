#!/usr/bin/env bash
# =============================================================================
# T-040: продление Let's Encrypt-сертификата и перезагрузка Nginx.
#
# Рекомендуемый cron (от root):
#   0 3 * * * /opt/vetassistant/scripts/renew_ssl.sh >> /var/log/vetassistant-ssl.log 2>&1
#
# Certbot сам пропускает продление, если до истечения больше 30 дней.
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

if [[ "${EUID}" -eq 0 ]]; then
    DOCKER=(docker)
else
    command -v sudo >/dev/null 2>&1 || { echo "Нужен root или sudo" >&2; exit 1; }
    DOCKER=(sudo docker)
fi
COMPOSE=(-f docker-compose.prod.yml -f docker-compose.ssl.yml)

if [[ ! -f deploy/certbot/conf/live/vetassistant/fullchain.pem ]]; then
    echo "Сертификат deploy/certbot/conf/live/vetassistant/fullchain.pem не найден." >&2
    exit 1
fi

echo "[renew_ssl] $(date -Is) Проверяю сертификат..."
"${DOCKER[@]}" compose "${COMPOSE[@]}" --profile tools run --rm certbot \
    renew --webroot -w /var/www/certbot --quiet

echo "[renew_ssl] Перезагружаю Nginx..."
"${DOCKER[@]}" compose "${COMPOSE[@]}" exec -T frontend nginx -s reload

echo "[renew_ssl] Готово."
