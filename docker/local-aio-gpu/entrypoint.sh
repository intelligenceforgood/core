#!/bin/bash
set -e

echo "=========================================="
echo "  I4G Local — All-in-One (GPU)"
echo "=========================================="
echo ""
echo "  Core API:  http://localhost:8000"
echo "  SSI  API:  http://localhost:8100"
echo "  Console:   http://localhost:3000"
echo "  Ollama:    http://localhost:11434"
echo ""
echo "  LLM: Ollama ($I4G_LLM__CHAT_MODEL)"
echo "  Embeddings: $I4G_VECTOR__EMBED_MODEL"
echo "  Auth: mock (no login required)"
echo "  DB: SQLite (pre-loaded from backup)"
echo "  Browser: Playwright + Chromium (headless)"
echo ""

# Check for GPU availability
if command -v nvidia-smi &>/dev/null; then
    echo "  GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'detected but query failed')"
    echo "  VRAM: $(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null || echo 'unknown')"
else
    echo "  GPU: NOT DETECTED — Ollama will fall back to CPU"
    echo "       Run with: docker run --gpus all ..."
fi
echo ""
echo "=========================================="

# Apply any migrations newer than the baked-in backup
echo "Checking database migrations..."
cd /app/core && alembic upgrade head 2>&1 || echo "WARN: alembic upgrade skipped (non-fatal)"
echo ""

exec supervisord -n -c /etc/supervisor/conf.d/i4g.conf
