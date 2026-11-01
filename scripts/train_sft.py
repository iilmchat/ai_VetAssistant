#!/usr/bin/env python
"""SFT/QLoRA-обучение Qwen3-8B на диалогах VetAssistant (T-015).

Скрипт не импортирует Unsloth/torch на уровне модуля: `--dry-run` работает на
Windows/CPU без GPU и без установленных training-зависимостей. Тяжелые
импорты выполняются только в `run_training()`.

Примеры::

    python scripts/train_sft.py --dry-run
    python scripts/train_sft.py --dry-run --limit 3
    python scripts/train_sft.py --config configs/train_sft.yaml
    python scripts/train_sft.py --limit 20 --max-steps 10   # smoke на GPU
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import subprocess
import time
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import ValidationError

from configs.settings import PROJECT_ROOT
from configs.training import (
    DEFAULT_TRAINING_CONFIG,
    TrainingConfig,
    TrainingConfigError,
    load_training_config,
    resolve_path,
)
from data_pipeline.cli import configure_logging, positive_int
from data_pipeline.dataset_io import read_jsonl
from data_pipeline.schemas import DialogueRecord

DEFAULT_ADAPTER_NAME = "adapter"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="SFT/QLoRA-обучение Qwen3-8B на data/train.jsonl.",
        epilog="Для локальной проверки используйте --dry-run: GPU/torch не нужны.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_TRAINING_CONFIG,
        metavar="PATH",
        help=f"YAML-конфиг обучения (по умолчанию {DEFAULT_TRAINING_CONFIG.name})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="переопределить output_dir из конфига",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=None,
        metavar="N",
        help="взять не больше N train-диалогов (для smoke/проверки)",
    )
    parser.add_argument(
        "--max-steps",
        type=positive_int,
        default=None,
        metavar="N",
        help="остановиться после N шагов (для smoke на GPU)",
    )
    parser.add_argument(
        "--resume-from-checkpoint",
        default=None,
        metavar="PATH",
        help="путь к checkpoint для продолжения обучения",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="после обучения сохранить merged 16-bit модель (Unsloth)",
    )
    parser.add_argument(
        "--preview-count",
        type=positive_int,
        default=1,
        metavar="N",
        help="сколько примеров показать в --dry-run (по умолчанию 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="проверить конфиг и данные, показать ChatML-превью; не обучать",
    )
    return parser.parse_args(argv)


def load_dialogues(path: Path, *, limit: int | None = None) -> list[DialogueRecord]:
    """Прочитать JSONL и провалидировать диалоги через `DialogueRecord`.

    Raises:
        FileNotFoundError: файл отсутствует.
        ValueError: файл пуст или запись не соответствует схеме.
    """
    if not path.exists():
        raise FileNotFoundError(f"нет файла диалогов: {path}")

    records: list[DialogueRecord] = []
    for line_no, payload in enumerate(read_jsonl(path), start=1):
        try:
            records.append(DialogueRecord.model_validate(payload))
        except ValidationError as exc:
            raise ValueError(f"{path}:{line_no}: диалог не прошёл валидацию: {exc}") from exc
        if limit is not None and len(records) >= limit:
            break

    if not records:
        raise ValueError(f"файл диалогов пуст: {path}")
    return records


def render_chatml_preview(record: DialogueRecord) -> str:
    """Показать диалог в упрощенном ChatML без загрузки токенизатора."""
    parts: list[str] = []
    for message in record.messages:
        parts.append(f"<|im_start|>{message.role}\n{message.content}<|im_end|>")
    return "\n".join(parts)


def format_chat(record: DialogueRecord, tokenizer: Any) -> str:
    """Применить chat template Qwen к сообщениям и добавить EOS.

    Qwen3 поддерживает ``enable_thinking``; для SFT отключаем reasoning-блок,
    чтобы модель училась сразу отвечать владельцу. Для токенизаторов без этого
    аргумента используется обычный шаблон.
    """
    messages = [{"role": message.role, "content": message.content} for message in record.messages]
    kwargs = {
        "tokenize": False,
        "add_generation_prompt": False,
        "enable_thinking": False,
    }
    try:
        text = tokenizer.apply_chat_template(messages, **kwargs)
    except TypeError:
        kwargs.pop("enable_thinking")
        text = tokenizer.apply_chat_template(messages, **kwargs)

    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"chat template вернул пустой текст для {record.id}")

    eos_token = getattr(tokenizer, "eos_token", None)
    if isinstance(eos_token, str) and eos_token and not text.endswith(eos_token):
        text += eos_token
    return text


def dataset_stats(records: Sequence[DialogueRecord]) -> dict[str, Any]:
    """Краткая статистика для dry-run и метаданных прогона."""
    message_counts = [len(record.messages) for record in records]
    assistant_chars = sum(
        len(message.content)
        for record in records
        for message in record.messages
        if message.role == "assistant"
    )
    return {
        "records": len(records),
        "topics": dict(sorted(Counter(record.topic for record in records).items())),
        "messages_min": min(message_counts) if message_counts else 0,
        "messages_max": max(message_counts) if message_counts else 0,
        "messages_avg": round(sum(message_counts) / len(message_counts), 2)
        if message_counts
        else 0.0,
        "assistant_chars": assistant_chars,
    }


def dataset_hash(paths: Sequence[Path]) -> str:
    """SHA-256 по содержимому train/val файлов (для ID прогона)."""
    digest = hashlib.sha256()
    for path in paths:
        if not path.exists():
            continue
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    """Текущий git-коммит или ``unknown`` вне git-репозитория."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _filter_kwargs(target: Any, values: dict[str, Any]) -> dict[str, Any]:
    """Оставить только параметры, которые принимает SFTConfig/SFTTrainer.

    Версии TRL меняют имена (``max_length``/``max_seq_length``,
    ``eval_strategy``/``evaluation_strategy``, ``processing_class``/``tokenizer``),
    поэтому передаем только поддерживаемые аргументы.
    """
    parameters = inspect.signature(target).parameters
    return {key: value for key, value in values.items() if key in parameters}


