# Короткие команды для GPU-сервера.
# Перед запуском активируйте venv: source .venv/bin/activate

.PHONY: smoke train merge

# 5-минутная проверка Unsloth/CUDA и всего training-пайплайна.
smoke:
	python scripts/train_sft.py --limit 20 --max-steps 10

# Полное SFT/QLoRA-обучение по configs/train_sft.yaml.
train:
	python scripts/train_sft.py

# Merge LoRA adapter в merged 16-bit HF-модель.
merge:
	python scripts/merge_lora.py
