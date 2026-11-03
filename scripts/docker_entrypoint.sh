#!/usr/bin/env bash
# =============================================================================
# T-110: entrypoint API-контейнера с автоматической сборкой RAG-индекса.
#
# Если VET_API_AUTO_INGEST=1 и ChromaDB ещё не содержит документов, скрипт
# строит индекс ДО запуска uvicorn. Это важно для сервера с 6 ГБ RAM:
# модель эмбеддингов не работает одновременно с загруженной 8B-моделью.
#
# Переменные:
#   VET_API_AUTO_INGEST      1 — проверять и строить индекс (по умолчанию 0)
#   VET_API_INGEST_STRICT    1 — падать при ошибке ingest (по умолчанию 0)
#   VET_API_KNOWLEDGE_DIR    статьи (по умолчанию /app/data/knowledge)
#   VET_API_CHROMA_DIR       ChromaDB (по умолчанию /app/data/chroma_db)
#   VET_API_CHROMA_COLLECTION, VET_API_EMBEDDING_MODEL
# =============================================================================
set -Eeuo pipefail

CHROMA_DIR="${VET_API_CHROMA_DIR:-/app/data/chroma_db}"
COLLECTION="${VET_API_CHROMA_COLLECTION:-msd_vet_manual}"
EMBEDDING_MODEL="${VET_API_EMBEDDING_MODEL:-sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2}"
KNOWLEDGE_DIR="${VET_API_KNOWLEDGE_DIR:-/app/data/knowledge}"
AUTO_INGEST="${VET_API_AUTO_INGEST:-0}"
INGEST_STRICT="${VET_API_INGEST_STRICT:-0}"

log() {
    printf '[entrypoint] %s\n' "$*"
}

index_ready() {
    # Быстрая проверка: без ChromaDB-файла индекса точно нет.
    if [[ ! -f "${CHROMA_DIR}/chroma.sqlite3" ]]; then
        return 1
    fi

    # Проверяем, что коллекция существует и в ней есть документы.
    CHROMA_DIR="${CHROMA_DIR}" CHROMA_COLLECTION="${COLLECTION}" \
        python - <<'PY'
import os
import sys

from chromadb import PersistentClient

try:
    collection = PersistentClient(
        path=os.environ["CHROMA_DIR"],
    ).get_collection(os.environ["CHROMA_COLLECTION"])
except Exception:
    sys.exit(1)

sys.exit(0 if collection.count() > 0 else 1)
PY
}

build_index() {
    log "ChromaDB не найдена или пуста: ${CHROMA_DIR}"

    if [[ ! -d "${KNOWLEDGE_DIR}" ]]; then
        log "ОШИБКА: каталог статей не найден: ${KNOWLEDGE_DIR}"
        return 1
    fi

    log "Строю RAG-индекс из ${KNOWLEDGE_DIR} (до запуска API)..."
    mkdir -p "${CHROMA_DIR}"
    python scripts/ingest_knowledge.py \
        --knowledge-dir "${KNOWLEDGE_DIR}" \
        --chroma-dir "${CHROMA_DIR}" \
        --collection "${COLLECTION}" \
        --embedding-model "${EMBEDDING_MODEL}"
}

if [[ "${AUTO_INGEST}" == "1" ]]; then
    if index_ready; then
        log "RAG-индекс уже готов: ${CHROMA_DIR} (ingest пропущен)."
    elif build_index; then
        log "RAG-индекс готов."
    else
        log "ОШИБКА: не удалось построить RAG-индекс."
        if [[ "${INGEST_STRICT}" == "1" ]]; then
            exit 1
        fi
        log "Продолжаю запуск API без RAG."
    fi
fi

exec "$@"
