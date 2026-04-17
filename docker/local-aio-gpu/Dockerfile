#
# I4G All-in-One Local Image — NVIDIA GPU Variant
# Target hardware: Linux x86_64, 64 GB RAM, NVIDIA RTX 4090 (24 GB VRAM)
#
# Bundles: Core API (:8000) + SSI API (:8100) + UI Console (:3000) + Ollama (:11434)
# Pre-loaded with SQLite + Chroma data, Ollama models, Playwright + system Chromium.
# No external services required — GPU-accelerated Ollama LLM, mock identity, local storage.
#
# Build from the i4g/ workspace root:
#   docker build -f core/docker/local-aio-gpu/Dockerfile -t i4g-local-gpu .
#
# Run (requires NVIDIA Container Toolkit):
#   docker run --gpus all -p 3000:3000 -p 8000:8000 -p 8100:8100 i4g-local-gpu
#
# Ships with small models to keep the image size down for transfer:
#   Chat:       tinyllama     (~637 MB)
#   Embeddings: all-minilm    (~45 MB)
#
# After loading, upgrade to GPU-optimized models on the target machine:
#   docker exec i4g ollama pull llama3.1:8b       # ~4.7 GB, recommended
#   docker exec i4g ollama pull nomic-embed-text  # ~274 MB, recommended
# Then restart with -e I4G_LLM__CHAT_MODEL=llama3.1:8b (see runbook).

# ── Stage 1: Build UI ────────────────────────────────────────────────
FROM node:20-bullseye-slim AS ui-build

ENV PNPM_HOME="/pnpm" PATH="$PNPM_HOME:$PATH"
RUN corepack enable
WORKDIR /app

# Install deps (cached unless lockfile changes)
COPY ui/pnpm-lock.yaml ui/pnpm-workspace.yaml ui/package.json ui/turbo.json ui/tsconfig.base.json ./
COPY ui/packages/ui-kit/package.json packages/ui-kit/package.json
COPY ui/packages/sdk/package.json packages/sdk/package.json
COPY ui/packages/tokens/package.json packages/tokens/package.json
COPY ui/apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile

# Copy full source and build
COPY ui/ .

# Point UI at container-internal services
ENV I4G_API_URL=http://127.0.0.1:8000 \
    I4G_API_KEY=dev-analyst-token \
    I4G_API_KIND=core \
    NEXT_PUBLIC_FEEDBACK_ENABLED=true \
    SSI_API_URL=http://127.0.0.1:8100 \
    NEXT_PUBLIC_SSI_WS_URL=ws://127.0.0.1:8100

RUN pnpm --filter web build

# ── Stage 2: Python backend (core + ssi) ─────────────────────────────
# Build on the same Ubuntu 22.04 base so glibc (2.35) matches the CUDA runtime stage.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS python-deps

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 DEBIAN_FRONTEND=noninteractive

WORKDIR /build

