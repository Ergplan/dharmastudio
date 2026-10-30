#!/usr/bin/env bash
# Dharma Studio backend, dev mode (auto-reload). Run from the repo root: scripts/dev.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || { echo "no .venv — run ./install_mac.sh first"; exit 1; }
[ -f data/studio.db ] || $PY -m backend.seed
.venv/bin/python -m backend.book_seed >/dev/null 2>&1 || true
exec .venv/bin/uvicorn backend.api:app --host 127.0.0.1 --port "${PORT:-8787}" --reload --reload-dir backend --reload-dir engine
