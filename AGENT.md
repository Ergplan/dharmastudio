# Brief for the local agent (Claude Code on the Mac mini)

You are continuing **Dharma Studio** at `~/apps/dharma-studio`. Read `SPEC.md` (the contract), `engine/art_direction.md`
(the look), and `README.md` (how to run). The author is Rachit Agarwal (Rishikesh Studio); the book is
*The Cycle of Dharma*. Keys live in `.env` only.

## Rules that never bend
1. No image is generated for a panel whose characters are not all locked (409 from the API; the UI shows why).
2. In **shards** mode image models never draw text: every caption, balloon, title is typeset by the layout (the only
   in-image glyphs permitted are राम on Agastya's arrow). In **painted-page** mode (Volume 1's default since
   2026-10-31) the image model letters the page itself, so every box text must be a verbatim manuscript excerpt of at
   most 14 words, and the critic's transcription must match every box exactly with no extra text — else the page is
   repainted (≤ 2) and flagged; never auto-approved. The house style is `engine/director/painted.py` HOUSE_STYLE, verbatim.
3. Captions are the book's sentences unless the author edits them in Script.
4. Every candidate keeps its full prompt + feedback (ledger and reproducibility).
5. Approved pages are frozen; the PDF is assembled from approved page artifacts only.
6. Proportion rule in every prompt: one scale per panel; no giants unless the book says so.

## Running
```
cd ~/apps/dharma-studio && ./install_mac.sh          # once
./scripts/dev.sh                                      # backend on :8787, serves frontend/dist
cd frontend && npm run dev                            # optional: hot-reload UI on :5173
python -m backend.seed                                # Chapter 1 + Rama lock + canvases (idempotent)
pytest -q
```

## Where things are
- `backend/` FastAPI (api.py routes, models.py, jobs.py worker, render.py, seed.py)
- `engine/` the comic engine: `comic/visual_logic.py` (dials), `comic/layout.py` (shards, captions, canvases, PDF),
  `comic/script.py` (prompt recipe), `providers.py` (Sunburst, Gemini, Topaz), `llm.py` (Claude/OpenAI router),
  `agents.py` (panel_script, hindi_draft, scene_rewrite, silhouette_prompt, cast_proposal)
- `frontend/` Vite + React + TS; `npm run build` → `frontend/dist`
- `data/` studio.db, media, canvases, artifacts, exports (never committed)

## Open work, in priority order
1. Lock Hanuman, Ravana, Vibhishana, Lakshmana with the author (Characters screen → generate refs → approve → lock),
   then regenerate their Chapter 1 panels.
2. Shard editor polish: snapping, multi-select, copy shape to another page.
3. Silhouette library seeding: 40 marginalia (bows, maces, lotus, compass roses, Lanka map, Trikuta, chariot,
   Hanuman in flight, Devanagari verse fragments) — ink on white, auto-keyed.
4. Critic role: QA each candidate (faces/limbs/heads count, text present, proportion) and sort candidates by score.
5. Volume 2/3 canvases (iron, glass) with their caption styles.
6. Hindi: translator review flow (hi_is_draft → reviewed), Mukta/Noto sizes per canvas.
7. Export: PDF/X-1a-ish flattening via Ghostscript if the printer needs it; spreads option (2-up).

## Working style
Small commits with clear messages. Run `pytest -q` before each commit. Never put keys in code or the DB.
When the author gives feedback on a panel, put it in the panel's feedback box in the app (so it is recorded with
the candidate), not in a prompt file.
