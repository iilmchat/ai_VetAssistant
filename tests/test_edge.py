"""Тесты Edge-артефактов и SFTP-загрузчика (T-043/T-044)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.upload_model import (
    _sftp_options,
    _ssh_options,
    build_sftp_batch,
    validate_local_model,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def _yaml(relative: str) -> dict[str, Any]:
    data = yaml.safe_load(_read(relative))
    assert isinstance(data, dict)
    return data


def test_edge_compose_has_no_published_ports_and_secure_bot() -> None:
    compose = _yaml("docker-compose.edge.yml")
    services = compose["services"]

    assert {"api", "db", "frontend", "bot"} <= set(services)
    assert "ui" not in services
    for service in services.values():
        assert "ports" not in service

    assert services["frontend"]["expose"] == ["80"]
    assert services["api"]["expose"] == ["8000"]

    bot = services["bot"]
    assert bot["networks"] == ["edge"]
    assert bot["depends_on"]["api"]["condition"] == "service_healthy"
    bot_env = bot["environment"]
    assert bot_env["TELEGRAM_BOT_TOKEN"] == "${TELEGRAM_BOT_TOKEN:-}"
    assert bot_env["VET_BOT_ALLOWED_TELEGRAM_IDS"] == (
        "${VET_BOT_ALLOWED_TELEGRAM_IDS:-}"
    )
    assert bot_env["VET_BOT_USE_RAG"] == "${VET_BOT_USE_RAG:-true}"


def test_edge_networks_are_isolated_correctly() -> None:
    compose = _yaml("docker-compose.edge.yml")
    services = compose["services"]
    networks = compose["networks"]

    assert networks["edge"]["external"] is True
    assert networks["internal"]["internal"] is True
    assert services["db"]["networks"] == ["internal"]
    assert services["api"]["networks"] == ["internal", "edge"]
    assert services["frontend"]["networks"] == ["edge"]


def test_edge_api_defaults_to_closed_registration() -> None:
    compose = _yaml("docker-compose.edge.yml")
    api_env = compose["services"]["api"]["environment"]

    assert api_env["VET_API_ALLOW_PUBLIC_REGISTRATION"] == (
        "${VET_API_ALLOW_PUBLIC_REGISTRATION:-false}"
    )


def test_caddyfile_proxies_api_and_spa() -> None:
    caddyfile = _read("deploy/Caddyfile")

    assert "ai-pets.ru {" in caddyfile
    assert "www.ai-pets.ru {" in caddyfile
    assert "redir https://ai-pets.ru{uri} permanent" in caddyfile
    assert "handle_path /api/*" in caddyfile
    assert "reverse_proxy api:8000" in caddyfile
    assert "reverse_proxy frontend:80" in caddyfile


def test_ssh_and_sftp_use_correct_port_flags() -> None:
    ssh_options = _ssh_options(port=2222, identity=None, password="")
    sftp_options = _sftp_options(port=2222, identity=None, password="")

    assert ssh_options[:2] == ["-p", "2222"]
    assert sftp_options[:2] == ["-P", "2222"]
    assert "-p" not in sftp_options
    assert "-P" in sftp_options


def test_build_sftp_batch_quotes_paths_and_uses_reput() -> None:
    batch = build_sftp_batch(Path("C:/models/model.gguf"), "/srv/model.gguf.part")

    assert batch == 'reput "C:/models/model.gguf" "/srv/model.gguf.part"\n'


def test_validate_local_model_checks_size_and_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.upload_model as upload_model

    model = tmp_path / "model.gguf"
    payload = b"model-bytes"
    model.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(upload_model, "MODEL_EXPECTED_SIZE", len(payload))
    monkeypatch.setattr(upload_model, "MODEL_SHA256_PREFIX", digest[:6])
    monkeypatch.setattr(upload_model, "MODEL_SHA256_SUFFIX", digest[-4:])

    assert validate_local_model(model, None) == digest
    assert validate_local_model(model, digest) == digest


def test_validate_local_model_rejects_wrong_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.upload_model as upload_model

    model = tmp_path / "model.gguf"
    model.write_bytes(b"too-small")
    monkeypatch.setattr(upload_model, "MODEL_EXPECTED_SIZE", 999_999)

    with pytest.raises(upload_model.UploadError, match="размер модели"):
        validate_local_model(model, None)
