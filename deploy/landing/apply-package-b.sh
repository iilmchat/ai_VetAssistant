#!/usr/bin/env bash
# Package B: ai-pets.ru -> landing, app.ai-pets.ru -> React SPA + FastAPI.
#
# Run as root on 62.109.1.230 AFTER the DNS A-record for app.ai-pets.ru is live.
# The script does NOT edit tracked docker-compose.edge.yml: CI does
# `git pull --ff-only` there, and a manual edit would make the tree dirty.
# Instead it creates a separate Compose project `vetassistant-landing`.
#
# Usage:
#   bash /srv/vetassistant/deploy/landing/apply-package-b.sh
#
# Optional:
#   SKIP_DNS_CHECK=1 bash ...   # only if DNS is known to be ready
#
# Rollback after success:
#   cp /root/backups/package-b-<stamp>/Caddyfile /srv/ai-infra/Caddyfile
#   docker exec edge-caddy caddy reload --config /etc/caddy/Caddyfile

set -Eeuo pipefail

VET_DIR="${VET_DIR:-/srv/vetassistant}"
INFRA_DIR="${INFRA_DIR:-/srv/ai-infra}"
CADDY_CONTAINER="${CADDY_CONTAINER:-edge-caddy}"
ROOT_DOMAIN="${ROOT_DOMAIN:-ai-pets.ru}"
APP_DOMAIN="${APP_DOMAIN:-app.ai-pets.ru}"
SERVER_IP="${SERVER_IP:-62.109.1.230}"
SKIP_DNS_CHECK="${SKIP_DNS_CHECK:-0}"

COMPOSE_LANDING="$VET_DIR/docker-compose.landing.yml"
CADDYFILE="$INFRA_DIR/Caddyfile"
LANDING_DIR="$VET_DIR/landing"
NGINX_CONF="$LANDING_DIR/nginx.conf"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${BACKUP_DIR:-/root/backups/package-b-$STAMP}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

log() { printf '\n==> %s\n' "$*"; }
warn() { printf '\nWARN: %s\n' "$*" >&2; }
fail() {
    printf '\nERROR: %s\n' "$*" >&2
    printf 'Backups: %s\n' "$BACKUP_DIR" >&2
    exit 1
}

[[ "$(id -u)" -eq 0 ]] || fail "run as root"
command -v docker >/dev/null || fail "docker not found"
command -v python3 >/dev/null || fail "python3 not found"
command -v curl >/dev/null || fail "curl not found"
command -v getent >/dev/null || fail "getent not found"

for path in "$CADDYFILE" "$LANDING_DIR/index.html" "$NGINX_CONF"; do
    [[ -f "$path" ]] || fail "not found: $path"
done
docker inspect "$CADDY_CONTAINER" >/dev/null 2>&1 || fail "container not found: $CADDY_CONTAINER"

log "DNS check: $APP_DOMAIN -> $SERVER_IP"
if [[ "$SKIP_DNS_CHECK" == "1" ]]; then
    warn "SKIP_DNS_CHECK=1: DNS check skipped"
else
    resolved=""
    for _ in $(seq 1 30); do
        if getent ahostsv4 "$APP_DOMAIN" | awk '{print $1}' | grep -qx "$SERVER_IP"; then
            resolved="$SERVER_IP"
            break
        fi
        sleep 10
    done
    [[ -n "$resolved" ]] || fail "DNS $APP_DOMAIN does not point to $SERVER_IP yet. Add the A-record and rerun."
    echo "OK: $APP_DOMAIN -> $resolved"
fi

mkdir -p "$BACKUP_DIR"
cp -a "$CADDYFILE" "$BACKUP_DIR/Caddyfile"
if [[ -f "$COMPOSE_LANDING" ]]; then
    cp -a "$COMPOSE_LANDING" "$BACKUP_DIR/docker-compose.landing.yml"
fi
log "Backups: $BACKUP_DIR"

# ---------------------------------------------------------------------------
# 1. Landing container (separate Compose project, no edits to tracked files)
# ---------------------------------------------------------------------------
log "1/6 write and validate landing compose"

cat > "$COMPOSE_LANDING" <<EOF
name: vetassistant-landing

x-logging: &default-logging
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"

