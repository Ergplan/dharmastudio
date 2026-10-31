"""Book API — /api/book/* : the layered book (paper / art / text per page) imported from a local package.

The book itself never ships with the studio: the author imports a `dharma-book/1` package (folder, .dharmabook or
.zip) at runtime and it is copied into <data>/books/<id>/ (backend/book_store.py). Rendering: engine/book_render.py.

GET    /import/candidates                         packages found in ~/apps/dharma-pipeline/exports, ~/Documents, ~/Downloads
POST   /import                    {path}           import a folder / manifest.json / .dharmabook / .zip
POST   /import/upload             (multipart file) import an uploaded .dharmabook / .zip
GET    /books                                      imported books
GET    /books/{bid}                                book meta + page summaries (in order, numbered)
DELETE /books/{bid}
PUT    /books/{bid}/order         {order: [pid]}  reorder
POST   /books/{bid}/undo                           undo the last change in the book
GET    /books/{bid}/history                        the action log (newest first)
POST   /books/{bid}/pages         {mode: blank|duplicate, source?, after?}
POST   /books/{bid}/pages/from-image   (multipart file, after?)
GET    /books/{bid}/pages/{pid}                    the full page (layers)
PATCH  /books/{bid}/pages/{pid}   {paper?, art?, text?, layers?, page_number?}
DELETE /books/{bid}/pages/{pid}
PUT    /books/{bid}/pages/{pid}/layers   {paper?, art?, text?}   layer visibility
PATCH  /books/{bid}/pages/{pid}/paper    {texture?, shloka_id?|null, figures?}
PATCH  /books/{bid}/pages/{pid}/art      {x,y,w,h,fit,focus,torn}
POST   /books/{bid}/pages/{pid}/art      (multipart file)  replace the painting
POST   /books/{bid}/pages/{pid}/text     {kind, style, text, x, y, w, h, font?, size?, align?, tail?, kicker?, title?}
PATCH  /books/{bid}/pages/{pid}/text/{tid}
DELETE /books/{bid}/pages/{pid}/text/{tid}
GET    /books/{bid}/pages/{pid}/history  ·  POST …/undo  ·  POST …/restore {seq}
GET    /books/{bid}/pages/{pid}/render?paper=screen|print   HTML (the same renderer as the PDF)
GET    /books/{bid}/pages/{pid}/thumb    small JPEG       GET …/png   the page as PNG at page_px
POST   /books/{bid}/export/pdf    {paper: print|screen, cover}   -> job (book_pdf)
POST   /books/{bid}/export/package                  -> a .dharmabook of the current book
GET    /books/{bid}/exports
GET    /shlokas  ·  /figures  ·  /textures  ·  /fonts  ·  /fonts/{file}  ·  /assets/textures/{file}
"""

from __future__ import annotations

import copy
import glob
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy.orm import Session

from engine import book_render as R

from . import book_store as S
from . import db, jobs

router = APIRouter(prefix="/api/book", tags=["book"])

CANDIDATE_NAME = "Cycle_of_Dharma_V1_V3.dharmabook"


def Sess() -> Any:  # noqa: N802
    return Depends(db.get_session)


def _err(e: S.BookError) -> HTTPException:
    return HTTPException(e.status, e.detail)


def _call(fn, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN202
    try:
        return fn(*a, **k)
    except S.BookError as e:
        raise _err(e) from None


# ---------------------------------------------------------------------------------
# resources for the renderer
# ---------------------------------------------------------------------------------


def http_resources(bid: str) -> R.Resources:
    bdir = S.book_dir(bid)

    def url(kind: str, path: Path) -> str:
        v = int(path.stat().st_mtime) if path.exists() else 0
        if kind == "art":
            return f"/media/books/{bid}/{path.relative_to(bdir).as_posix()}?v={v}"
        if kind == "figure":
            return f"/media/books/_assets/{path.name}"
        if kind in ("texture", "card"):
            return f"/api/book/assets/textures/{path.name}"
        if kind == "font":
            return f"/api/book/fonts/{path.name}"
        return path.as_uri()

    return R.Resources("http", bdir, S.assets_dir(), url)


class ScreenResources(R.Resources):
    """file:// resources with the art downscaled (for the screen PDF: a lighter file)."""

    def url(self, kind: str, path: Path) -> str:  # noqa: D102
        if kind == "art" and self.book_dir:
            small = self.book_dir / "_screen" / path.relative_to(self.book_dir)
            if not small.exists() or small.stat().st_mtime < path.stat().st_mtime:
                from PIL import Image

                small.parent.mkdir(parents=True, exist_ok=True)
                with Image.open(path) as im:
                    im = im.convert("RGB")
                    if im.width > 1100:
                        im = im.resize((1100, round(im.height * 1100 / im.width)), Image.LANCZOS)
                    im.save(small, "JPEG", quality=84)
            path = small
        return super().url(kind, path)


def file_resources(bid: str) -> R.Resources:
    return R.Resources("file", S.book_dir(bid), S.assets_dir())


# ---------------------------------------------------------------------------------
# validation of edits
# ---------------------------------------------------------------------------------


def _num(v: Any, lo: float = -10000, hi: float = 20000) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"not a number: {v!r}") from None
    return round(max(lo, min(hi, f)), 2)


