# Dharma Studio

A local comic-production studio for *The Cycle of Dharma* (Rachit Agarwal, Rishikesh Studio). Runs on the Mac mini,
opens at <http://localhost:8787>. The spec is `SPEC.md`; the art direction is `engine/art_direction.md`.

```
backend/   FastAPI app (api.py), SQLAlchemy models (models.py), worker (jobs.py), render/gate/export (render.py),
           generation (gen.py), manuscript import (manuscript.py), seed (seed.py)
engine/    layout (shards, captions, PDF), visual logic, prompt recipe, providers (Sunburst / Gemini / Topaz),
           text agents (engine/llm.py routes Claude or OpenAI per role), canvases (procedural paper textures)
frontend/  React app (built separately; served from frontend/dist at /)
data/      studio.db, canvases/, candidates/, refs/, silhouettes/, artifacts/, exports/, enhanced/, manuscript/
```

## Run on the Mac mini

```bash
git clone <repo> ~/apps/dharma-studio && cd ~/apps/dharma-studio
./install_mac.sh          # venv, deps, Playwright Chromium (or system Chrome), .env, seed, frontend build
# put your keys in .env (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, TOPAZ_API_KEY)
scripts/serve.sh          # http://localhost:8787   (dev with auto-reload: scripts/dev.sh)
```

Without keys every provider runs in **dry-run**: Sunburst/Gemini paint Pillow placeholders, Topaz falls back to
Lanczos, the agents use rule-based fallbacks. The whole workflow (gate → generate → pick → approve → export PDF)
still runs end to end, which is how the tests work.

Keys are read from `.env` only — never stored in the database, never sent to the UI (the Project screen only sees
`true/false` per provider).

### Seed

`python -m backend.seed` (add `--reset` to start over) creates the project, three volumes (Volume 1 on Parchment),
the eight canvases with their textures, the characters from `engine/characters.yaml` (Rama locked with
`engine/refs/rama_reference.png` as his primary approved reference), Chapter 1 *The Last Night of Lanka* with pages
1–10 and 32 panels, the shapes from the auto-cut, and the 64 candidates in `data/ch1_candidates/` with the picks.

### Frontend

The React app lives in `frontend/`; `npm run build` writes `frontend/dist`, which the backend serves at `/`.
During development the Vite dev server on :5173 talks to the API on :8787 (CORS is open for it).

## API

See `SPEC.md` §4, §8 and §9 — every route is implemented under `/api/*`, images are served from `/media/*`
(paths relative to `data/`). Interactive docs at <http://localhost:8787/docs>. The response shapes are the frontend's
contract (`frontend/src/api/types.ts`, mirrored by the mock in `frontend/src/mock/server.ts`): job-starting routes
return `{job_id, job}`; a job's `progress` is 0–1 (a `{page, panel, done, total, cost_so_far}` object for a Director
batch) with a `label`; `GET /api/pages?chapter_id` embeds each page's panels and candidates, its `balance`
(`image / parchment / ink` fractions), `thumb` and `artifact`; a page's `canvas_override` is a canvas key.

Additions beyond the spec: `POST /api/pages/{id}/generate-all`, `GET /api/pages/{id}/manifest`,
`GET /api/panels/{id}/prompt`, `PUT /api/panels/{id}/candidates/{cid}` (reject), `POST /api/export/estimate`,
`POST /api/project/journey/reset`, `PUT /api/project`, `POST /api/chapters/{id}/hindi`, `GET /api/chapters/{id}`,
`DELETE` for characters/refs/silhouettes, `GET /api/fonts.css` (the embedded Devanagari fonts for the live render).
`GET /api/pages/{id}/render` takes `lang`, `paper`, `embed` and `canvas` (a key, to preview another canvas).

### Jobs

Generation, prefill, reference generation, silhouettes, cast proposal, export and the director batch run in one
background worker thread. `POST` returns the Job (202); poll `GET /api/jobs/{id}` for `status`, `log`, `progress`,
`result` and `cost_usd`. `POST /api/jobs/{id}/stop` halts a batch after the current panel.

### Export

`PUT /api/pages/{id}` with `status: "approved"` freezes the page and writes self-contained HTML artifacts (fonts,
images and the canvas texture embedded) to `data/artifacts/vol{V}/ch{C}/page-{NNN}-{en|hi}.html`.
`POST /api/export` assembles only approved pages (409 `{"unapproved": [...]}` unless `allow_partial`), renders
170×260 mm + 3 mm bleed with crop marks (`paper: "print"` = ink only on the stock; `"screen"` = with the paper
texture), optionally Topaz-upscales the selected images, and compresses the PDF (JPEG q92, soft masks kept).
PDFs land in `data/exports/` and are listed by `GET /api/exports`.

The PDF renderer is Playwright Chromium; if it is not installed the export falls back to
`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --headless --print-to-pdf`.

## Tests

```bash
.venv/bin/python -m pytest -q                 # API + engine, against a temporary data dir
.venv/bin/python -m backend.seed --reset      # then, with the server running on :8787 serving frontend/dist:
.venv/bin/python scripts/e2e_real.py          # Playwright through every screen against the real backend
```

`scripts/e2e_real.py` logs every HTTP response ≥ 400 and every console error, exits non-zero on any, and saves
`docs/screens/real_*.png`. `--reset` drops and recreates the tables in place (a running server keeps working) and
clears the generated media; `data/ch1_candidates/` and the canvas textures are kept.

They run against a temporary data directory and cover: the seed (32 panels, Rama locked), the lock gate (409 with
the unlocked names), the page render (a clipPath per panel, the Devanagari fallback, print mode), shape round-trips
and the shard palette, dry-run candidate generation and selection, the scene-rewrite fallback, the prompt recipe,
silhouettes and marginalia, the director batch (pages 1–2 end in review with candidates per panel), stop, and
approve → artifacts → a 10-page PDF export.
