"""QR BUILDER API: saved QR records (link + style + size), live preview at printed size on the parchment, the decode
test (300 + 150 dpi, zxing-cpp), exports (SVG / PNG 600 dpi / PDF) and placing a QR on a page (the page element)."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from engine import qr as Q
from engine.comic import manuscript as MS

from . import db, links
from .models import Canvas, Page
from .motion_models import Link, Moment, PageQR, QRCode

PAGE_W, PAGE_H = 170.0, 260.0
MARGIN = 6.0


def S() -> Any:  # noqa: N802
    return Depends(db.get_session)


router = APIRouter(prefix="/api", tags=["qr"])


# ---------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------


def emblem_bytes(q: QRCode) -> bytes | None:
    p = db.abs_path(q.emblem_path)
    return p.read_bytes() if p and p.exists() else None


def style_of(q: QRCode) -> Q.QRStyle:
    return Q.QRStyle.from_dict(q.style, emblem_bytes(q))


def url_of(session: Session, q: QRCode) -> str:
    link = session.get(Link, q.link_id)
    if link is None:
        raise HTTPException(404, "the QR's link is gone")
    return links.short_url(link.code)


def signature(url: str, style: Q.QRStyle) -> str:
    h = hashlib.sha1()
    h.update(url.encode())
    h.update(json.dumps(style.json(), sort_keys=True).encode())
    if style.emblem_png:
        h.update(hashlib.sha1(style.emblem_png).digest())
    return h.hexdigest()


def is_tested(session: Session, q: QRCode) -> bool:
    try:
        url = url_of(session, q)
    except HTTPException:
        return False
    return bool(q.test and q.test.get("ok") and q.test_sig == signature(url, style_of(q)))


def require_tested(session: Session, q: QRCode, what: str) -> None:
    if not is_tested(session, q):
        raise HTTPException(409, f"QR #{q.id} has not passed the decode test for its current link and style — run the test before you {what}")


def run_test(session: Session, q: QRCode) -> dict[str, Any]:
    url = url_of(session, q)
    st = style_of(q)
    res = Q.decode_test(url, st)
    q.test = res
    q.test_sig = signature(url, st)
    if not res.get("ok"):
        q.approved = False
    session.flush()
    return res


def j_qr(session: Session, q: QRCode) -> dict[str, Any]:
    link = session.get(Link, q.link_id)
    st = style_of(q)
    url = links.short_url(link.code) if link else ""
    w, h = Q.dimensions(url, st) if url else (st.size_mm, st.size_mm)
    placed = session.scalars(select(PageQR).where(PageQR.qr_id == q.id)).all()
    return {"id": q.id, "name": q.name or (link.code if link else f"QR {q.id}"), "link_id": q.link_id, "code": link.code if link else None, "url": url,
            "style": st.json(), "has_emblem_upload": bool(q.emblem_path), "tested": is_tested(session, q), "test": q.test or None,
            "approved": q.approved and is_tested(session, q), "width_mm": round(w, 2), "height_mm": round(h, 2),
            "link_locked": bool(link and link.print_locked),
            "placements": [{"id": p.id, "page_id": p.page_id, "x_mm": p.x_mm, "y_mm": p.y_mm, "w_mm": p.w_mm} for p in placed],
            "preview_url": f"/api/qr/{q.id}/preview.png", "svg_url": f"/api/qr/{q.id}/export.svg"}


def ink_for_volume(session: Session, page: Page | None) -> str:
    if page is None:
        return Q.SEPIA
    c = session.get(Canvas, page.canvas_override) if page.canvas_override else None
    c = c or page.chapter.volume.canvas
    return (c.ink if c else None) or Q.SEPIA


# ---------------------------------------------------------------------------------
# placement (free parchment, lower outer corner preferred)
# ---------------------------------------------------------------------------------


def free_spot(session: Session, page: Page, w_mm: float, h_mm: float, exclude_pq: int | None = None) -> tuple[float, float]:
    from . import render

    render.ensure_shapes(session, page)
    grid = MS.Grid(PAGE_W, PAGE_H)
    for p in page.panels:
        poly = (p.shape or {}).get("polygon_mm") or []
        if len(poly) >= 3:
            grid.polygon([(float(x), float(y)) for x, y in poly])
    if page.is_opener:
        grid.rect((MARGIN, MARGIN, PAGE_W - MARGIN, 46.0))
    grid.rect((PAGE_W - 12, PAGE_H - 8, PAGE_W, PAGE_H), 0)  # folio
    for m in page.marginalia or []:
        x, y, w = float(m.get("x_mm", 0)), float(m.get("y_mm", 0)), float(m.get("w_mm", 30))
        grid.rect((x, y, x + w, y + float(m.get("h_mm") or w)))
    for pq in session.scalars(select(PageQR).where(PageQR.page_id == page.id)).all():
        if pq.id != exclude_pq:
            q = session.get(QRCode, pq.qr_id)
            hh = Q.dimensions(url_of(session, q), Q.QRStyle.from_dict({**(q.style or {}), "size_mm": pq.w_mm}))[1] if q else pq.w_mm
            grid.rect((pq.x_mm, pq.y_mm, pq.x_mm + pq.w_mm, pq.y_mm + hh))
    outer_right = page.number % 2 == 1  # recto: outer edge on the right
    corner = (PAGE_W - MARGIN, PAGE_H - MARGIN) if outer_right else (MARGIN, PAGE_H - MARGIN)
    best, best_d = None, 1e9
    for x0, y0, x1, y1 in grid.candidates():
        if x1 - x0 < w_mm or y1 - y0 < h_mm:
            continue
        x = x1 - w_mm if outer_right else x0
        y = y1 - h_mm
        d = abs((x + w_mm / 2) - corner[0]) + abs((y + h_mm / 2) - corner[1]) * 1.2
        if d < best_d:
            best, best_d = (x, y), d
    if best is None:  # no free parchment big enough: the lower outer margin, over whatever is there
        best = (PAGE_W - MARGIN - w_mm, PAGE_H - MARGIN - 8 - h_mm) if outer_right else (MARGIN, PAGE_H - MARGIN - 8 - h_mm)
    return round(best[0], 2), round(best[1], 2)


def place(session: Session, q: QRCode, page: Page, x_mm: float | None = None, y_mm: float | None = None, w_mm: float | None = None) -> PageQR:
    require_tested(session, q, "place it")
    w = max(Q.MIN_MM, float(w_mm or (q.style or {}).get("size_mm") or 22.0))
    url = url_of(session, q)
    ww, hh = Q.dimensions(url, Q.QRStyle.from_dict({**(q.style or {}), "size_mm": w}))
    existing = session.scalar(select(PageQR).where(PageQR.page_id == page.id, PageQR.qr_id == q.id))
    if x_mm is None or y_mm is None:
        x_mm, y_mm = free_spot(session, page, ww, hh, exclude_pq=existing.id if existing else None)
    if existing is None:
        existing = PageQR(page_id=page.id, qr_id=q.id)
        session.add(existing)
    existing.x_mm, existing.y_mm, existing.w_mm = float(x_mm), float(y_mm), w
    session.flush()
    return existing


def element_png_path(session: Session, pq: PageQR) -> Path:
    """The placed QR as a 600 dpi transparent PNG (cached by signature) — drawn by the page layout like marginalia."""
    q = session.get(QRCode, pq.qr_id)
    st = Q.QRStyle.from_dict({**(q.style or {}), "size_mm": pq.w_mm}, emblem_bytes(q))
    url = url_of(session, q)
    sig = signature(url, st)[:16]
    d = db.DATA_DIR / "motion" / "qr"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"qr{q.id}-{sig}.png"
    if not p.exists():
        p.write_bytes(Q.png(url, st, 600))
    return p


def page_elements(session: Session, page_id: int) -> list[dict[str, Any]]:
    """For the layout: [{path, url, x_mm, y_mm, w_mm, h_mm, colour}] of every QR on the page."""
    out = []
    for pq in session.scalars(select(PageQR).where(PageQR.page_id == page_id)).all():
        q = session.get(QRCode, pq.qr_id)
        if q is None:
            continue
        st = Q.QRStyle.from_dict({**(q.style or {}), "size_mm": pq.w_mm}, emblem_bytes(q))
        url = url_of(session, q)
        w, h = Q.dimensions(url, st)
        p = element_png_path(session, pq)
        out.append({"id": pq.id, "qr_id": q.id, "path": p, "url": db.media_url(db.rel(p)), "x_mm": pq.x_mm - (w - pq.w_mm) / 2, "y_mm": pq.y_mm,
                    "w_mm": w, "h_mm": h, "colour": st.colour, "tested": is_tested(session, q), "code": session.get(Link, q.link_id).code})
    return out


# ---------------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------------


class QRIn(BaseModel):
    link_id: int | None = None
    # inline link creation (target_type + target_ref [+ code])
    target_type: str | None = None
    target_ref: str | None = None
    code: str | None = None
    name: str | None = None
    style: dict[str, Any] | None = None


class RenderIn(BaseModel):
    link_id: int | None = None
    code: str | None = None
    style: dict[str, Any] | None = None
    test: bool = False
    dpi: int = 200


class PlaceIn(BaseModel):
    page_id: int
    x_mm: float | None = None
    y_mm: float | None = None
    w_mm: float | None = None


class PageQRIn(BaseModel):
    x_mm: float | None = None
    y_mm: float | None = None
    w_mm: float | None = None


def _qr(session: Session, qid: int) -> QRCode:
    q = session.get(QRCode, qid)
    if q is None:
        raise HTTPException(404, "QR not found")
    return q


@router.get("/qr/options")
def qr_options() -> dict[str, Any]:
    return {"modules": list(Q.MODULES), "emblems": list(Q.EMBLEMS), "ec_levels": list(Q.EC_LEVELS), "labels": Q.LABELS, "min_mm": Q.MIN_MM,
            "max_emblem_area": Q.MAX_EMBLEM_AREA, "colours": [{"id": "sepia", "hex": Q.SEPIA, "label": "Dark sepia"}, {"id": "black", "hex": Q.BLACK, "label": "Black"}],
            "defaults": Q.QRStyle().json(), "decoder": Q.decoder_available(), "test_dpis": list(Q.TEST_DPIS)}


@router.get("/qr")
def list_qr(session: Session = S()) -> list[dict[str, Any]]:
    return [j_qr(session, q) for q in session.scalars(select(QRCode).order_by(QRCode.id.desc())).all()]


@router.post("/qr", status_code=201)
def create_qr(body: QRIn, session: Session = S()) -> dict[str, Any]:
    link = session.get(Link, body.link_id) if body.link_id else None
    if link is None:
        if not body.target_type:
            raise HTTPException(422, "pick a link or give target_type/target_ref to create one")
        try:
            link = links.create(session, body.target_type, body.target_ref or "", body.code)
        except links.LinkError as e:
            raise HTTPException(e.status, str(e)) from e
    style = Q.QRStyle.from_dict(body.style)
    if body.style and float(body.style.get("size_mm", Q.MIN_MM)) < Q.MIN_MM:
        raise HTTPException(422, f"minimum printed size is {Q.MIN_MM:.0f} mm")
    q = QRCode(link_id=link.id, name=body.name or link.code, style=style.json())
    session.add(q)
    session.flush()
    session.commit()
    return j_qr(session, q)


@router.get("/qr/{qid}")
def get_qr(qid: int, session: Session = S()) -> dict[str, Any]:
    return j_qr(session, _qr(session, qid))


@router.put("/qr/{qid}")
def put_qr(qid: int, body: QRIn, session: Session = S()) -> dict[str, Any]:
    q = _qr(session, qid)
    if body.style is not None:
        if float(body.style.get("size_mm", Q.MIN_MM)) < Q.MIN_MM:
            raise HTTPException(422, f"minimum printed size is {Q.MIN_MM:.0f} mm")
        q.style = Q.QRStyle.from_dict({**(q.style or {}), **body.style}).json()
    if body.link_id is not None and body.link_id != q.link_id:
        if session.get(Link, body.link_id) is None:
            raise HTTPException(404, "link not found")
        q.link_id = body.link_id
    if body.name is not None:
        q.name = body.name
    session.commit()
    return j_qr(session, q)


@router.delete("/qr/{qid}")
def delete_qr(qid: int, session: Session = S()) -> dict[str, Any]:
    q = _qr(session, qid)
    for pq in session.scalars(select(PageQR).where(PageQR.qr_id == q.id)).all():
        session.delete(pq)
    for m in session.scalars(select(Moment).where(Moment.qr_id == q.id)).all():
        m.qr_id = None
    session.delete(q)
    session.commit()
    return {"ok": True}


@router.post("/qr/{qid}/emblem")
async def upload_emblem(qid: int, file: UploadFile = File(...), session: Session = S()) -> dict[str, Any]:
    q = _qr(session, qid)
    raw = await file.read()
    name = (file.filename or "").lower()
    if name.endswith(".svg") or raw.lstrip()[:5] in (b"<?xml", b"<svg "):
        try:
            raw = Q.rasterise_svg_upload(raw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"could not rasterise the SVG: {exc}") from exc
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, "upload a PNG or SVG") from exc
    im.thumbnail((1024, 1024))
    d = db.DATA_DIR / "motion" / "emblems"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"qr{q.id}-{hashlib.sha1(raw).hexdigest()[:10]}.png"
    im.save(p)
    q.emblem_path = db.rel(p)
    q.style = {**(q.style or {}), "emblem": "upload"}
    session.commit()
    return j_qr(session, q)


@router.post("/qr/{qid}/test")
def test_qr(qid: int, session: Session = S()) -> dict[str, Any]:
    q = _qr(session, qid)
    run_test(session, q)
    session.commit()
    return j_qr(session, q)


@router.post("/qr/{qid}/approve")
def approve_qr(qid: int, session: Session = S()) -> dict[str, Any]:
    q = _qr(session, qid)
    require_tested(session, q, "approve it")
    q.approved = True
    session.commit()
    return j_qr(session, q)


@router.post("/qr/render")
def render_live(body: RenderIn, session: Session = S()) -> dict[str, Any]:
    """Live preview of an unsaved style: PNG at printed size on parchment (+ the decode test when asked)."""
    code = body.code
    if body.link_id:
        link = session.get(Link, body.link_id)
        if link is None:
            raise HTTPException(404, "link not found")
        code = link.code
    if not code:
        raise HTTPException(422, "give a link_id or a code")
    url = links.short_url(code)
    st = Q.QRStyle.from_dict(body.style)
    w, h = Q.dimensions(url, st)
    png = Q.preview_png(url, st, max(96, min(400, body.dpi)))
    out = {"url": url, "width_mm": round(w, 2), "height_mm": round(h, 2), "png": "data:image/png;base64," + base64.b64encode(png).decode(), "style": st.json()}
    if body.test:
        out["test"] = Q.decode_test(url, st)
    return out


@router.get("/qr/{qid}/preview.png")
def qr_preview(qid: int, dpi: int = 200, session: Session = S()) -> Response:
    q = _qr(session, qid)
    return Response(Q.preview_png(url_of(session, q), style_of(q), max(72, min(600, dpi))), media_type="image/png")


@router.get("/qr/{qid}/export.{fmt}")
def qr_export(qid: int, fmt: str, session: Session = S()) -> Response:
    q = _qr(session, qid)
    url, st = url_of(session, q), style_of(q)
    link = session.get(Link, q.link_id)
    name = f"qr-{link.code}-{int(st.size_mm)}mm"
    if fmt == "svg":
        return Response(Q.svg(url, st), media_type="image/svg+xml", headers={"Content-Disposition": f'attachment; filename="{name}.svg"'})
    if fmt == "png":
        return Response(Q.png(url, st, 600), media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{name}-600dpi.png"'})
    if fmt == "pdf":
        return Response(Q.pdf(url, st), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    raise HTTPException(404, "svg | png | pdf")


@router.post("/qr/{qid}/place", status_code=201)
def qr_place(qid: int, body: PlaceIn, session: Session = S()) -> dict[str, Any]:
    q = _qr(session, qid)
    page = session.get(Page, body.page_id)
    if page is None:
        raise HTTPException(404, "page not found")
    pq = place(session, q, page, body.x_mm, body.y_mm, body.w_mm)
    session.commit()
    return {"placement": {"id": pq.id, "page_id": pq.page_id, "qr_id": pq.qr_id, "x_mm": pq.x_mm, "y_mm": pq.y_mm, "w_mm": pq.w_mm}, "qr": j_qr(session, q)}


@router.get("/pages/{pid}/qr")
def page_qr(pid: int, session: Session = S()) -> list[dict[str, Any]]:
    if session.get(Page, pid) is None:
        raise HTTPException(404, "page not found")
    return [{k: (str(v) if isinstance(v, Path) else v) for k, v in e.items() if k != "path"} for e in page_elements(session, pid)]


@router.put("/page-qr/{eid}")
def move_page_qr(eid: int, body: PageQRIn, session: Session = S()) -> dict[str, Any]:
    pq = session.get(PageQR, eid)
    if pq is None:
        raise HTTPException(404, "placement not found")
    if body.w_mm is not None:
        if body.w_mm < Q.MIN_MM:
            raise HTTPException(422, f"minimum printed size is {Q.MIN_MM:.0f} mm")
        pq.w_mm = float(body.w_mm)
    if body.x_mm is not None:
        pq.x_mm = max(0.0, min(PAGE_W - pq.w_mm, float(body.x_mm)))
    if body.y_mm is not None:
        pq.y_mm = max(0.0, min(PAGE_H - pq.w_mm, float(body.y_mm)))
    session.commit()
    return {"id": pq.id, "page_id": pq.page_id, "qr_id": pq.qr_id, "x_mm": pq.x_mm, "y_mm": pq.y_mm, "w_mm": pq.w_mm}


@router.delete("/page-qr/{eid}")
def delete_page_qr(eid: int, session: Session = S()) -> dict[str, Any]:
    pq = session.get(PageQR, eid)
    if pq is None:
        raise HTTPException(404, "placement not found")
    session.delete(pq)
    session.commit()
    return {"ok": True}

