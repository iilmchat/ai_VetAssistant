#!/usr/bin/env python
"""Загрузка реальных статей MSD Vet Manual в локальную базу знаний (T-030, T-133).

Скрипт скачивает профессиональные статьи MSD Vet Manual, извлекает основной
текст и сохраняет его в ``data/knowledge/real/*.txt``. Эти файлы затем
индексируются ``scripts/ingest_knowledge.py``.

По умолчанию берутся встроенные статьи (``ARTICLES``), с ``--url`` можно
скачать любую статью по прямой ссылке, а ``--batch expansion`` загружает
набор узких тем T-156 (стоматология, офтальмология, эндокринология и др.).

Примеры::

    python scripts/download_msd.py --help
    python scripts/download_msd.py --dry-run
    python scripts/download_msd.py
    python scripts/download_msd.py --batch expansion
    python scripts/download_msd.py --batch all
    python scripts/download_msd.py --url https://www.msdvetmanual.com/...
    python scripts/download_msd.py --url URL1 --url URL2
"""

from __future__ import annotations

import argparse
import re
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
FILENAME_SLUG_LIMIT = 80



@dataclass(frozen=True)
class MsdArticle:
    """Описание одной статьи для загрузки."""

    slug: str
    title: str
    url: str
    filename: str
    topic: str = ""


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

#: Новые узкие темы T-156: стоматология, офтальмология, эндокринология,
#: дерматология, ортопедия, нефрология и респираторные болезни.
EXPANSION_ARTICLES: tuple[MsdArticle, ...] = (
    MsdArticle(
        slug="dental-disorders-dogs",
        title="Dental Disorders of Dogs",
        url=(
            "https://www.msdvetmanual.com/dog-owners/"
            "digestive-disorders-of-dogs/dental-disorders-of-dogs"
        ),
        filename="msd_dental_disorders_dogs.txt",
        topic="Стоматология",
    ),
    MsdArticle(
        slug="dental-disorders-cats",
        title="Dental Disorders of Cats",
        url=(
            "https://www.msdvetmanual.com/cat-owners/"
            "digestive-disorders-of-cats/dental-disorders-of-cats"
        ),
        filename="msd_dental_disorders_cats.txt",
        topic="Стоматология",
    ),
    MsdArticle(
        slug="glaucoma-dogs",
        title="Glaucoma in Dogs",
        url=(
            "https://www.msdvetmanual.com/dog-owners/"
            "eye-disorders-of-dogs/glaucoma-in-dogs"
        ),
        filename="msd_glaucoma_dogs.txt",
        topic="Офтальмология",
    ),
    MsdArticle(
        slug="thyroid-disorders-dogs",
        title="Disorders of the Thyroid Gland in Dogs",
        url=(
            "https://www.msdvetmanual.com/dog-owners/"
            "hormonal-disorders-of-dogs/disorders-of-the-thyroid-gland-in-dogs"
        ),
        filename="msd_thyroid_disorders_dogs.txt",
        topic="Эндокринология",
    ),
    MsdArticle(
        slug="thyroid-disorders-cats",
        title="Disorders of the Thyroid Gland in Cats",
        url=(
            "https://www.msdvetmanual.com/cat-owners/"
            "hormonal-disorders-of-cats/disorders-of-the-thyroid-gland-in-cats"
        ),
        filename="msd_thyroid_disorders_cats.txt",
        topic="Эндокринология",
    ),
    MsdArticle(
        slug="allergies-dogs",
        title="Allergies in Dogs",
        url=(
            "https://www.msdvetmanual.com/dog-owners/"
            "skin-disorders-of-dogs/allergies-in-dogs"
        ),
        filename="msd_allergies_dogs.txt",
        topic="Дерматология",
    ),
    MsdArticle(
        slug="ringworm-cats",
        title="Ringworm (Dermatophytosis) in Cats",
        url=(
            "https://www.msdvetmanual.com/cat-owners/"
            "skin-disorders-of-cats/ringworm-dermatophytosis-in-cats"
        ),
        filename="msd_ringworm_cats.txt",
        topic="Дерматология",
    ),
    MsdArticle(
        slug="osteoarthritis-dogs",
        title="Osteoarthritis (Degenerative Joint Disease) in Dogs",
        url=(
            "https://www.msdvetmanual.com/dog-owners/"
            "bone-joint-and-muscle-disorders-of-dogs/"
            "osteoarthritis-degenerative-joint-disease"
        ),
        filename="msd_osteoarthritis_dogs.txt",
        topic="Ортопедия",
    ),
    MsdArticle(
        slug="chronic-kidney-disease-dogs",
        title="Chronic Kidney Disease in Dogs",
        url=(
            "https://www.msdvetmanual.com/dog-owners/"
            "kidney-and-urinary-tract-disorders-of-dogs/"
            "chronic-kidney-disease-in-dogs"
        ),
        filename="msd_chronic_kidney_disease_dogs.txt",
        topic="Нефрология",
    ),
    MsdArticle(
        slug="feline-asthma",
        title="Tracheobronchitis (Bronchitis, Bronchial Asthma) in Cats",
        url=(
            "https://www.msdvetmanual.com/cat-owners/"
            "lung-and-airway-disorders-of-cats/"
            "tracheobronchitis-bronchitis-bronchial-asthma-in-cats"
        ),
        filename="msd_feline_asthma_bronchitis.txt",
        topic="Респираторные болезни",
    ),
)

