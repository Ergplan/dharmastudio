"""Dharma Studio API (SPEC §4, §8, §9). JSON under /api/*, images under /media/*, the built frontend at /.

Response shapes follow the frontend's contract (frontend/src/api/types.ts, mirrored by frontend/src/mock/server.ts):
job-starting routes return {job_id, job}; jobs carry a numeric 0-1 progress (a page-by-page object for batches) and
a label; pages embed their panels and candidates; media paths are relative to data/ (the UI maps them to /media/).
"""

from __future__ import annotations

import io
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from engine import agents, colour, llm, providers
from engine import typography as T
from engine.canvases import CANVASES
from engine.comic import callouts as CO
from engine.comic import layout as L
from engine.comic import manuscript as MS
from engine.comic.script import STATES
from engine.settings import REPO_ROOT, settings

from . import db, gen, jobs, manuscript, render
from .models import Candidate, Canvas, Chapter, Character, CharacterRef, Job, Ledger, Page, Panel, Project, Silhouette, Volume


@asynccontextmanager
async def lifespan(_app: FastAPI):  # noqa: ANN201
    db.init_db()
    with db.session_scope() as s:
        render.ensure_canvases(s)
        render.ensure_typography(s)
        render.ensure_devotional_silhouettes(s)
        jobs.sync_models(s)
    jobs.start_worker()
    yield