# Install Python 3.11 from deadsnakes + build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common gpg-agent \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev \
    build-essential \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    tesseract-ocr libtesseract-dev \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 \
    libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info \
    fonts-liberation fonts-noto-cjk libzbar0 \
    && rm -rf /var/lib/apt/lists/*

# Bootstrap pip and set python3.11 as default
RUN python3.11 -m ensurepip --upgrade \
    && python3.11 -m pip install --upgrade pip \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# Pre-install heavy shared deps
RUN python -m pip install --no-cache-dir \
    "paddlepaddle" \
    "paddleocr>=2.7" \
    "faiss-cpu" \
    "langchain" \
    "weasyprint"

# Install core
COPY core/pyproject.toml core/README.md core/VERSION.txt core/LICENSE /build/core/
COPY core/src /build/core/src
RUN python -m pip install --no-cache-dir /build/core

# Install ssi
COPY ssi/pyproject.toml ssi/README.md ssi/VERSION.txt ssi/LICENSE /build/ssi/
COPY ssi/src /build/ssi/src
RUN python -m pip install --no-cache-dir /build/ssi

# ── Stage 3: Final runtime (NVIDIA CUDA base for GPU acceleration) ───
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS runtime

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DEBIAN_FRONTEND=noninteractive

# System runtime libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    # core: paddleocr + tesseract runtime
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    tesseract-ocr \
    # ssi: weasyprint + zbar runtime
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 \
    libgdk-pixbuf-2.0-0 shared-mime-info \
    fonts-liberation fonts-noto-cjk libzbar0 \
    # ssi: system Chromium for zendriver (undetected Chrome via CDP)
    chromium-browser \
    # node.js + misc
    curl zstd ca-certificates gnupg \
    # supervisor to run all services
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Copy Python 3.11 + all installed packages from the build stage.
# deadsnakes installs to /usr/lib/python3.11 and /usr/local/lib/python3.11.
COPY --from=python-deps /usr/bin/python3.11 /usr/bin/python3.11
COPY --from=python-deps /usr/lib/python3.11 /usr/lib/python3.11
COPY --from=python-deps /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=python-deps /usr/local/bin /usr/local/bin
RUN ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && ldconfig

# Install Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g pnpm@9 \
    && rm -rf /var/lib/apt/lists/*

# Install Ollama (auto-detects CUDA at runtime via NVIDIA Container Toolkit)
RUN curl -fsSL https://ollama.com/install.sh | sh

# Pre-pull small models to keep image size down (upgrade on target machine).
# tinyllama (637 MB chat) + all-minilm (45 MB embeddings)
RUN ollama serve & \
    sleep 5 && \
    ollama pull tinyllama && \
    ollama pull all-minilm && \
    kill %1 || true

# Install Playwright Chromium (with system deps) for SSI browser capture
RUN python -m playwright install chromium --with-deps

# ── Core setup ──
WORKDIR /app/core
COPY core/config ./config
COPY core/templates ./templates
COPY core/alembic.ini ./alembic.ini
COPY core/src ./src
COPY core/pyproject.toml core/README.md core/VERSION.txt core/LICENSE ./

# ── SSI setup ──
WORKDIR /app/ssi
COPY ssi/config ./config
COPY ssi/templates ./templates
COPY ssi/src ./src
COPY ssi/pyproject.toml ssi/README.md ssi/VERSION.txt ssi/LICENSE ./

# ── UI setup (built output from stage 1) ──
WORKDIR /app/ui
COPY --from=ui-build /app/apps/web/.next ./apps/web/.next
COPY --from=ui-build /app/apps/web/public ./apps/web/public
COPY --from=ui-build /app/apps/web/next.config.ts ./apps/web/next.config.ts
COPY --from=ui-build /app/apps/web/package.json ./apps/web/package.json
COPY --from=ui-build /app/node_modules ./node_modules
COPY --from=ui-build /app/apps/web/node_modules ./apps/web/node_modules
COPY --from=ui-build /app/package.json ./package.json
COPY --from=ui-build /pnpm /pnpm

# ── Data: restore backup (SQLite + Chroma) ──
WORKDIR /app/core
RUN mkdir -p /app/core/data
COPY core/data/backups/backup_local_20260409T233135Z.tar.gz /tmp/backup.tar.gz
RUN tar xzf /tmp/backup.tar.gz -C /app/core/data && rm /tmp/backup.tar.gz

# ── Supervisor + entrypoint ──
COPY core/docker/local-aio-gpu/supervisord.conf /etc/supervisor/conf.d/i4g.conf
COPY core/docker/local-aio-gpu/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ── Environment: fully local, GPU-accelerated Ollama ──
ENV I4G_ENV=local \
    I4G_RUNTIME__PROJECT_ROOT=/app/core \
    # Core LLM: Ollama (ships with tinyllama — upgrade to llama3.1:8b after loading)
    I4G_LLM__PROVIDER=ollama \
    I4G_LLM__CHAT_MODEL=tinyllama \
    I4G_LLM__OLLAMA_BASE_URL=http://127.0.0.1:11434 \
    I4G_VECTOR__EMBED_MODEL=all-minilm \
    I4G_IDENTITY__PROVIDER=mock \
    I4G_STORAGE__STRUCTURED_BACKEND=sqlite \
    I4G_VECTOR__BACKEND=chroma \
    I4G_API__CORS_ORIGINS='["*"]' \
    # SSI LLM: Ollama (GPU-accelerated)
    SSI_ENV=local \
    SSI_PROJECT_ROOT=/app/ssi \
    SSI_LLM__PROVIDER=ollama \
    SSI_LLM__MODEL=tinyllama \
    SSI_LLM__OLLAMA_BASE_URL=http://127.0.0.1:11434 \
    SSI_INTEGRATION__CORE_API_URL=http://127.0.0.1:8000 \
    SSI_INTEGRATION__PUSH_TO_CORE=false \
    # SSI Browser: Playwright + zendriver (sandbox off — running as root)
    SSI_BROWSER__SANDBOX=false \
    SSI_BROWSER__HEADLESS=true \
    SSI_ZEN_BROWSER__CHROME_BINARY=/usr/bin/chromium-browser \
    SSI_ZEN_BROWSER__HEADLESS=true \
    SSI_PROXY__ENABLED=false \
    SSI_API__REQUIRE_AUTH=false \
    SSI_EVIDENCE__STORAGE_BACKEND=local \
    SSI_STORAGE__BACKEND=sqlite \
    SSI_STORAGE__DB_URL=sqlite:////app/core/data/i4g_store.db \
    # UI proxy env
    I4G_API_URL=http://127.0.0.1:8000 \
    I4G_API_KEY=dev-analyst-token \
    I4G_API_KIND=core \
    SSI_API_URL=http://127.0.0.1:8100 \
    NEXT_PUBLIC_SSI_WS_URL=ws://127.0.0.1:8100 \
    PNPM_HOME="/pnpm" \
    PATH="/pnpm:$PATH" \
    NODE_ENV=production \
    # NVIDIA runtime: ensure GPU is visible to Ollama
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

EXPOSE 3000 8000 8100 11434

ENTRYPOINT ["/entrypoint.sh"]