#: Наборы статей для ``--batch``.
BATCHES: dict[str, tuple[MsdArticle, ...]] = {
    "default": ARTICLES,
    "expansion": EXPANSION_ARTICLES,
    "all": (*ARTICLES, *EXPANSION_ARTICLES),
}


def _slugify(value: str) -> str:
    """Привести последний сегмент URL к безопасному имени файла."""
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return (slug or "article")[:FILENAME_SLUG_LIMIT]


def article_from_url(url: str) -> MsdArticle:
    """Собрать описание статьи из прямой ссылки (T-133).

    Имя файла выводится из последнего сегмента пути: повторное скачивание той
    же статьи перезапишет тот же TXT, а не создаст дубль.

    Raises:
        ValueError: ссылка не абсолютная, без хоста или без пути к статье.
    """
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"ожидалась абсолютная http(s)-ссылка: {url}")
    segments = [segment for segment in parts.path.split("/") if segment]
    if not segments:
        raise ValueError(f"в ссылке нет пути к статье: {url}")

    slug = _slugify(segments[-1])
    return MsdArticle(
        slug=slug,
        title=segments[-1].replace("-", " "),
        url=url.strip(),
        filename=f"msd_{slug}.txt",
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
        "--url",
        action="append",
        metavar="URL",
        help=(
            "прямая ссылка на статью MSD; можно указать несколько раз. "
            "Без --url скачивается выбранный --batch"
        ),
    )
    parser.add_argument(
        "--batch",
        choices=tuple(BATCHES),
        default="default",
        help=(
            "набор статей без --url: default — две базовые, "
            "expansion — 10 новых тем T-156, all — все (по умолчанию default)"
        ),
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

    if args.url:
        try:
            articles = tuple(article_from_url(url) for url in args.url)
        except ValueError as exc:
            logger.error("{}", exc)
            return 2
    else:
        articles = BATCHES[args.batch]

    if args.dry_run:
        for article in articles:
            topic = f"[{article.topic}] " if article.topic else ""
            logger.info(
                "DRY-RUN {}{} -> {} ({})",
                topic,
                article.url,
                args.output_dir / article.filename,
                article.title,
            )
        logger.info("Всего статей в наборе {}: {}", args.batch, len(articles))
        return 0

    saved = 0
    errors = 0
    for article in articles:
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