app = FastAPI(title="Dharma Studio", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8787", "http://127.0.0.1:8787"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
CANVAS_SPEC = {c["key"]: c for c in CANVASES}
SUGGESTED = {1: ["parchment_painted"], 2: ["iron"], 3: ["glass"]}


def S() -> Any:  # noqa: N802
    return Depends(db.get_session)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------------
# serialisers
# ---------------------------------------------------------------------------------


def j_canvas(c: Canvas) -> dict[str, Any]:
    spec = CANVAS_SPEC.get(c.key, {})
    base = spec.get("base", (232, 214, 178))
    return {"id": c.id, "key": c.key, "name": c.name, "paper_texture": c.paper_texture, "texture_url": db.media_url(c.paper_texture), "swatch": "#%02x%02x%02x" % tuple(base),
            "ink": c.ink, "gutter": c.gutter, "caption_style": c.caption_style, "marginalia_style": c.marginalia_style, "preview": c.preview, "description": spec.get("era_hint", "")}


def j_chapter(c: Chapter, brief: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {"id": c.id, "volume_id": c.volume_id, "number": c.number, "title": c.title, "pages_from": c.pages_from, "pages_to": c.pages_to, "page_count": len(c.pages), "words": len((c.text or "").split())}
    if not brief:
        d["text"] = c.text or ""
    return d


def j_volume(v: Volume) -> dict[str, Any]:
    return {"id": v.id, "project_id": v.project_id, "number": v.number, "title": v.title, "canvas_id": v.canvas_id, "canvas_key": v.canvas.key if v.canvas else None,
            "era_default": v.era_default, "suggested_canvas_keys": SUGGESTED.get(v.number, []), "chapters": [j_chapter(c, brief=True) for c in v.chapters],
            "typography": render.volume_typography(v)}


def j_ref(r: CharacterRef) -> dict[str, Any]:
    return {"id": r.id, "character_id": r.character_id, "path": r.path, "url": db.media_url(r.path), "provider": r.provider, "prompt": r.prompt, "is_primary": r.is_primary, "approved": r.approved}


def j_character(c: Character) -> dict[str, Any]:
    return {"id": c.id, "project_id": c.project_id, "name": c.name, "form_key": c.form_key, "look": c.look, "locked": c.locked, "primary_ref_id": c.primary_ref_id, "refs": [j_ref(r) for r in c.refs]}


def j_candidate(c: Candidate) -> dict[str, Any]:
    return {"id": c.id, "panel_id": c.panel_id, "path": c.path, "url": db.media_url(c.path), "provider": c.provider, "model": c.model, "prompt_full": c.prompt_full, "feedback_used": c.feedback_used,
            "cost_usd": c.cost_usd, "created_at": c.created_at.isoformat() if c.created_at else None, "qa": c.qa or None, "rejected": c.rejected}


def j_panel(session: Session, p: Panel) -> dict[str, Any]:
    sel = next((c for c in p.candidates if c.id == p.selected_candidate_id), None)
    return {"id": p.id, "page_id": p.page_id, "n": p.n, "number": p.page.number * 100 + p.n, "kind": p.kind, "shape": p.shape, "image_group": p.image_group, "scene": p.scene, "scale": p.scale, "state": p.state,
            "beat": p.beat, "weight": p.weight, "characters": list(p.characters or []), "environment": p.environment, "source_page": p.source_page, "caption_en": p.caption_en or "", "caption_hi": p.caption_hi or "",
            "balloon_en": p.balloon_en or "", "balloon_hi": p.balloon_hi or "", "speaker": p.speaker or "", "hi_is_draft": p.hi_is_draft, "selected_candidate_id": p.selected_candidate_id,
            "locked_shape": p.locked_shape, "sfx": p.sfx or "", "text_colours": p.text_colours or None, "callout_shape": p.callout_shape or "auto", "balloon_shape": p.balloon_shape or "auto", "unlocked": render.panel_gate(session, p), "candidates": [j_candidate(c) for c in p.candidates], "image_url": db.media_url(sel.path) if sel else None}


def j_page(session: Session, pg: Page) -> dict[str, Any]:
    render.ensure_shapes(session, pg)
    unlocked = render.page_gate(session, pg)
    views = [render.panel_view(session, p) for p in pg.panels]
    look = L.page_look_for(views, pg.beat)
    override = session.get(Canvas, pg.canvas_override) if pg.canvas_override else None
    sel = next((p for p in pg.panels if p.selected_candidate_id), None)
    thumb = session.get(Candidate, sel.selected_candidate_id) if sel else None
    arts = pg.artifacts or {}
    return {"id": pg.id, "chapter_id": pg.chapter_id, "number": pg.number, "beat": pg.beat or look.beat, "beat_explicit": pg.beat, "status": pg.status,
            "canvas_override": override.key if override else None, "marginalia": pg.marginalia or [], "seed": pg.seed, "is_opener": pg.is_opener, "epigraph": pg.epigraph, "epigraph_hi": pg.epigraph_hi,
            "balance": render.balance(session, pg), "thumb": db.media_url(thumb.path) if thumb else None, "artifact": arts.get("en"), "artifacts": arts,
            "gate": {"ok": not unlocked, "unlocked": unlocked}, "look": look.__dict__, "typography_override": pg.typography_override or None, "ink_dissolve": pg.ink_dissolve, "manuscript": pg.manuscript or None,
            "typography": render.page_typography(pg).summary(), "panels": [j_panel(session, p) for p in pg.panels]}


JOB_LABELS = {"panel": "Panel", "page": "Page", "refs": "References", "silhouettes": "Silhouettes", "prefill": "Prefill", "hindi": "Hindi drafts", "propose": "Propose cast", "export": "Export", "batch": "Director", "manuscript": "Manuscript"}


def j_job(j: Job) -> dict[str, Any]:
    prog = j.progress or {}
    if j.kind == "batch":
        progress: Any = {"page": prog.get("page") or 0, "panel": prog.get("panel") or 0, "done": int(prog.get("done") or 0), "total": int(prog.get("total") or 0), "cost_so_far": float(prog.get("cost_so_far") or 0.0)}
    elif j.status == "done":
        progress = 1.0
    else:
        total = int(prog.get("total") or 0)
        progress = round(min(1.0, int(prog.get("done") or 0) / total), 3) if total else 0.0
    return {"id": j.id, "kind": j.kind, "ref_id": j.ref_id, "status": j.status, "progress": progress, "log": j.log or "", "cost_usd": j.cost_usd or 0.0, "label": (j.params or {}).get("label") or f"{JOB_LABELS.get(j.kind, j.kind)} #{j.id}",
            "stop": j.stop, "result": j.result or {}, "params": j.params or {}, "created_at": j.created_at.isoformat() if j.created_at else None, "updated_at": j.updated_at.isoformat() if j.updated_at else None}


def job_resp(j: Job, **extra: Any) -> dict[str, Any]:
    return {"job_id": j.id, "job": j_job(j), **extra}


def j_silhouette(s: Silhouette) -> dict[str, Any]:
    return {"id": s.id, "project_id": s.project_id, "path": s.path, "url": db.media_url(s.path), "tags": s.tags, "source": s.source, "prompt": s.prompt}


def project_row(session: Session) -> Project:
    p = session.scalar(select(Project))
    if p is None:
        p = Project(title="The Cycle of Dharma", author="Rachit Agarwal", settings={"models": {}})
        session.add(p)
        session.commit()
    return p


def chapter1(session: Session) -> Chapter | None:
    chapters = session.scalars(select(Chapter)).all()
    return next((c for c in sorted(chapters, key=lambda c: (c.volume.number, c.number)) if c.number == 1), None)


def journey(session: Session, proj: Project) -> dict[str, Any]:
    """Computed from state: manuscript present -> models chosen -> all Chapter-1 characters locked -> canvases set ->
    chapter 1 has pages. "Start over" (journey/reset) shows the stepper from step 1 until a manuscript is uploaded."""
    order = ["manuscript", "models", "characters", "canvas", "prefill", "pages"]
    ch1 = chapter1(session)
    if (proj.settings or {}).get("journey_restart"):
        return {"step": "manuscript", "done": [], "chapter1_unlocked": [], "chapter1_id": ch1.id if ch1 else None}
    chapters = session.scalars(select(Chapter)).all()
    done: list[str] = []
    if proj.manuscript_pdf or any((c.text or "").strip() for c in chapters):
        done.append("manuscript")
    models = (proj.settings or {}).get("models") or {}
    avail = llm.choices()
    if all(models.get(r) or not avail.get(r) for r in ("script_writer", "prompt_writer", "critic", "image")):
        done.append("models")  # chosen, or nothing to choose for a role (no key: dry-run)
    ch1_unlocked: list[str] = []
    if ch1 and ch1.pages:
        keys: list[str] = []
        for pg in ch1.pages:
            for p in pg.panels:
                for k in p.characters or []:
                    if k not in keys:
                        keys.append(k)
        ch1_unlocked = render.unlocked_names(session, keys)
        if not ch1_unlocked:
            done.append("characters")
    elif session.scalar(select(func.count(Character.id)).where(Character.locked.is_(True))):
        done.append("characters")
    vols = session.scalars(select(Volume)).all()
    if vols and all(v.canvas_id for v in vols if v.number == 1):
        done.append("canvas")
    if ch1 and ch1.pages:
        done.append("prefill")
    if ch1 and ch1.pages and all(pg.status == "approved" for pg in ch1.pages):
        done.append("pages")
    step = next((s for s in order if s not in done), "pages")
    return {"step": step, "done": done, "chapter1_unlocked": ch1_unlocked, "chapter1_id": ch1.id if ch1 else None}


# ---------------------------------------------------------------------------------
# project / models / journey / volumes / canvases
# ---------------------------------------------------------------------------------


@app.get("/api/project")
def get_project(session: Session = S()) -> dict[str, Any]:
    proj = project_row(session)
    jobs.sync_models(session)
    total = session.scalar(select(func.coalesce(func.sum(Ledger.usd), 0.0))) or 0.0
    return {"id": proj.id, "title": proj.title, "author": proj.author, "manuscript_pdf": proj.manuscript_pdf, "settings": {**(proj.settings or {}), "models": llm.selected()}, "keys": settings.key_status(),
            "journey": journey(session, proj), "ledger_total_usd": round(float(total), 4),
            "dry_run": {"sunburst": settings.dry_run_sunburst, "gemini": settings.dry_run_gemini, "topaz": settings.dry_run_topaz, "agents": settings.dry_run_agents}}


class ProjectIn(BaseModel):
    title: str | None = None
    author: str | None = None
    settings: dict[str, Any] | None = None


@app.put("/api/project")
def put_project(body: ProjectIn, session: Session = S()) -> dict[str, Any]:
    proj = project_row(session)
    if body.title is not None:
        proj.title = body.title
    if body.author is not None:
        proj.author = body.author
    if body.settings is not None:
        proj.settings = {**(proj.settings or {}), **body.settings}
    session.commit()
    return get_project(session)


@app.post("/api/project/journey/reset")
def journey_reset(session: Session = S()) -> dict[str, Any]:
    """Start over: nothing is deleted; the stepper returns to step 1 until a manuscript is uploaded again."""
    proj = project_row(session)
    proj.settings = {**(proj.settings or {}), "journey_restart": True}
    session.commit()
    return journey(session, proj)


@app.get("/api/models")
def get_models(session: Session = S()) -> dict[str, Any]:
    jobs.sync_models(session)
    return {"providers": llm.providers(), "roles": llm.choice_objects(), "available": llm.choices(), "selected": llm.selected()}


class ModelsIn(BaseModel):
    script_writer: str | None = None
    prompt_writer: str | None = None
    critic: str | None = None
    image: str | None = None


@app.put("/api/project/models")
def put_models(body: ModelsIn, session: Session = S()) -> dict[str, Any]:
    proj = project_row(session)
    models = dict((proj.settings or {}).get("models") or {})
    for role, val in body.model_dump().items():
        if val is None:
            continue
        if not llm.known_model(role, val):
            raise HTTPException(400, f"{role}: unknown model {val}")
        models[role] = val
    proj.settings = {**(proj.settings or {}), "models": models}
    session.commit()
    jobs.sync_models(session)
    return get_models(session)


@app.post("/api/project/manuscript")
async def upload_manuscript(file: UploadFile = File(...), volume_id: int | None = Form(None), session: Session = S()) -> dict[str, Any]:
    """Extract text, detect chapters, create Volume/Chapter rows. Runs inline; recorded as a finished `manuscript` job."""
    proj = project_row(session)
    d = db.DATA_DIR / "manuscript"
    d.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename or "manuscript.pdf")
    dst = d / name
    dst.write_bytes(await file.read())
    # A book with a contents table (The Cycle of Dharma): split it on this Mac into all three volumes, no model run.
    if dst.suffix.lower() == ".pdf":
        try:
            from backend import book_seed

            res = book_seed.import_manuscript(dst, session)
            chapters_all = session.scalars(select(Chapter).order_by(Chapter.volume_id, Chapter.number)).all()
            out = [j_chapter(c, brief=True) for c in chapters_all]
            log = (f"received {name} ({dst.stat().st_size // 1024} KB)\nread the contents table: {res['entries']} parts, {res['words']} words\n"
                   f"loaded {len(out)} chapters across the three books ({res['created']} new, {res['updated']} updated)\ndone\n")
            job = Job(kind="manuscript", ref_id=proj.id, status="done", log=log, params={"label": f"Manuscript · {name}", "file": name},
                      result={"chapters": out, "book": res}, progress={"done": 1, "total": 1})
            session.add(job)
            session.commit()
            v1 = session.scalar(select(Volume).where(Volume.project_id == proj.id, Volume.number == 1))
            return job_resp(job, manuscript_pdf=proj.manuscript_pdf, volume_id=v1.id if v1 else None, chapters=out)
        except ValueError:
            pass  # no contents table: fall back to heading detection below
    try:
        text, offsets = manuscript.extract_text(dst)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"could not read {name}: {exc}") from exc
    chapters = manuscript.detect_chapters(text, offsets)
    proj.manuscript_pdf = db.rel(dst)
    proj.settings = {k: v for k, v in (proj.settings or {}).items() if k != "journey_restart"}
    vol = session.get(Volume, volume_id) if volume_id else None
    if vol is None:
        vol = session.scalar(select(Volume).where(Volume.project_id == proj.id, Volume.number == 1))
    if vol is None:
        vol = Volume(project_id=proj.id, number=1, title="Book One", era_default="treta")
        session.add(vol)
        session.flush()
    out = []
    for ch in chapters:
        row = session.scalar(select(Chapter).where(Chapter.volume_id == vol.id, Chapter.number == ch["number"]))
        if row is None:
            row = Chapter(volume_id=vol.id, number=ch["number"], title=ch["title"])
            session.add(row)
        row.text = ch["text"]
        row.pages_from, row.pages_to = ch["pages_from"], ch["pages_to"]
        if ch["title"] and (not row.title or row.title.startswith("Chapter")):
            row.title = ch["title"]
        session.flush()
        out.append(j_chapter(row, brief=True))
    log = f"received {name} ({dst.stat().st_size // 1024} KB)\nextracted {len(text)} characters\ndetected {len(out)} chapters: " + ", ".join(c["title"] for c in out) + "\ndone\n"
    job = Job(kind="manuscript", ref_id=proj.id, status="done", log=log, params={"label": f"Manuscript · {name}", "file": name}, result={"chapters": out, "volume_id": vol.id}, progress={"done": 1, "total": 1})
    session.add(job)
    session.commit()
    return job_resp(job, manuscript_pdf=proj.manuscript_pdf, volume_id=vol.id, chapters=out)


