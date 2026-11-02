"""Тесты загрузки реальных статей MSD Vet Manual (T-030)."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from scripts.download_msd import (
    ARTICLES,
    download_article,
    extract_article,
    main,
    to_proxy_url,
)

SAMPLE_HTML = """
<html>
  <head><title>Sample</title><script>bad()</script></head>
  <body>
    <nav>Навигация</nav>
    <h1>Toxicoses From Human Analgesics in Animals</h1>
    <main data-testid="topic-main-content">
      <p>Acetaminophen is toxic to cats.</p>
      <p>Dogs and cats are exposed to human analgesics.</p>
      <p>Seek veterinary care if ingestion is suspected.</p>
      <p>This paragraph exists to make the extracted text long enough for validation.
      It repeats clinically relevant details about poisoning and treatment.
      Cats are especially susceptible because of limited glucuronidation.
      Treatment includes decontamination, N-acetylcysteine, and supportive care.
      Owners should contact a veterinarian immediately after suspected exposure.
      Do not induce vomiting unless instructed by a veterinary professional.</p>
    </main>
    <footer>Подвал</footer>
  </body>
</html>
"""


def test_to_proxy_url_preserves_path_and_adds_translate_params() -> None:
    url = (
        "https://www.msdvetmanual.com/toxicology/"
        "toxicoses-from-human-analgesics/toxicoses-from-human-analgesics-in-animals"
    )

    proxy = to_proxy_url(url)

    assert proxy.startswith("https://www-msdvetmanual-com.translate.goog/toxicology/")
    assert "_x_tr_sl=auto" in proxy
    assert "_x_tr_tl=ru" in proxy


def test_extract_article_returns_title_and_main_text() -> None:
    title, text = extract_article(SAMPLE_HTML)

    assert title == "Toxicoses From Human Analgesics in Animals"
    assert "Acetaminophen is toxic to cats." in text
    assert "Навигация" not in text
    assert "Подвал" not in text


def test_extract_article_rejects_too_short_text() -> None:
    with pytest.raises(ValueError, match="основной текст"):
        extract_article("<html><body><main>коротко</main></body></html>")


def test_download_article_falls_back_to_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_fetch(url: str, *, timeout: float) -> str:
        calls.append(url)
        if len(calls) == 1:
            raise requests.ConnectionError("direct is slow")
        return SAMPLE_HTML

    monkeypatch.setattr("scripts.download_msd.fetch_html", fake_fetch)

    output = download_article(ARTICLES[0], output_dir=tmp_path)

    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "Source: https://www.msdvetmanual.com/" in content
    assert "Acetaminophen is toxic to cats." in content
    assert calls[1].startswith("https://www-msdvetmanual-com.translate.goog/")


def test_dry_run_does_not_create_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "knowledge"

    assert main(["--dry-run", "--output-dir", str(output_dir)]) == 0
    assert not output_dir.exists()
