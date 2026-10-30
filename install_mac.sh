#!/usr/bin/env bash
# Dharma Studio — one-shot install on the Mac mini.
#   git clone ... ~/apps/dharma-studio && cd ~/apps/dharma-studio && ./install_mac.sh
# Needs: python3 (3.11+; 3.13 recommended, `brew install python@3.13`), node 20+ for the frontend (optional).
set -euo pipefail
cd "$(dirname "$0")"

# pip's macOS "truststore" crashes when Python cannot read the macOS version (platform.mac_ver() == ''),
# which kills ensurepip and every pip install. Use pip's classic certificate handling instead.
export PIP_USE_DEPRECATED=legacy-certs
export SYSTEM_VERSION_COMPAT=0

# If uv is installed (brew install uv) it builds the venv without pip at all - the most robust path.
if command -v uv >/dev/null 2>&1 && [ ! -x .venv/bin/python ]; then
  echo "== venv (uv)"
  uv venv --python 3.13 .venv || uv venv .venv
  uv pip install --python .venv/bin/python pip
fi

# Pick a Python that can build a working venv. Prefer 3.13/3.12 (Homebrew's 3.14 can fail at ensurepip).
make_venv() {
  local py="$1"
  command -v "$py" >/dev/null 2>&1 || return 1
  "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null || return 1
  rm -rf .venv
  if "$py" -m venv .venv 2>/dev/null && [ -x .venv/bin/pip ]; then return 0; fi
  # ensurepip failed: build the venv without pip and bootstrap pip from PyPI
  rm -rf .venv
  "$py" -m venv --without-pip .venv 2>/dev/null || return 1
  curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py && .venv/bin/python /tmp/get-pip.py -q || { rm -rf .venv; return 1; }
  [ -x .venv/bin/pip ]
}

echo "== venv"
if [ -x .venv/bin/pip ] && .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  echo "using existing .venv ($(.venv/bin/python --version))"
else
  ok=""
  for py in ${PYTHON:-} python3.13 python3.12 python3.11 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 python3; do
    [ -n "$py" ] || continue
    if make_venv "$py"; then ok="$py"; break; fi
  done
  if [ -z "$ok" ]; then
    echo "Could not create a Python virtualenv. Run: brew install python@3.13   then ./install_mac.sh again"; exit 1
  fi
  echo "venv created with $ok ($(.venv/bin/python --version))"
fi
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