TEXT_FIELDS = ("kind", "text", "x", "y", "w", "h", "style", "font", "size", "weight", "line", "align", "tail", "kicker", "title", "color")


def clean_text_box(t: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    out = dict(base or {})
    for k, v in t.items():
        if k not in TEXT_FIELDS:
            continue
        if k in ("x", "y"):
            out[k] = _num(v)
        elif k in ("w", "h"):
            out[k] = _num(v, 20, 20000)
        elif k in ("size", "line", "weight"):
            out[k] = None if v in (None, "") else _num(v, 8 if k != "weight" else 100, 400 if k != "weight" else 900)
        elif k == "style":
            if v not in R.STYLES:
                raise HTTPException(400, f"style must be one of {', '.join(R.STYLES)}")
            out[k] = v
        elif k == "kind":
            if v not in R.TEXT_KINDS:
                raise HTTPException(400, f"kind must be one of {', '.join(R.TEXT_KINDS)}")
            out[k] = v
        elif k == "font":
            if v is not None and v not in R.book_fonts():
                raise HTTPException(400, f"unknown font {v!r}")
            out[k] = v
        elif k == "align":
            if v is not None and v not in R.ALIGNS:
                raise HTTPException(400, "align must be left, center or right")
            out[k] = v
        elif k == "tail":
            if v is None:
                out[k] = None
            elif isinstance(v, (list, tuple)) and len(v) == 2:
                out[k] = [_num(v[0]), _num(v[1])]
            else:
                raise HTTPException(400, "tail is [x, y] or null")
        elif k == "color":
            out[k] = str(v)[:32] if v else None
        else:
            out[k] = "" if v is None else str(v)[:4000]
    if out.get("style") == "header" and "text" in t and "title" not in t:
        out["title"] = out["text"]
    if out.get("style") == "header" and ("title" in t or "kicker" in t) and "text" not in t:
        out["text"] = " · ".join(x for x in (out.get("kicker"), out.get("title")) if x)
    return {k: v for k, v in out.items() if v is not None or k == "tail"}


def clean_paper(p: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    if "texture" in p:
        if p["texture"] not in R.texture_names():
            raise HTTPException(400, f"unknown texture {p['texture']!r}")
        out["texture"] = p["texture"]
    if "shloka_id" in p:
        if p["shloka_id"] in (None, ""):
            out["shloka"] = None
        else:
            s = R.shloka(str(p["shloka_id"]))
            if s is None:
                raise HTTPException(400, f"unknown shloka {p['shloka_id']!r}")
            out["shloka"] = {"id": s["id"], "lines": s["lines"], "source": s["source"]}
    if "shloka" in p:
        s = p["shloka"]
        if s is None:
            out["shloka"] = None
        elif isinstance(s, dict) and isinstance(s.get("lines"), list):
            out["shloka"] = {"id": str(s.get("id") or "custom"), "lines": [str(x)[:300] for x in s["lines"][:6]], "source": str(s.get("source") or "")[:200]}
        else:
            raise HTTPException(400, "shloka is {id, lines[], source} or null")
    if "figures" in p:
        figs = []
        names = set(R.figure_names())
        for f in p["figures"] or []:
            if f.get("name") not in names:
                raise HTTPException(400, f"unknown figure {f.get('name')!r}")
            figs.append({"name": f["name"], "x": _num(f.get("x", 0)), "y": _num(f.get("y", 0)), "h": _num(f.get("h", 400), 20, 6000),
                         "opacity": _num(f.get("opacity", 0.4), 0, 1), "mirror": bool(f.get("mirror"))})
        out["figures"] = figs
    return out


def clean_art(a: dict[str, Any], base: dict[str, Any] | None) -> dict[str, Any] | None:
    if base is None:
        raise HTTPException(409, "this page has no art yet: upload a painting first")
    out = dict(base)
    for k in ("x", "y"):
        if k in a:
            out[k] = _num(a[k])
    for k in ("w", "h"):
        if k in a:
            out[k] = _num(a[k], 20, 20000)
    if "fit" in a:
        if a["fit"] not in ("cover", "contain", "fill"):
            raise HTTPException(400, "fit is cover, contain or fill")
        out["fit"] = a["fit"]
    if "focus" in a:
        f = a["focus"] or [0.5, 0.5]
        out["focus"] = [_num(f[0], 0, 1), _num(f[1], 0, 1)]
    if "torn" in a:
        out["torn"] = bool(a["torn"])
    return out


# ---------------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------------


def page_hash(p: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps({k: v for k, v in p.items() if k != "number"}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def page_view(bid: str, p: dict[str, Any]) -> dict[str, Any]:
    art = p.get("art")
    h = page_hash(p)
    return {**p, "rev": h, "thumb": f"/api/book/books/{bid}/pages/{p['id']}/thumb?v={h}",
            "art_url": f"/media/books/{bid}/{art['file']}" if art and art.get("file") else None}


def page_summary(bid: str, p: dict[str, Any]) -> dict[str, Any]:
    h = page_hash(p)
    return {"id": p["id"], "number": p.get("number"), "rev": h, "thumb": f"/api/book/books/{bid}/pages/{p['id']}/thumb?v={h}", "texts": len(p.get("text") or []),
            "has_art": bool(p.get("art")), "layers": p.get("layers"), "template": p.get("template"), "era": p.get("era"),
            "header": next((t.get("title") or t.get("text") for t in p.get("text") or [] if t.get("style") == "header"), None)}


def book_view(bid: str) -> dict[str, Any]:
    b = S.load_book(bid)
    ps = S.pages(bid)
    cover = (b.get("cover") or {}).get("file")
    return {**S.summary(b), "page_px": b.get("page_px"), "trim_mm": b.get("trim_mm"), "bleed_mm": b.get("bleed_mm"), "frame": b.get("frame"), "styles": b.get("styles"),
            "cover_url": f"/media/books/{bid}/{cover}" if cover else None, "pages_list": [page_summary(bid, p) for p in ps],
            "undo": len(S.history(bid)), "format": b.get("format")}


# ---------------------------------------------------------------------------------
# catalogue
# ---------------------------------------------------------------------------------


@router.get("/shlokas")
def get_shlokas() -> list[dict[str, Any]]:
    return R.shlokas()


@router.get("/figures")
def get_figures() -> list[dict[str, Any]]:
    out = []
    for n in R.figure_names():
        p = R.figure_png(n, S.assets_dir())
        out.append({"name": n, "url": f"/media/books/_assets/{p.name}" if p else None, "aspect": R.image_aspect(R.FIGURES / f"fig_{n}.png")})
    return out


@router.get("/textures")
def get_textures() -> list[dict[str, Any]]:
    return [{"name": n, "url": f"/api/book/assets/textures/{n}.jpg"} for n in R.texture_names()]


@router.get("/fonts")
def get_fonts() -> list[dict[str, Any]]:
    house = list(R._HOUSE)
    return [{"family": fam, "house": fam in house, "faces": [{"file": f, "weight": w, "style": s, "url": f"/api/book/fonts/{f}"} for f, w, s in faces]}
            for fam, faces in sorted(R.book_fonts().items(), key=lambda kv: (kv[0] not in house, kv[0]))]


@router.get("/fonts/{name}", include_in_schema=False)
def get_font(name: str) -> Response:
    p = R.font_file(name)
    if p is None:
        raise HTTPException(404, "font not found")
    return FileResponse(p, media_type="font/ttf", headers={"Cache-Control": "public, max-age=31536000, immutable", "Access-Control-Allow-Origin": "*"})


@router.get("/assets/textures/{name}", include_in_schema=False)
def get_texture(name: str) -> Response:
    p = R.TEXTURES / name
    if "/" in name or not p.is_file() or p.suffix.lower() not in (".jpg", ".png"):
        raise HTTPException(404, "texture not found")
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


# ---------------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------------


def search_dirs() -> list[Path]:
    home = Path(os.environ.get("HOME") or Path.home())
    return [home / "apps" / "dharma-pipeline" / "exports", home / "Documents", home / "Downloads"]


@router.get("/import/candidates")
def import_candidates() -> dict[str, Any]:
    """Packages on this Mac the author may import (offered only; nothing is imported until asked)."""
    found = []
    for d in search_dirs():
        if not d.is_dir():
            continue
        try:
            items = sorted(d.glob(f"*{S.PACKAGE_EXT}"))
        except OSError:
            continue
        for f in items:
            if f.is_file():
                st = f.stat()
                found.append({"path": str(f), "name": f.name, "dir": str(d), "bytes": st.st_size, "preferred": f.name == CANDIDATE_NAME,
                              "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")})
    found.sort(key=lambda x: (not x["preferred"], x["name"]))
    return {"candidates": found, "searched": [str(d) for d in search_dirs()], "name": CANDIDATE_NAME}


@router.post("/import")
def import_book(body: dict[str, Any]) -> dict[str, Any]:
    path = str(body.get("path") or "").strip()
    if not path:
        raise HTTPException(400, "path is required")
    b = _call(S.import_path, path)
    return book_view(b["id"])


@router.post("/import/upload")
def import_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    tmp = Path(tempfile.mkstemp(suffix=".zip", dir=S.root())[1])
    try:
        with open(tmp, "wb") as fo:
            shutil.copyfileobj(file.file, fo, 1 << 20)
        import zipfile

        if not zipfile.is_zipfile(tmp):
            raise HTTPException(400, "upload a .dharmabook or .zip package")
        b = _call(S.import_zip, tmp, file.filename or "upload")
    finally:
        tmp.unlink(missing_ok=True)
    return book_view(b["id"])


# ---------------------------------------------------------------------------------
# books and pages
# ---------------------------------------------------------------------------------


@router.get("/books")
def books() -> list[dict[str, Any]]:
    return S.list_books()


@router.get("/books/{bid}")
def get_book(bid: str) -> dict[str, Any]:
    return _call(book_view, bid)


@router.delete("/books/{bid}")
def delete_book(bid: str) -> dict[str, Any]:
    _call(S.delete_book, bid)
    return {"deleted": bid}


@router.put("/books/{bid}/order")
def put_order(bid: str, body: dict[str, Any]) -> dict[str, Any]:
    _call(S.set_order, bid, [str(x) for x in body.get("order") or []])
    return book_view(bid)


@router.post("/books/{bid}/undo")
def book_undo(bid: str) -> dict[str, Any]:
    r = _call(S.undo, bid)
    return {**r, "book": book_view(bid)}


@router.get("/books/{bid}/history")
def book_history(bid: str) -> list[dict[str, Any]]:
    return [{k: e[k] for k in ("seq", "at", "kind", "action", "pid")} for e in _call(S.history, bid)][::-1]


@router.post("/books/{bid}/pages")
def add_page(bid: str, body: dict[str, Any]) -> dict[str, Any]:
    mode = body.get("mode") or "blank"
    b = _call(S.load_book, bid)
    pid = S.new_page_id(bid)
    after = body.get("after")
    if mode == "blank":
        page = S.blank_page(pid, b)
    elif mode == "duplicate":
        src = _call(S.load_page, bid, str(body.get("source") or after or ""))
        page = copy.deepcopy(src)
        page["id"] = pid
        for i, t in enumerate(page.get("text") or []):
            t["id"] = f"{pid}-t{i + 1}"
        after = after or src["id"]
    else:
        raise HTTPException(400, "mode is blank or duplicate (from an image: POST …/pages/from-image)")
    p = _call(S.add_page, bid, page, after, f"add page ({mode})")
    return {"page": page_view(bid, p), "book": book_view(bid)}


@router.post("/books/{bid}/pages/from-image")
def add_page_from_image(bid: str, file: UploadFile = File(...), after: str | None = Form(None)) -> dict[str, Any]:
    b = _call(S.load_book, bid)
    pid = S.new_page_id(bid)
    tmp = Path(tempfile.mkstemp(suffix=Path(file.filename or "x.jpg").suffix, dir=S.book_dir(bid))[1])
    try:
        with open(tmp, "wb") as fo:
            shutil.copyfileobj(file.file, fo, 1 << 20)
        try:
            rel = S.save_art_file(bid, tmp, pid)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"not an image: {exc}") from None
    finally:
        tmp.unlink(missing_ok=True)
    page = S.blank_page(pid, b)
    page["art"] = {"file": rel, **S.frame_window(b), "torn": True, "fit": "cover"}
    page["template"] = "IMAGE"
    p = _call(S.add_page, bid, page, after, "add page (from image)")
    return {"page": page_view(bid, p), "book": book_view(bid)}


@router.get("/books/{bid}/pages/{pid}")
def get_page(bid: str, pid: str) -> dict[str, Any]:
    p = _call(S.load_page, bid, pid)
    p["number"] = S.number_of(S.load_book(bid), pid)
    return page_view(bid, p)


@router.patch("/books/{bid}/pages/{pid}")
def patch_page(bid: str, pid: str, body: dict[str, Any]) -> dict[str, Any]:
    def fn(p: dict[str, Any]) -> None:
        if "paper" in body:
            p["paper"] = clean_paper(body["paper"] or {}, p.get("paper") or {})
        if "art" in body:
            p["art"] = None if body["art"] is None else clean_art(body["art"], p.get("art"))
        if "text" in body:
            p["text"] = [clean_text_box(t) for t in body["text"] or []]
        if "layers" in body:
            p["layers"] = {**(p.get("layers") or {}), **{k: bool(v) for k, v in (body["layers"] or {}).items() if k in ("paper", "art", "text")}}
        if "page_number" in body:
            p["page_number"] = bool(body["page_number"])

    return page_view(bid, _call(S.mutate_page, bid, pid, fn, str(body.get("action") or "edit page")))


@router.delete("/books/{bid}/pages/{pid}")
def delete_page(bid: str, pid: str) -> dict[str, Any]:
    r = _call(S.delete_page, bid, pid)
    return {**r, "book": book_view(bid)}


@router.put("/books/{bid}/pages/{pid}/layers")
def put_layers(bid: str, pid: str, body: dict[str, Any]) -> dict[str, Any]:
    vis = {k: bool(v) for k, v in body.items() if k in ("paper", "art", "text")}
    label = "show/hide " + ", ".join(f"{k} {'on' if v else 'off'}" for k, v in vis.items())
    return page_view(bid, _call(S.mutate_page, bid, pid, lambda p: p.update(layers={**p["layers"], **vis}), label))


@router.patch("/books/{bid}/pages/{pid}/paper")
def patch_paper(bid: str, pid: str, body: dict[str, Any]) -> dict[str, Any]:
    return page_view(bid, _call(S.mutate_page, bid, pid, lambda p: p.update(paper=clean_paper(body, p.get("paper") or {})), "edit paper"))


@router.patch("/books/{bid}/pages/{pid}/art")
def patch_art(bid: str, pid: str, body: dict[str, Any]) -> dict[str, Any]:
    return page_view(bid, _call(S.mutate_page, bid, pid, lambda p: p.update(art=clean_art(body, p.get("art"))), "edit art"))


@router.post("/books/{bid}/pages/{pid}/art")
def replace_art(bid: str, pid: str, file: UploadFile = File(...)) -> dict[str, Any]:
    b = _call(S.load_book, bid)
    _call(S.load_page, bid, pid)
    tmp = Path(tempfile.mkstemp(suffix=Path(file.filename or "x.jpg").suffix, dir=S.book_dir(bid))[1])
    try:
        with open(tmp, "wb") as fo:
            shutil.copyfileobj(file.file, fo, 1 << 20)
        try:
            rel = S.save_art_file(bid, tmp, pid)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"not an image: {exc}") from None
    finally:
        tmp.unlink(missing_ok=True)

    def fn(p: dict[str, Any]) -> None:
        base = p.get("art") or {**S.frame_window(b), "torn": True, "fit": "cover"}
        p["art"] = {**base, "file": rel}

    return page_view(bid, _call(S.mutate_page, bid, pid, fn, "replace art"))


@router.post("/books/{bid}/pages/{pid}/text")
def add_text(bid: str, pid: str, body: dict[str, Any]) -> dict[str, Any]:
    b = _call(S.load_book, bid)
    fw = S.frame_window(b)
    style = body.get("style") or "parchment"
    defaults = {"kind": "dialogue" if style == "glass" else "header" if style == "header" else "narration", "text": "New text", "style": style,
                "x": fw["x"] + 60, "y": fw["y"] + 60, "w": 760, "h": 170 if style != "header" else 190, "tail": None}
    if style == "header":
        defaults.update(kicker="BOOK ONE", title="Title")
        merged = {**defaults, **body}
        defaults["text"] = " · ".join(str(x) for x in (merged.get("kicker"), merged.get("title")) if x)
    box = clean_text_box({**defaults, **body})
    out: dict[str, Any] = {}

    def fn(p: dict[str, Any]) -> None:
        box["id"] = S.next_text_id(p)
        p["text"].append(box)
        out["id"] = box["id"]

    page = _call(S.mutate_page, bid, pid, fn, "add text box")
    return {**page_view(bid, page), "created": out.get("id")}


@router.patch("/books/{bid}/pages/{pid}/text/{tid}")
def patch_text(bid: str, pid: str, tid: str, body: dict[str, Any]) -> dict[str, Any]:
    def fn(p: dict[str, Any]) -> None:
        for i, t in enumerate(p["text"]):
            if t.get("id") == tid:
                p["text"][i] = {**clean_text_box(body, t), "id": tid}
                if body.get("z") in ("front", "back"):
                    box = p["text"].pop(i)
                    p["text"].insert(len(p["text"]) if body["z"] == "front" else 0, box)
                return
        raise S.BookError(404, "text box not found")

    keys = sorted(k for k in body if k in TEXT_FIELDS or k == "z")
    label = "move text" if set(keys) <= {"x", "y"} else "resize text" if set(keys) <= {"x", "y", "w", "h"} else f"edit text ({', '.join(keys)})"
    return page_view(bid, _call(S.mutate_page, bid, pid, fn, label))


@router.delete("/books/{bid}/pages/{pid}/text/{tid}")
def delete_text(bid: str, pid: str, tid: str) -> dict[str, Any]:
    def fn(p: dict[str, Any]) -> None:
        n = len(p["text"])
        p["text"] = [t for t in p["text"] if t.get("id") != tid]
        if len(p["text"]) == n:
            raise S.BookError(404, "text box not found")

    return page_view(bid, _call(S.mutate_page, bid, pid, fn, "delete text box"))


@router.get("/books/{bid}/pages/{pid}/history")
def get_page_history(bid: str, pid: str) -> list[dict[str, Any]]:
    _call(S.load_page, bid, pid)
    return S.page_history(bid, pid)


@router.post("/books/{bid}/pages/{pid}/undo")
def page_undo(bid: str, pid: str) -> dict[str, Any]:
    r = _call(S.undo, bid, pid)
    return {**r, "page": get_page(bid, pid)}


@router.post("/books/{bid}/pages/{pid}/restore")
def page_restore(bid: str, pid: str, body: dict[str, Any]) -> dict[str, Any]:
    return page_view(bid, _call(S.restore, bid, pid, int(body.get("seq") or 0)))


# ---------------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------------


@router.get("/books/{bid}/pages/{pid}/render", response_class=HTMLResponse)
def render_page(bid: str, pid: str, paper: str = "screen", embed: bool = False) -> HTMLResponse:
    b = _call(S.load_book, bid)
    p = _call(S.load_page, bid, pid)
    res = R.Resources("embed", S.book_dir(bid), S.assets_dir()) if embed else http_resources(bid)
    return HTMLResponse(R.page_document(b, p, res, "print" if paper == "print" else "screen", S.number_of(b, pid)))


@router.get("/books/{bid}/pages/{pid}/thumb", include_in_schema=False)
def thumb(bid: str, pid: str) -> Response:
    b = _call(S.load_book, bid)
    p = _call(S.load_page, bid, pid)
    d = S.book_dir(bid) / "thumbs"
    d.mkdir(exist_ok=True)
    f = d / f"{pid}-{page_hash(p)}.jpg"
    if not f.exists():
        for old in d.glob(f"{pid}-*.jpg"):
            old.unlink(missing_ok=True)
        make_thumb(b, p, S.book_dir(bid), f)
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})