@app.get("/api/volumes")
def get_volumes(session: Session = S()) -> list[dict[str, Any]]:
    return [j_volume(v) for v in session.scalars(select(Volume).order_by(Volume.number)).all()]


class VolumeIn(BaseModel):
    canvas_id: int | None = None
    title: str | None = None
    era_default: str | None = None


@app.put("/api/volumes/{vid}")
def put_volume(vid: int, body: VolumeIn, session: Session = S()) -> dict[str, Any]:
    v = session.get(Volume, vid)
    if v is None:
        raise HTTPException(404, "volume not found")
    if "canvas_id" in body.model_fields_set:
        if body.canvas_id is not None and session.get(Canvas, body.canvas_id) is None:
            raise HTTPException(400, "canvas not found")
        v.canvas_id = body.canvas_id
    if body.title is not None:
        v.title = body.title
    if body.era_default is not None:
        v.era_default = body.era_default
    session.commit()
    return j_volume(v)


@app.get("/api/volumes/{vid}/typography")
def get_volume_typography(vid: int, session: Session = S()) -> dict[str, Any]:
    v = session.get(Volume, vid)
    if v is None:
        raise HTTPException(404, "volume not found")
    return {"volume_id": v.id, "stored": v.typography or {}, "typography": render.volume_typography(v), "resolved": T.resolve(v.typography or {}).summary()}


@app.put("/api/volumes/{vid}/typography")
def put_volume_typography(vid: int, body: dict[str, Any], session: Session = S()) -> dict[str, Any]:
    """A full or partial setting. Keys sent as null are removed (inherit the preset/default); sending `preset` alone
    clears the per-role fonts so the preset's own fonts apply."""
    v = session.get(Volume, vid)
    if v is None:
        raise HTTPException(404, "volume not found")
    try:
        clean = T.validate(body, partial=True)
    except T.TypographyError as exc:
        raise HTTPException(400, str(exc)) from exc
    cur = dict(v.typography or {})
    if clean.get("preset") and not (set(clean) & set(T.FONT_KEYS)):
        for k in T.FONT_KEYS:
            cur.pop(k, None)
    for k, val in clean.items():
        if val is None:
            cur.pop(k, None)
        else:
            cur[k] = val
    v.typography = cur
    session.commit()
    return get_volume_typography(vid, session)


@app.get("/api/typography/presets")
def typography_presets() -> dict[str, Any]:
    return {"presets": T.presets_json(), "sizes": T.SIZES, "default": T.DEFAULT_SETTING, "colour_modes": list(T.COLOUR_MODES), "states": list(T.STATES),
            "state_colours": {st: {"box": colour.STATE_BOX[st], "text": colour.STATE_TEXT[st], "border": colour.STATE_ACCENT[st]} for st in T.STATES}}


@app.get("/api/fonts")
def get_fonts() -> list[dict[str, Any]]:
    return T.catalog_json()


@app.get("/api/fonts/{name}", include_in_schema=False)
def get_font_file(name: str) -> Response:
    path = T.font_file(name)
    if path is None:
        raise HTTPException(404, "font not found")
    return FileResponse(path, media_type="font/ttf", headers={"Cache-Control": "public, max-age=31536000, immutable", "Access-Control-Allow-Origin": "*"})


