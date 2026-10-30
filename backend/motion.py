"""MOTION — moments (a page carrying a 30-second film made from its approved panels) and Seedance takes.

Rendering runs on the studio's job worker (backend.jobs): kinds `motion_render` (a moment -> EN/HI x 16:9/9:16 MP4s
+ posters) and `seedance` (one take). Narration via ElevenLabs when a key is present; otherwise none (captions are
timed by length). Every take and narration is costed into the ledger.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.motion import assemble as A
from engine.motion import ffmpeg as FF
from engine.motion import kenburns as KB
from engine.motion import providers as SP
from engine.motion import tts

from . import db, jobs, links
from .models import Candidate, Ledger, Page, Panel
from .motion_models import Link, Moment, MotionTake, QRCode

STATUSES = ("draft", "rendering", "review", "approved", "published")
VARIANTS = (("en", "16x9"), ("en", "9x16"), ("hi", "16x9"), ("hi", "9x16"))
SIZES = {"full": {"16x9": (1920, 1080), "9x16": (1080, 1920)}, "preview": {"16x9": (960, 540), "9x16": (540, 960)},
         "tiny": {"16x9": (256, 144), "9x16": (144, 256)}}
DEFAULT_MOVES = ("push_in", "parallax", "pan", "pull_out", "crane", "orbit")
TEXTURE = Path(__file__).resolve().parent.parent / "engine" / "textures" / "page_warm.jpg"
HI_BOOK = "द साइकिल ऑफ़ धर्म"


class MotionError(ValueError):
    def __init__(self, msg: str, status: int = 422) -> None:
        super().__init__(msg)
        self.status = status


def motion_dir(*parts: str) -> Path:
    d = db.DATA_DIR.joinpath("motion", *parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def ledger(session: Session, provider: str, usd: float, ref: str) -> None:
    if usd:
        session.add(Ledger(provider=provider, usd=round(float(usd), 4), ref=ref))


# ---------------------------------------------------------------------------------
# moments
# ---------------------------------------------------------------------------------


def panel_still(session: Session, panel: Panel) -> Path | None:
    if not panel.selected_candidate_id:
        return None
    c = session.get(Candidate, panel.selected_candidate_id)
    p = db.abs_path(c.path) if c else None
    return p if p and p.exists() else None


def panel_focal(panel: Panel) -> tuple[float, float]:
    f = (panel.shape or {}).get("focal") or {}
    try:
        x, y = float(f.get("x", 0.5)), float(f.get("y", 0.5))
        return (min(1, max(0, x)), min(1, max(0, y))) if 0 <= x <= 1 and 0 <= y <= 1 else (0.5, 0.5)
    except (TypeError, ValueError):
        return (0.5, 0.5)


def default_shots(session: Session, page: Page) -> list[dict[str, Any]]:
    out = []
    for i, p in enumerate([p for p in page.panels if panel_still(session, p)]):
        fx, fy = panel_focal(p)
        out.append({"panel_id": p.id, "source": "kenburns", "duration_s": 6, "move": DEFAULT_MOVES[i % len(DEFAULT_MOVES)], "focal": {"x": fx, "y": fy}})
    return out


def default_narration(page: Page, lang: str) -> str:
    key = "caption_hi" if lang == "hi" else "caption_en"
    return " ".join(" ".join((getattr(p, key) or "").split()) for p in page.panels if getattr(p, key)).strip()


def create_moment(session: Session, page: Page, code: str | None = None, title_en: str | None = None, title_hi: str | None = None) -> Moment:
    if session.scalar(select(Moment).where(Moment.page_id == page.id)):
        raise MotionError(f"page {page.number} is already a moment", 409)
    shots = default_shots(session, page)
    if not shots:
        raise MotionError("this page has no selected panel images yet — pick candidates first")
    m = Moment(page_id=page.id, title_en=title_en or page.chapter.title or f"Page {page.number}", title_hi=title_hi or "",
               shots=shots, narration_en=default_narration(page, "en"), narration_hi=default_narration(page, "hi"), status="draft", outputs={}, render_meta={})
    session.add(m)
    session.flush()
    want = code or links.page_code(page)
    link = session.scalar(select(Link).where(Link.code == want))
    if link is not None and link.target_type == "page" and link.target_ref == str(page.id):
        link.target_type, link.target_ref = "moment", str(m.id)  # an existing page link now points at its moment
    elif link is None or code is None:
        try:
            link = links.create(session, "moment", str(m.id), want if link is None else None)
        except links.LinkError as e:
            raise MotionError(str(e), e.status) from e
    else:
        raise MotionError(f"code '{want}' is already used", 409)
    m.link_id = link.id
    session.flush()
    return m


def validate_shots(session: Session, shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for s in shots or []:
        src = s.get("source") or ("seedance" if s.get("take_id") else "kenburns")
        d = float(s.get("duration_s", 6))
        if not 5 <= d <= 10:
            raise MotionError("each shot is 5–10 s")
        mv = s.get("move") or "push_in"
        if mv not in KB.MOVES:
            raise MotionError(f"move must be one of {KB.MOVES}")
        item = {"source": src, "duration_s": d, "move": mv, "focal": s.get("focal") or {"x": 0.5, "y": 0.5}}
        if src == "seedance":
            t = session.get(MotionTake, int(s.get("take_id") or 0))
            if t is None or t.status != "done" or not t.path:
                raise MotionError(f"take {s.get('take_id')} is not ready")
            item["take_id"] = t.id
            if t.panel_id:
                item["panel_id"] = t.panel_id
        else:
            p = session.get(Panel, int(s.get("panel_id") or 0))
            if p is None or not panel_still(session, p):
                raise MotionError(f"panel {s.get('panel_id')} has no selected image")
            item["panel_id"] = p.id
        out.append(item)
    return out


def shot_specs(session: Session, m: Moment) -> list[A.ShotSpec]:
    specs = []
    for i, s in enumerate(m.shots or []):
        f = s.get("focal") or {}
        focal = (float(f.get("x", 0.5)), float(f.get("y", 0.5)))
        if s.get("source") == "seedance" and s.get("take_id"):
            t = session.get(MotionTake, s["take_id"])
            if t and t.path and db.abs_path(t.path).exists():
                specs.append(A.ShotSpec(kind="video", video=db.abs_path(t.path), duration=float(s.get("duration_s", 6))))
                continue
        p = session.get(Panel, s.get("panel_id") or 0)
        still = panel_still(session, p) if p else None
        if still is None:
            raise MotionError(f"shot {i + 1}: no image")
        specs.append(A.ShotSpec(kind="kenburns", image=still, move=s.get("move", "push_in"), duration=float(s.get("duration_s", 6)), focal=focal,
                                direction=1 if i % 2 == 0 else -1))
    if not specs:
        raise MotionError("the moment has no shots")
    return specs


def total_seconds(m: Moment) -> dict[str, Any]:
    want = sum(float(s.get("duration_s", 6)) for s in m.shots or [])
    k = len(m.shots or []) + 2
    avail = A.TOTAL_S - A.TITLE_S - A.END_S + (k - 1) * A.XFADE / FF.FPS
    return {"shots_s": round(want, 2), "available_s": round(avail, 2), "scale": round(avail / want, 3) if want else 0, "title_s": A.TITLE_S, "end_s": A.END_S, "total_s": A.TOTAL_S}


def j_moment(session: Session, m: Moment) -> dict[str, Any]:
    page = session.get(Page, m.page_id)
    link = session.get(Link, m.link_id) if m.link_id else None
    q = session.get(QRCode, m.qr_id) if m.qr_id else None
    if q is None and link is not None:
        q = session.scalar(select(QRCode).where(QRCode.link_id == link.id).order_by(QRCode.id))
    from . import qr_api

    shots = []
    for s in m.shots or []:
        thumb = None
        if s.get("take_id"):
            t = session.get(MotionTake, s["take_id"])
            thumb = db.media_url(t.thumb) if t and t.thumb else None
        if thumb is None and s.get("panel_id"):
            p = session.get(Panel, s["panel_id"])
            c = session.get(Candidate, p.selected_candidate_id) if p and p.selected_candidate_id else None
            thumb = db.media_url(c.path) if c else None
        shots.append({**s, "thumb": thumb})
    return {
        "id": m.id, "page_id": m.page_id, "page": page.number if page else None, "chapter": page.chapter.number if page else None, "chapter_id": page.chapter_id if page else None,
        "volume": page.chapter.volume.number if page else None, "chapter_title": page.chapter.title if page else "",
        "link_id": m.link_id, "code": link.code if link else None, "short_url": links.short_url(link.code) if link else None,
        "link_locked": bool(link and link.print_locked), "qr_id": q.id if q else None, "qr_tested": qr_api.is_tested(session, q) if q else False,
        "title_en": m.title_en, "title_hi": m.title_hi, "shots": shots, "narration_en": m.narration_en, "narration_hi": m.narration_hi,
        "voice": m.voice, "voice_id": m.voice_id, "music_path": m.music_path, "music_url": db.media_url(m.music_path) if m.music_path else None,
        "status": m.status, "outputs": {k: db.media_url(v) for k, v in (m.outputs or {}).items()}, "render_meta": m.render_meta or {},
        "timing": total_seconds(m), "published_at": m.published_at.isoformat() if m.published_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def update_moment(session: Session, m: Moment, body: dict[str, Any]) -> Moment:
    if m.status == "published" and any(k in body for k in ("shots", "narration_en", "narration_hi", "title_en", "title_hi")):
        m.status = "review"  # edits after publishing need a re-render/re-approve; the site keeps the old files until then
    if "shots" in body and body["shots"] is not None:
        m.shots = validate_shots(session, body["shots"])
        if m.status in ("approved",):
            m.status = "review"
    for k in ("title_en", "title_hi", "narration_en", "narration_hi", "voice_id", "music_path"):
        if k in body and body[k] is not None:
            setattr(m, k, body[k])
    if "voice" in body and body["voice"] is not None:
        if body["voice"] not in ("none", "elevenlabs"):
            raise MotionError("voice is none | elevenlabs")
        m.voice = body["voice"]
    if "qr_id" in body:
        m.qr_id = body["qr_id"]
    session.flush()
    return m


def approve(session: Session, m: Moment) -> Moment:
    missing = [f"{l}_{a}" for l, a in VARIANTS if not (m.outputs or {}).get(f"{l}_{a}")]
    if missing:
        raise MotionError(f"render first (missing {', '.join(missing)})", 409)
    m.status = "approved"
    session.flush()
    return m


def check_publishable(session: Session, m: Moment) -> None:
    from . import qr_api

    if m.status not in ("approved", "published"):
        raise MotionError("approve the moment before publishing", 409)
    if not m.link_id:
        raise MotionError("the moment has no short link", 409)
    qrs = session.scalars(select(QRCode).where(QRCode.link_id == m.link_id)).all()
    bad = [q.id for q in qrs if not qr_api.is_tested(session, q)]
    if bad:
        raise MotionError(f"QR {', '.join('#' + str(b) for b in bad)} for this link has not passed the decode test — test it before publishing", 409)


def publish(session: Session, m: Moment) -> Moment:
    check_publishable(session, m)
    m.status = "published"
    m.published_at = datetime.now(timezone.utc)
    session.flush()
    return m


# ---------------------------------------------------------------------------------
# render job
# ---------------------------------------------------------------------------------


def _narration(session: Session, m: Moment, lang: str, log: Any) -> tuple[Path | None, list | None, float, float]:
    text = (m.narration_hi if lang == "hi" else m.narration_en) or ""
    if m.voice != "elevenlabs" or not text.strip() or not tts.available():
        return None, None, 0.0, 0.0
    voice = m.voice_id or ""
    h = hashlib.sha1(f"{voice}|{lang}|{text}".encode()).hexdigest()[:12]
    p = motion_dir("narration") / f"m{m.id}-{lang}-{h}.mp3"
    meta = p.with_suffix(".json")
    import json

    if p.exists() and meta.exists():
        d = json.loads(meta.read_text())
        return p, [tuple(w) for w in d["words"]], float(d["duration"]), 0.0
    res = tts.synthesize(text, p, voice or None, lang)
    meta.write_text(json.dumps({"words": res["words"], "duration": res["duration"]}, ensure_ascii=False))
    ledger(session, "elevenlabs", res["cost_usd"], f"moment {m.id} narration {lang}")
    log(f"narration {lang}: {res['duration']:.1f} s (${res['cost_usd']:.3f})")
    return p, res["words"], float(res["duration"]), float(res["cost_usd"])


def film_spec(session: Session, m: Moment, lang: str, aspect: str, size: tuple[int, int], quality: str, shots: list[A.ShotSpec],
              narr: Path | None, words: list | None) -> A.FilmSpec:
    page = session.get(Page, m.page_id)
    link = session.get(Link, m.link_id) if m.link_id else None
    vol = page.chapter.volume.number
    code = link.code if link else links.page_code(page)
    url = links.short_url(code).replace("https://", "").replace("http://", "")
    if lang == "hi":
        title = m.title_hi or m.title_en
        sub = f"{HI_BOOK} — पुस्तक {vol}, पृष्ठ {page.number}"
        end_line = "और क्षण देखें"
    else:
        title = m.title_en
        sub = f"From The Cycle of Dharma — Book {vol}, page {page.number}"
        end_line = "Watch more moments"
    return A.FilmSpec(code=code, lang=lang, size=size, shots=shots, title=title, subtitle=sub, end_url=url, end_line=end_line,
                      narration_text=(m.narration_hi if lang == "hi" else m.narration_en) or "", narration_audio=narr, word_times=words,
                      music=db.abs_path(m.music_path) if m.music_path else None, texture=TEXTURE, quality=quality)


def render_moment(session: Session, m: Moment, size_key: str = "full", variants: list[tuple[str, str]] | None = None, log: Any = print,
                  progress: Any = None) -> dict[str, Any]:
    sizes = SIZES.get(size_key, SIZES["full"])
    quality = "full" if size_key == "full" else "draft"
    variants = variants or list(VARIANTS)
    shots = shot_specs(session, m)
    page = session.get(Page, m.page_id)
    link = session.get(Link, m.link_id) if m.link_id else None
    code = link.code if link else links.page_code(page)
    out_dir = motion_dir("moments", code)
    outputs = dict(m.outputs or {})
    meta: dict[str, Any] = {"variants": {}, "size": size_key, "rendered_at": datetime.now(timezone.utc).isoformat()}
    narrs: dict[str, tuple] = {}
    for i, (lang, aspect) in enumerate(variants):
        if lang not in narrs:
            narrs[lang] = _narration(session, m, lang, log)
        narr, words, ndur, _cost = narrs[lang]
        spec = film_spec(session, m, lang, aspect, sizes[aspect], quality, shots, narr, words)
        out = out_dir / f"{lang}-{aspect}.mp4"
        poster = None
        if lang == variants[0][0]:
            poster = out_dir / ("poster.jpg" if aspect == "16x9" else "poster-9x16.jpg")
        log(f"render {lang} {aspect} {sizes[aspect][0]}x{sizes[aspect][1]}")
        info = A.assemble(spec, out, poster, (lambda f, i=i: progress(i + f, len(variants))) if progress else None, narr_dur=ndur)
        outputs[f"{lang}_{aspect}"] = db.rel(out)
        if poster is not None and poster.exists():
            outputs["poster" if aspect == "16x9" else "poster_9x16"] = db.rel(poster)
        meta["variants"][f"{lang}_{aspect}"] = {k: info.get(k) for k in ("duration", "width", "height", "bytes", "has_audio", "frames", "kbps")}
        meta.setdefault("cues", {})[lang] = info.get("cues")
        meta["shot_seconds"] = [round(x, 2) for x in A.shot_seconds(spec)]
        log(f"  {info['duration']:.2f} s, {info['bytes'] / 1e6:.1f} MB")
    m.outputs = outputs
    m.render_meta = meta
    session.flush()
    return {"outputs": outputs, "meta": meta}


def h_motion_render(ctx: Any, p: dict[str, Any]) -> dict[str, Any]:
    m = ctx.session.get(Moment, ctx.job.ref_id)
    if m is None:
        raise ValueError("moment not found")
    prev = m.status
    m.status = "rendering"
    ctx.session.commit()
    variants = [tuple(v.split("_")) for v in p.get("variants") or []] or None
    try:
        res = render_moment(ctx.session, m, p.get("size", "full"), variants, ctx.log,
                            lambda done, total: ctx.progress(done=round(done * 100), total=total * 100))
    except Exception:
        m.status = prev if prev != "rendering" else "draft"
        ctx.session.commit()
        raise
    m.status = "review"
    ctx.session.commit()
    return {"moment_id": m.id, **res}


# ---------------------------------------------------------------------------------
# Seedance takes
# ---------------------------------------------------------------------------------


def take_still(session: Session, t: MotionTake) -> Path:
    if t.still_path:
        p = db.abs_path(t.still_path)
        if p and p.exists():
            return p
    if t.panel_id:
        p = panel_still(session, session.get(Panel, t.panel_id))
        if p:
            return p
    raise MotionError("the take has no still image")


def j_take(session: Session, t: MotionTake) -> dict[str, Any]:
    return {"id": t.id, "panel_id": t.panel_id, "still_url": db.media_url(t.still_path) if t.still_path else None, "prompt": t.prompt, "params": t.params or {},
            "provider": t.provider, "model": t.model, "cost_usd": t.cost_usd, "url": db.media_url(t.path) if t.path else None,
            "thumb": db.media_url(t.thumb) if t.thumb else None, "seed": t.seed, "dry_run": t.dry_run, "status": t.status, "job_id": t.job_id,
            "picked": t.picked, "notes": t.notes, "created_at": t.created_at.isoformat() if t.created_at else None}


def new_take(session: Session, body: dict[str, Any]) -> MotionTake:
    panel = session.get(Panel, int(body["panel_id"])) if body.get("panel_id") else None
    still_rel = body.get("still_path") or ""
    if panel is None and not still_rel:
        raise MotionError("pick a panel or upload a still")
    if panel is not None:
        if not panel_still(session, panel):
            raise MotionError("this panel has no selected image")
        if still_rel == "":
            c = session.get(Candidate, panel.selected_candidate_id)
            still_rel = c.path if c else ""
    req = SP.SeedanceRequest(image=Path("."), prompt="", duration=int(body.get("duration", 5)), resolution=body.get("resolution", "1080p"),
                             aspect=body.get("aspect", "16:9"), seed=body.get("seed"), camera=body.get("camera", "push_in"), provider=body.get("provider", "fal")).normalised()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        prompt = SP.write_prompt(panel.scene if panel else "", req.camera, list(panel.characters or []) if panel else [])["prompt"]
    t = MotionTake(panel_id=panel.id if panel else None, still_path=still_rel, prompt=prompt, provider=req.provider, status="queued",
                   params={"duration": req.duration, "resolution": req.resolution, "aspect": req.aspect, "seed": req.seed, "camera": req.camera,
                           "estimate": SP.estimate(req.provider, req.duration, req.resolution), "dry_size": body.get("dry_size")})
    session.add(t)
    session.flush()
    return t


def h_seedance(ctx: Any, p: dict[str, Any]) -> dict[str, Any]:
    t = ctx.session.get(MotionTake, ctx.job.ref_id)
    if t is None:
        raise ValueError("take not found")
    t.status = "running"
    ctx.session.commit()
    pr = t.params or {}
    req = SP.SeedanceRequest(image=take_still(ctx.session, t), prompt=t.prompt, duration=pr.get("duration", 5), resolution=pr.get("resolution", "1080p"),
                             aspect=pr.get("aspect", "16:9"), seed=pr.get("seed"), camera=pr.get("camera", "push_in"), provider=t.provider)
    out = motion_dir("takes") / f"take{t.id}.mp4"
    try:
        dry = tuple(pr["dry_size"]) if pr.get("dry_size") else None
        res = SP.run(req, out, lambda f, msg: ctx.progress(done=round(f * 100), total=100, label=msg), force_dry=bool(p.get("dry_run")), dry_size=dry)
    except Exception:
        t.status = "failed"
        ctx.session.commit()
        raise
    t.path = db.rel(res.path)
    t.model, t.cost_usd, t.seed, t.dry_run = res.model, res.cost_usd, res.seed, res.dry_run
    thumb = out.with_suffix(".jpg")
    try:
        FF.run(["-ss", str(min(1.0, req.duration / 2)), "-i", str(out), "-frames:v", "1", "-q:v", "4", str(thumb)])
        t.thumb = db.rel(thumb)
    except Exception:  # noqa: BLE001
        pass
    t.status = "done"
    ctx.add_cost(res.cost_usd)
    ledger(ctx.session, f"seedance-{t.provider}", res.cost_usd, f"take {t.id}")
    ctx.log(f"take {t.id}: {res.provider} {res.model}{' (dry run)' if res.dry_run else ''} ${res.cost_usd:.2f}")
    ctx.session.commit()
    return {"take_id": t.id, "dry_run": res.dry_run, "url": db.media_url(t.path)}


def send_to_moment(session: Session, t: MotionTake, m: Moment, replace_panel: bool = True) -> Moment:
    if t.status != "done" or not t.path:
        raise MotionError("the take is not ready", 409)
    shots = list(m.shots or [])
    shot = {"take_id": t.id, "source": "seedance", "duration_s": float(min(10, max(5, (t.params or {}).get("duration", 5)))),
            "move": (t.params or {}).get("camera", "push_in") if (t.params or {}).get("camera") in KB.MOVES else "push_in", "focal": {"x": 0.5, "y": 0.5}}
    if t.panel_id:
        shot["panel_id"] = t.panel_id
    idx = next((i for i, s in enumerate(shots) if replace_panel and t.panel_id and s.get("panel_id") == t.panel_id), None)
    if idx is None:
        shots.append(shot)
    else:
        shots[idx] = shot
    m.shots = validate_shots(session, shots)
    if m.status in ("approved", "published"):
        m.status = "review"
    for other in session.scalars(select(MotionTake).where(MotionTake.panel_id == t.panel_id)).all() if t.panel_id else []:
        other.picked = other.id == t.id
    t.picked = True
    session.flush()
    return m


def health() -> dict[str, Any]:
    from engine import qr as Q

    ff = FF.health()
    zx = Q.decoder_available()
    return {"ok": bool(ff.get("ok") and zx), "ffmpeg": ff, "zxing": zx, "keys": {**SP.keys(), "elevenlabs": tts.available()}}


def copy_music(src: Path, name: str) -> str:
    d = motion_dir("music")
    dst = d / name
    shutil.copyfile(src, dst)
    return db.rel(dst)


jobs.HANDLERS.update({"motion_render": h_motion_render, "seedance": h_seedance})
