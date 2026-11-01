#!/usr/bin/env python
"""Merge LoRA-адаптера Qwen3-8B в 16-bit Hugging Face модель (T-015).

Тяжелые импорты Unsloth выполняются только при реальном merge. `--dry-run`
проверяет конфиг и пути без GPU и без загрузки модели — это позволяет
подготовить команды локально.

Примеры::

    python scripts/merge_lora.py --dry-run
    python scripts/merge_lora.py --adapter-dir outputs/sft_qwen3_8b/adapter
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from configs.training import (
    DEFAULT_TRAINING_CONFIG,
    TrainingConfigError,
    load_training_config,
    resolve_path,
)
from data_pipeline.cli import configure_logging, positive_int

DEFAULT_ADAPTER_DIR = Path("outputs/sft_qwen3_8b/adapter")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Merge LoRA-адаптера в merged 16-bit модель (Unsloth).",
        epilog="Для проверки путей используйте --dry-run (GPU не нужен).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_TRAINING_CONFIG,
        metavar="PATH",
        help=f"YAML-конфиг обучения (по умолчанию {DEFAULT_TRAINING_CONFIG.name})",
    )
    parser.add_argument(
        "--adapter-dir",
        type=Path,
        default=DEFAULT_ADAPTER_DIR,
        metavar="PATH",
        help=f"каталог LoRA adapter (по умолчанию {DEFAULT_ADAPTER_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="куда сохранить merged-модель (по умолчанию merged_dir из конфига)",
    )
    parser.add_argument(
        "--max-seq-len",
        type=positive_int,
        default=None,
        metavar="N",
        help="переопределить max_seq_length из конфига",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="проверить конфиг и пути, не загружать модель",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    try:
        config = load_training_config(args.config)
    except (TrainingConfigError, ValidationError) as exc:
        logger.error("Не удалось прочитать конфиг: {}", exc)
        return 1

    adapter_dir = resolve_path(args.adapter_dir)
    output_dir = resolve_path(
        args.output_dir or config.merged_dir or (resolve_path(config.output_dir) / "merged")
    )
    max_seq_len = args.max_seq_len or config.training.max_seq_len

    logger.info("Базовая модель: {}", config.base_model)
    logger.info("LoRA adapter: {}", adapter_dir)
    logger.info("Merged output: {}", output_dir)
    logger.info("max_seq_len: {}", max_seq_len)

    if args.dry_run:
        if adapter_dir.exists():
            logger.info("adapter найден")
        else:
            logger.warning("adapter пока отсутствует: {}", adapter_dir)
        logger.info("--dry-run: merge не запускался, GPU/Unsloth не загружались")
        return 0

    if not adapter_dir.exists():
        logger.error("LoRA adapter не найден: {}", adapter_dir)
        return 1
    if not (adapter_dir / "adapter_config.json").exists():
        logger.warning(
            "В {} нет adapter_config.json; ожидается каталог, сохранённый train_sft.py",
            adapter_dir,
        )

    try:
        from unsloth import FastLanguageModel

        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=str(adapter_dir),
            max_seq_length=max_seq_len,
            dtype=None,
            load_in_4bit=False,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Merge LoRA → {}", output_dir)
        model.save_pretrained_merged(
            str(output_dir),
            tokenizer,
            save_method="merged_16bit",
        )
        metadata = {
            "created_at": datetime.now(UTC).isoformat(),
            "base_model": config.base_model,
            "adapter_dir": str(adapter_dir),
            "output_dir": str(output_dir),
            "max_seq_len": max_seq_len,
            "save_method": "merged_16bit",
        }
        (output_dir / "merge_metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except ImportError as exc:
        logger.error(
            "Unsloth не установлен ({}). Установите requirements-train.txt на GPU-сервере.",
            exc,
        )
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        logger.exception("Merge прерван: {}", exc)
        return 1

    logger.info("Готово: {}", output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
