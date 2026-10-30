"""MOTION, SEEDANCE and SITE routes (an APIRouter included by backend/api.py), plus the local site preview at
/site-preview/."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.motion import kenburns as KB
from engine.motion import providers as SP
from engine.motion import tts

from . import db, jobs, links, motion, qr_api, site_gen
from .models import Job, Page, Panel
from .motion_models import Link, Moment, MotionTake, QRCode

jobs.HANDLERS.update({"site_publish": site_gen.h_site_publish})

router = APIRouter(tags=["motion"])


def S() -> Any:  # noqa: N802
    return Depends(db.get_session)


def _job(j: Job) -> dict[str, Any]:
    from .api import job_resp

    return job_resp(j)


def _merr(e: motion.MotionError) -> HTTPException:
    return HTTPException(e.status, str(e))


def _moment(session: Session, mid: int) -> Moment:
    m = session.get(Moment, mid)
    if m is None:
        raise HTTPException(404, "moment not found")
    return m


# ---------------------------------------------------------------------------------
# health / options
# ---------------------------------------------------------------------------------


@router.get("/api/motion/health")
def motion_health() -> dict[str, Any]:
    return motion.health()


@router.get("/api/motion/options")
def motion_options() -> dict[str, Any]:
    return {"moves": [{"id": m, "label": KB.MOVE_LABELS[m]} for m in KB.MOVES], "camera_presets": [{"id": k, "label": KB.MOVE_LABELS.get(k, k), "text": v} for k, v in SP.CAMERA_PRESETS.items()],
            "providers": [{"id": "fal", "label": "fal.ai", "key": SP.keys()["fal"]}, {"id": "byteplus", "label": "BytePlus ModelArk", "key": SP.keys()["byteplus"]}],
            "resolutions": list(SP.RESOLUTIONS), "aspects": list(SP.ASPECTS), "durations": [5, 6, 7, 8, 9, 10],
            "voice": {"elevenlabs": tts.available(), "default_voice_id": tts.DEFAULT_VOICE}, "total_s": 30, "title_s": 1.5, "end_s": 2.0}


# ---------------------------------------------------------------------------------
# moments
# ---------------------------------------------------------------------------------


class MomentIn(BaseModel):
    page_id: int | None = None
    code: str | None = None
    title_en: str | None = None
    title_hi: str | None = None
    shots: list[dict[str, Any]] | None = None
    narration_en: str | None = None
    narration_hi: str | None = None
    voice: str | None = None
    voice_id: str | None = None
    qr_id: int | None = None


class RenderIn(BaseModel):
    size: str = "full"  # full | preview | tiny
    variants: list[str] | None = None  # en_16x9 …


class PublishIn(BaseModel):
    deploy: bool = True


class MomentQRIn(BaseModel):
    style: dict[str, Any] | None = None
    place: bool = False
    test: bool = True


@router.get("/api/moments")
def list_moments(session: Session = S()) -> list[dict[str, Any]]:
    return [motion.j_moment(session, m) for m in session.scalars(select(Moment).order_by(Moment.id)).all()]


@router.post("/api/moments", status_code=201)
def create_moment(body: MomentIn, session: Session = S()) -> dict[str, Any]:
    page = session.get(Page, body.page_id or 0)
    if page is None:
        raise HTTPException(404, "page not found")
    try:
        m = motion.create_moment(session, page, body.code, body.title_en, body.title_hi)
    except motion.MotionError as e:
        session.rollback()
        raise _merr(e) from e
    session.commit()
    return motion.j_moment(session, m)


@router.get("/api/pages/{pid}/moment")
def page_moment(pid: int, session: Session = S()) -> Any:
    m = session.scalar(select(Moment).where(Moment.page_id == pid))
    return motion.j_moment(session, m) if m else None


@router.get("/api/moments/{mid}")
def get_moment(mid: int, session: Session = S()) -> dict[str, Any]:
    return motion.j_moment(session, _moment(session, mid))


@router.put("/api/moments/{mid}")
def put_moment(mid: int, body: MomentIn, session: Session = S()) -> dict[str, Any]:
    m = _moment(session, mid)
    try:
        motion.update_moment(session, m, body.model_dump(exclude_unset=True))
    except motion.MotionError as e:
        session.rollback()
        raise _merr(e) from e
    session.commit()
    return motion.j_moment(session, m)


@router.delete("/api/moments/{mid}")
def delete_moment(mid: int, session: Session = S()) -> dict[str, Any]:
    m = _moment(session, mid)
    if m.status == "published":
        raise HTTPException(409, "unpublish first")
    session.delete(m)
    session.commit()
    return {"ok": True}


@router.post("/api/moments/{mid}/render", status_code=202)
def render_moment(mid: int, body: RenderIn | None = None, session: Session = S()) -> dict[str, Any]:
    m = _moment(session, mid)
    body = body or RenderIn()
    try:
        motion.shot_specs(session, m)
    except motion.MotionError as e:
        raise _merr(e) from e
    j = jobs.submit(session, "motion_render", m.id, {"size": body.size, "variants": body.variants, "label": f"Moment {m.id} film"})
    return _job(j)


@router.post("/api/moments/{mid}/approve")
def approve_moment(mid: int, session: Session = S()) -> dict[str, Any]:
    m = _moment(session, mid)
    try:
        motion.approve(session, m)
    except motion.MotionError as e:
        raise _merr(e) from e
    session.commit()
    return motion.j_moment(session, m)


@router.post("/api/moments/{mid}/publish")
def publish_moment(mid: int, request: Request, body: PublishIn | None = None, session: Session = S()) -> dict[str, Any]:
    m = _moment(session, mid)
    try:
        motion.publish(session, m)
    except motion.MotionError as e:
        raise _merr(e) from e
    session.commit()
    j = jobs.submit(session, "site_publish", None, {"publish": bool((body or PublishIn()).deploy), "origin": str(request.base_url).rstrip("/"), "label": "Site publish"})
    return {"moment": motion.j_moment(session, m), **_job(j)}


@router.post("/api/moments/{mid}/unpublish")
def unpublish_moment(mid: int, session: Session = S()) -> dict[str, Any]:
    m = _moment(session, mid)
    if m.status == "published":
        m.status = "approved"
    session.commit()
    return motion.j_moment(session, m)


@router.post("/api/moments/{mid}/music")
async def moment_music(mid: int, file: UploadFile = File(...), session: Session = S()) -> dict[str, Any]:
    m = _moment(session, mid)
    raw = await file.read()
    ext = Path(file.filename or "music.mp3").suffix.lower() or ".mp3"
    if ext not in (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"):
        raise HTTPException(422, "upload an audio file (mp3, m4a, wav, ogg, flac)")
    p = motion.motion_dir("music") / f"m{m.id}-{hashlib.sha1(raw).hexdigest()[:10]}{ext}"
    p.write_bytes(raw)
    m.music_path = db.rel(p)
    session.commit()
    return motion.j_moment(session, m)


@router.delete("/api/moments/{mid}/music")
def moment_music_delete(mid: int, session: Session = S()) -> dict[str, Any]:
    m = _moment(session, mid)
    m.music_path = None
    session.commit()
    return motion.j_moment(session, m)


@router.post("/api/moments/{mid}/qr")
def moment_qr(mid: int, body: MomentQRIn | None = None, session: Session = S()) -> dict[str, Any]:
    """The moment's QR: create (on its link) if missing, run the decode test, optionally place it on the page."""
    body = body or MomentQRIn()
    m = _moment(session, mid)
    if not m.link_id:
        raise HTTPException(409, "the moment has no link")
    q = session.get(QRCode, m.qr_id) if m.qr_id else None
    if q is None:
        q = session.scalar(select(QRCode).where(QRCode.link_id == m.link_id).order_by(QRCode.id))
    from engine import qr as Q

    if q is None:
        page = session.get(Page, m.page_id)
        style = {"colour": qr_api.ink_for_volume(session, page), **(body.style or {})}
        q = QRCode(link_id=m.link_id, name=session.get(Link, m.link_id).code, style=Q.QRStyle.from_dict(style).json())
        session.add(q)
        session.flush()
    elif body.style:
        q.style = Q.QRStyle.from_dict({**(q.style or {}), **body.style}).json()
    m.qr_id = q.id
    if body.test:
        qr_api.run_test(session, q)
    if body.place:
        qr_api.place(session, q, session.get(Page, m.page_id))
    session.commit()
    return {"moment": motion.j_moment(session, m), "qr": qr_api.j_qr(session, q)}


