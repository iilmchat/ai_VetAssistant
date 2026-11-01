"""Тесты SFT/QLoRA-подготовки без GPU (T-015).

`train_sft.py --dry-run` и `merge_lora.py --dry-run` не должны импортировать
Unsloth/torch. Проверяем конфиг, парсинг диалогов, ChatML-превью и CLI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from configs.training import TrainingConfig, load_training_config
from data_pipeline.dataset_io import write_jsonl
from data_pipeline.schemas import DialogueRecord
from scripts.merge_lora import main as merge_main
from scripts.train_sft import (
    dataset_stats,
    format_chat,
    load_dialogues,
    render_chatml_preview,
)
from scripts.train_sft import (
    main as train_main,
)

MESSAGES = [
    {"role": "user", "content": "Кот не ест второй день, что делать?"},
    {"role": "assistant", "content": "Сколько коту лет и как давно он не ест?"},
    {"role": "user", "content": "Два года, второй день."},
    {"role": "assistant", "content": "Покажите кота ветеринару в ближайшие сутки."},
]


def _dialogue_payload(record_id: str = "bulk-0001") -> dict[str, Any]:
    return {
        "id": record_id,
        "stage": "B",
        "topic": "gastroenterology",
        "messages": MESSAGES,
        "model": "fake-model",
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
        "latency_s": 0.01,
        "attempts": 1,
        "prompts_version": 4,
        "generated_at": "2026-01-01T00:00:00Z",
    }


def _write_dialogues(path: Path, count: int = 2) -> Path:
    write_jsonl(
        path,
        [_dialogue_payload(f"bulk-{index:04d}") for index in range(1, count + 1)],
    )
    return path


def _write_config(path: Path, train: Path, val: Path | None) -> Path:
    payload: dict[str, Any] = {
        "base_model": "fake/Qwen3-test",
        "datasets": {
            "train": str(train),
            "val": str(val) if val is not None else None,
        },
        "output_dir": str(path.parent / "output"),
        "merge": False,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class _FakeTokenizer:
    """Минимальный двойник chat template Qwen без transformers."""

    eos_token = "<|endoftext|>"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def apply_chat_template(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append({"messages": messages, **kwargs})
        return "\n".join(
            f"<|im_start|>{message['role']}\n{message['content']}<|im_end|>" for message in messages
        )


def test_load_training_config_and_defaults() -> None:
    config = load_training_config()

    assert isinstance(config, TrainingConfig)
    assert config.base_model == "Qwen/Qwen3-8B"
    assert config.lora.r == 16
    assert config.training.max_seq_len == 4096
    assert config.training.packing is False


def test_training_config_rejects_invalid_lora(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        "base_model: Qwen/Qwen3-8B\nlora:\n  r: 0\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="r"):
        load_training_config(path)


def test_load_dialogues_validates_and_limits(tmp_path: Path) -> None:
    path = _write_dialogues(tmp_path / "train.jsonl", count=3)

    records = load_dialogues(path, limit=2)

    assert [record.id for record in records] == ["bulk-0001", "bulk-0002"]
    assert isinstance(records[0], DialogueRecord)


def test_load_dialogues_rejects_broken_record(tmp_path: Path) -> None:
    path = tmp_path / "broken.jsonl"
    path.write_text(json.dumps({"id": "broken"}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="валидацию"):
        load_dialogues(path)


def test_render_chatml_preview_contains_dialogue() -> None:
    record = DialogueRecord.model_validate(_dialogue_payload())

    text = render_chatml_preview(record)

    assert "<|im_start|>user" in text
    assert "<|im_start|>assistant" in text
    assert "ветеринару" in text
    assert text.count("<|im_end|>") == 4


def test_format_chat_uses_template_and_eos() -> None:
    record = DialogueRecord.model_validate(_dialogue_payload())
    tokenizer = _FakeTokenizer()

    text = format_chat(record, tokenizer)

    assert tokenizer.calls[0]["tokenize"] is False
    assert tokenizer.calls[0]["add_generation_prompt"] is False
    assert tokenizer.calls[0]["enable_thinking"] is False
    assert tokenizer.calls[0]["messages"][0]["role"] == "user"
    assert text.endswith(tokenizer.eos_token)


def test_dataset_stats() -> None:
    records = [
        DialogueRecord.model_validate(_dialogue_payload("bulk-0001")),
        DialogueRecord.model_validate(
            {
                **_dialogue_payload("bulk-0002"),
                "topic": "dermatology",
            }
        ),
    ]

    stats = dataset_stats(records)

    assert stats["records"] == 2
    assert stats["messages_min"] == 4
    assert stats["messages_max"] == 4
    assert stats["topics"] == {"dermatology": 1, "gastroenterology": 1}
    assert stats["assistant_chars"] > 0


def test_train_sft_dry_run_does_not_need_gpu(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    train = _write_dialogues(tmp_path / "train.jsonl", count=2)
    val = _write_dialogues(tmp_path / "val.jsonl", count=1)
    config = _write_config(tmp_path / "train.yaml", train, val)

    exit_code = train_main(
        [
            "--config",
            str(config),
            "--dry-run",
            "--limit",
            "1",
            "--preview-count",
            "1",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "ChatML preview" in captured
    assert "обучение не запускалось" in captured
    assert "bulk-0001" in captured
    assert not (tmp_path / "output").exists()


def test_train_sft_missing_data_returns_one(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(
        tmp_path / "train.yaml",
        tmp_path / "absent.jsonl",
        None,
    )

    exit_code = train_main(["--config", str(config), "--dry-run"])

    assert exit_code == 1
    assert "Не удалось подготовить" in capsys.readouterr().out


def test_merge_lora_dry_run_does_not_need_gpu(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(tmp_path / "train.yaml", tmp_path / "train.jsonl", None)
    adapter = tmp_path / "adapter"
    adapter.mkdir()

    exit_code = merge_main(
        [
            "--config",
            str(config),
            "--adapter-dir",
            str(adapter),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Merged output" in captured
    assert "merge не запускался" in captured


def test_merge_lora_missing_adapter_returns_one(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(tmp_path / "train.yaml", tmp_path / "train.jsonl", None)

    exit_code = merge_main(
        [
            "--config",
            str(config),
            "--adapter-dir",
            str(tmp_path / "absent-adapter"),
        ]
    )

    assert exit_code == 1
    assert "adapter не найден" in capsys.readouterr().out
