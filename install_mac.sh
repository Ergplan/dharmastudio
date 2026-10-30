#!/usr/bin/env bash
# Dharma Studio — one-shot install on the Mac mini.
#   git clone ... ~/apps/dharma-studio && cd ~/apps/dharma-studio && ./install_mac.sh
# Needs: python3 (3.11+; 3.13 recommended, `brew install python@3.13`), node 20+ for the frontend (optional).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "python3 >= 3.11 required (found: $($PYTHON --version 2>&1)). brew install python@3.13"; exit 1
fi

echo "== venv"
[ -d .venv ] || "$PYTHON" -m venv .venv
.venv/bin/pip install --upgrade pip >/dev/null
echo "== python deps"
.venv/bin/pip install -e ".[dev]"

echo "== PDF renderer"
# Playwright's Chromium is optional: the export falls back to the system Chrome in headless print mode
# (/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --headless --print-to-pdf).
if .venv/bin/pip install "playwright>=1.45" >/dev/null 2>&1 && .venv/bin/playwright install chromium >/dev/null 2>&1; then
  echo "playwright chromium installed"
elif [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
  echo "playwright not available; exports will use Google Chrome (headless)"
else
  echo "WARNING: no PDF renderer found. Install Google Chrome or run: .venv/bin/playwright install chromium"
fi

echo "== .env"
[ -f .env ] || { cp .env.example .env; echo "created .env — add your keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, TOPAZ_API_KEY)"; }

echo "== database + seed (Chapter 1, Rama locked, canvases)"
.venv/bin/python scripts/restore_seed_art.py
[ -f data/studio.db ] || .venv/bin/python -m backend.seed

if [ -d frontend ] && command -v npm >/dev/null 2>&1; then
  echo "== frontend"
  (cd frontend && npm install && npm run build) || echo "frontend build failed; the API still runs at http://localhost:8787/docs"
fi

echo
echo "Done. Start the studio:   scripts/serve.sh     (dev with reload: scripts/dev.sh)"
echo "Open                      http://localhost:8787"