# ---------------------------------------------------------------------------------
# Seedance
# ---------------------------------------------------------------------------------


class TakeIn(BaseModel):
    panel_id: int | None = None
    still_path: str | None = None
    prompt: str | None = None
    duration: int = 5
    resolution: str = "1080p"
    aspect: str = "16:9"
    seed: int | None = None
    camera: str = "push_in"
    provider: str = "fal"
    dry_run: bool = False
    dry_size: list[int] | None = None


class PromptIn(BaseModel):
    panel_id: int | None = None
    scene: str | None = None
    camera: str = "push_in"


class SendIn(BaseModel):
    moment_id: int


class TakeNoteIn(BaseModel):
    notes: str | None = None


@router.get("/api/seedance/estimate")
def seedance_estimate(provider: str = "fal", duration: int = 5, resolution: str = "1080p") -> dict[str, Any]:
    return SP.estimate(provider if provider in SP.PROVIDERS else "fal", max(5, min(10, duration)), resolution if resolution in SP.RESOLUTIONS else "1080p")


@router.post("/api/seedance/prompt")
def seedance_prompt(body: PromptIn, session: Session = S()) -> dict[str, Any]:
    panel = session.get(Panel, body.panel_id) if body.panel_id else None
    scene = body.scene if body.scene is not None else (panel.scene if panel else "")
    return SP.write_prompt(scene, body.camera, list(panel.characters or []) if panel else [])


