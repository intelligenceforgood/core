#!/bin/bash
set -e

echo "=========================================="
echo "  I4G Local — All-in-One Container"
echo "=========================================="
echo ""
echo "  Core API:  http://localhost:8000"
echo "  SSI  API:  http://localhost:8100"
echo "  Console:   http://localhost:3000"
echo "  Ollama:    http://localhost:11434"
echo ""
echo "  LLM: Ollama (tinyllama — small test model)"
echo "  Embeddings: all-minilm (45MB)"
echo "  Auth: mock (no login required)"
echo "  DB: SQLite (pre-loaded from backup)"
echo "  Browser: Playwright + Chromium (headless)"
echo ""
echo "=========================================="

# Apply any migrations newer than the baked-in backup
echo "Checking database migrations..."
cd /app/core && alembic upgrade head 2>&1 || echo "WARN: alembic upgrade skipped (non-fatal)"
echo ""

exec supervisord -n -c /etc/supervisor/conf.d/i4g.conf
