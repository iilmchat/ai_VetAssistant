"""Тесты production-конфигурации и деплоя (T-040)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def _yaml(relative: str) -> dict[str, Any]:
    data = yaml.safe_load(_read(relative))
    assert isinstance(data, dict)
    return data


def test_prod_compose_publishes_only_frontend_http() -> None:
    compose = _yaml("docker-compose.prod.yml")
    services = compose["services"]

    assert {"db", "api", "frontend"} <= set(services)
    assert "bot" not in services
    assert services["frontend"]["ports"] == ["80:80"]
    assert "ports" not in services["api"]
    assert services["api"]["expose"] == ["8000"]
    assert "ports" not in services["db"]
    assert services["frontend"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert "postgres_data" in compose["volumes"]


def test_prod_compose_requires_production_secrets() -> None:
    compose = _yaml("docker-compose.prod.yml")
    api_env = compose["services"]["api"]["environment"]
    db_env = compose["services"]["db"]["environment"]

    assert "VET_API_JWT_SECRET" in api_env
    assert "POSTGRES_PASSWORD" in db_env
    assert "bot" not in compose["services"]


def test_ssl_overlay_adds_https_and_certbot() -> None:
    compose = _yaml("docker-compose.ssl.yml")
    services = compose["services"]

    assert services["frontend"]["ports"] == ["443:443"]
    assert any(
        "ssl.conf" in volume for volume in services["frontend"]["volumes"]
    )
    assert "certbot" in services
    assert services["certbot"]["profiles"] == ["tools"]


def test_env_production_example_documents_secrets() -> None:
    template = _read(".env.production.example")

    for key in (
        "POSTGRES_PASSWORD=",
        "VET_API_JWT_SECRET=",
        "VET_DOMAIN=",
        "LETSENCRYPT_EMAIL=",
        "VET_API_ALLOW_PUBLIC_REGISTRATION=false",
    ):
        assert key in template
    assert "openssl rand -hex 32" in template
    assert "TELEGRAM_BOT_TOKEN" not in template


def test_gitignore_keeps_env_secret_but_tracks_production_example() -> None:
    gitignore = _read(".gitignore")

    assert "\n.env\n" in gitignore
    assert "!.env.production.example" in gitignore
    assert "deploy/certbot/conf/" in gitignore
    assert "deploy/certbot/www/" in gitignore


def test_nginx_proxies_api_and_serves_spa() -> None:
    nginx = _read("frontend/nginx.conf")

    assert "proxy_pass http://api:8000/;" in nginx
    assert "try_files $uri $uri/ /index.html;" in nginx
    assert "proxy_buffering off;" in nginx
    assert "/.well-known/acme-challenge/" in nginx


def test_ssl_config_uses_fixed_certificate_and_redirects_http() -> None:
    ssl_config = _read("deploy/nginx/ssl.conf")

    assert "listen 443 ssl;" in ssl_config
    assert "listen 80 default_server;" in ssl_config
    assert "return 301 https://$host$request_uri;" in ssl_config
    assert "/etc/letsencrypt/live/vetassistant/fullchain.pem" in ssl_config
    assert "Strict-Transport-Security" in ssl_config


def test_deploy_script_installs_docker_and_starts_prod_stack() -> None:
    script = _read("scripts/deploy.sh")

    assert script.startswith("#!/usr/bin/env bash")
    assert "set -Eeuo pipefail" in script
    assert "docker-compose.prod.yml" in script
    assert "docker-compose.ssl.yml" in script
    assert "compose up -d --build" in script
    assert "openssl rand -hex 32" in script
    assert "certbot" in script
    assert "TELEGRAM_BOT_TOKEN" not in script
    assert "VET_BOT_AUTH_SECRET" not in script


def test_renew_ssl_script_uses_prod_overlay() -> None:
    script = _read("scripts/renew_ssl.sh")

    assert "docker-compose.prod.yml" in script
    assert "docker-compose.ssl.yml" in script
    assert "renew --webroot" in script
    assert "nginx -s reload" in script


def test_release_version_is_1_0_0_everywhere() -> None:
    package = json.loads(_read("frontend/package.json"))
    lockfile = json.loads(_read("frontend/package-lock.json"))
    dev_compose = _yaml("docker-compose.yml")
    prod_compose = _yaml("docker-compose.prod.yml")

    assert 'version = "1.0.0"' in _read("pyproject.toml")
    assert 'version="1.0.0"' in _read("app/main.py")
    assert package["version"] == "1.0.0"
    assert lockfile["version"] == "1.0.0"
    assert lockfile["packages"][""]["version"] == "1.0.0"
    assert dev_compose["services"]["api"]["image"] == "vetassistant:1.0.0"
    assert (
        dev_compose["services"]["frontend"]["image"]
        == "vetassistant-frontend:1.0.0"
    )
    assert prod_compose["services"]["api"]["image"] == "vetassistant:1.0.0"
    assert (
        prod_compose["services"]["frontend"]["image"]
        == "vetassistant-frontend:1.0.0"
    )


def test_release_documents_exist_and_are_linked() -> None:
    security = _read("SECURITY.md")
    readme = _read("README.md")
    changelog = _read("docs/CHANGELOG.md")

    assert "VET_API_JWT_SECRET" in security
    assert "POSTGRES_PASSWORD" in security
    assert "Report a vulnerability" in security
    assert "[SECURITY.md](SECURITY.md)" in readme
    assert "[DEPLOYMENT.md](DEPLOYMENT.md)" in readme
    assert "Production Ready" in readme
    assert "## [1.0.0] — 2026-11-03" in changelog