@router.post("/api/seedance/upload", status_code=201)
async def seedance_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    from PIL import Image

    raw = await file.read()
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, "upload an image") from exc
    p = motion.motion_dir("stills") / f"still-{hashlib.sha1(raw).hexdigest()[:12]}.jpg"
    im.save(p, "JPEG", quality=94)
    return {"still_path": db.rel(p), "url": db.media_url(db.rel(p)), "width": im.width, "height": im.height}


@router.get("/api/seedance/takes")
def list_takes(panel_id: int | None = None, session: Session = S()) -> list[dict[str, Any]]:
    q = select(MotionTake).order_by(MotionTake.id.desc())
    if panel_id:
        q = q.where(MotionTake.panel_id == panel_id)
    return [motion.j_take(session, t) for t in session.scalars(q.limit(200)).all()]


@router.post("/api/seedance/takes", status_code=202)
def create_take(body: TakeIn, session: Session = S()) -> dict[str, Any]:
    try:
        t = motion.new_take(session, body.model_dump())
    except motion.MotionError as e:
        session.rollback()
        raise _merr(e) from e
    session.commit()
    j = jobs.submit(session, "seedance", t.id, {"dry_run": body.dry_run, "label": f"Seedance take {t.id}"})
    t.job_id = j.id
    session.commit()
    return {"take": motion.j_take(session, t), **_job(j)}


@router.get("/api/seedance/takes/{tid}")
def get_take(tid: int, session: Session = S()) -> dict[str, Any]:
    t = session.get(MotionTake, tid)
    if t is None:
        raise HTTPException(404, "take not found")
    return motion.j_take(session, t)


@router.put("/api/seedance/takes/{tid}")
def put_take(tid: int, body: TakeNoteIn, session: Session = S()) -> dict[str, Any]:
    t = session.get(MotionTake, tid)
    if t is None:
        raise HTTPException(404, "take not found")
    if body.notes is not None:
        t.notes = body.notes
    session.commit()
    return motion.j_take(session, t)


@router.post("/api/seedance/takes/{tid}/send")
def send_take(tid: int, body: SendIn, session: Session = S()) -> dict[str, Any]:
    t = session.get(MotionTake, tid)
    if t is None:
        raise HTTPException(404, "take not found")
    m = _moment(session, body.moment_id)
    try:
        motion.send_to_moment(session, t, m)
    except motion.MotionError as e:
        session.rollback()
        raise _merr(e) from e
    session.commit()
    return {"moment": motion.j_moment(session, m), "take": motion.j_take(session, t)}