@app.get("/api/textures/{name}", include_in_schema=False)
def get_texture(name: str) -> Response:
    """The callout scrap textures, prepared for the page (640 px JPEG)."""
    m = re.fullmatch(r"scrap_(light|warm|dark)\.jpg", name)
    if not m:
        raise HTTPException(404, "texture not found")
    return Response(CO.scrap_bytes(m.group(1)), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/callouts")
def get_callouts() -> dict[str, Any]:
    kinds = [{"kind": k, "label": CO.LABELS[k], "note": CO.NOTES[k], "paper": CO.paper_for(k, "quiet"), "thumb_url": f"/api/callouts/thumb/{k}.svg"} for k in CO.KINDS]
    balloons = [{"kind": k, "label": CO.LABELS[k], "note": CO.NOTES[k], "paper": "light", "thumb_url": f"/api/callouts/thumb/{k}.svg?paper=light"} for k in CO.BALLOON_KINDS]
    return {"captions": kinds, "balloons": balloons, "auto_by_state": CO.AUTO_BY_STATE, "paper_by_state": CO.PAPER_BY_STATE}


@app.get("/api/callouts/thumb/{name}", include_in_schema=False)
def callout_thumb(name: str, paper: str | None = None, state: str = "quiet") -> Response:
    kind = name.removesuffix(".svg")
    if kind not in CO.KINDS + CO.BALLOON_KINDS:
        raise HTTPException(404, "unknown shape")
    st = "ego" if kind == "jagged_dark" and state == "quiet" else state
    return Response(CO.thumbnail(kind, paper, st), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/manuscript/verses")
def get_verses() -> list[dict[str, Any]]:
    return [{k: v.get(k) for k in ("id", "source", "lines", "iast", "meaning", "tags")} for v in MS.verses()]


@app.get("/api/manuscript/figures")
def get_figures() -> list[dict[str, Any]]:
    return [{"id": f, "name": MS.FIGURE_NAMES.get(f, f), "tags": list(MS.FIGURE_TAGS.get(f, ())), "url": MS.FIGURE_URL.format(id=f), "aspect": round(MS.figure_aspect(f), 4)} for f in MS.figure_ids()]


@app.get("/api/figures/{name}", include_in_schema=False)
def get_figure(name: str) -> Response:
    fid = name.removesuffix(".png")
    if fid not in MS.figure_ids():
        raise HTTPException(404, "figure not found")
    return Response(MS.figure_png(fid), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/canvases")
def get_canvases(session: Session = S()) -> list[dict[str, Any]]:
    return [j_canvas(c) for c in session.scalars(select(Canvas).order_by(Canvas.id)).all()]


# ---------------------------------------------------------------------------------
# characters
# ---------------------------------------------------------------------------------


@app.get("/api/characters")
def get_characters(session: Session = S()) -> list[dict[str, Any]]:
    return [j_character(c) for c in session.scalars(select(Character).order_by(Character.id)).all()]


class CharacterIn(BaseModel):
    name: str | None = None
    form_key: str | None = None
    look: str | None = None
    locked: bool | None = None
    primary_ref_id: int | None = None


@app.post("/api/characters", status_code=201)
def post_character(body: CharacterIn, session: Session = S()) -> dict[str, Any]:
    if not body.name:
        raise HTTPException(400, "name required")
    proj = project_row(session)
    key = (body.form_key or body.name).strip().lower().replace(" ", "-")
    if session.scalar(select(Character).where(Character.form_key == key)):
        raise HTTPException(409, f"form_key {key} exists")
    c = Character(project_id=proj.id, name=body.name.strip(), form_key=key, look=body.look or "", locked=False)
    session.add(c)
    session.commit()
    return j_character(c)


def _approved_primary(c: Character) -> CharacterRef | None:
    r = next((x for x in c.refs if x.id == c.primary_ref_id), None)
    return r if (r and r.approved) else None


@app.put("/api/characters/{cid}")
def put_character(cid: int, body: CharacterIn, session: Session = S()) -> dict[str, Any]:
    c = session.get(Character, cid)
    if c is None:
        raise HTTPException(404, "character not found")
    if body.name is not None:
        c.name = body.name
    if body.look is not None:
        c.look = body.look
    if body.primary_ref_id is not None:
        r = session.get(CharacterRef, body.primary_ref_id)
        if r is None or r.character_id != c.id:
            raise HTTPException(400, "ref not found on this character")
        for x in c.refs:
            x.is_primary = x.id == r.id
        r.approved = True
        c.primary_ref_id = r.id
    if body.locked is not None:
        if body.locked and not _approved_primary(c):
            raise HTTPException(409, f"{c.name} cannot be locked: it needs an approved primary reference image.")
        c.locked = body.locked
    session.commit()
    return j_character(c)


@app.delete("/api/characters/{cid}")
def delete_character(cid: int, session: Session = S()) -> dict[str, Any]:
    c = session.get(Character, cid)
    if c is None:
        raise HTTPException(404, "character not found")
    session.delete(c)
    session.commit()
    return {"ok": True}


class RefsGenIn(BaseModel):
    provider: str = "sunburst"
    n: int = Field(2, ge=1, le=6)


@app.post("/api/characters/{cid}/refs/generate", status_code=202)
def gen_refs(cid: int, body: RefsGenIn, session: Session = S()) -> dict[str, Any]:
    c = session.get(Character, cid)
    if c is None:
        raise HTTPException(404, "character not found")
    if len(c.refs) + body.n > 6:
        raise HTTPException(400, f"a character keeps at most 6 reference images ({len(c.refs)} now)")
    prov = providers.normalise_provider(body.provider)
    return job_resp(jobs.submit(session, "refs", c.id, {"provider": prov, "n": body.n, "label": f"{c.name} · {body.n} reference candidates ({prov})"}))


def _save_png(raw: bytes, dst: Any) -> None:
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as im:
        im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(dst, "PNG")


async def _uploads(files: list[UploadFile] | None, file: UploadFile | None) -> list[tuple[str, bytes]]:
    out = []
    for f in [*(files or []), *([file] if file else [])]:
        out.append((f.filename or "upload.png", await f.read()))
    if not out:
        raise HTTPException(400, "no file")
    return out


@app.post("/api/characters/{cid}/refs/upload", status_code=201)
async def upload_refs(cid: int, files: list[UploadFile] | None = File(None), file: UploadFile | None = File(None), session: Session = S()) -> list[dict[str, Any]]:
    c = session.get(Character, cid)
    if c is None:
        raise HTTPException(404, "character not found")
    items = await _uploads(files, file)
    if len(c.refs) + len(items) > 6:
        raise HTTPException(400, f"a character keeps at most 6 reference images ({len(c.refs)} now)")
    d = db.DATA_DIR / "refs" / f"c{c.id}"
    d.mkdir(parents=True, exist_ok=True)
    added = []
    for name, raw in items:
        ref = CharacterRef(character_id=c.id, path="", provider="upload", prompt=f"uploaded: {name}", is_primary=False, approved=False)
        session.add(ref)
        session.flush()
        dst = d / f"upload_{ref.id}.png"
        try:
            _save_png(raw, dst)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"{name} is not an image") from exc
        ref.path = db.rel(dst)
        added.append(ref)
    session.commit()
    return [j_ref(r) for r in added]


class RefIn(BaseModel):
    is_primary: bool | None = None
    approved: bool | None = None


@app.put("/api/characters/{cid}/refs/{rid}")
def put_ref(cid: int, rid: int, body: RefIn, session: Session = S()) -> dict[str, Any]:
    c = session.get(Character, cid)
    r = session.get(CharacterRef, rid)
    if c is None or r is None or r.character_id != c.id:
        raise HTTPException(404, "ref not found")
    if body.is_primary:
        for x in c.refs:
            x.is_primary = x.id == r.id
        c.primary_ref_id = r.id
    elif body.is_primary is False and r.is_primary:
        r.is_primary = False
        c.primary_ref_id = None
        c.locked = False  # the lock needs an approved primary
    if body.approved is not None:
        r.approved = body.approved
        if not r.approved and r.is_primary and c.locked:
            c.locked = False
    session.commit()
    return j_ref(r)


@app.delete("/api/characters/{cid}/refs/{rid}")
def delete_ref(cid: int, rid: int, session: Session = S()) -> dict[str, Any]:
    c = session.get(Character, cid)
    r = session.get(CharacterRef, rid)
    if c is None or r is None or r.character_id != c.id:
        raise HTTPException(404, "ref not found")
    if c.primary_ref_id == r.id:
        c.primary_ref_id = None
        c.locked = False
    session.delete(r)
    session.commit()
    return {"ok": True}


@app.post("/api/characters/propose", status_code=202)
def propose_cast(session: Session = S()) -> dict[str, Any]:
    return job_resp(jobs.submit(session, "propose", None, {"label": f"Propose cast from manuscript ({llm.model_for('script_writer')})"}))


# ---------------------------------------------------------------------------------
# chapters
# ---------------------------------------------------------------------------------


@app.get("/api/chapters")
def get_chapters(session: Session = S()) -> list[dict[str, Any]]:
    rows = session.scalars(select(Chapter)).all()
    return [j_chapter(c, brief=True) for c in sorted(rows, key=lambda c: (c.volume.number, c.number))]


@app.get("/api/chapters/{cid}")
def get_chapter(cid: int, session: Session = S()) -> dict[str, Any]:
    c = session.get(Chapter, cid)
    if c is None:
        raise HTTPException(404, "chapter not found")
    return j_chapter(c)


class ChapterIn(BaseModel):
    title: str | None = None
    text: str | None = None
    pages_from: int | None = None
    pages_to: int | None = None
    number: int | None = None


@app.put("/api/chapters/{cid}")
def put_chapter(cid: int, body: ChapterIn, session: Session = S()) -> dict[str, Any]:
    c = session.get(Chapter, cid)
    if c is None:
        raise HTTPException(404, "chapter not found")
    for k in body.model_fields_set:
        v = getattr(body, k)
        if k in ("title", "text", "number") and v is None:
            continue
        setattr(c, k, v)
    session.commit()
    return j_chapter(c)


class PrefillIn(BaseModel):
    hindi: bool = True


@app.post("/api/chapters/{cid}/prefill", status_code=202)
def prefill(cid: int, body: PrefillIn | None = None, session: Session = S()) -> dict[str, Any]:
    c = session.get(Chapter, cid)
    if c is None:
        raise HTTPException(404, "chapter not found")
    return job_resp(jobs.submit(session, "prefill", c.id, {"hindi": body.hindi if body else True, "label": f"Prefill chapter {c.number} ({llm.model_for('script_writer')})"}))


@app.post("/api/chapters/{cid}/hindi", status_code=202)
def hindi(cid: int, session: Session = S()) -> dict[str, Any]:
    c = session.get(Chapter, cid)
    if c is None:
        raise HTTPException(404, "chapter not found")
    return job_resp(jobs.submit(session, "hindi", c.id, {"label": f"Draft Hindi · chapter {c.number}"}))


# ---------------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------------


@app.get("/api/pages")
def get_pages(chapter_id: int | None = None, session: Session = S()) -> list[dict[str, Any]]:
    q = select(Page).order_by(Page.number)
    if chapter_id:
        q = q.where(Page.chapter_id == chapter_id)
    out = [j_page(session, p) for p in session.scalars(q).all()]
    session.commit()  # ensure_shapes may have filled shapes
    return out


def _page(session: Session, pid: int) -> Page:
    p = session.get(Page, pid)
    if p is None:
        raise HTTPException(404, "page not found")
    return p


@app.get("/api/pages/{pid}")
def get_page(pid: int, session: Session = S()) -> dict[str, Any]:
    out = j_page(session, _page(session, pid))
    session.commit()
    return out


class PageIn(BaseModel):
    beat: str | None = None
    status: str | None = None
    marginalia: list[dict[str, Any]] | None = None
    canvas_override: str | int | None = None  # a canvas key (the UI) or id; null clears
    is_opener: bool | None = None
    epigraph: str | None = None
    epigraph_hi: str | None = None
    seed: int | None = None
    typography_override: dict[str, Any] | None = None  # partial setting over the volume's; null or {} = reset to volume
    ink_dissolve: bool | None = None  # null = auto
    manuscript: dict[str, Any] | None = None  # {auto: false, verses: [...], figures: [...]}; null or {auto: true} = automatic


@app.put("/api/pages/{pid}")
def put_page(pid: int, body: PageIn, session: Session = S()) -> Any:
    pg = _page(session, pid)
    fields = body.model_fields_set
    frozen = pg.status == "approved" and body.status in (None, "approved")
    if frozen and fields & {"beat", "marginalia", "is_opener", "seed"}:
        raise HTTPException(409, "Page is approved and frozen. Un-approve it before editing.")
    if "beat" in fields and body.beat != pg.beat:
        if body.beat and body.beat not in ("calm", "tension", "action", "revelation", "hex"):
            raise HTTPException(400, "bad beat")
        pg.beat = body.beat or None
        render.recut(session, pg)
    if "marginalia" in fields and body.marginalia is not None:
        pg.marginalia = body.marginalia
    if "canvas_override" in fields:
        v = body.canvas_override
        if v in (None, "", 0):
            pg.canvas_override = None
        else:
            c = session.get(Canvas, v) if isinstance(v, int) else render.canvas_by_key(session, str(v))
            if c is None:
                raise HTTPException(400, f"canvas {v} not found")
            pg.canvas_override = c.id
    if body.is_opener is not None and body.is_opener != pg.is_opener:
        pg.is_opener = body.is_opener
        render.recut(session, pg)
    if body.epigraph is not None:
        pg.epigraph = body.epigraph
    if body.epigraph_hi is not None:
        pg.epigraph_hi = body.epigraph_hi
    if body.seed is not None:
        pg.seed = body.seed
    if "ink_dissolve" in fields:
        pg.ink_dissolve = body.ink_dissolve
    if "manuscript" in fields:
        m = body.manuscript or {}
        if not m or m.get("auto", True) is not False:
            pg.manuscript = None
        else:
            vs = [v for v in (m.get("verses") or []) if isinstance(v, dict) and MS.verse(str(v.get("id")))]
            fs = [f for f in (m.get("figures") or []) if isinstance(f, dict) and f.get("id") in MS.figure_ids()]
            if len(vs) != len(m.get("verses") or []) or len(fs) != len(m.get("figures") or []):
                raise HTTPException(400, "unknown verse or figure id")
            keep = ("id", "x_mm", "y_mm", "w_mm", "rotation", "opacity", "font", "ruled")
            pg.manuscript = {"auto": False, "verses": [{k: v[k] for k in keep if k in v} for v in vs], "figures": [{k: f[k] for k in keep if k in f} for f in fs]}
    if "typography_override" in fields:
        try:
            ov = T.validate(body.typography_override or {})
        except T.TypographyError as exc:
            raise HTTPException(400, str(exc)) from exc
        pg.typography_override = ov or None
    if body.status is not None:
        if body.status not in ("empty", "draft", "generating", "review", "approved"):
            raise HTTPException(400, "bad status")
        if body.status == "approved":
            unlocked = render.page_gate(session, pg)
            if unlocked:
                return JSONResponse({"unlocked": unlocked, "detail": f"Cannot approve: unlocked characters on this page — {', '.join(unlocked)}."}, status_code=409)
            pg.status = "approved"
            render.write_artifacts(session, pg)  # the frozen page as standalone HTML artifacts
        else:
            if pg.status == "approved":
                pg.artifacts = {}
            pg.status = body.status
    elif pg.status == "approved" and fields & {"canvas_override", "epigraph", "epigraph_hi", "typography_override", "ink_dissolve", "manuscript"}:
        render.write_artifacts(session, pg)
    session.commit()
    return j_page(session, pg)


@app.get("/api/pages/{pid}/render", response_class=HTMLResponse)
def render_page(pid: int, lang: str = "en", paper: str = "screen", embed: bool = False, canvas: str | None = None, print_texture: bool = False, session: Session = S()) -> HTMLResponse:
    pg = _page(session, pid)
    if lang not in ("en", "hi"):
        raise HTTPException(400, "lang must be en|hi")
    if paper not in ("screen", "print"):
        raise HTTPException(400, "paper must be screen|print")
    html = render.page_document(session, pg, lang=lang, paper=paper, embed=embed, canvas_key=canvas or None, print_texture=print_texture)
    session.commit()
    return HTMLResponse(html)


@app.get("/api/fonts.css", include_in_schema=False)
def fonts_css() -> Response:
    return Response(L.font_css(), media_type="text/css", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/pages/{pid}/manuscript")
def page_manuscript(pid: int, session: Session = S()) -> dict[str, Any]:
    out = render.manuscript_state(session, _page(session, pid))
    session.commit()
    return out


@app.post("/api/pages/{pid}/manuscript/auto")
def page_manuscript_auto(pid: int, session: Session = S()) -> dict[str, Any]:
    """Re-place automatically (drops the author's own placement)."""
    pg = _page(session, pid)
    pg.manuscript = None
    if pg.status == "approved":
        render.write_artifacts(session, pg)
    session.commit()
    return render.manuscript_state(session, pg)


@app.get("/api/pages/{pid}/manifest")
def page_manifest(pid: int, session: Session = S()) -> dict[str, Any]:
    out = render.page_manifest(session, _page(session, pid))
    session.commit()
    return out


@app.get("/api/pages/{pid}/gate")
def page_gate(pid: int, session: Session = S()) -> dict[str, Any]:
    unlocked = render.page_gate(session, _page(session, pid))
    return {"ok": not unlocked, "unlocked": unlocked}


@app.post("/api/pages/{pid}/recut")
def page_recut(pid: int, session: Session = S()) -> dict[str, Any]:
    pg = _page(session, pid)
    if pg.status == "approved":
        raise HTTPException(409, "Page is approved and frozen. Un-approve it before re-cutting.")
    render.recut(session, pg)
    session.commit()
    return j_page(session, pg)


def _gate_409(names: list[str], what: str) -> JSONResponse:
    s = "s" if len(names) > 1 else ""
    return JSONResponse({"unlocked": names, "detail": f"Cannot generate: unlocked character{s} on this {what} — {', '.join(names)}. Lock them on the Characters screen first."}, status_code=409)


class GenAllIn(BaseModel):
    provider: str | None = None
    n: int = Field(2, ge=1, le=6)
    all: bool = False  # also regenerate panels that already have a selection


@app.post("/api/pages/{pid}/generate-all", status_code=202)
def page_generate_all(pid: int, body: GenAllIn | None = None, session: Session = S()) -> Any:
    pg = _page(session, pid)
    body = body or GenAllIn()
    unlocked = render.page_gate(session, pg)
    if unlocked:
        return _gate_409(unlocked, "page")
    if pg.status == "approved":
        raise HTTPException(409, "Page is approved and frozen. Un-approve it before regenerating.")
    prov = providers.normalise_provider(body.provider or llm.model_for("image"))
    targets = len(pg.panels) if body.all else len(gen.page_has_unselected(pg))
    return job_resp(jobs.submit(session, "page", pg.id, {"provider": prov, "n": body.n, "all": body.all, "label": f"Page {pg.number} · {targets} panels × {body.n} ({prov})"}))


# ---------------------------------------------------------------------------------
# panels and candidates
# ---------------------------------------------------------------------------------


def _panel(session: Session, pid: int) -> Panel:
    p = session.get(Panel, pid)
    if p is None:
        raise HTTPException(404, "panel not found")
    return p


class PanelIn(BaseModel):
    scene: str | None = None
    scale: str | None = None
    state: str | None = None
    beat: str | None = None
    weight: float | None = None
    kind: str | None = None
    characters: list[str] | None = None
    environment: str | None = None
    caption_en: str | None = None
    caption_hi: str | None = None
    balloon_en: str | None = None
    balloon_hi: str | None = None
    speaker: str | None = None
    hi_is_draft: bool | None = None
    image_group: str | None = None
    shape: dict[str, Any] | None = None
    locked_shape: bool | None = None
    shape_kind: str | None = None  # convenience: a fresh polygon of this kind in the current bbox
    sfx: str | None = None
    callout_shape: str | None = None  # auto | a callout kind
    balloon_shape: str | None = None
    text_colours: dict[str, Any] | None = None  # {box, text, border} pins the callout colours; null or {"mode": "auto"} = auto


TEXT_ONLY = {"caption_en", "caption_hi", "balloon_en", "balloon_hi", "speaker", "hi_is_draft", "sfx", "text_colours", "callout_shape", "balloon_shape"}


@app.put("/api/panels/{pid}")
def put_panel(pid: int, body: PanelIn, session: Session = S()) -> dict[str, Any]:
    p = _panel(session, pid)
    fields = set(body.model_fields_set)
    if p.page.status == "approved" and fields - TEXT_ONLY:
        raise HTTPException(409, "Page is approved and frozen. Un-approve it before editing shards or scenes.")
    if body.scale is not None and body.scale not in ("EWS", "WS", "MWS", "MS", "MCU", "CU", "ECU"):
        raise HTTPException(400, "bad scale")
    if body.state is not None and body.state not in STATES:
        raise HTTPException(400, "bad state")
    if body.kind is not None and body.kind not in ("shard", "plate"):
        raise HTTPException(400, "bad kind")
    if "text_colours" in fields:
        tc = body.text_colours or {}
        if tc and tc.get("mode") != "auto":
            if not (colour.is_hex(tc.get("box")) and colour.is_hex(tc.get("text"))) or (tc.get("border") and not colour.is_hex(tc["border"])):
                raise HTTPException(400, "text_colours needs box and text as #rrggbb (border optional)")
            p.text_colours = {k: str(tc[k]).lower() for k in ("box", "text", "border") if tc.get(k)}
        else:
            p.text_colours = None
    for k in fields - {"shape", "shape_kind", "locked_shape", "text_colours"}:
        v = getattr(body, k)
        if k == "sfx":
            p.sfx = (v or "").strip()
        elif k in ("callout_shape", "balloon_shape"):
            allowed = CO.KINDS if k == "callout_shape" else CO.BALLOON_KINDS
            if v not in (None, "", "auto") and v not in allowed:
                raise HTTPException(400, f"{k} must be auto or one of {', '.join(allowed)}")
            setattr(p, k, None if v in (None, "", "auto") else v)
        elif k in ("beat", "image_group", "environment", "speaker"):
            setattr(p, k, v or (None if k != "speaker" else None))
        elif v is not None:
            setattr(p, k, v)
    if "caption_hi" in fields or "balloon_hi" in fields:
        p.hi_is_draft = bool(body.hi_is_draft) if "hi_is_draft" in fields else False  # the author's Hindi is no longer a draft
    if body.shape is not None:
        p.shape = L.normalise_shape(body.shape)
        p.locked_shape = True if body.locked_shape is None else body.locked_shape
    elif body.locked_shape is not None:
        p.locked_shape = body.locked_shape
    if body.shape_kind:
        if body.shape_kind not in L.SHAPE_KINDS:
            raise HTTPException(400, "bad shape kind")
        poly = [(float(x), float(y)) for x, y in (p.shape or {}).get("polygon_mm") or []]
        bbox = L._bbox(poly) if len(poly) >= 3 else (L.MARGIN, L.MARGIN, L.PAGE_W - L.MARGIN, L.PAGE_H - L.MARGIN)
        new = L.shape_from_kind(body.shape_kind, bbox, seed=(p.page.seed or 7) * 100 + p.n)
        new["focal"] = (p.shape or {}).get("focal") or new["focal"]
        p.shape = new
        p.locked_shape = True
    session.commit()
    return j_panel(session, p)


class GenIn(BaseModel):
    provider: str | None = None
    n: int = Field(2, ge=1, le=6)
    feedback: str | None = None
    rewrite: bool = False  # true: let the prompt_writer rewrite the scene from the feedback before generating


@app.get("/api/panels/{pid}/palette")
def panel_palette(pid: int, session: Session = S()) -> dict[str, Any]:
    """The selected image's palette and picker swatches (box/text/border with their contrast) for the inspector."""
    p = _panel(session, pid)
    path, _url = render.candidate_path(session, p)
    pal = colour.palette(path)
    cv = render.canvas_view(render.canvas_for_page(session, p.page))
    paper = L._paper_hex(cv)
    ty = render.page_typography(p.page)
    auto = colour.smart(pal, p.state, paper=paper, ink=(cv.caption_style or {}).get("text", cv.ink))
    return {"palette": [colour.rgb_to_hex(c) for c, _ in pal], "swatches": colour.swatches(pal, paper), "auto": auto, "colour_mode": ty.colour_mode, "pinned": p.text_colours or None}


@app.post("/api/panels/{pid}/generate", status_code=202)
def panel_generate(pid: int, body: GenIn | None = None, session: Session = S()) -> Any:
    p = _panel(session, pid)
    body = body or GenIn()
    unlocked = render.page_gate(session, p.page)
    if unlocked:
        return _gate_409(unlocked, "page")
    if p.page.status == "approved":
        raise HTTPException(409, "Page is approved and frozen. Un-approve it before regenerating.")
    if body.feedback and body.rewrite:
        p.scene = agents.scene_rewrite(p.scene, body.feedback, gen.panel_info(p))
        session.commit()
    prov = providers.normalise_provider(body.provider or llm.model_for("image"))
    refs = len(gen.full_prompt(session, p)[1])
    return job_resp(jobs.submit(session, "panel", p.id, {"provider": prov, "n": body.n, "feedback": body.feedback or "", "label": f"Panel {p.page.number}.{p.n} · {body.n} candidates ({prov}, {refs} refs)"}))


class SelectIn(BaseModel):
    candidate_id: int | None = None


@app.post("/api/panels/{pid}/select")
def panel_select(pid: int, body: SelectIn, session: Session = S()) -> dict[str, Any]:
    p = _panel(session, pid)
    if p.page.status == "approved":
        raise HTTPException(409, "Page is approved and frozen. Un-approve it before changing the selection.")
    if body.candidate_id is None:
        p.selected_candidate_id = None
    else:
        c = session.get(Candidate, body.candidate_id)
        if c is None or c.panel_id != p.id:
            raise HTTPException(404, "candidate not found on this panel")
        gen.select_candidate(session, p, c)
    session.commit()
    return j_panel(session, p)


class RewriteIn(BaseModel):
    feedback: str
    apply: bool = False  # the author accepts the proposal with PUT /api/panels/{id} {scene}


@app.post("/api/panels/{pid}/rewrite")
def panel_rewrite(pid: int, body: RewriteIn, session: Session = S()) -> dict[str, Any]:
    p = _panel(session, pid)
    scene = agents.scene_rewrite(p.scene, body.feedback, gen.panel_info(p))
    previous = p.scene
    if body.apply:
        if p.page.status == "approved":
            raise HTTPException(409, "Page is approved and frozen.")
        p.scene = scene
        session.commit()
    return {"scene": scene, "previous": previous}


@app.get("/api/panels/{pid}/prompt")
def panel_prompt_preview(pid: int, session: Session = S()) -> dict[str, Any]:
    prompt, refs, names = gen.full_prompt(session, _panel(session, pid))
    return {"prompt": prompt, "references": [db.rel(r) for r in refs], "reference_names": names}


class CandidateIn(BaseModel):
    rejected: bool | None = None


def _set_candidate(session: Session, c: Candidate | None, body: CandidateIn) -> dict[str, Any]:
    if c is None:
        raise HTTPException(404, "candidate not found")
    if body.rejected is not None:
        c.rejected = body.rejected
    session.commit()
    return j_candidate(c)


@app.put("/api/panels/{pid}/candidates/{cid}")
def put_panel_candidate(pid: int, cid: int, body: CandidateIn, session: Session = S()) -> dict[str, Any]:
    c = session.get(Candidate, cid)
    return _set_candidate(session, c if (c and c.panel_id == pid) else None, body)


@app.put("/api/candidates/{cid}")
def put_candidate(cid: int, body: CandidateIn, session: Session = S()) -> dict[str, Any]:
    return _set_candidate(session, session.get(Candidate, cid), body)


# ---------------------------------------------------------------------------------
# silhouettes
# ---------------------------------------------------------------------------------


@app.get("/api/silhouettes")
def get_silhouettes(session: Session = S()) -> list[dict[str, Any]]:
    return [j_silhouette(s) for s in session.scalars(select(Silhouette).order_by(Silhouette.id)).all()]


class SilGenIn(BaseModel):
    prompt: str = ""
    n: int = Field(1, ge=1, le=6)
    tags: list[str] | str | None = None


@app.post("/api/silhouettes/generate", status_code=202)
def sil_generate(body: SilGenIn, session: Session = S()) -> dict[str, Any]:
    tags = body.tags.split(",") if isinstance(body.tags, str) else (body.tags or [])
    tags = [t.strip() for t in tags if t.strip()]
    if not body.prompt.strip() and not tags:
        raise HTTPException(400, "a prompt or tags required")
    label = f"Silhouettes · {body.n} ({', '.join(tags) or body.prompt[:24]})"
    return job_resp(jobs.submit(session, "silhouettes", None, {"prompt": body.prompt, "n": body.n, "tags": tags, "label": label}))


def _has_alpha(raw: bytes) -> bool:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.mode != "RGBA":
                return False
            lo, _hi = im.getchannel("A").getextrema()
            return lo < 255
    except Exception:  # noqa: BLE001
        return False


@app.post("/api/silhouettes/upload", status_code=201)
async def sil_upload(files: list[UploadFile] | None = File(None), file: UploadFile | None = File(None), tags: str = Form(""), session: Session = S()) -> list[dict[str, Any]]:
    proj = project_row(session)
    items = await _uploads(files, file)
    out = []
    for name, raw in items:
        try:
            keyed = raw if _has_alpha(raw) else providers.key_to_alpha(raw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"{name} is not an image") from exc
        s = Silhouette(project_id=proj.id, path="", tags=[t.strip() for t in tags.split(",") if t.strip()] or ["uploaded"], source="uploaded", prompt=f"uploaded: {name}")
        session.add(s)
        session.flush()
        dst = db.DATA_DIR / "silhouettes" / f"sil_{s.id}.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(keyed)
        s.path = db.rel(dst)
        out.append(s)
    session.commit()
    return [j_silhouette(s) for s in out]


@app.delete("/api/silhouettes/{sid}")
def sil_delete(sid: int, session: Session = S()) -> dict[str, Any]:
    s = session.get(Silhouette, sid)
    if s is None:
        raise HTTPException(404, "silhouette not found")
    session.delete(s)
    session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------------


class ExportIn(BaseModel):
    chapter_id: int | None = None
    volume_id: int | None = None
    lang: list[str] = Field(default_factory=lambda: ["en"])
    paper: str = "print"
    upscale: bool = False
    allow_partial: bool = False
    print_texture: bool = False  # print mode: also print the paper texture (default off: the stock is the paper)


def _export_scope(session: Session, body: ExportIn) -> tuple[list[Page], str]:
    if not (body.chapter_id or body.volume_id):
        raise HTTPException(400, "chapter_id or volume_id required")
    pages = render.export_pages(session, body.chapter_id, body.volume_id)
    if body.chapter_id:
        ch = session.get(Chapter, body.chapter_id)
        scope = f"Chapter {ch.number} · {ch.title}" if ch else f"Chapter {body.chapter_id}"
    else:
        v = session.get(Volume, body.volume_id)
        scope = f"Volume {v.number} · {v.title}" if v else f"Volume {body.volume_id}"
    return pages, scope


@app.post("/api/export/estimate")
def export_estimate(body: ExportIn, session: Session = S()) -> dict[str, Any]:
    pages, _scope = _export_scope(session, body)
    approved = [p for p in pages if p.status == "approved"]
    images = sum(1 for p in approved for x in p.panels if x.selected_candidate_id)
    usd = images * settings.topaz_cost_per_image if (body.upscale and not settings.dry_run_topaz) else 0.0
    return {"usd": round(usd, 3), "images": images, "approved": len(approved), "total": len(pages), "unapproved": len(pages) - len(approved), "unapproved_pages": [p.number for p in pages if p.status != "approved"]}


@app.post("/api/export", status_code=202)
def post_export(body: ExportIn, session: Session = S()) -> Any:
    if body.paper not in ("screen", "print"):
        raise HTTPException(400, "paper must be screen|print")
    langs = [x for x in body.lang if x in ("en", "hi")] or ["en"]
    pages, scope = _export_scope(session, body)
    if not pages:
        raise HTTPException(404, "no pages")
    unapproved = [p.number for p in pages if p.status != "approved"]
    if len(unapproved) == len(pages):
        return JSONResponse({"unapproved": unapproved, "detail": "Nothing to export: no approved pages in the selected scope."}, status_code=409)
    if unapproved and not body.allow_partial:
        return JSONResponse({"unapproved": unapproved, "detail": f"Unapproved pages: {', '.join(map(str, unapproved))}. Pass allow_partial to export the approved ones."}, status_code=409)
    label = f"Export {scope} · {'+'.join(x.upper() for x in langs)} · {body.paper}{' · Topaz' if body.upscale else ''}"
    job = jobs.submit(session, "export", body.chapter_id or body.volume_id, {"chapter_id": body.chapter_id, "volume_id": body.volume_id, "lang": langs, "paper": body.paper, "upscale": body.upscale, "print_texture": body.print_texture, "scope": scope, "label": label})
    return job_resp(job, export=render.export_record(job))


@app.get("/api/exports")
def get_exports(session: Session = S()) -> list[dict[str, Any]]:
    rows = session.scalars(select(Job).where(Job.kind == "export").order_by(Job.id.desc()).limit(100)).all()
    return [render.export_record(j) for j in rows]


# ---------------------------------------------------------------------------------
# jobs / ledger
# ---------------------------------------------------------------------------------


@app.get("/api/jobs")
def get_jobs(active: str | None = Query(None), limit: int = 50, session: Session = S()) -> list[dict[str, Any]]:
    q = select(Job).order_by(Job.id.desc())
    if active not in (None, "", "0", "false"):
        # running and queued jobs, plus those that finished in the last few seconds so the tray can show the outcome
        recent = (utcnow() - timedelta(seconds=5)).replace(tzinfo=None)
        q = q.where((Job.status.in_(["queued", "running"])) | (Job.updated_at >= recent))
    return [j_job(j) for j in session.scalars(q.limit(limit)).all()]


@app.get("/api/jobs/{jid}")
def get_job(jid: int, session: Session = S()) -> dict[str, Any]:
    j = session.get(Job, jid)
    if j is None:
        raise HTTPException(404, "job not found")
    return j_job(j)


@app.post("/api/jobs/{jid}/stop")
def stop_job(jid: int, session: Session = S()) -> dict[str, Any]:
    j = session.get(Job, jid)
    if j is None:
        raise HTTPException(404, "job not found")
    if j.status in ("queued", "running"):
        j.stop = True
        if j.status == "queued":
            j.status = "stopped"
            j.log = (j.log or "") + "stopped before it started\n"
        session.commit()
    return j_job(j)


@app.get("/api/ledger")
def get_ledger(session: Session = S()) -> dict[str, Any]:
    rows = session.scalars(select(Ledger).order_by(Ledger.id.desc()).limit(500)).all()
    by_provider: dict[str, float] = {}
    for prov, usd in session.execute(select(Ledger.provider, func.sum(Ledger.usd)).group_by(Ledger.provider)).all():
        by_provider[prov] = round(float(usd or 0), 4)
    return {"total": round(sum(by_provider.values()), 4), "by_provider": by_provider,
            "rows": [{"id": r.id, "provider": r.provider, "usd": r.usd, "ref": r.ref, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}


# ---------------------------------------------------------------------------------
# director (SPEC §9)
# ---------------------------------------------------------------------------------


class BatchIn(BaseModel):
    chapter_id: int
    pages: Any = None  # [1,2,3] | {"next": 5}
    candidates_per_panel: int = Field(2, ge=1, le=6)
    provider: str | None = None
    prefill_text: bool = True
    run_critic: bool = True
    dry_run: bool = False


def _estimate(session: Session, body: BatchIn) -> dict[str, Any]:
    ch = session.get(Chapter, body.chapter_id)
    if ch is None:
        raise HTTPException(404, "chapter not found")
    nums = jobs.batch_pages(session, ch, body.pages)
    panels = 0
    for num in nums:
        pg = next((p for p in ch.pages if p.number == num), None)
        if pg is None or not pg.panels:
            panels += 4 if body.prefill_text else 0  # an ordinary page before prefill: ~4 panels
        elif pg.status != "approved" and not render.page_gate(session, pg):
            panels += len(gen.page_has_unselected(pg))
    provider = providers.normalise_provider(body.provider or llm.model_for("image"))
    images = panels * body.candidates_per_panel
    dry = settings.dry_run_sunburst if provider == "sunburst" else settings.dry_run_gemini
    usd = 0.0 if (dry or body.dry_run) else images * providers.estimate_cost_per_image(provider)
    return {"pages": nums, "panels": panels, "images": images, "usd": round(usd, 3), "provider": provider, "dry_run": dry or body.dry_run}


def _parse_pages(raw: str | None, nxt: int | None) -> Any:
    if nxt:
        return {"next": nxt}
    if not raw:
        return None
    try:
        v = json.loads(raw)
        if isinstance(v, (list, dict)):
            return v
        return [int(v)]
    except (ValueError, TypeError):
        return [int(x) for x in raw.split(",") if x.strip()]


@app.get("/api/director/estimate")
def director_estimate_get(chapter_id: int, pages: str | None = None, next: int | None = None, candidates_per_panel: int = 2, provider: str | None = None,  # noqa: A002
                          prefill_text: bool = True, run_critic: bool = True, session: Session = S()) -> dict[str, Any]:
    return _estimate(session, BatchIn(chapter_id=chapter_id, pages=_parse_pages(pages, next), candidates_per_panel=candidates_per_panel, provider=provider, prefill_text=prefill_text, run_critic=run_critic))


@app.post("/api/director/estimate")
def director_estimate_post(body: BatchIn, session: Session = S()) -> dict[str, Any]:
    return _estimate(session, body)


@app.post("/api/director/batch", status_code=202)
def director_batch(body: BatchIn, session: Session = S()) -> dict[str, Any]:
    if session.get(Chapter, body.chapter_id) is None:
        raise HTTPException(404, "chapter not found")
    params = body.model_dump()
    params["provider"] = providers.normalise_provider(body.provider or llm.model_for("image"))
    est = _estimate(session, body)
    if not est["pages"]:
        raise HTTPException(422, "No pages selected for the batch.")
    params["estimate"] = est
    params["label"] = f"Director · pages {', '.join(map(str, est['pages']))} · {body.candidates_per_panel}/panel ({params['provider']})"
    return job_resp(jobs.submit(session, "batch", body.chapter_id, params))


# ---------------------------------------------------------------------------------
# media and the frontend
# ---------------------------------------------------------------------------------


# --- app version and updates (packaged Mac app) -----------------------------------------------------------
@app.get("/api/app/version")
def app_version() -> dict:
    from backend import updater

    return updater.current()


@app.get("/api/app/update/check")
def app_update_check() -> dict:
    from backend import updater

    return updater.check()


@app.get("/api/app/update/status")
def app_update_status() -> dict:
    from backend import updater

    return updater.status()


@app.post("/api/app/update/apply")
def app_update_apply() -> dict:
    from backend import updater

    return updater.apply_async()


# --- keys (desktop app: macOS Keychain; source checkout: .env) -------------------------------------------
_KEY_FIELDS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY", "topaz": "TOPAZ_API_KEY"}


@app.get("/api/settings/keys")
def get_keys() -> dict:
    import os

    return {"keys": settings.key_status(), "store": ("keychain" if os.environ.get("DHARMA_USE_KEYCHAIN") == "1" else "private file") if os.environ.get("DHARMA_DESKTOP") else ".env"}


@app.put("/api/settings/keys")
def put_keys(body: dict) -> dict:
    """Set or clear keys. Values are written to the Keychain (app) or .env (source) and applied live; they are
    never returned by any route."""
    import os

    desktop = bool(os.environ.get("DHARMA_DESKTOP"))
    for short, env_name in _KEY_FIELDS.items():
        if short not in body:
            continue
        val = (body.get(short) or "").strip() or None
        if desktop:
            stored = False
            if os.environ.get("DHARMA_USE_KEYCHAIN") == "1":  # opt-in; the default is the private file below
                try:
                    import keyring

                    if val:
                        keyring.set_password("Dharma Studio", env_name, val)
                    else:
                        try:
                            keyring.delete_password("Dharma Studio", env_name)
                        except Exception:  # noqa: BLE001
                            pass
                    stored = True
                except Exception:  # noqa: BLE001
                    stored = False
            if not stored:  # private keys.env next to the data, readable only by this user
                kf = db.DATA_DIR.parent / "keys.env"
                lines = kf.read_text().splitlines() if kf.exists() else []
                lines = [ln for ln in lines if not ln.startswith(env_name + "=")]
                if val:
                    lines.append(f"{env_name}={val}")
                kf.write_text("\n".join(lines) + "\n")
                kf.chmod(0o600)
        else:
            env_path = REPO_ROOT / ".env"
            lines = env_path.read_text().splitlines() if env_path.exists() else []
            lines = [ln for ln in lines if not ln.startswith(env_name + "=")]
            if val:
                lines.append(f"{env_name}={val}")
            env_path.write_text("\n".join(lines) + "\n")
        setattr(settings, short + "_api_key", val)
        if val:
            os.environ[env_name] = val
        else:
            os.environ.pop(env_name, None)
    return {"keys": settings.key_status(), "store": ("keychain" if os.environ.get("DHARMA_USE_KEYCHAIN") == "1" else "private file") if desktop else ".env"}


app.mount("/media", StaticFiles(directory=str(db.DATA_DIR)), name="media")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str, request: Request) -> Any:  # noqa: ARG001
    """The built frontend (frontend/dist) at /, with client-side routes falling back to index.html."""
    if full_path.startswith(("api/", "media/")):
        raise HTTPException(404, "not found")
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        return JSONResponse({"app": "Dharma Studio", "api": "/api", "docs": "/docs", "note": "build the frontend (cd frontend && npm run build) to serve the UI here"})
    f = (FRONTEND_DIST / full_path).resolve()
    if full_path and f.is_file() and FRONTEND_DIST.resolve() in f.parents:
        return FileResponse(f)
    return FileResponse(index)
