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

#: Адрес API по умолчанию для Streamlit UI (локальный запуск).
DEFAULT_UI_API_URL = "http://127.0.0.1:8000/v1/chat/completions"

#: Таймаут HTTP-запроса UI к API по умолчанию.
DEFAULT_UI_TIMEOUT_S = 300.0

#: Размер контекста llama.cpp по умолчанию.
#: 4096 экономит RAM на CPU-инференсе; при OOM снижайте до 2048.
DEFAULT_N_CTX = 4096

#: Локальная async-SQLite БД по умолчанию; Docker Compose переопределяет на PostgreSQL.
DEFAULT_DATABASE_URL = (
    f"sqlite+aiosqlite:///{(PROJECT_ROOT / 'data' / 'vetassistant.db').as_posix()}"
)


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
    n_ctx: int = Field(default=DEFAULT_N_CTX, ge=512, description="Размер контекста llama.cpp")
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
    database_url: str = Field(
        default=DEFAULT_DATABASE_URL,
        min_length=1,
        description="SQLAlchemy async URL (PostgreSQL/asyncpg или SQLite/aiosqlite)",
    )
    jwt_secret: str = Field(
        default="dev-insecure-jwt-secret-change-me",
        min_length=16,
        description="Секрет подписи JWT (обязательно заменить в production)",
    )
    access_token_expire_minutes: int = Field(
        default=60 * 24 * 7,
        ge=1,
        description="Срок жизни access-токена, минуты",
    )
    allow_public_registration: bool = Field(
        default=True,
        description=(
            "Разрешить публичную регистрацию; в production обычно false"
        ),
    )


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    """Вернуть настройки API (кеш на процесс)."""
    # Значения приходят из окружения, а не из аргументов конструктора.
    return AppSettings()


class UISettings(BaseSettings):
    """Параметры Streamlit UI; в Docker позволяют указать адрес API-сервиса."""

    model_config = SettingsConfigDict(
        env_prefix="VET_UI_",
        env_file=(".env", str(PROJECT_ROOT / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    api_url: str = Field(
        default=DEFAULT_UI_API_URL,
        min_length=1,
        description="Полный URL /v1/chat/completions",
    )
    model_id: str = Field(
        default=DEFAULT_MODEL_ID,
        min_length=1,
        description="Имя модели в запросах UI",
    )
    timeout_s: float = Field(
        default=DEFAULT_UI_TIMEOUT_S,
        gt=0,
        description="Таймаут запроса к API, секунды",
    )


@lru_cache(maxsize=1)
def get_ui_settings() -> UISettings:
    """Вернуть настройки UI (кеш на процесс)."""
    return UISettings()
