"""LINKS — the single source of truth for every printed short URL (https://cycleofdharma.world/v/{code}).

Rules
- code: lowercase a-z 0-9 and '-', 1-40 chars, starts/ends alphanumeric, not reserved, unique. Default "{volume}-{page}".
- once print_locked (set when a page carrying its QR is exported in print mode, or by hand) the CODE can never change
  and the link can never be deleted; only its destination / enabled / notes may change.
- a disabled printed link serves a friendly "coming soon" watch page, never a 404.
- status: published (enabled and resolves to something live) | draft | broken (target missing; for external URLs a
  HEAD check when online).
"""

from __future__ import annotations

import csv
import io
import os
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db
from .models import Chapter, Page
from .motion_models import Link, Moment, PageQR, QRCode

CODE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
RESERVED = {"v", "api", "media", "moments", "site-preview", "index", "404", "robots", "sitemap", "_next", "fonts", "static", "admin", "manifest"}
TARGET_TYPES = ("moment", "chapter", "page", "url")
DEFAULT_SITE = "https://cycleofdharma.world"


def site_url() -> str:
    from engine.settings import settings

    return (getattr(settings, "site_url", None) or os.environ.get("SITE_URL") or DEFAULT_SITE).rstrip("/")


def short_url(code: str) -> str:
    return f"{site_url()}/v/{code}"


class LinkError(ValueError):
    def __init__(self, msg: str, status: int = 422) -> None:
        super().__init__(msg)
        self.status = status


def check_code(session: Session, code: str, exclude_id: int | None = None) -> str | None:
    """None if the code is usable, else the reason."""
    if not code:
        return "the code is empty"
    if not CODE_RE.match(code):
        return "use lowercase a–z, 0–9 and '-' (1–40 characters, starting and ending with a letter or digit)"
    if "--" in code:
        return "no double hyphens"
    if code in RESERVED:
        return f"'{code}' is reserved"
    other = session.scalar(select(Link).where(Link.code == code))
    if other is not None and other.id != exclude_id:
        return f"'{code}' is already used (link #{other.id})"
    return None


def suggest_code(session: Session, base: str) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", (base or "").lower()).strip("-")[:36] or "m"
    code, k = base, 2
    while check_code(session, code):
        code = f"{base}-{k}"
        k += 1
    return code


def page_code(page: Page) -> str:
    return f"{page.chapter.volume.number}-{page.number}"


def is_url(s: str | None) -> bool:
    return bool(s) and bool(re.match(r"^https?://[^\s/$.?#].[^\s]*$", s or "", re.I))


# ---------------------------------------------------------------------------------
# resolution / status
# ---------------------------------------------------------------------------------


def target_row(session: Session, link: Link) -> Any:
    t, ref = link.target_type, (link.target_ref or "").strip()
    if t == "url":
        return ref if is_url(ref) else None
    if not ref.isdigit():
        return None
    model = {"moment": Moment, "chapter": Chapter, "page": Page}.get(t)
    return session.get(model, int(ref)) if model else None


def moment_for(session: Session, link: Link) -> Moment | None:
    row = target_row(session, link)
    if isinstance(row, Moment):
        return row
    if isinstance(row, Page):
        return session.scalar(select(Moment).where(Moment.page_id == row.id))
    return session.scalar(select(Moment).where(Moment.link_id == link.id))


def page_of(session: Session, link: Link) -> Page | None:
    row = target_row(session, link)
    if isinstance(row, Moment):
        return session.get(Page, row.page_id)
    if isinstance(row, Page):
        return row
    pq = session.scalar(select(PageQR).join(QRCode, QRCode.id == PageQR.qr_id).where(QRCode.link_id == link.id))
    return session.get(Page, pq.page_id) if pq else None


