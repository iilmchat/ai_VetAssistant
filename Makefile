# Короткие команды для GPU-сервера.
# Перед запуском активируйте venv: source .venv/bin/activate

.PHONY: smoke

# 5-минутная проверка Unsloth/CUDA и всего training-пайплайна.
smoke:
	python scripts/train_sft.py --limit 20 --max-steps 10