def build_sft_config(
    config: TrainingConfig,
    *,
    output_dir: Path,
    run_name: str,
    has_eval: bool,
    max_steps: int | None = None,
) -> Any:
    """Собрать SFTConfig с совместимостью между версиями TRL."""
    from trl import SFTConfig

    params: dict[str, Any] = {
        "output_dir": str(output_dir),
        "run_name": run_name,
        "num_train_epochs": config.training.epochs,
        "per_device_train_batch_size": config.training.per_device_batch_size,
        "per_device_eval_batch_size": 1,
        "gradient_accumulation_steps": config.training.grad_accum,
        "learning_rate": config.training.lr,
        "lr_scheduler_type": config.training.lr_scheduler,
        "warmup_ratio": config.training.warmup_ratio,
        "bf16": config.training.bf16,
        "fp16": not config.training.bf16,
        "optim": config.training.optim,
        "logging_steps": config.training.logging_steps,
        "save_total_limit": config.training.save_total_limit,
        "seed": config.training.seed,
        "report_to": config.training.report_to,
        "dataset_text_field": "text",
        "packing": config.training.packing,
        "neftune_noise_alpha": config.training.neftune_alpha,
        "dataset_num_proc": 2,
    }
    if max_steps is not None:
        params["max_steps"] = max_steps

    signature = inspect.signature(SFTConfig).parameters
    if "max_length" in signature:
        params["max_length"] = config.training.max_seq_len
    elif "max_seq_length" in signature:
        params["max_seq_length"] = config.training.max_seq_len

    if has_eval:
        params["eval_steps"] = config.training.eval_steps
        params["save_steps"] = config.training.eval_steps
        params["save_strategy"] = "steps"
        params["load_best_model_at_end"] = True
        params["metric_for_best_model"] = "eval_loss"
        params["greater_is_better"] = False
    else:
        params["save_strategy"] = "steps"
        params["save_steps"] = config.training.save_steps
        params["load_best_model_at_end"] = False

    if "eval_strategy" in signature:
        params["eval_strategy"] = "steps" if has_eval else "no"
    elif "evaluation_strategy" in signature:
        params["evaluation_strategy"] = "steps" if has_eval else "no"

    return SFTConfig(**_filter_kwargs(SFTConfig, params))


def build_trainer(
    model: Any,
    tokenizer: Any,
    config: TrainingConfig,
    *,
    output_dir: Path,
    run_name: str,
    has_eval: bool,
    train_dataset: Any,
    eval_dataset: Any | None,
    max_steps: int | None = None,
) -> Any:
    """Собрать SFTTrainer с совместимым именем tokenizer/processing_class."""
    from trl import SFTTrainer

    sft_config = build_sft_config(
        config,
        output_dir=output_dir,
        run_name=run_name,
        has_eval=has_eval,
        max_steps=max_steps,
    )
    trainer_params: dict[str, Any] = {
        "model": model,
        "args": sft_config,
        "train_dataset": train_dataset,
    }
    if eval_dataset is not None:
        trainer_params["eval_dataset"] = eval_dataset

    signature = inspect.signature(SFTTrainer).parameters
    if "processing_class" in signature:
        trainer_params["processing_class"] = tokenizer
    elif "tokenizer" in signature:
        trainer_params["tokenizer"] = tokenizer
    if "dataset_text_field" in signature:
        trainer_params["dataset_text_field"] = "text"

    return SFTTrainer(**_filter_kwargs(SFTTrainer, trainer_params))