def resolved(session: Session, link: Link) -> dict[str, Any]:
    """What a scan of the short URL shows: kind and destination."""
    su = short_url(link.code)
    if not link.enabled:
        return {"kind": "coming_soon", "destination": su + "/", "label": "Coming soon page"}
    if link.destination_override:
        return {"kind": "redirect", "destination": link.destination_override, "label": "302 → override"}
    row = target_row(session, link)
    if link.target_type == "url":
        return {"kind": "redirect", "destination": row or link.target_ref, "label": "302 → URL"}
    if link.target_type == "chapter":
        return {"kind": "chapter", "destination": su + "/", "label": "Chapter page"}
    m = moment_for(session, link)
    if m is not None and m.status == "published":
        return {"kind": "moment", "destination": su + "/", "label": "Watch page"}
    return {"kind": "coming_soon", "destination": su + "/", "label": "Coming soon (not yet published)"}


def status(session: Session, link: Link) -> dict[str, Any]:
    row = target_row(session, link)
    reasons = []
    if row is None:
        reasons.append(f"{link.target_type} target '{link.target_ref}' not found")
    for what in ("destination_override", "target"):
        chk = (link.check or {}).get(what)
        if chk and chk.get("ok") is False:
            reasons.append(f"{what} check failed: {chk.get('error') or chk.get('status')}")
    if link.destination_override and not is_url(link.destination_override):
        reasons.append("destination override is not a URL")
    if reasons:
        return {"status": "broken", "reasons": reasons}
    r = resolved(session, link)
    if link.enabled and r["kind"] in ("moment", "redirect", "chapter"):
        if r["kind"] == "chapter":
            ch = row
            live = session.scalars(select(Moment).join(Page, Page.id == Moment.page_id).where(Page.chapter_id == ch.id, Moment.status == "published")).first()
            return {"status": "published" if live else "draft", "reasons": [] if live else ["no published moment in this chapter yet"]}
        return {"status": "published", "reasons": []}
    return {"status": "draft", "reasons": ["disabled — serves the coming-soon page"] if not link.enabled else ["the moment is not published yet"]}


def where_printed(session: Session, link: Link) -> list[dict[str, Any]]:
    out = []
    rows = session.execute(select(PageQR, QRCode).join(QRCode, QRCode.id == PageQR.qr_id).where(QRCode.link_id == link.id)).all()
    for pq, q in rows:
        pg = session.get(Page, pq.page_id)
        if pg is None:
            continue
        out.append({"page_id": pg.id, "volume": pg.chapter.volume.number, "chapter": pg.chapter.number, "page": pg.number, "qr_id": q.id,
                    "x_mm": pq.x_mm, "y_mm": pq.y_mm, "w_mm": pq.w_mm})
    return out


def title_of(session: Session, link: Link) -> str:
    m = moment_for(session, link)
    if m is not None and m.title_en:
        return m.title_en
    row = target_row(session, link)
    if isinstance(row, Chapter):
        return row.title
    if isinstance(row, Page):
        return f"{row.chapter.title} — page {row.number}"
    return link.notes or ""


def j_link(session: Session, link: Link) -> dict[str, Any]:
    st = status(session, link)
    pg = page_of(session, link)
    m = moment_for(session, link)
    return {
        "id": link.id, "code": link.code, "short_url": short_url(link.code), "target_type": link.target_type, "target_ref": link.target_ref,
        "destination_override": link.destination_override, "enabled": link.enabled, "notes": link.notes, "print_locked": link.print_locked,
        "scans_note": link.scans_note, "status": st["status"], "reasons": st["reasons"], "resolved": resolved(session, link),
        "where_printed": where_printed(session, link), "title": title_of(session, link), "check": link.check or {},
        "volume": pg.chapter.volume.number if pg else None, "page": pg.number if pg else None, "page_id": pg.id if pg else None,
        "moment_id": m.id if m else None, "moment_status": m.status if m else None,
        "qr_ids": [q.id for q in session.scalars(select(QRCode).where(QRCode.link_id == link.id)).all()],
        "created_at": link.created_at.isoformat() if link.created_at else None,
    }


# ---------------------------------------------------------------------------------
# mutations
# ---------------------------------------------------------------------------------


