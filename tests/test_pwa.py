"""Тесты PWA-оболочки и мобильной готовности (T-176, T-177)."""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = PROJECT_ROOT / "frontend" / "public"


def test_web_app_manifest_is_installable() -> None:
    manifest = json.loads(
        (PUBLIC_DIR / "manifest.webmanifest").read_text(encoding="utf-8")
    )

    assert manifest["name"].startswith("VetAssistant")
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["theme_color"] == "#171717"
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert all(icon["type"] == "image/png" for icon in manifest["icons"])
    assert all(
        "maskable" in icon.get("purpose", "") for icon in manifest["icons"]
    )


def test_service_worker_caches_shell_but_not_api() -> None:
    service_worker = (PUBLIC_DIR / "sw.js").read_text(encoding="utf-8")

    assert "CACHE_NAME" in service_worker
    assert "cache.addAll(APP_SHELL)" in service_worker
    assert "/manifest.webmanifest" in service_worker
    assert "pwa-512.png" in service_worker
    assert "url.pathname.startsWith('/api/')" in service_worker
    assert "url.pathname.startsWith('/v1/')" in service_worker
    assert "url.origin !== self.location.origin" in service_worker


def test_png_icons_exist() -> None:
    for name in ("pwa-192.png", "pwa-512.png", "apple-touch-icon.png"):
        path = PUBLIC_DIR / name
        assert path.exists(), name
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_index_html_links_pwa_metadata() -> None:
    html = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'rel="manifest"' in html
    assert "/manifest.webmanifest" in html
    assert 'name="viewport"' in html
    assert "viewport-fit=cover" in html
    assert 'name="theme-color"' in html
    assert 'rel="apple-touch-icon"' in html
