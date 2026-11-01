"""Конфигурация SFT/QLoRA-обучения (T-015).

Конфиг хранится отдельно от `settings.py`: это параметры эксперимента, а не
секреты окружения. Загрузчик намеренно не импортирует Unsloth/torch, поэтому
его можно валидировать и тестировать на машине без GPU.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from configs.settings import PROJECT_ROOT

DEFAULT_TRAINING_CONFIG = PROJECT_ROOT / "configs" / "train_sft.yaml"


class TrainingConfigError(ValueError):
    """Файл тренировочного конфига отсутствует или не проходит схему."""


class DatasetConfig(BaseModel):
    """Пути к train/validation JSONL с диалогами."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    train: Path = Field(default=PROJECT_ROOT / "data" / "train.jsonl")
    val: Path | None = Field(default=PROJECT_ROOT / "data" / "val.jsonl")


class LoRAConfig(BaseModel):
    """Параметры LoRA-адаптера."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    r: int = Field(default=16, ge=1)
    alpha: int = Field(default=32, ge=1)
    dropout: float = Field(default=0.05, ge=0.0, le=1.0)
    target_modules: list[str] = Field(
        default_factory=lambda: [
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ]
    )

    @field_validator("target_modules")
    @classmethod
    def _non_empty_modules(cls, modules: list[str]) -> list[str]:
        cleaned = [module.strip() for module in modules]
        if not cleaned or any(not module for module in cleaned):
            raise ValueError("target_modules не должен быть пустым")
        return cleaned


class TrainingParams(BaseModel):
    """Гиперпараметры QLoRA из Design §4."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    epochs: float = Field(default=2.0, gt=0.0)
    lr: float = Field(default=2.0e-4, gt=0.0)
    lr_scheduler: Literal["cosine", "linear", "constant"] = "cosine"
    warmup_ratio: float = Field(default=0.03, ge=0.0, le=1.0)
    per_device_batch_size: int = Field(default=2, ge=1)
    grad_accum: int = Field(default=8, ge=1)
    max_seq_len: int = Field(default=4096, ge=128)
    bf16: bool = True
    neftune_alpha: float = Field(default=5.0, ge=0.0)
    packing: bool = False
    logging_steps: int = Field(default=10, ge=1)
    eval_steps: int = Field(default=50, ge=1)
    save_steps: int = Field(default=50, ge=1)
    save_total_limit: int = Field(default=2, ge=1)
    seed: int = 3407
    optim: str = "adamw_8bit"
    report_to: str = "none"


class TrainingConfig(BaseModel):
    """Полный конфиг запуска SFT."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_model: str = Field(default="Qwen/Qwen3-8B", min_length=1)
    method: Literal["qlora"] = "qlora"
    load_in_4bit: bool = True
    datasets: DatasetConfig = Field(default_factory=DatasetConfig)
    lora: LoRAConfig = Field(default_factory=LoRAConfig)
    training: TrainingParams = Field(default_factory=TrainingParams)
    output_dir: Path = Field(default=PROJECT_ROOT / "outputs" / "sft_qwen3_8b")
    merged_dir: Path | None = None
    merge: bool = False


def load_training_config(path: Path = DEFAULT_TRAINING_CONFIG) -> TrainingConfig:
    """Прочитать YAML-конфиг и провалидировать все параметры.

    Raises:
        TrainingConfigError: файл не найден, не является YAML-объектом или
            не проходит схему Pydantic.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise TrainingConfigError(f"конфиг обучения не найден: {path}") from exc

    try:
        payload = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise TrainingConfigError(f"некорректный YAML в {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise TrainingConfigError(f"{path}: ожидался YAML-объект на верхнем уровне")

    try:
        return TrainingConfig.model_validate(payload)
    except ValueError as exc:
        raise TrainingConfigError(f"{path}: {exc}") from exc


def resolve_path(path: Path) -> Path:
    """Разрешить относительный путь от корня репозитория."""
    return path if path.is_absolute() else PROJECT_ROOT / path
