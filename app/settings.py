"""Настройки API локальной GGUF-модели (T-022).

Как и остальные конфиги проекта, читаются через pydantic-settings из `.env`;
`os.getenv` не используется (RULES §3).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from configs.settings import PROJECT_ROOT

#: Путь к основной Q4_K_M-модели, полученной в T-018.
DEFAULT_MODEL_PATH = PROJECT_ROOT / "data" / "gguf" / "qwen3-8b-vet-Q4_K_M.gguf"

#: Имя модели по умолчанию в ответах OpenAI-совместимого API.
DEFAULT_MODEL_ID = "qwen3-8b-vet"


class AppSettings(BaseSettings):
    """Параметры загрузки GGUF-модели и генерации."""

    model_config = SettingsConfigDict(
        env_prefix="VET_API_",
        env_file=(".env", str(PROJECT_ROOT / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    model_path: Path = Field(default=DEFAULT_MODEL_PATH, description="Путь к GGUF-файлу")
    model_id: str = Field(
        default=DEFAULT_MODEL_ID,
        min_length=1,
        description="Имя модели в ответах API",
    )
    n_ctx: int = Field(default=8192, ge=512, description="Размер контекста llama.cpp")
    n_threads: int | None = Field(default=None, ge=1, description="Потоки CPU (None — авто)")
    n_gpu_layers: int = Field(default=0, ge=0, description="Слоёв на GPU (0 — только CPU)")
    chroma_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "chroma_db",
        description="Папка локальной ChromaDB",
    )
    chroma_collection: str = Field(
        default="msd_vet_manual",
        min_length=1,
        description="Имя коллекции ChromaDB",
    )
    embedding_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        min_length=1,
        description="Модель эмбеддингов sentence-transformers",
    )
    rag_top_k: int = Field(default=3, ge=1, le=10, description="Сколько чанков извлекать")


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    """Вернуть настройки API (кеш на процесс)."""
    # Значения приходят из окружения, а не из аргументов конструктора.
    return AppSettings()
