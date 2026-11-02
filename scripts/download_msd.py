#!/usr/bin/env python
"""Загрузка реальных статей MSD Vet Manual в локальную базу знаний (T-030).

Скрипт скачивает 1–2 профессиональные статьи MSD Vet Manual, извлекает
основной текст и сохраняет его в ``data/knowledge/real/*.txt``. Эти файлы
затем индексируются ``scripts/ingest_knowledge.py``.

Примеры::

    python scripts/download_msd.py --help
    python scripts/download_msd.py --dry-run
    python scripts/download_msd.py
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from loguru import logger

from configs.settings import PROJECT_ROOT
from data_pipeline.cli import configure_logging

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "knowledge" / "real"
DIRECT_TIMEOUT_S = 20.0
DEFAULT_TIMEOUT_S = 120.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)
PROXY_HOST = "www-msdvetmanual-com.translate.goog"


@dataclass(frozen=True)
class MsdArticle:
    """Описание одной статьи для загрузки."""

    slug: str
    title: str
    url: str
    filename: str


ARTICLES: tuple[MsdArticle, ...] = (
    MsdArticle(
        slug="analgesics",
        title="Toxicoses From Human Analgesics in Animals",
        url=(
            "https://www.msdvetmanual.com/toxicology/"
            "toxicoses-from-human-analgesics/"
            "toxicoses-from-human-analgesics-in-animals"
        ),
        filename="msd_toxicoses_from_human_analgesics.txt",
    ),
    MsdArticle(
        slug="diarrhea",
        title="Acute Hemorrhagic Diarrhea Syndrome in Dogs",
        url=(
            "https://www.msdvetmanual.com/digestive-system/"
            "diseases-of-the-large-intestine-in-small-animals/"
            "acute-hemorrhagic-diarrhea-syndrome-in-dogs"
        ),
        filename="msd_acute_hemorrhagic_diarrhea_dogs.txt",
    ),
)


def to_proxy_url(url: str) -> str:
    """Построить URL статьи через Google Translate-прокси.

    Прокси нужен как fallback: прямой CloudFront иногда отдаёт страницу
    крайне медленно. Содержимое при этом остаётся оригинальной статьёй MSD.
    """
    parts = urlsplit(url)
    query = parse_qsl(parts.query)
    query.extend(
        [
            ("_x_tr_sl", "auto"),
            ("_x_tr_tl", "ru"),
            ("_x_tr_hl", "en"),
        ]
    )
    return urlunsplit(
        (
            parts.scheme,
            PROXY_HOST,
            parts.path,
            urlencode(query),
            "",
        )
    )


def fetch_html(url: str, *, timeout: float) -> str:
    """Скачать HTML статьи."""
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def extract_article(html: str) -> tuple[str, str]:
    """Извлечь заголовок и основной текст статьи из HTML.

    Raises:
        ValueError: в HTML не найден осмысленный основной текст.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(
        ["script", "style", "nav", "header", "footer", "aside", "form", "button", "noscript"]
    ):
        tag.decompose()

    title_tag = soup.find("h1")
    title = title_tag.get_text(" ", strip=True) if title_tag is not None else ""

    main = soup.select_one('[data-testid="topic-main-content"]')
    if main is None:
        main = soup.find("main")
    if main is None:
        main = soup.body or soup

    lines = [line.strip() for line in main.get_text("\n").splitlines() if line.strip()]
    text = "\n".join(lines)
    if len(text) < 500:
        raise ValueError(f"не удалось извлечь основной текст (получено {len(text)} символов)")
    return title or "MSD Vet Manual article", text


def save_article(
    article: MsdArticle,
    title: str,
    text: str,
    *,
    output_dir: Path,
) -> Path:
    """Сохранить статью в TXT с источником и датой загрузки."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / article.filename
    content = (
        f"Source: {article.url}\nTitle: {title}\nDownloaded: {date.today().isoformat()}\n\n{text}\n"
    )
    output_path.write_text(content, encoding="utf-8")
    return output_path


def download_article(
    article: MsdArticle,
    *,
    output_dir: Path,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Path:
    """Скачать одну статью: сначала напрямую, затем через прокси.

    Fallback также срабатывает, если прямой ответ оказался неполным и
    ``extract_article`` не нашёл достаточно текста.
    """
    sources = (
        (article.url, min(timeout, DIRECT_TIMEOUT_S)),
        (to_proxy_url(article.url), timeout),
    )
    last_error: Exception | None = None
    for url, source_timeout in sources:
        try:
            html = fetch_html(url, timeout=source_timeout)
            if "</html>" not in html.lower():
                raise ValueError("получен неполный HTML")
            title, text = extract_article(html)
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            logger.warning("Не удалось получить {}: {}", url, exc)
            continue

        output_path = save_article(article, title, text, output_dir=output_dir)
        logger.info("Сохранено: {} ({} символов)", output_path, len(text))
        return output_path

    raise ValueError(f"не удалось загрузить статью {article.url}: {last_error}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Скачать реальные статьи MSD Vet Manual в data/knowledge/real.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        metavar="PATH",
        help=f"куда сохранять TXT (по умолчанию {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        metavar="SECONDS",
        help=f"таймаут загрузки (по умолчанию {DEFAULT_TIMEOUT_S})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать план загрузки, не обращаясь к сети",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    if args.timeout <= 0:
        logger.error("--timeout должен быть больше нуля")
        return 1

    if args.dry_run:
        for article in ARTICLES:
            logger.info(
                "DRY-RUN {} -> {} ({})",
                article.url,
                args.output_dir / article.filename,
                article.title,
            )
        return 0

    saved = 0
    errors = 0
    for article in ARTICLES:
        try:
            download_article(
                article,
                output_dir=args.output_dir,
                timeout=float(args.timeout),
            )
        except (requests.RequestException, ValueError, OSError) as exc:
            errors += 1
            logger.error("Не удалось загрузить {}: {}", article.url, exc)
        else:
            saved += 1

    logger.info("Итого: сохранено {}, ошибок {}", saved, errors)
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