def create(session: Session, target_type: str, target_ref: str, code: str | None = None, destination_override: str | None = None,
           notes: str = "", enabled: bool = True) -> Link:
    if target_type not in TARGET_TYPES:
        raise LinkError(f"target_type must be one of {TARGET_TYPES}")
    tmp = Link(code="", target_type=target_type, target_ref=str(target_ref or ""))
    if target_type == "url" and not is_url(tmp.target_ref):
        raise LinkError("a url target must be an http(s) URL")
    if target_type != "url" and target_row(session, tmp) is None:
        raise LinkError(f"{target_type} {target_ref} not found", 404)
    if destination_override and not is_url(destination_override):
        raise LinkError("the destination override must be an http(s) URL")
    if not code:
        pg = None
        row = target_row(session, tmp)
        if isinstance(row, Moment):
            pg = session.get(Page, row.page_id)
        elif isinstance(row, Page):
            pg = row
        base = page_code(pg) if pg else (f"{row.volume.number}-ch{row.number}" if isinstance(row, Chapter) else "link")
        code = base if not check_code(session, base) else suggest_code(session, base)
    code = code.strip()
    err = check_code(session, code)
    if err:
        raise LinkError(err, 409 if "already used" in err else 422)
    link = Link(code=code, target_type=target_type, target_ref=str(target_ref or ""), destination_override=destination_override or None, notes=notes or "", enabled=enabled)
    session.add(link)
    session.flush()
    return link


def update(session: Session, link: Link, body: dict[str, Any]) -> Link:
    if "code" in body and body["code"] is not None and body["code"] != link.code:
        if link.print_locked:
            raise LinkError(f"'{link.code}' is printed (locked); its code can never change — edit the destination instead", 409)
        err = check_code(session, body["code"], exclude_id=link.id)
        if err:
            raise LinkError(err, 409 if "already used" in err else 422)
        link.code = body["code"]
    for k in ("target_type", "target_ref"):
        if k in body and body[k] is not None:
            setattr(link, k, str(body[k]))
    if link.target_type not in TARGET_TYPES:
        raise LinkError(f"target_type must be one of {TARGET_TYPES}")
    if "destination_override" in body:
        v = (body.get("destination_override") or "").strip() or None
        if v and not is_url(v):
            raise LinkError("the destination override must be an http(s) URL")
        link.destination_override = v
        link.check = {k: v2 for k, v2 in (link.check or {}).items() if k != "destination_override"}
    for k in ("enabled", "notes", "scans_note"):
        if k in body and body[k] is not None:
            setattr(link, k, body[k])
    if body.get("print_locked") is True:
        link.print_locked = True
    elif body.get("print_locked") is False and link.print_locked:
        raise LinkError("a printed link cannot be unlocked", 409)
    session.flush()
    return link


def delete(session: Session, link: Link) -> None:
    if link.print_locked:
        raise LinkError(f"'{link.code}' is printed (locked) and can never be deleted — disable it instead (it will show a coming-soon page)", 409)
    for q in session.scalars(select(QRCode).where(QRCode.link_id == link.id)).all():
        for pq in session.scalars(select(PageQR).where(PageQR.qr_id == q.id)).all():
            session.delete(pq)
        for m in session.scalars(select(Moment).where(Moment.qr_id == q.id)).all():
            m.qr_id = None
        session.delete(q)
    for m in session.scalars(select(Moment).where(Moment.link_id == link.id)).all():
        m.link_id = None
    session.delete(link)
    session.flush()


def lock_for_pages(session: Session, page_ids: list[int]) -> list[str]:
    """Print export: every link whose QR sits on one of these pages becomes print_locked. Returns the codes."""
    if not page_ids:
        return []
    codes = []
    rows = session.execute(select(Link).join(QRCode, QRCode.link_id == Link.id).join(PageQR, PageQR.qr_id == QRCode.id).where(PageQR.page_id.in_(page_ids))).scalars().all()
    for link in rows:
        if not link.print_locked:
            link.print_locked = True
        codes.append(link.code)
    session.flush()
    return sorted(set(codes))


