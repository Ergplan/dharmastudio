"""Art Director API — /api/art-director/* (an APIRouter included by backend/api.py).

GET  /guardrails                        the master prompt: raw text (verbatim) + parsed sections, ages, negatives, quality test
GET  /chapters                          chapters grouped by Book, keyed by MANUSCRIPT number, with age + palette
GET  /chapters/{id}                     manuscript text (paragraphs), setting, cast -> studio keys, pages
POST /brief/check                       deterministic validation of a scene brief (no model)
POST /estimate                          {brief, settings} -> images, usd, worst case
POST /direct                            {brief, settings} -> run + job ("Direct this page"); 409 when the brief is blocked
POST /direct-chapter                    {chapter_id, next, settings} -> run + job ("Direct next N pages")
GET  /runs?chapter_id&page_id           run summaries;  GET /runs/{id}  the full record
POST /runs/{id}/stop                    stop after the current image
GET  /covers                            one entry per volume
POST /covers/{volume_id}/compose        poster art prompt from the volume's chapters
POST /covers/{volume_id}/paint          {provider, n} -> job (art only, no text)
PUT  /covers/{volume_id}                {publisher, art_path}
POST /covers/{volume_id}/reference      upload the author's current cover (kept in the data dir)
POST /covers/{volume_id}/typeset        {art: painted|reference|none} -> PNG + PDF (300 ppi) + SVG
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.director import guardrails as G
from engine.director.brief import SceneBrief

from . import db, director as D, jobs
from .director_models import DirectorRun
from .models import Chapter, Job, Volume

router = APIRouter(prefix="/api/art-director", tags=["art-director"])


def S() -> Any:  # noqa: N802
    return Depends(db.get_session)


def _job_resp(j: Job) -> dict[str, Any]:
    from .api import job_resp

    return job_resp(j)


class LineIn(BaseModel):
    text: str
    kind: str = "dialogue"
    speaker: str | None = None
    adapted_approved: bool = False


class BriefIn(BaseModel):
    chapter_id: int
    action: str = ""
    characters: list[str] = Field(default_factory=list)
    setting: str = ""
    lines: list[LineIn] = Field(default_factory=list)
    page_id: int | None = None
    page_number: int | None = None
    age: str | None = None
    full_page: bool = False


class SettingsIn(BaseModel):
    candidates: int = Field(2, ge=1, le=4)
    retries: int = Field(2, ge=0, le=2)
    budget_usd: float = Field(3.0, ge=0.0, le=100.0)
    run_critic: bool = True
    provider: str | None = None


class DirectIn(BaseModel):
    brief: BriefIn
    settings: SettingsIn = Field(default_factory=SettingsIn)


class ChapterDirectIn(BaseModel):
    chapter_id: int
    next: int = Field(3, ge=1, le=20)
    settings: SettingsIn = Field(default_factory=SettingsIn)


def _brief(b: BriefIn) -> SceneBrief:
    return SceneBrief.from_json(b.model_dump())


@router.get("/guardrails")
def guardrails() -> dict[str, Any]:
    return G.load().to_json()


@router.get("/chapters")
def chapters(session: Session = S()) -> dict[str, Any]:
    return D.chapters_grouped(session)


@router.get("/chapters/{cid}")
def chapter(cid: int, session: Session = S()) -> dict[str, Any]:
    ch = session.get(Chapter, cid)
    if ch is None:
        raise HTTPException(404, "chapter not found")
    return D.chapter_detail(session, ch)


@router.post("/brief/check")
def brief_check(body: BriefIn, session: Session = S()) -> dict[str, Any]:
    if session.get(Chapter, body.chapter_id) is None:
        raise HTTPException(404, "chapter not found")
    return D.check_brief(session, _brief(body))


@router.post("/estimate")
def estimate(body: DirectIn, session: Session = S()) -> dict[str, Any]:
    if session.get(Chapter, body.brief.chapter_id) is None:
        raise HTTPException(404, "chapter not found")
    return D.estimate_for(session, _brief(body.brief), body.settings.model_dump())


@router.post("/direct", status_code=202)
def direct(body: DirectIn, session: Session = S()) -> Any:
    ch = session.get(Chapter, body.brief.chapter_id)
    if ch is None:
        raise HTTPException(404, "chapter not found")
    run, check = D.create_run(session, _brief(body.brief), body.settings.model_dump())
    if not check["can_paint"]:
        return JSONResponse({"detail": "; ".join(check["errors"]), "run": D.j_run(run), "check": check, "needs_reference": check["needs_reference"]}, status_code=409)
    label = f"Art Director · {run.manuscript.get('label', '')} · p.{body.brief.page_number or 'next'}"
    job = jobs.submit(session, "art_director", run.id, {"run_id": run.id, "label": label})
    run.job_id = job.id
    session.commit()
    return {**_job_resp(job), "run": D.j_run(run)}


@router.post("/direct-chapter", status_code=202)
def direct_chapter(body: ChapterDirectIn, session: Session = S()) -> Any:
    ch = session.get(Chapter, body.chapter_id)
    if ch is None:
        raise HTTPException(404, "chapter not found")
    mc = D.manuscript_of(ch)
    if not (mc.text or "").strip():
        raise HTTPException(409, "No manuscript text for this chapter yet: drop the book PDF in Project → Manuscript.")
    st = {**D.DEFAULTS, **body.settings.model_dump(), "next": body.next}
    st["provider"] = D.image_provider(st)
    run = DirectorRun(kind="chapter", status="queued", chapter_id=ch.id, manuscript={"label": mc.label, "number": mc.manuscript_number, "title": mc.title, "book": mc.book_title, "volume": mc.volume},
                      brief={"chapter_id": ch.id, "next": body.next}, settings=st, guardrails_sha=G.load().sha256, steps=[], prompts=[], candidates=[], flags=[], check={}, plan={})
    session.add(run)
    session.commit()
    job = jobs.submit(session, "art_director", run.id, {"run_id": run.id, "label": f"Art Director · {mc.label} · next {body.next} pages"})
    run.job_id = job.id
    session.commit()
    return {**_job_resp(job), "run": D.j_run(run)}


@router.get("/runs")
def runs(chapter_id: int | None = None, page_id: int | None = None, limit: int = 30, session: Session = S()) -> list[dict[str, Any]]:
    q = select(DirectorRun).order_by(DirectorRun.id.desc()).limit(limit)
    if chapter_id:
        q = q.where(DirectorRun.chapter_id == chapter_id)
    if page_id:
        q = q.where(DirectorRun.page_id == page_id)
    return [D.j_run(r, full=False) for r in session.scalars(q).all()]


@router.get("/runs/{rid}")
def run(rid: int, session: Session = S()) -> dict[str, Any]:
    r = session.get(DirectorRun, rid)
    if r is None:
        raise HTTPException(404, "run not found")
    out = D.j_run(r)
    if r.kind == "chapter":
        out["children"] = [D.j_run(c, full=False) for c in session.scalars(select(DirectorRun).where(DirectorRun.parent_id == r.id).order_by(DirectorRun.id)).all()]
    return out


@router.post("/runs/{rid}/stop")
def stop(rid: int, session: Session = S()) -> dict[str, Any]:
    r = session.get(DirectorRun, rid)
    if r is None:
        raise HTTPException(404, "run not found")
    if r.job_id:
        j = session.get(Job, r.job_id)
        if j is not None and j.status in ("queued", "running"):
            j.stop = True
            if j.status == "queued":
                j.status = "stopped"
                r.status = "stopped"
            session.commit()
    return D.j_run(r, full=False)


# --- covers -----------------------------------------------------------------------------------------------------


def _volume(session: Session, vid: int) -> Volume:
    v = session.get(Volume, vid)
    if v is None:
        raise HTTPException(404, "volume not found")
    return v


class CoverIn(BaseModel):
    publisher: str | None = None
    art_path: str | None = None


class CoverPaintIn(BaseModel):
    provider: str | None = None
    n: int = Field(2, ge=1, le=4)


class TypesetIn(BaseModel):
    art: str = "painted"  # painted | reference | none


@router.get("/covers")
def covers(session: Session = S()) -> list[dict[str, Any]]:
    out = [D.j_cover(session, v) for v in session.scalars(select(Volume).order_by(Volume.number)).all()]
    session.commit()
    return out


@router.post("/covers/{vid}/compose")
def cover_compose(vid: int, session: Session = S()) -> dict[str, Any]:
    v = _volume(session, vid)
    D.compose_cover(session, v)
    return D.j_cover(session, v)


@router.post("/covers/{vid}/paint", status_code=202)
def cover_paint(vid: int, body: CoverPaintIn, session: Session = S()) -> dict[str, Any]:
    v = _volume(session, vid)
    job = jobs.submit(session, "art_cover", v.id, {"volume_id": v.id, "provider": body.provider, "n": body.n, "label": f"Cover · Volume {v.number} · {body.n} art"})
    return _job_resp(job)


@router.put("/covers/{vid}")
def cover_put(vid: int, body: CoverIn, session: Session = S()) -> dict[str, Any]:
    v = _volume(session, vid)
    c = D.cover_row(session, v)
    if body.publisher is not None:
        c.publisher = body.publisher.strip()
    if body.art_path is not None:
        if body.art_path and body.art_path not in [a.get("path") for a in c.art_candidates or []]:
            raise HTTPException(422, "art_path must be one of the painted candidates")
        c.art_path = body.art_path or None
    session.commit()
    return D.j_cover(session, v)


@router.post("/covers/{vid}/reference", status_code=201)
async def cover_reference(vid: int, file: UploadFile = File(...), session: Session = S()) -> dict[str, Any]:
    v = _volume(session, vid)
    raw = await file.read()
    from io import BytesIO

    from PIL import Image

    try:
        with Image.open(BytesIO(raw)) as im:
            im.load()
            rgb = im.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"not an image: {exc}") from exc
    dst = D.cover_dir(v) / "reference_current_cover.png"
    rgb.save(dst, "PNG")
    c = D.cover_row(session, v)
    c.reference_path = db.rel(dst)
    session.commit()
    return D.j_cover(session, v)


@router.post("/covers/{vid}/typeset")
def cover_typeset(vid: int, body: TypesetIn, session: Session = S()) -> dict[str, Any]:
    v = _volume(session, vid)
    D.typeset_cover(session, v, body.art)
    return D.j_cover(session, v)
