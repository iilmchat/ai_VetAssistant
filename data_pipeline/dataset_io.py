"""Чтение и запись JSONL, подготовка сидов (T-003)."""

from __future__ import annotations

import json
from collections.abc import Collection, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import ValidationError

from data_pipeline.schemas import SeedRecord


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Итерировать JSON-объекты файла, пропуская пустые и битые строки.

    Битая строка не роняет чтение: логируем предупреждение и идём дальше.
    Так `--resume` не теряет весь прогресс из-за одного испорченного хвоста.
    """
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("{}:{} — пропущена битая JSON-строка: {}", path.name, line_no, exc)
                continue
            if isinstance(payload, dict):
                yield payload
            else:
                logger.warning("{}:{} — пропущена строка: ожидался JSON-объект", path.name, line_no)


def collect_existing_ids(path: Path) -> set[str]:
    """Собрать id уже обработанных записей — основа `--resume`."""
    ids: set[str] = set()
    for payload in read_jsonl(path):
        record_id = payload.get("id")
        if isinstance(record_id, str) and record_id:
            ids.add(record_id)
    return ids


def read_seed_records(path: Path) -> list[SeedRecord]:
    """Прочитать и провалидировать сиды.

    Raises:
        FileNotFoundError: файла сидов нет.
        ValueError: запись не прошла схему или id повторяется.
    """
    if not path.exists():
        raise FileNotFoundError(f"файл сидов не найден: {path}")

    seeds: list[SeedRecord] = []
    seen: set[str] = set()
    for index, payload in enumerate(read_jsonl(path), start=1):
        try:
            seed = SeedRecord.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"{path}: запись #{index} не прошла валидацию:\n{exc}") from exc
        if seed.id in seen:
            raise ValueError(f"{path}: дубликат id {seed.id!r}")
        seen.add(seed.id)
        seeds.append(seed)
    return seeds


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    """Дописать одну запись в JSONL (UTF-8, LF, append)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def select_pending(
    seeds: Sequence[SeedRecord],
    *,
    existing_ids: Collection[str] = (),
    limit: int | None = None,
) -> list[SeedRecord]:
    """Отбросить уже обработанные сиды (`--resume`) и применить `--limit`."""
    if limit is not None and limit < 1:
        raise ValueError("limit должен быть >= 1")
    pending = [seed for seed in seeds if seed.id not in existing_ids]
    return pending[:limit] if limit is not None else pending