services:
  landing:
    image: nginx:stable-alpine
    container_name: vetassistant-landing
    restart: unless-stopped
    logging: *default-logging
    expose:
      - "80"
    volumes:
      - ${LANDING_DIR}:/usr/share/nginx/html:ro
      - ${NGINX_CONF}:/etc/nginx/conf.d/default.conf:ro
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://127.0.0.1/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 5s
    networks:
      - edge

networks:
  edge:
    external: true
    name: edge
EOF

cd "$VET_DIR"
docker compose -f "$COMPOSE_LANDING" config >/dev/null
echo "compose config OK"

log "2/6 start landing"
docker compose -f "$COMPOSE_LANDING" up -d

health=""
for _ in $(seq 1 30); do
    health="$(docker inspect --format '{{.State.Health.Status}}' vetassistant-landing 2>/dev/null || true)"
    [[ "$health" == "healthy" ]] && break
    sleep 2
done
if [[ "$health" != "healthy" ]]; then
    docker logs --tail 80 vetassistant-landing || true
    fail "landing is not healthy (status: ${health:-unknown})"
fi
docker exec vetassistant-landing wget -qO- http://127.0.0.1/healthz >/dev/null
echo "landing is healthy"

# ---------------------------------------------------------------------------
# 2. Caddy configs: first app-only (root stays on frontend), then full switch
# ---------------------------------------------------------------------------
log "3/6 prepare Caddy snippets"

cat > "$WORK_DIR/Caddyfile.edge.snippet" <<'CADDY'
ai-pets.ru {
	encode zstd gzip
	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options "nosniff"
		X-Frame-Options "SAMEORIGIN"
		Referrer-Policy "strict-origin-when-cross-origin"
		Permissions-Policy "geolocation=(), microphone=(), camera=()"
	}
	# Infra files live in the landing web-root; never serve them.
	@landing_private path /README.md /DEPLOY.md /nginx.conf /compose.edge.fragment.yml /Caddyfile.edge.snippet
	respond @landing_private 404
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
CADDY

python3 - "$CADDYFILE" "$WORK_DIR/Caddyfile.edge.snippet" "$WORK_DIR/Caddyfile.app-only" "$WORK_DIR/Caddyfile.full" <<'PY'
import sys
from pathlib import Path


def block(text: str, label: str) -> str | None:
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if line.strip() == f"{label} {{":
            start = i
            break
    if start is None:
        return None

    depth = 0
    for j in range(start, len(lines)):
        depth += lines[j].count("{") - lines[j].count("}")
        if j > start and depth == 0:
            return "".join(lines[start:j + 1])
    raise SystemExit(f"unbalanced Caddy block: {label}")


def remove(text: str, label: str) -> str:
    found = block(text, label)
    if found is None:
        return text
    return text.replace(found, "", 1)


caddy_path = Path(sys.argv[1])
snippet_path = Path(sys.argv[2])
app_only_path = Path(sys.argv[3])
full_path = Path(sys.argv[4])

current = caddy_path.read_text(encoding="utf-8")
snippet = snippet_path.read_text(encoding="utf-8")
app_block = block(snippet, "app.ai-pets.ru")
if app_block is None:
    raise SystemExit("app.ai-pets.ru block not found in generated snippet")

app_only = remove(current, "app.ai-pets.ru").rstrip() + "\n\n" + app_block.strip() + "\n"

full = current
for label in ("app.ai-pets.ru", "ai-pets.ru", "www.ai-pets.ru"):
    full = remove(full, label)
full = full.rstrip() + "\n\n" + snippet.strip() + "\n"

app_only_path.write_text(app_only, encoding="utf-8")
full_path.write_text(full, encoding="utf-8")
print("prepared:", app_only_path)
print("prepared:", full_path)
PY

validate_caddy() {
    docker exec "$CADDY_CONTAINER" caddy validate --config /etc/caddy/Caddyfile
}

reload_caddy() {
    docker exec "$CADDY_CONTAINER" caddy reload --config /etc/caddy/Caddyfile
}

