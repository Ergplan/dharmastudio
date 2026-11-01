"""Stitch API — /api/stitch/* : graphic-novel art stitched into the blank space of the author's typeset book PDF.

The PDF is never re-typeset: art is added on top (engine/stitch.py). Store: backend/stitch_store.py (data/stitch/).

Projects
GET    /projects                                       the stitch projects
POST   /projects/upload           (multipart file, title?)   import a PDF (upload)
POST   /projects/import           {path, title?}       import a PDF from a path on this Mac
GET    /projects/{p}                                   project + page summaries (kind, side, slots, pieces placed)
PATCH  /projects/{p}              {title}
DELETE /projects/{p}
GET    /projects/{p}/analysis     ?refresh=1           engine.stitch.analyse() of the PDF (cached)
GET    /projects/{p}/pages/{n}                         one page: text blocks, free space, slots, placements, AI results
GET    /projects/{p}/pages/{n}/preview.png  ?dpi=&art=0|1   the page rendered by the server (with its placements)
GET    /projects/{p}/pages/{n}/thumb.jpg               small, with art
POST   /projects/{p}/placements   {page, slot | rect, style?, pieces[{photo, subject?, crop?}], tilt?, size?, sepia?}
PATCH  /projects/{p}/placements/{id}    (same fields)       DELETE /projects/{p}/placements/{id}
POST   /projects/{p}/plates       {after (odd), items[2]{photo, subject?, crop?, caption, tilt?}}
PATCH  /projects/{p}/plates/{id}  ·  DELETE  ·  GET /projects/{p}/plates/{id}/{k}/preview.png
POST   /projects/{p}/undo  ·  GET /projects/{p}/history
POST   /projects/{p}/export                            -> job stitch_pdf (the finished PDF)
GET    /projects/{p}/exports
POST   /projects/{p}/suggest      {page}               the AI picture editor proposes pieces for the page's slots
POST   /projects/{p}/suggestions/{n}/{k}/accept        place suggestion k (nothing is placed before this)
DELETE /projects/{p}/suggestions/{n}
POST   /projects/{p}/review       {page?}              the AI reviewer checks placements against the text (one page
                                                       inline; every placed page as job stitch_review)
POST   /projects/{p}/reviews/{n}/{k}/accept            apply the reviewer's replacement for flag k
DELETE /projects/{p}/reviews/{n}

Photo repo
GET    /repo                      ?q=&source=&tag=     the library (searchable)
GET    /repo/books                                     imported Books whose art can be added
POST   /repo/import-book          {book_id}            every page's art of an imported Book
POST   /repo/import-folder        {path, tags?, recursive?}
POST   /repo/upload               (multipart files[], tags?)
GET    /repo/{id}  ·  PATCH {name, tags, era, chapter, page}  ·  DELETE
POST   /repo/{id}/subjects        {label, x, y, w, h}  ·  PATCH /repo/{id}/subjects/{sid}  ·  DELETE
POST   /repo/{id}/subjects/bulk   {subjects[]}         keep several (e.g. the AI proposals)
POST   /repo/{id}/find-subjects                        the OpenAI vision model proposes 4–8 subject crops (not saved)
"""

from __future__ import annotations

import io
import json
import random
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from engine import stitch as E
from engine.settings import settings

from . import db, jobs
from . import stitch_store as S

router = APIRouter(prefix="/api/stitch", tags=["stitch"])


def Sess() -> Any:  # noqa: N802
    return Depends(db.get_session)