def head_check(session: Session, link: Link, timeout: float = 8.0) -> dict[str, Any]:
    """HEAD the external destinations (override, url target). Offline -> unknown (not broken)."""
    import httpx

    out = dict(link.check or {})
    for what, url in (("destination_override", link.destination_override), ("target", link.target_ref if link.target_type == "url" else None)):
        if not url:
            out.pop(what, None)
            continue
        try:
            r = httpx.head(url, follow_redirects=True, timeout=timeout)
            if r.status_code in (405, 403):
                r = httpx.get(url, follow_redirects=True, timeout=timeout)
            out[what] = {"ok": r.status_code < 400, "status": r.status_code, "at": datetime.now(timezone.utc).isoformat()}
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            out[what] = {"ok": None, "error": f"offline? {type(exc).__name__}", "at": datetime.now(timezone.utc).isoformat()}
        except Exception as exc:  # noqa: BLE001
            out[what] = {"ok": False, "error": str(exc)[:200], "at": datetime.now(timezone.utc).isoformat()}
    link.check = out
    session.flush()
    return out


def printer_csv(session: Session) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["code", "url", "volume", "page", "title", "locked", "enabled"])
    for link in session.scalars(select(Link).order_by(Link.code)).all():
        pg = page_of(session, link)
        w.writerow([link.code, short_url(link.code), pg.chapter.volume.number if pg else "", pg.number if pg else "", title_of(session, link),
                    "yes" if link.print_locked else "no", "yes" if link.enabled else "no"])
    return buf.getvalue()


# ---------------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------------

router = APIRouter(prefix="/api", tags=["links"])


def S() -> Any:  # noqa: N802
    return Depends(db.get_session)


class LinkIn(BaseModel):
    code: str | None = None
    target_type: str | None = None
    target_ref: str | None = None
    destination_override: str | None = None
    enabled: bool | None = None
    notes: str | None = None
    print_locked: bool | None = None
    scans_note: str | None = None


def _err(e: LinkError) -> HTTPException:
    return HTTPException(e.status, str(e))


def _link(session: Session, lid: int) -> Link:
    link = session.get(Link, lid)
    if link is None:
        raise HTTPException(404, "link not found")
    return link


@router.get("/links")
def list_links(session: Session = S()) -> list[dict[str, Any]]:
    return [j_link(session, x) for x in session.scalars(select(Link).order_by(Link.code)).all()]


@router.get("/links/check-code")
def api_check_code(code: str, exclude_id: int | None = None, session: Session = S()) -> dict[str, Any]:
    err = check_code(session, code, exclude_id)
    return {"ok": err is None, "error": err, "suggestion": suggest_code(session, code) if err else code, "short_url": short_url(code)}


@router.get("/links/export.csv")
def links_csv(session: Session = S()) -> Response:
    return Response(printer_csv(session), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="cycleofdharma-links.csv"'})


@router.post("/links", status_code=201)
def post_link(body: LinkIn, session: Session = S()) -> dict[str, Any]:
    try:
        link = create(session, body.target_type or "moment", body.target_ref or "", body.code, body.destination_override, body.notes or "",
                      True if body.enabled is None else body.enabled)
    except LinkError as e:
        raise _err(e) from e
    session.commit()
    return j_link(session, link)


@router.get("/links/{lid}")
def get_link(lid: int, session: Session = S()) -> dict[str, Any]:
    return j_link(session, _link(session, lid))


@router.put("/links/{lid}")
def put_link(lid: int, body: LinkIn, session: Session = S()) -> dict[str, Any]:
    link = _link(session, lid)
    try:
        update(session, link, body.model_dump(exclude_unset=True))
    except LinkError as e:
        session.rollback()
        raise _err(e) from e
    session.commit()
    return j_link(session, link)


@router.post("/links/{lid}/lock")
def lock_link(lid: int, session: Session = S()) -> dict[str, Any]:
    link = _link(session, lid)
    link.print_locked = True
    session.commit()
    return j_link(session, link)


@router.post("/links/{lid}/check")
def check_link(lid: int, session: Session = S()) -> dict[str, Any]:
    link = _link(session, lid)
    head_check(session, link)
    session.commit()
    return j_link(session, link)


@router.delete("/links/{lid}")
def delete_link(lid: int, session: Session = S()) -> dict[str, Any]:
    link = _link(session, lid)
    try:
        delete(session, link)
    except LinkError as e:
        raise _err(e) from e
    session.commit()
    return {"ok": True}
