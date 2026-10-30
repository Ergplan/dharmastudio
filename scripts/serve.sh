#!/usr/bin/env bash
# Dharma Studio, production mode on the Mac mini (no reload). Open http://localhost:8787
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f data/studio.db ] || .venv/bin/python -m backend.seed
exec .venv/bin/uvicorn backend.api:app --host 127.0.0.1 --port "${PORT:-8787}"