def _call(fn, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN202
    try:
        return fn(*a, **k)
    except S.StitchError as e:
        raise HTTPException(e.status, e.detail) from None


# ---------------------------------------------------------------------------------
# images
# ---------------------------------------------------------------------------------


@lru_cache(maxsize=12)
def _open(path: str, mtime: float) -> Any:
    from PIL import Image

    with Image.open(path) as im:
        return im.convert("RGB")


def load_photo(pid: str) -> Any:
    p = S.photo(pid)
    f = S.photo_path(p)
    if not f.exists():
        raise S.StitchError(404, f"photo file missing: {pid}")
    return _open(str(f), f.stat().st_mtime)


def photo_view(p: dict[str, Any]) -> dict[str, Any]:
    return {**p, "url": f"/media/stitch/repo/{p['file']}", "thumb": f"/media/stitch/repo/thumbs/{p['id']}.jpg"}


_render_lock = threading.Lock()


def cached_render(prid: str):  # noqa: ANN201
    """A placement's drawn piece, cached on disk by everything that changes its picture."""
    d = S.project_dir(prid) / "cache"
    d.mkdir(exist_ok=True)

    def get(pl: dict[str, Any]) -> E.Rendered:
        key = E.placement_key(pl)
        png, meta = d / f"{key}.png", d / f"{key}.json"
        if png.exists() and meta.exists():
            return E.Rendered(tuple(json.loads(meta.read_text())), png.read_bytes())
        r = E.render_placement(pl, load_photo)
        png.write_bytes(r.png)
        meta.write_text(json.dumps(r.rect))
        return r

    return get


# ---------------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------------


def _ver(p: dict[str, Any], n: int) -> str:
    import hashlib

    pls = [E.placement_key(x) for x in p.get("placements") or [] if int(x["page"]) == n]
    return hashlib.sha1(json.dumps(pls).encode()).hexdigest()[:10]


def page_summary(prid: str, p: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
    n = a["n"]
    placed = [x for x in p.get("placements") or [] if int(x["page"]) == n]
    filled = {x.get("slot") for x in placed}
    v = _ver(p, n)
    return {"n": n, "kind": a["kind"], "side": a["side"], "outer": a["outer"], "chapter": a.get("chapter"),
            "slots": [{"id": s["id"], "kind": s["kind"], "filled": s["id"] in filled} for s in a["slots"]], "placed": len(placed),
            "thumb": f"/api/stitch/projects/{prid}/pages/{n}/thumb.jpg?v={v}", "rev": v,
            "suggestions": len(((p.get("suggestions") or {}).get(str(n)) or {}).get("items") or []),
            "flags": sum(1 for it in ((p.get("reviews") or {}).get(str(n)) or {}).get("items") or [] if not it.get("ok"))}


def project_view(prid: str) -> dict[str, Any]:
    p = S.load(prid)
    a = S.analysis(prid)
    return {**S.summary(p), "body": a.get("body"), "pages_list": [page_summary(prid, p, x) for x in a["pages"]],
            "placements_list": p.get("placements") or [], "plates_list": p.get("plates") or [], "undo": len(S.history(prid))}


def page_detail(prid: str, n: int) -> dict[str, Any]:
    p = S.load(prid)
    a = S.analysis(prid)
    if not 1 <= n <= len(a["pages"]):
        raise HTTPException(404, "page not found")
    info = a["pages"][n - 1]
    v = _ver(p, n)
    return {**info, "rev": v, "preview": f"/api/stitch/projects/{prid}/pages/{n}/preview.png?v={v}",
            "plain": f"/api/stitch/projects/{prid}/pages/{n}/preview.png?art=0",
            "placements": [x for x in p.get("placements") or [] if int(x["page"]) == n],
            "plates_after": [x for x in p.get("plates") or [] if int(x["after"]) == n],
            "suggestions": (p.get("suggestions") or {}).get(str(n)), "review": (p.get("reviews") or {}).get(str(n))}


# ---------------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------------


@router.get("/projects")
def projects() -> list[dict[str, Any]]:
    return S.list_projects()


@router.post("/projects/upload")
def project_upload(file: UploadFile = File(...), title: str | None = Form(None)) -> dict[str, Any]:
    tmp = Path(tempfile.mkstemp(suffix=".pdf", dir=S.root())[1])
    try:
        with open(tmp, "wb") as fo:
            shutil.copyfileobj(file.file, fo, 1 << 20)
        p = _call(S.create_project, tmp, title, file.filename or "book.pdf")
    finally:
        tmp.unlink(missing_ok=True)
    return project_view(p["id"])


@router.post("/projects/import")
def project_import(body: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(body.get("path") or "").strip()).expanduser()
    if not str(body.get("path") or "").strip():
        raise HTTPException(400, "path is required")
    if not path.is_file():
        raise HTTPException(404, f"not found: {path}")
    if path.suffix.lower() != ".pdf":
        raise HTTPException(400, "expected a .pdf")
    p = _call(S.create_project, path, body.get("title"), path.name)
    return project_view(p["id"])


@router.get("/projects/{prid}")
def get_project(prid: str) -> dict[str, Any]:
    return _call(project_view, prid)


@router.patch("/projects/{prid}")
def patch_project(prid: str, body: dict[str, Any]) -> dict[str, Any]:
    def fn(p: dict[str, Any]) -> None:
        if body.get("title"):
            p["title"] = str(body["title"])[:160]

    _call(S.mutate, prid, fn, "rename", record=False)
    return project_view(prid)


@router.delete("/projects/{prid}")
def delete_project(prid: str) -> dict[str, Any]:
    _call(S.delete_project, prid)
    return {"deleted": prid}


@router.get("/projects/{prid}/analysis")
def get_analysis(prid: str, refresh: bool = False) -> dict[str, Any]:
    return _call(S.analysis, prid, refresh)


@router.get("/projects/{prid}/pages/{n}")
def get_page(prid: str, n: int) -> dict[str, Any]:
    _call(S.project_dir, prid)
    return page_detail(prid, n)


@router.get("/projects/{prid}/pages/{n}/preview.png", include_in_schema=False)
def page_preview(prid: str, n: int, dpi: int = 110, art: int = 1) -> Response:
    p = _call(S.load, prid)
    if not 1 <= n <= int(p["pages"]):
        raise HTTPException(404, "page not found")
    dpi = max(30, min(300, dpi))
    pls = [x for x in p.get("placements") or [] if int(x["page"]) == n] if art else []
    with _render_lock:
        png = E.page_png(S.source_pdf(prid), n, pls, load_photo, dpi, cached_render(prid))
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.get("/projects/{prid}/pages/{n}/thumb.jpg", include_in_schema=False)
def page_thumb(prid: str, n: int) -> Response:
    p = _call(S.load, prid)
    if not 1 <= n <= int(p["pages"]):
        raise HTTPException(404, "page not found")
    d = S.project_dir(prid) / "thumbs"
    d.mkdir(exist_ok=True)
    f = d / f"{n}-{_ver(p, n)}.jpg"
    if not f.exists():
        from PIL import Image

        for old in d.glob(f"{n}-*.jpg"):
            old.unlink(missing_ok=True)
        pls = [x for x in p.get("placements") or [] if int(x["page"]) == n]
        with _render_lock:
            png = E.page_png(S.source_pdf(prid), n, pls, load_photo, 34, cached_render(prid))
        Image.open(io.BytesIO(png)).convert("RGB").save(f, "JPEG", quality=80)
    return Response(f.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ---------------------------------------------------------------------------------
# placements
# ---------------------------------------------------------------------------------


def _num(v: Any, lo: float, hi: float, default: float) -> float:
    if v is None or v == "":
        return default
    try:
        return round(max(lo, min(hi, float(v))), 3)
    except (TypeError, ValueError):
        raise HTTPException(400, f"not a number: {v!r}") from None


def clean_piece(x: Any) -> dict[str, Any]:
    if isinstance(x, str):
        x = {"photo": x}
    if not isinstance(x, dict) or not x.get("photo"):
        raise HTTPException(400, "a piece is {photo, subject?, crop?}")
    ph = _call(S.photo, str(x["photo"]))
    out: dict[str, Any] = {"photo": ph["id"]}
    sub = None
    if x.get("subject"):
        sub = next((s for s in ph.get("subjects") or [] if s["id"] == x["subject"]), None)
        if sub is None:
            raise HTTPException(400, f"photo {ph['id']} has no subject {x['subject']!r}")
        out["subject"] = sub["id"]
    crop = E.norm_crop(x.get("crop")) if x.get("crop") else None
    if crop is None and sub is not None:
        crop = {k: sub[k] for k in ("x", "y", "w", "h")}
    if crop:
        out["crop"] = crop
    return out


def _slot_of(info: dict[str, Any], sid: str) -> dict[str, Any] | None:
    return next((s for s in info["slots"] if s["id"] == sid), None)


def clean_placement(body: dict[str, Any], base: dict[str, Any] | None, prid: str) -> dict[str, Any]:
    a = S.analysis(prid)
    out = dict(base or {})
    page = int(body.get("page", out.get("page") or 0) or 0)
    if not 1 <= page <= len(a["pages"]):
        raise HTTPException(400, f"page must be 1–{len(a['pages'])}")
    info = a["pages"][page - 1]
    out["page"] = page
    if "slot" in body or "rect" in body or base is None:
        sid = body.get("slot") or (None if body.get("rect") else out.get("slot"))
        if body.get("rect"):
            try:
                r = [round(float(v), 2) for v in body["rect"]][:4]
                assert len(r) == 4 and r[2] - r[0] >= 10 and r[3] - r[1] >= 10
            except Exception:  # noqa: BLE001
                raise HTTPException(400, "rect is [x0, y0, x1, y1] in PDF points") from None
            if r[0] < 0 or r[1] < 0 or r[2] > info["w"] or r[3] > info["h"]:
                raise HTTPException(400, "the rect leaves the page")
            if not E._clear(r, info["blocks"] + info["folio"]):
                raise HTTPException(400, "the rect covers the page's text: art only goes in blank space")
            out["slot"], out["rect"] = "custom", r
        else:
            slot = _slot_of(info, str(sid or ""))
            if slot is None:
                raise HTTPException(400, f"page {page} has no slot {sid!r} (it has: {', '.join(s['id'] for s in info['slots']) or 'none'})")
            out["slot"], out["rect"] = slot["id"], slot["rect"]
            out.setdefault("style", E.default_style(slot["kind"]))
    if "style" in body:
        if body["style"] not in E.STYLES:
            raise HTTPException(400, f"style is one of {', '.join(E.STYLES)}")
        out["style"] = body["style"]
    out.setdefault("style", "torn")
    if "pieces" in body:
        out["pieces"] = [clean_piece(x) for x in body["pieces"] or []]
    pieces = out.get("pieces") or []
    if out["style"] == "collage":
        if not 2 <= len(pieces) <= 4:
            raise HTTPException(400, "a collage takes 2–4 pieces")
    else:
        if not pieces:
            raise HTTPException(400, "choose a photo for this placement")
        out["pieces"] = pieces[:1] if out["style"] == "icon" else pieces[:1]
    out["tilt"] = _num(body.get("tilt", out.get("tilt")), -12, 12, 0.0 if out["style"] in ("icon", "collage") else round(random.uniform(-1.6, 1.6), 2))
    out["size"] = _num(body.get("size", out.get("size")), 0.3, 1.0, 1.0)
    out["sepia"] = _num(body.get("sepia", out.get("sepia")), 0, 0.8, 0.14)
    out["seed"] = int(body.get("seed") or out.get("seed") or random.randint(1, 10**6))
    return out


def _new_id(items: list[dict[str, Any]], prefix: str) -> str:
    taken = {x["id"] for x in items}
    n = 1
    while f"{prefix}{n}" in taken:
        n += 1
    return f"{prefix}{n}"


def add_placement(prid: str, body: dict[str, Any], action: str = "place art") -> dict[str, Any]:
    pl = clean_placement(body, None, prid)
    out: dict[str, Any] = {}

    def fn(p: dict[str, Any]) -> None:
        pls = p.setdefault("placements", [])
        if pl["slot"] != "custom":   # one placement per slot: placing again replaces it
            pls[:] = [x for x in pls if not (int(x["page"]) == pl["page"] and x.get("slot") == pl["slot"])]
        pl["id"] = _new_id(pls, "pl")
        pls.append(pl)
        out.update(pl)

    S.mutate(prid, fn, f"{action} on page {pl['page']} ({pl['slot']})")
    return out


@router.post("/projects/{prid}/placements")
def post_placement(prid: str, body: dict[str, Any]) -> dict[str, Any]:
    _call(S.project_dir, prid)
    pl = add_placement(prid, body)
    return {"placement": pl, "page": page_detail(prid, pl["page"])}


@router.patch("/projects/{prid}/placements/{plid}")
def patch_placement(prid: str, plid: str, body: dict[str, Any]) -> dict[str, Any]:
    p = _call(S.load, prid)
    base = next((x for x in p.get("placements") or [] if x["id"] == plid), None)
    if base is None:
        raise HTTPException(404, "placement not found")
    new = clean_placement({k: v for k, v in body.items() if k != "page"}, base, prid)

    def fn(p: dict[str, Any]) -> None:
        p["placements"] = [new if x["id"] == plid else x for x in p["placements"]]

    keys = sorted(k for k in body if k in ("style", "pieces", "tilt", "size", "sepia", "slot", "rect", "seed"))
    S.mutate(prid, fn, f"edit piece on page {new['page']} ({', '.join(keys) or 'nothing'})")
    return {"placement": new, "page": page_detail(prid, new["page"])}


@router.delete("/projects/{prid}/placements/{plid}")
def delete_placement(prid: str, plid: str) -> dict[str, Any]:
    p = _call(S.load, prid)
    base = next((x for x in p.get("placements") or [] if x["id"] == plid), None)
    if base is None:
        raise HTTPException(404, "placement not found")
    S.mutate(prid, lambda p: p.update(placements=[x for x in p["placements"] if x["id"] != plid]), f"remove piece from page {base['page']}")
    return {"deleted": plid, "page": page_detail(prid, int(base["page"]))}


# ---------------------------------------------------------------------------------
# plates
# ---------------------------------------------------------------------------------


def clean_plate(body: dict[str, Any], base: dict[str, Any] | None, count: int) -> dict[str, Any]:
    out = dict(base or {})
    if "after" in body or base is None:
        try:
            after = int(body.get("after"))
        except (TypeError, ValueError):
            raise HTTPException(400, "after is the page number the pair follows") from None
        bad = E.plate_ok(after, count)
        if bad:
            raise HTTPException(400, bad)
        out["after"] = after
    if "items" in body or base is None:
        items = body.get("items") or []
        if len(items) != 2:
            raise HTTPException(400, "plates come as a facing pair: give two items (photo + caption each)")
        cl = []
        for j, it in enumerate(items):
            piece = clean_piece(it)
            piece["caption"] = " ".join(str(it.get("caption") or "").split())[:240]
            if it.get("tilt") is not None:
                piece["tilt"] = _num(it["tilt"], -8, 8, 0)
            if it.get("sepia") is not None:
                piece["sepia"] = _num(it["sepia"], 0, 0.8, 0.1)
            cl.append(piece)
        out["items"] = cl
    out["seed"] = int(body.get("seed") or out.get("seed") or random.randint(1, 10**6))
    return out


@router.post("/projects/{prid}/plates")
def post_plate(prid: str, body: dict[str, Any]) -> dict[str, Any]:
    p = _call(S.load, prid)
    pp = clean_plate(body, None, int(p["pages"]))

    def fn(p: dict[str, Any]) -> None:
        if any(int(x["after"]) == pp["after"] for x in p.get("plates") or []):
            raise S.StitchError(409, f"there is already a plate pair after page {pp['after']}")
        pp["id"] = _new_id(p.setdefault("plates", []), "pp")
        p["plates"].append(pp)

    _call(S.mutate, prid, fn, f"plate pair after page {pp['after']}")
    return {"plate": pp, "project": project_view(prid)}


@router.patch("/projects/{prid}/plates/{ppid}")
def patch_plate(prid: str, ppid: str, body: dict[str, Any]) -> dict[str, Any]:
    p = _call(S.load, prid)
    base = next((x for x in p.get("plates") or [] if x["id"] == ppid), None)
    if base is None:
        raise HTTPException(404, "plate pair not found")
    new = clean_plate(body, base, int(p["pages"]))

    def fn(p: dict[str, Any]) -> None:
        if any(int(x["after"]) == new["after"] and x["id"] != ppid for x in p["plates"]):
            raise S.StitchError(409, f"there is already a plate pair after page {new['after']}")
        p["plates"] = [new if x["id"] == ppid else x for x in p["plates"]]

    _call(S.mutate, prid, fn, f"edit plate pair after page {new['after']}")
    return {"plate": new, "project": project_view(prid)}


@router.delete("/projects/{prid}/plates/{ppid}")
def delete_plate(prid: str, ppid: str) -> dict[str, Any]:
    p = _call(S.load, prid)
    if not any(x["id"] == ppid for x in p.get("plates") or []):
        raise HTTPException(404, "plate pair not found")
    S.mutate(prid, lambda p: p.update(plates=[x for x in p["plates"] if x["id"] != ppid]), "remove plate pair")
    return {"deleted": ppid, "project": project_view(prid)}


@router.get("/projects/{prid}/plates/{ppid}/{k}/preview.png", include_in_schema=False)
def plate_preview(prid: str, ppid: str, k: int, dpi: int = 110) -> Response:
    p = _call(S.load, prid)
    pp = next((x for x in p.get("plates") or [] if x["id"] == ppid), None)
    if pp is None or k not in (0, 1):
        raise HTTPException(404, "plate not found")
    items = pp.get("items") or []
    item = items[k] if k < len(items) else None
    with _render_lock:
        png = E.plate_png(S.source_pdf(prid), int(pp["after"]), item, load_photo, int(pp.get("seed") or 777) + k, E.plate_tilt(item or {}, k), max(30, min(200, dpi)))
    return Response(png, media_type="image/png")


# ---------------------------------------------------------------------------------
# undo, export
# ---------------------------------------------------------------------------------


@router.post("/projects/{prid}/undo")
def project_undo(prid: str) -> dict[str, Any]:
    r = _call(S.undo, prid)
    return {"undone": r["undone"], "remaining": r["remaining"], "project": project_view(prid)}


@router.get("/projects/{prid}/history")
def project_history(prid: str) -> list[dict[str, Any]]:
    return [{k: e[k] for k in ("seq", "at", "action")} for e in _call(S.history, prid)][::-1]


def h_stitch_pdf(ctx: jobs.Ctx, params: dict[str, Any]) -> dict[str, Any]:
    prid = str(params["project_id"])
    p = S.load(prid)
    out = S.project_dir(prid) / "exports"
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    pdf = out / f"{S.slug(p.get('title', 'book'))}-stitched-{stamp}.pdf"
    ctx.log(f"{len(p.get('placements') or [])} piece(s) on {len({x['page'] for x in p.get('placements') or []})} page(s), {len(p.get('plates') or [])} plate pair(s)")

    def prog(done: int, total: int, msg: str) -> None:
        ctx.check_stop()
        ctx.progress(done=done, total=total)
        ctx.log(msg)

    data, errors = E.render(S.source_pdf(prid), p, load_photo, prog, cached_render(prid))
    for e in errors:
        ctx.log(f"skipped: {e}")
    tmp = pdf.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(pdf)
    import pymupdf as fitz

    with fitz.open(str(pdf)) as d:
        pages = len(d)
    ctx.progress(done=1, total=1)
    ctx.log(f"wrote {pdf.name}: {pages} pages, {len(data) / 1e6:.1f} MB")
    return {"pdf": db.rel(pdf), "url": db.media_url(db.rel(pdf)), "pages": pages, "bytes": len(data), "errors": errors}


jobs.HANDLERS.setdefault("stitch_pdf", h_stitch_pdf)


@router.post("/projects/{prid}/export", status_code=202)
def export_pdf(prid: str, session: Session = Sess()) -> dict[str, Any]:
    p = _call(S.load, prid)
    from .api import job_resp

    j = jobs.submit(session, "stitch_pdf", None, {"project_id": prid, "label": f"Stitch PDF · {p.get('title', '')}"})
    return job_resp(j)


@router.get("/projects/{prid}/exports")
def list_exports(prid: str) -> list[dict[str, Any]]:
    d = _call(S.project_dir, prid) / "exports"
    out = []
    if d.is_dir():
        for f in sorted(d.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True):
            out.append({"name": f.name, "url": db.media_url(db.rel(f)), "bytes": f.stat().st_size,
                        "modified": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
    return out


# ---------------------------------------------------------------------------------
# AI: subjects (vision), suggest (picture editor), review (independent reviewer)
# the two model calls below are what the tests replace
# ---------------------------------------------------------------------------------


class AIError(Exception):
    pass


def ask_vision(system: str, user: str, images: list[Path]) -> Any:
    """The configured OpenAI vision model (the critic's model when it is a gpt-* one, else the vision defaults)."""
    from engine import llm

    if not settings.openai_api_key:
        raise AIError("Find subjects needs OPENAI_API_KEY in .env (the OpenAI vision model)")
    chosen = llm.model_for("critic")
    models = ([chosen] if chosen.startswith("gpt") else []) + ["gpt-6.1-sol", "gpt-5.5", "gpt-5"]
    ans, used = llm.ask_json_models(list(dict.fromkeys(models)), system, user, images)
    if used is None:
        raise AIError("the OpenAI vision model did not answer")
    return ans


def ask_llm(role: str, system: str, user: str, images: list[Path] | None = None) -> Any:
    """The language model configured for `role` on the Project screen (Claude or OpenAI)."""
    from engine import llm

    if not llm.is_available(role):
        raise AIError(f"no key for the {role.replace('_', ' ')} model ({llm.model_for(role)}): add it to .env")
    return llm.ask_json(role, system, user, images or [])


def _ai(fn, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN202
    try:
        return fn(*a, **k)
    except AIError as e:
        raise HTTPException(400, str(e)) from None
    except S.StitchError as e:
        raise HTTPException(e.status, e.detail) from None
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — provider failure
        raise HTTPException(502, f"the model failed: {type(e).__name__}: {str(e)[:300]}") from None


def _sync_models(session: Session) -> None:
    try:
        jobs.sync_models(session)
    except Exception:  # noqa: BLE001
        pass


SUBJECTS_SYSTEM = """You are the picture editor of an illustrated novel. You look at one graphic-novel painting and choose
the strongest SUBJECTS to cut out of it as small torn-paper pieces: a face, a figure in action, a weapon, a chariot, a city
in flames — each a clear, readable subject that works on its own when cut out. Avoid empty caption boxes, panel gutters,
lettering and blank sky. Answer strict JSON only."""


def find_subjects(phid: str) -> list[dict[str, Any]]:
    from PIL import Image

    ph = S.photo(phid)
    tmp = Path(tempfile.mkstemp(suffix=".jpg", dir=S.root())[1])
    try:
        with Image.open(S.photo_path(ph)) as im:
            im = im.convert("RGB")
            im.thumbnail((1024, 1024))
            im.save(tmp, "JPEG", quality=85)
        user = (f"The painting is {ph['w']} x {ph['h']} px" + (f", from {ph.get('book')} page {ph.get('page')}" if ph.get("book") else "") +
                ". Return 4 to 8 subject crops as {\"crops\": [{\"label\": short name, \"what\": one sentence, \"drama\": 0-10, "
                "\"x\": left, \"y\": top, \"w\": width, \"h\": height}]} with x, y, w, h as fractions (0..1) of the image. "
                "Most dramatic first. A crop should be at least 0.08 of the image wide and tall.")
        ans = ask_vision(SUBJECTS_SYSTEM, user, [tmp])
    finally:
        tmp.unlink(missing_ok=True)
    raw = (ans or {}).get("crops") if isinstance(ans, dict) else ans
    out = []
    for k, c in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(c, dict):
            continue
        try:
            s = S.clean_subject({**c, "label": c.get("label") or c.get("subject") or f"subject {k + 1}", "ai": True}, f"ai{k + 1}")
        except S.StitchError:
            continue
        if s["w"] >= 0.04 and s["h"] >= 0.04:
            out.append(s)
    out.sort(key=lambda s: -s.get("drama", 0))
    return out[:8]


def _catalogue(limit: int = 160) -> list[dict[str, Any]]:
    out = []
    for p in S.photos()[:limit]:
        out.append({"photo": p["id"], "name": p.get("name"), "book_page": p.get("page"), "chapter": p.get("chapter"), "era": p.get("era"), "tags": p.get("tags"),
                    "subjects": [{"subject": s["id"], "label": s.get("label"), "what": s.get("what"), "drama": s.get("drama")} for s in p.get("subjects") or []]})
    return out


SUGGEST_SYSTEM = """You are the picture editor of an illustrated edition of a novel. The novel's pages are typeset and final;
art from the graphic-novel version is stitched ONLY into blank areas: a wide torn strip above a chapter heading (slot "top"),
a sewn collage of 2-4 torn pieces at a chapter's end (slot "bottom"), a small round icon in the top outer corner (slot "corner").
Choose pieces from the photo library that show what THIS page's text is about (the same characters, place, moment) —
never a scene from later in the story, never a mismatch of characters. Prefer a named subject crop when one fits.
Answer strict JSON only."""


def suggest(prid: str, n: int) -> dict[str, Any]:
    a = S.analysis(prid)
    if not 1 <= n <= len(a["pages"]):
        raise S.StitchError(404, "page not found")
    info = a["pages"][n - 1]
    if not info["slots"]:
        raise S.StitchError(409, f"page {n} has no blank area for art")
    cat = _catalogue()
    if not cat:
        raise S.StitchError(409, "the photo repo is empty: add photos first")
    user = json.dumps({"page": n, "chapter": info.get("chapter"), "text": info["text"][:3000],
                       "slots": [{"slot": s["id"], "kind": s["kind"], "pieces": "2-4" if s["kind"] == "collage" else "1"} for s in info["slots"]],
                       "library": cat,
                       "answer": {"picks": [{"slot": "top|bottom|corner", "pieces": [{"photo": "id", "subject": "subject id or null"}], "why": "one sentence tying it to the text"}]}},
                      ensure_ascii=False)
    ans = ask_llm("prompt_writer", SUGGEST_SYSTEM, user)
    items = []
    for pick in (ans or {}).get("picks") or [] if isinstance(ans, dict) else []:
        slot = _slot_of(info, str(pick.get("slot") or ""))
        if slot is None:
            continue
        pieces = []
        for x in pick.get("pieces") or []:
            try:
                pieces.append(clean_piece({"photo": x.get("photo"), "subject": x.get("subject") or None}))
            except HTTPException:
                try:
                    pieces.append(clean_piece({"photo": x.get("photo")}))
                except HTTPException:
                    continue
        need = (2, 4) if slot["kind"] == "collage" else (1, 1)
        if len(pieces) < need[0]:
            continue
        items.append({"slot": slot["id"], "style": E.default_style(slot["kind"]), "pieces": pieces[: need[1]], "why": str(pick.get("why") or "")[:400]})
    res = {"at": S.now(), "items": items}
    S.mutate(prid, lambda p: p.setdefault("suggestions", {}).__setitem__(str(n), res), "suggest", record=False)
    return res


REVIEW_SYSTEM = """You are an independent reviewer of an illustrated edition of a novel. For each piece of art placed on a page,
check it against the page's text and its chapter: does it show the right characters, place and moment? Flag mismatches
(a character who is not in this part of the story, a scene from much later, the wrong setting, a jarring tone). Do not flag
a piece for being merely atmospheric if it fits the chapter. You may propose a better photo / subject from the library.
Answer strict JSON only."""


def review_page(prid: str, n: int) -> dict[str, Any]:
    p = S.load(prid)
    a = S.analysis(prid)
    if not 1 <= n <= len(a["pages"]):
        raise S.StitchError(404, "page not found")
    info = a["pages"][n - 1]
    pls = [x for x in p.get("placements") or [] if int(x["page"]) == n]
    if not pls:
        raise S.StitchError(409, f"nothing is placed on page {n}")

    def desc(pc: dict[str, Any]) -> dict[str, Any]:
        ph = next((x for x in S.photos() if x["id"] == pc["photo"]), {})
        sub = next((s for s in ph.get("subjects") or [] if s["id"] == pc.get("subject")), None)
        return {"photo": pc["photo"], "name": ph.get("name"), "book_page": ph.get("page"), "chapter": ph.get("chapter"), "tags": ph.get("tags"),
                "subject": (sub or {}).get("label"), "what": (sub or {}).get("what")}

    tmp = Path(tempfile.mkstemp(suffix=".png", dir=S.root())[1])
    try:
        with _render_lock:
            tmp.write_bytes(E.page_png(S.source_pdf(prid), n, pls, load_photo, 72, cached_render(prid)))
        user = json.dumps({"page": n, "chapter": info.get("chapter"), "text": info["text"][:3000],
                           "placements": [{"placement": x["id"], "slot": x.get("slot"), "style": x.get("style"), "pieces": [desc(pc) for pc in x.get("pieces") or []]} for x in pls],
                           "library": _catalogue(120),
                           "answer": {"items": [{"placement": "id", "ok": True, "issue": "what does not match (empty when ok)",
                                                 "replace": {"piece": 0, "photo": "id", "subject": "id or null"}}]}}, ensure_ascii=False)
        ans = ask_llm("critic", REVIEW_SYSTEM, user, [tmp])
    finally:
        tmp.unlink(missing_ok=True)
    ids = {x["id"] for x in pls}
    items = []
    for it in (ans or {}).get("items") or [] if isinstance(ans, dict) else []:
        if it.get("placement") not in ids:
            continue
        row: dict[str, Any] = {"placement": it["placement"], "ok": bool(it.get("ok")), "issue": str(it.get("issue") or "")[:500]}
        rep = it.get("replace") if isinstance(it.get("replace"), dict) else None
        if rep and rep.get("photo") and not row["ok"]:
            try:
                piece = clean_piece({"photo": rep["photo"], "subject": rep.get("subject") or None})
                row["replace"] = {"piece": max(0, int(rep.get("piece") or 0)), **piece}
            except (HTTPException, ValueError, TypeError):
                pass
        items.append(row)
    res = {"at": S.now(), "items": items}
    S.mutate(prid, lambda p: p.setdefault("reviews", {}).__setitem__(str(n), res), "review", record=False)
    return res


@router.post("/projects/{prid}/suggest")
def post_suggest(prid: str, body: dict[str, Any], session: Session = Sess()) -> dict[str, Any]:
    _call(S.project_dir, prid)
    _sync_models(session)
    n = int(body.get("page") or 0)
    res = _ai(suggest, prid, n)
    return {**res, "page": page_detail(prid, n)}


@router.post("/projects/{prid}/suggestions/{n}/{k}/accept")
def accept_suggestion(prid: str, n: int, k: int) -> dict[str, Any]:
    p = _call(S.load, prid)
    items = (((p.get("suggestions") or {}).get(str(n))) or {}).get("items") or []
    if not 0 <= k < len(items):
        raise HTTPException(404, "suggestion not found")
    s = items[k]
    pl = add_placement(prid, {"page": n, "slot": s["slot"], "style": s["style"], "pieces": s["pieces"]}, "accept suggestion")

    def fn(p: dict[str, Any]) -> None:
        its = p["suggestions"][str(n)]["items"]
        its[k] = {**its[k], "accepted": pl["id"]}

    S.mutate(prid, fn, "accept suggestion", record=False)
    return {"placement": pl, "page": page_detail(prid, n)}


@router.delete("/projects/{prid}/suggestions/{n}")
def clear_suggestions(prid: str, n: int) -> dict[str, Any]:
    _call(S.mutate, prid, lambda p: (p.get("suggestions") or {}).pop(str(n), None), "clear suggestions", record=False)
    return page_detail(prid, n)


def h_stitch_review(ctx: jobs.Ctx, params: dict[str, Any]) -> dict[str, Any]:
    prid = str(params["project_id"])
    p = S.load(prid)
    pages = sorted({int(x["page"]) for x in p.get("placements") or []})
    flags, failed = 0, []
    for k, n in enumerate(pages):
        ctx.check_stop()
        ctx.progress(done=k, total=len(pages))
        try:
            r = review_page(prid, n)
        except Exception as exc:  # noqa: BLE001 — one page failing must not lose the others
            failed.append(n)
            ctx.log(f"page {n}: not reviewed — {exc}")
            continue
        bad = [x for x in r["items"] if not x["ok"]]
        flags += len(bad)
        ctx.log(f"page {n}: {len(r['items']) - len(bad)} ok, {len(bad)} flagged" + "".join(f"\n  {x['placement']}: {x['issue']}" for x in bad))
    ctx.progress(done=len(pages), total=len(pages))
    if failed and len(failed) == len(pages):
        raise RuntimeError("no page could be reviewed (see the log)")
    return {"pages": pages, "flags": flags, "failed": failed}


jobs.HANDLERS.setdefault("stitch_review", h_stitch_review)


@router.post("/projects/{prid}/review")
def post_review(prid: str, body: dict[str, Any], session: Session = Sess()) -> dict[str, Any]:
    p = _call(S.load, prid)
    _sync_models(session)
    if body.get("page"):
        n = int(body["page"])
        res = _ai(review_page, prid, n)
        return {**res, "page": page_detail(prid, n)}
    if not p.get("placements"):
        raise HTTPException(409, "nothing is placed yet")
    from .api import job_resp

    j = jobs.submit(session, "stitch_review", None, {"project_id": prid, "label": f"Stitch review · {p.get('title', '')}"})
    return job_resp(j)


@router.post("/projects/{prid}/reviews/{n}/{k}/accept")
def accept_review(prid: str, n: int, k: int) -> dict[str, Any]:
    p = _call(S.load, prid)
    items = (((p.get("reviews") or {}).get(str(n))) or {}).get("items") or []
    if not 0 <= k < len(items) or not items[k].get("replace"):
        raise HTTPException(404, "no replacement to accept")
    it = items[k]
    base = next((x for x in p.get("placements") or [] if x["id"] == it["placement"]), None)
    if base is None:
        raise HTTPException(409, "that placement no longer exists")
    rep = it["replace"]
    pieces = list(base.get("pieces") or [])
    j = min(int(rep.get("piece") or 0), len(pieces) - 1)
    pieces[j] = {kk: v for kk, v in rep.items() if kk in ("photo", "subject", "crop")}
    r = patch_placement(prid, base["id"], {"pieces": pieces})

    def fn(p: dict[str, Any]) -> None:
        p["reviews"][str(n)]["items"][k] = {**it, "ok": True, "accepted": True}

    S.mutate(prid, fn, "accept review", record=False)
    return {**r, "page": page_detail(prid, n)}


@router.delete("/projects/{prid}/reviews/{n}")
def clear_review(prid: str, n: int) -> dict[str, Any]:
    _call(S.mutate, prid, lambda p: (p.get("reviews") or {}).pop(str(n), None), "clear review", record=False)
    return page_detail(prid, n)


# ---------------------------------------------------------------------------------
# photo repo
# ---------------------------------------------------------------------------------


@router.get("/repo")
def repo(q: str = "", source: str | None = None, tag: str | None = None) -> dict[str, Any]:
    ps = S.search(q, source, tag)
    tags: dict[str, int] = {}
    for p in S.photos():
        for t in p.get("tags") or []:
            tags[t] = tags.get(t, 0) + 1
    return {"photos": [photo_view(p) for p in ps], "total": len(S.photos()), "tags": sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))[:60]}


@router.get("/repo/books")
def repo_books() -> list[dict[str, Any]]:
    from . import book_store as B

    out = []
    for b in B.list_books():
        have = sum(1 for p in S.photos() if p.get("book_id") == b["id"])
        out.append({**b, "in_repo": have})
    return out


@router.post("/repo/import-book")
def import_book(body: dict[str, Any]) -> dict[str, Any]:
    from . import book_store as B

    bid = str(body.get("book_id") or "")
    try:
        b = B.load_book(bid)
        pages = B.pages(bid)
        bdir = B.book_dir(bid)
    except B.BookError as e:
        raise HTTPException(e.status, e.detail) from None
    added, known, chapter = 0, 0, None
    for pg in pages:
        head = next((t.get("title") or t.get("text") for t in pg.get("text") or [] if t.get("style") == "header"), None)
        chapter = head or chapter
        art = pg.get("art") or {}
        f = bdir / str(art.get("file") or "")
        if not art.get("file") or not f.is_file():
            continue
        tags = [b.get("title") or "book", f"page {pg['number']}"] + ([pg["era"]] if pg.get("era") else [])
        _, created = _call(S.add_photo, f, {"source": "book", "origin": f"{bid}/{art['file']}", "name": f"{b.get('title', 'Book')} · p{pg['number']}",
                                            "book": b.get("title"), "book_id": bid, "page": pg["number"], "era": pg.get("era"), "chapter": chapter, "tags": tags})
        added += created
        known += not created
    return {"added": added, "already": known, "total": len(S.photos())}


@router.post("/repo/import-folder")
def import_folder(body: dict[str, Any]) -> dict[str, Any]:
    d = Path(str(body.get("path") or "").strip()).expanduser()
    if not str(body.get("path") or "").strip() or not d.is_dir():
        raise HTTPException(404, f"not a folder: {d}")
    files = sorted((d.rglob("*") if body.get("recursive") else d.iterdir()))
    files = [f for f in files if f.is_file() and f.suffix.lower() in S.IMAGE_EXT and not f.name.startswith(".")]
    if not files:
        raise HTTPException(400, "no images (.jpg, .png, .webp) in that folder")
    tags = S.clean_tags(body.get("tags")) or [d.name]
    added, known, bad = 0, 0, []
    for f in files[:2000]:
        try:
            _, created = S.add_photo(f, {"source": "folder", "origin": str(f), "tags": tags})
        except S.StitchError as e:
            bad.append(f"{f.name}: {e.detail}")
            continue
        added += created
        known += not created
    return {"added": added, "already": known, "skipped": bad[:20], "total": len(S.photos())}


@router.post("/repo/upload")
def upload_photos(files: list[UploadFile] = File(...), tags: str | None = Form(None)) -> dict[str, Any]:
    added, known, bad, ids = 0, 0, [], []
    work = Path(tempfile.mkdtemp(prefix="upload-", dir=S.root()))
    try:
        for up in files:
            name = Path(up.filename or "photo.jpg").name
            f = work / name
            with open(f, "wb") as fo:
                shutil.copyfileobj(up.file, fo, 1 << 20)
            try:
                rec, created = S.add_photo(f, {"source": "upload", "origin": name, "tags": S.clean_tags(tags)})
            except S.StitchError as e:
                bad.append(f"{name}: {e.detail}")
                continue
            ids.append(rec["id"])
            added += created
            known += not created
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"added": added, "already": known, "skipped": bad, "ids": ids, "total": len(S.photos())}


@router.get("/repo/{phid}")
def get_photo(phid: str) -> dict[str, Any]:
    return photo_view(_call(S.photo, phid))


@router.patch("/repo/{phid}")
def patch_photo(phid: str, body: dict[str, Any]) -> dict[str, Any]:
    def fn(p: dict[str, Any]) -> None:
        if "name" in body:
            p["name"] = str(body["name"] or p["name"])[:120]
        if "tags" in body:
            p["tags"] = S.clean_tags(body["tags"])
        for k in ("era", "chapter"):
            if k in body:
                p[k] = (str(body[k])[:120] or None) if body[k] else None
        if "page" in body:
            p["page"] = int(body["page"]) if body["page"] not in (None, "") else None

    return photo_view(_call(S.mutate_photo, phid, fn))


@router.delete("/repo/{phid}")
def delete_photo(phid: str) -> dict[str, Any]:
    used = [pr["id"] for pr in S.list_projects() if any(pc["photo"] == phid for x in S.load(pr["id"]).get("placements") or [] for pc in x.get("pieces") or [])
            or any(it.get("photo") == phid for x in S.load(pr["id"]).get("plates") or [] for it in x.get("items") or [])]
    if used:
        raise HTTPException(409, f"the photo is placed in {', '.join(used)}: remove those pieces first")
    _call(S.delete_photo, phid)
    return {"deleted": phid}


@router.post("/repo/{phid}/subjects")
def add_subject(phid: str, body: dict[str, Any]) -> dict[str, Any]:
    def fn(p: dict[str, Any]) -> None:
        p.setdefault("subjects", []).append(S.clean_subject(body, S.next_subject_id(p)))

    return photo_view(_call(S.mutate_photo, phid, fn))


@router.post("/repo/{phid}/subjects/bulk")
def add_subjects(phid: str, body: dict[str, Any]) -> dict[str, Any]:
    def fn(p: dict[str, Any]) -> None:
        for s in body.get("subjects") or []:
            p.setdefault("subjects", []).append(S.clean_subject(s, S.next_subject_id(p)))

    return photo_view(_call(S.mutate_photo, phid, fn))


@router.patch("/repo/{phid}/subjects/{sid}")
def patch_subject(phid: str, sid: str, body: dict[str, Any]) -> dict[str, Any]:
    def fn(p: dict[str, Any]) -> None:
        for i, s in enumerate(p.get("subjects") or []):
            if s["id"] == sid:
                p["subjects"][i] = S.clean_subject({**s, **body}, sid)
                return
        raise S.StitchError(404, "subject not found")

    return photo_view(_call(S.mutate_photo, phid, fn))


@router.delete("/repo/{phid}/subjects/{sid}")
def delete_subject(phid: str, sid: str) -> dict[str, Any]:
    def fn(p: dict[str, Any]) -> None:
        n = len(p.get("subjects") or [])
        p["subjects"] = [s for s in p.get("subjects") or [] if s["id"] != sid]
        if len(p["subjects"]) == n:
            raise S.StitchError(404, "subject not found")

    return photo_view(_call(S.mutate_photo, phid, fn))


@router.post("/repo/{phid}/find-subjects")
def post_find_subjects(phid: str) -> dict[str, Any]:
    _call(S.photo, phid)
    return {"proposals": _ai(find_subjects, phid)}