# ---------------------------------------------------------------------------------
# site
# ---------------------------------------------------------------------------------


class SiteSettingsIn(BaseModel):
    site_url: str | None = None
    media_base: str | None = None


@router.get("/api/site")
def site_state(session: Session = S()) -> dict[str, Any]:
    from .motion_models import SitePublish

    prev = site_gen.site_dir() / "preview" / "index.html"
    rows = session.scalars(select(SitePublish).order_by(SitePublish.id.desc()).limit(10)).all()
    pub = site_gen.publishing(session)
    return {**pub, "checklist": site_gen.CHECKLIST, "preview_url": "/site-preview/" if prev.exists() else None,
            "published_moments": len(site_gen.published_moments(session)), "links": session.query(Link).count(),
            "history": [{"id": r.id, "kind": r.kind, "ok": r.ok, "at": r.created_at.isoformat() if r.created_at else None, **(r.result or {})} for r in rows]}


@router.put("/api/site/settings")
def site_settings(body: SiteSettingsIn, session: Session = S()) -> dict[str, Any]:
    if body.site_url is not None and body.site_url and not links.is_url(body.site_url):
        raise HTTPException(422, "site URL must be http(s)")
    if body.media_base and not links.is_url(body.media_base):
        raise HTTPException(422, "media base must be an http(s) URL (or empty)")
    site_gen.set_publishing(session, body.site_url, body.media_base)
    session.commit()
    return site_gen.publishing(session)


@router.post("/api/site/secret")
def site_secret() -> dict[str, Any]:
    """Generate REVALIDATE_SECRET, store it with the keys, and show it once (paste it into Vercel's env vars)."""
    from .api import put_keys

    val = site_gen.new_secret()
    put_keys({"revalidate": val})
    return {"secret": val, "note": "Shown once. Paste it into Vercel → Project → Settings → Environment Variables as REVALIDATE_SECRET."}


@router.post("/api/site/preview")
def site_preview(request: Request, session: Session = S()) -> dict[str, Any]:
    res = site_gen.build_static(session, origin=str(request.base_url).rstrip("/"))
    session.commit()
    return {"url": "/site-preview/", "manifest_url": "/site-preview/manifest.json", **{k: v for k, v in res.items() if k != "manifest"}}


@router.get("/api/site/manifest")
def site_manifest(request: Request, session: Session = S()) -> dict[str, Any]:
    origin = str(request.base_url).rstrip("/")
    return site_gen.build_manifest(session, lambda code, key, rel: f"{origin}/media/{rel}")


@router.post("/api/site/publish", status_code=202)
def site_publish(request: Request, session: Session = S()) -> dict[str, Any]:
    j = jobs.submit(session, "site_publish", None, {"publish": True, "origin": str(request.base_url).rstrip("/"), "label": "Site publish"})
    return _job(j)


@router.post("/api/site/export")
def site_export(session: Session = S()) -> dict[str, Any]:
    p = site_gen.export_zip(session)
    session.commit()
    return {"url": db.media_url(db.rel(p)), "bytes": p.stat().st_size}


@router.get("/site-preview", include_in_schema=False)
@router.get("/site-preview/{path:path}", include_in_schema=False)
def site_preview_files(path: str = "") -> Response:
    root = (site_gen.site_dir() / "preview").resolve()
    if not (root / "index.html").exists():
        return HTMLResponse("<p>No preview yet — build it from the Site panel.</p>", status_code=404)
    f = (root / path).resolve()
    if root not in f.parents and f != root:
        raise HTTPException(404, "not found")
    if f.is_dir():
        f = f / "index.html"
    if not f.exists():
        return FileResponse(root / "404.html", status_code=404, media_type="text/html")
    if f.name == "manifest.json":
        return FileResponse(f, media_type="application/json", headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"})
    return FileResponse(f, headers={"Access-Control-Allow-Origin": "*"})