restore_caddy() {
    cp -a "$BACKUP_DIR/Caddyfile" "$CADDYFILE"
    validate_caddy >/dev/null 2>&1 || true
    reload_caddy >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# 3. Add app subdomain only; root still points to the existing frontend
# ---------------------------------------------------------------------------
log "4/6 add app.ai-pets.ru (root stays on frontend)"
cp "$WORK_DIR/Caddyfile.app-only" "$CADDYFILE"
if ! validate_caddy; then
    restore_caddy
    fail "app-only Caddy config is invalid; original Caddyfile restored"
fi
if ! reload_caddy; then
    restore_caddy
    fail "Caddy reload failed for app-only config; original Caddyfile restored"
fi

echo "waiting for https://$APP_DOMAIN/ ..."
app_ok=0
for _ in $(seq 1 40); do
    if curl -fsS --max-time 5 -o /dev/null "https://$APP_DOMAIN/"; then
        app_ok=1
        break
    fi
    sleep 3
done
if [[ "$app_ok" -ne 1 ]]; then
    restore_caddy
    fail "app.ai-pets.ru is not reachable; original Caddyfile restored"
fi
if ! curl -fsS --max-time 10 "https://$APP_DOMAIN/api/health" >/dev/null; then
    restore_caddy
    fail "app.ai-pets.ru/api/health failed; original Caddyfile restored"
fi
echo "app and API are reachable"

# ---------------------------------------------------------------------------
# 4. Full switch: root -> landing, app stays on frontend
# ---------------------------------------------------------------------------
log "5/6 switch root to landing"
cp "$WORK_DIR/Caddyfile.full" "$CADDYFILE"
if ! validate_caddy; then
    restore_caddy
    fail "full Caddy config is invalid; original Caddyfile restored"
fi
if ! reload_caddy; then
    restore_caddy
    fail "Caddy reload failed for full config; original Caddyfile restored"
fi

sleep 2
root_code="$(curl -s -o /dev/null -w '%{http_code}' "https://$ROOT_DOMAIN/" || true)"
if [[ "$root_code" != "200" ]]; then
    restore_caddy
    fail "landing returned HTTP ${root_code:-000}; original Caddyfile restored"
fi

# ---------------------------------------------------------------------------
# 5. Smoke checks
# ---------------------------------------------------------------------------
log "6/6 smoke checks"

printf 'root:    %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "https://$ROOT_DOMAIN/" || true)"
printf 'app:     %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "https://$APP_DOMAIN/" || true)"
printf 'api:     %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "https://$APP_DOMAIN/api/health" || true)"
printf 'www:     %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "https://www.$ROOT_DOMAIN/" || true)"
printf 'privacy: %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "https://$ROOT_DOMAIN/privacy/" || true)"
printf 'terms:   %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "https://$ROOT_DOMAIN/terms/" || true)"

if curl -sI "https://$APP_DOMAIN/" | grep -qi '^x-robots-tag:.*noindex'; then
    echo "noindex app header: OK"
else
    warn "X-Robots-Tag noindex not found on app"
fi

root_cache="$(curl -sI "https://$ROOT_DOMAIN/" | tr -d '\r' | awk -F': ' 'tolower($1)=="cache-control" {print $2}')"
css_cache="$(curl -sI "https://$ROOT_DOMAIN/assets/styles.css" | tr -d '\r' | awk -F': ' 'tolower($1)=="cache-control" {print $2}')"
echo "html cache-control: ${root_cache:-missing}"
echo "css cache-control:  ${css_cache:-missing}"
[[ "$root_cache" == "no-cache" ]] || warn "unexpected HTML Cache-Control: ${root_cache:-missing}"
[[ "$css_cache" == *"max-age=31536000"* ]] || warn "unexpected CSS Cache-Control: ${css_cache:-missing}"

for private_path in README.md DEPLOY.md nginx.conf compose.edge.fragment.yml Caddyfile.edge.snippet; do
    code="$(curl -s -o /dev/null -w '%{http_code}' "https://$ROOT_DOMAIN/$private_path" || true)"
    if [[ "$code" == "404" ]]; then
        echo "private /$private_path: 404 OK"
    else
        warn "private /$private_path returned $code (expected 404)"
    fi
done

echo
echo "DONE. Backups: $BACKUP_DIR"
echo "Rollback:"
echo "  cp $BACKUP_DIR/Caddyfile $CADDYFILE"
echo "  docker exec $CADDY_CONTAINER caddy reload --config /etc/caddy/Caddyfile"
