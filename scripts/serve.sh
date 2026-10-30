#!/usr/bin/env bash
# Dharma Studio, production mode on the Mac mini (no reload). Open http://localhost:8787
set -euo pipefail
cd "$(dirname "$0")/.."
[ -x .venv/bin/uvicorn ] || { echo "Dharma Studio is not installed yet - run ./install_mac.sh first"; exit 1; }
[ -f data/studio.db ] || .venv/bin/python -m backend.seed
exec .venv/bin/uvicorn backend.api:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8787}"