def write_run_metadata(
    path: Path,
    *,
    config: TrainingConfig,
    run_id: str,
    train_path: Path,
    val_path: Path | None,
    train_stats: dict[str, Any],
    val_stats: dict[str, Any] | None,
    adapter_dir: Path | None,
    merged_dir: Path | None,
) -> None:
    """Записать метаданные прогона: конфиг, данные, коммит, артефакты."""
    payload = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "base_model": config.base_model,
        "train_path": str(train_path),
        "val_path": str(val_path) if val_path is not None else None,
        "dataset_sha256": dataset_hash([train_path] + ([val_path] if val_path else [])),
        "train_stats": train_stats,
        "val_stats": val_stats,
        "config": config.model_dump(mode="json"),
        "adapter_dir": str(adapter_dir) if adapter_dir is not None else None,
        "merged_dir": str(merged_dir) if merged_dir is not None else None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_training(
    config: TrainingConfig,
    args: argparse.Namespace,
    train_records: Sequence[DialogueRecord],
    val_records: Sequence[DialogueRecord],
    *,
    output_dir: Path,
) -> int:
    """Запустить QLoRA-SFT. Все тяжелые импорты находятся внутри функции."""
    from datasets import Dataset
    from unsloth import FastLanguageModel

    started = time.perf_counter()
    run_id = f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{git_commit()[:8]}"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Загрузка базовой модели {} (4-bit={})", config.base_model, config.load_in_4bit)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=config.base_model,
        max_seq_length=config.training.max_seq_len,
        dtype=None,
        load_in_4bit=config.load_in_4bit,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=config.lora.r,
        target_modules=config.lora.target_modules,
        lora_alpha=config.lora.alpha,
        lora_dropout=config.lora.dropout,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=config.training.seed,
        use_rslora=False,
    )
    FastLanguageModel.for_training(model)

    logger.info("Форматирование {} train и {} val диалогов", len(train_records), len(val_records))
    train_dataset = Dataset.from_list(
        [{"text": format_chat(record, tokenizer)} for record in train_records]
    )
    eval_dataset = (
        Dataset.from_list([{"text": format_chat(record, tokenizer)} for record in val_records])
        if val_records
        else None
    )

    trainer = build_trainer(
        model,
        tokenizer,
        config,
        output_dir=output_dir,
        run_name=run_id,
        has_eval=eval_dataset is not None,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        max_steps=args.max_steps,
    )
    logger.info("Старт обучения: run_id={} output={}", run_id, output_dir)
    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)

    adapter_dir = output_dir / DEFAULT_ADAPTER_NAME
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)
    logger.info("LoRA adapter сохранён: {}", adapter_dir)

    merged_dir: Path | None = None
    if config.merge:
        merged_dir = resolve_path(config.merged_dir or (output_dir / "merged"))
        logger.info("Merge LoRA → {}", merged_dir)
        model.save_pretrained_merged(
            str(merged_dir),
            tokenizer,
            save_method="merged_16bit",
        )

    metadata_path = output_dir / "run_metadata.json"
    write_run_metadata(
        metadata_path,
        config=config,
        run_id=run_id,
        train_path=resolve_path(config.datasets.train),
        val_path=resolve_path(config.datasets.val) if config.datasets.val else None,
        train_stats=dataset_stats(train_records),
        val_stats=dataset_stats(val_records) if val_records else None,
        adapter_dir=adapter_dir,
        merged_dir=merged_dir,
    )
    elapsed = time.perf_counter() - started
    logger.info("Обучение завершено за {:.1f} мин; метаданные: {}", elapsed / 60, metadata_path)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI."""
    args = parse_args(argv)
    configure_logging()

    try:
        config = load_training_config(args.config)
        if args.merge:
            config = config.model_copy(update={"merge": True})
        train_path = resolve_path(config.datasets.train)
        val_path = resolve_path(config.datasets.val) if config.datasets.val else None
        train_records = load_dialogues(train_path, limit=args.limit)
        val_records: list[DialogueRecord] = []
        if val_path is not None and val_path.exists():
            val_records = load_dialogues(val_path, limit=args.limit)
        elif val_path is not None:
            logger.warning("Validation-файл не найден: {}; обучение без eval", val_path)
    except (TrainingConfigError, FileNotFoundError, ValueError, ValidationError) as exc:
        logger.error("Не удалось подготовить обучение: {}", exc)
        return 1

    output_dir = resolve_path(args.output_dir or config.output_dir)
    train_stats = dataset_stats(train_records)
    val_stats = dataset_stats(val_records) if val_records else None
    logger.info(
        "Конфиг: {} | train: {} | val: {} | output: {}",
        args.config,
        train_stats["records"],
        val_stats["records"] if val_stats else 0,
        output_dir,
    )

    if args.dry_run:
        logger.info("--- train stats: {}", json.dumps(train_stats, ensure_ascii=False))
        if val_stats:
            logger.info("--- val stats: {}", json.dumps(val_stats, ensure_ascii=False))
        for index, record in enumerate(train_records[: args.preview_count], start=1):
            logger.info(
                "--- ChatML preview {}/{} | id={} | topic={} ---\n{}",
                index,
                min(args.preview_count, len(train_records)),
                record.id,
                record.topic,
                render_chatml_preview(record),
            )
        logger.info(
            "--dry-run: обучение не запускалось, файлы не записывались; "
            "токенизатор и GPU не загружались"
        )
        return 0

    try:
        return run_training(
            config,
            args,
            train_records,
            val_records,
            output_dir=output_dir,
        )
    except ImportError as exc:
        logger.error(
            "Training-зависимости не установлены ({}). "
            "Установите requirements-train.txt на GPU-сервере.",
            exc,
        )
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        logger.exception("Обучение прервано: {}", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
