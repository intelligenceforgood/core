# syntax=docker/dockerfile:1

FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    I4G_RUNTIME__PROJECT_ROOT=/app

WORKDIR /app

# System deps required by scientific Python stack and paddleocr runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    tesseract-ocr \
    libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata
COPY pyproject.toml README.md VERSION.txt LICENSE ./

# Pre-install heavy dependencies to leverage Docker cache
# This layer will be cached unless pyproject.toml changes
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir \
    "paddlepaddle" \
    "paddleocr>=2.7" \
    "faiss-cpu" \
    "langchain" \
    "google-cloud-aiplatform" \
    "google-cloud-storage"

# Copy source code (invalidates cache only if source changes)
COPY src ./src
COPY docker/fixtures/mock ./data/artifacts/mock

# Install the local package and remaining dependencies
RUN python -m pip install --no-cache-dir .

# Copy mock artifacts
COPY docker/fixtures/mock /app/data/artifacts/mock

# Cloud Run defaults to non-root user 65532; ensure writable artifact dirs
RUN mkdir -p /app/data \
    && chown -R 65532:65532 /app/data

ENV PORT=8080 \
    I4G_ENV=dev

USER 65532:65532

CMD ["uvicorn", "i4g.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