def make_thumb(b: dict[str, Any], p: dict[str, Any], bdir: Path, out: Path, width: int = 240) -> None:
    """A quick PIL sketch of the page (paper, art, text boxes as cards) for the page strip."""
    from PIL import Image, ImageDraw

    g = R.Geo.of(b)
    k = width / g.W
    H = round(g.H * k)
    lay = R.layers_of(p)
    tex = R.TEXTURES / f"{(p.get('paper') or {}).get('texture') or 'page_warm'}.jpg"
    if lay["paper"] and tex.exists():
        with Image.open(tex) as t:
            im = t.convert("RGB").resize((width, H))
    else:
        im = Image.new("RGB", (width, H), "#ffffff")
    art = p.get("art")
    if lay["art"] and art and (bdir / art["file"]).exists():
        with Image.open(bdir / art["file"]) as a:
            a.draft("RGB", (max(1, int(art["w"] * k)) * 2, max(1, int(art["h"] * k)) * 2))
            box = (max(1, round(art["w"] * k)), max(1, round(art["h"] * k)))
            if art.get("fit") == "contain":
                a2 = a.convert("RGB")
                a2.thumbnail(box)
                im.paste(a2, (round(art["x"] * k + (box[0] - a2.width) / 2), round(art["y"] * k + (box[1] - a2.height) / 2)))
            else:
                from PIL import ImageOps

                im.paste(ImageOps.fit(a.convert("RGB"), box), (round(art["x"] * k), round(art["y"] * k)))
    if lay["text"]:
        dr = ImageDraw.Draw(im, "RGBA")
        for t in p.get("text") or []:
            x0, y0 = t.get("x", 0) * k, t.get("y", 0) * k
            x1, y1 = x0 + t.get("w", 0) * k, y0 + t.get("h", 0) * k
            if str(t.get("style", "")).startswith("glass"):
                dr.rounded_rectangle([x0, y0, x1, y1], 3, fill=(14, 18, 26, 170), outline=(255, 255, 255, 110))
            else:
                dr.rectangle([x0, y0, x1, y1], fill=(239, 228, 201, 240), outline=(92, 52, 22, 200))
    im.save(out, "JPEG", quality=82)


