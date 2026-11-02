# syntax=docker/dockerfile:1
# Образ VetAssistant: FastAPI и Streamlit UI используют одни зависимости.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CMAKE_BUILD_PARALLEL_LEVEL=2 \
    CMAKE_ARGS="-DGGML_NATIVE=OFF"

WORKDIR /app

# build-essential/cmake нужны для сборки llama-cpp-python, libgomp1 — runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Сначала зависимости и код пакета — слой кешируется при изменении скриптов.
COPY pyproject.toml README.md ./
COPY app ./app
COPY configs ./configs
COPY data_pipeline ./data_pipeline
COPY evaluation ./evaluation

# CPU-сборка torch без CUDA-зависимостей; llama.cpp собирается без -march=native.
RUN python -m pip install --upgrade pip \
    && python -m pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install .

COPY scripts ./scripts

RUN mkdir -p /app/data

EXPOSE 8000 8501

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