def _chromium() -> str | None:
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM")
    if exe and Path(exe).exists():
        return exe
    found = sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome") + glob.glob("/opt/pw-browsers/chromium*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium"))
    return found[0] if found else None


def screenshot(html_path: Path, out_png: Path, w_mm: float, h_mm: float, px_w: int) -> Path:
    """Render one page of HTML to a PNG px_w pixels wide (Playwright, else the studio's headless shell / Chrome)."""
    css_w, css_h = w_mm / 25.4 * 96, h_mm / 25.4 * 96
    scale = px_w / css_w
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            try:
                br = pw.chromium.launch()
            except Exception:
                exe = _chromium()
                if not exe:
                    raise
                br = pw.chromium.launch(executable_path=exe)
            pg = br.new_page(viewport={"width": int(css_w) + 1, "height": int(css_h) + 1}, device_scale_factor=scale)
            pg.goto(html_path.resolve().as_uri())
            pg.evaluate("document.fonts.ready.then(() => Promise.all([...document.images].map(i => i.complete ? 1 : new Promise(r => { i.onload = i.onerror = r }))))")
            pg.locator("section.bpage").first.screenshot(path=str(out_png))
            br.close()
        return out_png
    except Exception:  # noqa: BLE001
        from engine import pdf_engine

        cands = [pdf_engine.installed(), _chromium(), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", shutil.which("chromium"), shutil.which("google-chrome")]
        exe = next((str(c) for c in cands if c and Path(str(c)).exists()), None)
        if not exe:
            raise HTTPException(503, "no headless browser available to render the PNG") from None
        subprocess.run([exe, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", f"--force-device-scale-factor={scale:.5f}",
                        f"--window-size={round(css_w)},{round(css_h)}", "--virtual-time-budget=4000", f"--screenshot={out_png}", html_path.resolve().as_uri()],
                       check=True, timeout=180, capture_output=True)
        return out_png


@router.get("/books/{bid}/pages/{pid}/png")
def page_png(bid: str, pid: str, paper: str = "screen") -> Response:
    b = _call(S.load_book, bid)
    p = _call(S.load_page, bid, pid)
    paper = "print" if paper == "print" else "screen"
    d = S.book_dir(bid) / "exports"
    d.mkdir(exist_ok=True)
    num = S.number_of(b, pid)
    html_path = d / f"_page-{pid}.html"
    extra = "html,body{background:transparent}"
    html_path.write_text(R.page_document(b, p, file_resources(bid), paper, num, extra), encoding="utf-8")
    w_mm, h_mm = R.page_size_mm(b, paper)
    g = R.Geo.of(b)
    out = d / f"page-{num or 0:03d}-{pid}{'-print' if paper == 'print' else ''}.png"
    try:
        screenshot(html_path, out, w_mm, h_mm, round(w_mm / g.k))
    finally:
        html_path.unlink(missing_ok=True)
    return FileResponse(out, media_type="image/png", filename=out.name)


# ---------------------------------------------------------------------------------
# exports
# ---------------------------------------------------------------------------------


PDF_CHUNK = 6  # pages per headless-Chrome pass: a whole book in one pass exhausts the renderer's memory


def h_book_pdf(ctx: jobs.Ctx, params: dict[str, Any]) -> dict[str, Any]:
    """The whole book (cover + pages in order) as one PDF. Rendered in chunks of PDF_CHUNK pages, then joined."""
    import pikepdf

    from engine.comic.layout import render_pdf

    bid = str(params["book_id"])
    paper = "print" if params.get("paper") != "screen" else "screen"
    cover = bool(params.get("cover", True))
    b = S.load_book(bid)
    ps = S.pages(bid)
    bdir = S.book_dir(bid)
    res = ScreenResources("file", bdir, S.assets_dir()) if paper == "screen" else file_resources(bid)
    out = bdir / "exports"
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    pdf = out / f"{S._slug(b.get('title', 'book'))}-{paper}-{stamp}.pdf"
    chunks = [ps[i:i + PDF_CHUNK] for i in range(0, len(ps), PDF_CHUNK)] or [[]]
    ctx.log(f"{len(ps)} pages{' + cover' if cover else ''}, {paper}, {len(chunks)} part(s)")
    work = Path(tempfile.mkdtemp(prefix="pdf-", dir=out))
    try:
        parts = []
        for k, chunk in enumerate(chunks):
            ctx.check_stop()
            ctx.progress(done=k, total=len(chunks) + 1)
            part = work / f"part-{k:03d}.pdf"
            htm = R.book_document(b, chunk, res, paper, cover=cover and k == 0, first_number=k * PDF_CHUNK + 1)
            render_pdf(htm, part, progress=lambda f, m: ctx.log(m))
            if paper == "print":
                try:
                    from engine.comic.proof import compress_pdf

                    compress_pdf(part)
                except Exception as exc:  # noqa: BLE001
                    ctx.log(f"compress skipped: {exc}")
            parts.append(part)
            ctx.log(f"part {k + 1}/{len(chunks)}: pages {k * PDF_CHUNK + 1}-{k * PDF_CHUNK + len(chunk)}")
        with pikepdf.new() as dst:
            for part in parts:
                with pikepdf.open(part) as src:
                    dst.pages.extend(src.pages)
            dst.docinfo["/Title"] = str(b.get("title") or "Book")
            if b.get("author"):
                dst.docinfo["/Author"] = str(b["author"])
            dst.save(pdf)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    ctx.progress(done=len(chunks) + 1, total=len(chunks) + 1)
    n = len(ps) + (1 if cover else 0)
    w, h = R.page_size_mm(b, paper)
    ctx.log(f"wrote {pdf.name}: {n} pages at {w} x {h} mm")
    return {"pdf": db.rel(pdf), "url": db.media_url(db.rel(pdf)), "pages": n, "paper": paper, "size_mm": [w, h], "bytes": pdf.stat().st_size}


jobs.HANDLERS.setdefault("book_pdf", h_book_pdf)


@router.post("/books/{bid}/export/pdf", status_code=202)
def export_pdf(bid: str, body: dict[str, Any], session: Session = Sess()) -> dict[str, Any]:
    b = _call(S.load_book, bid)
    from .api import job_resp

    paper = "screen" if body.get("paper") == "screen" else "print"
    j = jobs.submit(session, "book_pdf", None, {"book_id": bid, "paper": paper, "cover": bool(body.get("cover", True)),
                                                 "label": f"Book PDF ({paper}) · {b.get('title', '')}"})
    return job_resp(j)


@router.post("/books/{bid}/export/package")
def export_package(bid: str) -> dict[str, Any]:
    p = _call(S.export_package, bid)
    rel = db.rel(p)
    return {"path": str(p), "url": db.media_url(rel), "name": p.name, "bytes": p.stat().st_size}


@router.get("/books/{bid}/exports")
def list_exports(bid: str) -> list[dict[str, Any]]:
    d = _call(S.book_dir, bid) / "exports"
    out = []
    if d.is_dir():
        for f in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.suffix in (".pdf", S.PACKAGE_EXT, ".png"):
                out.append({"name": f.name, "url": db.media_url(db.rel(f)), "bytes": f.stat().st_size, "kind": f.suffix.lstrip("."),
                            "modified": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
    return out
