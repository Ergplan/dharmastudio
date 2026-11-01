"""Stitch store: the photo repo and the stitch projects, as plain files in the data folder (never in the repo).

    <data>/stitch/repo/index.json          the photo library: one record per photo (tags, book / page / era / chapter,
                                           subjects = named crop boxes in fractions of the photo)
    <data>/stitch/repo/photos/<id>.<ext>   the photos (copied in; a photo is identified by its content, so the same
                                           painting imported twice is one photo)
    <data>/stitch/repo/thumbs/<id>.jpg     grid thumbnails
    <data>/stitch/projects/<id>/
        project.json   title, source, placements, plates, AI suggestions and reviews
        source.pdf     the author's typeset PDF (a copy; it is never modified)
        analysis.json  engine.stitch.analyse() of source.pdf
        history.json   every change keeps the placements and plates as they were before (undo)
        cache/ exports/

Follows backend/book_store.py: JSON files written atomically, one lock, a capped action log with never-reused seqs.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import db

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
HISTORY_CAP = 400
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_lock = threading.RLock()


class StitchError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def root() -> Path:
    d = db.DATA_DIR / "stitch"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(p: Path, default: Any = None) -> Any:
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def _write(p: Path, data: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def check_id(x: Any, what: str = "id") -> str:
    if not ID_RE.match(str(x or "")):
        raise StitchError(400, f"bad {what}: {x!r}")
    return str(x)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "stitch").lower()).strip("-")[:40] or "stitch"


# ---------------------------------------------------------------------------------
# photo repo
# ---------------------------------------------------------------------------------


def repo_dir() -> Path:
    d = root() / "repo"
    (d / "photos").mkdir(parents=True, exist_ok=True)
    (d / "thumbs").mkdir(parents=True, exist_ok=True)
    return d


def photos() -> list[dict[str, Any]]:
    return _read(repo_dir() / "index.json", [])


def _save_photos(ps: list[dict[str, Any]]) -> None:
    _write(repo_dir() / "index.json", ps)


def photo(pid: str) -> dict[str, Any]:
    p = next((x for x in photos() if x["id"] == pid), None)
    if p is None:
        raise StitchError(404, f"photo not found: {pid}")
    return p


def photo_path(p: dict[str, Any]) -> Path:
    return repo_dir() / p["file"]


def clean_tags(v: Any) -> list[str]:
    if isinstance(v, str):
        v = re.split(r"[,;]", v)
    out: list[str] = []
    for t in v or []:
        t = " ".join(str(t).split())[:40]
        if t and t.lower() not in (x.lower() for x in out):
            out.append(t)
    return out[:20]


def add_photo(src: Path, meta: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Copy an image into the repo (identified by its content). Returns (record, created). Existing photos get the new
    tags merged in (and any book / page / era / chapter they did not have)."""
    from PIL import Image

    if src.suffix.lower() not in IMAGE_EXT:
        raise StitchError(400, f"not an image: {src.name}")
    h = hashlib.sha1()
    with open(src, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    pid = "ph" + h.hexdigest()[:12]
    with _lock:
        ps = photos()
        old = next((x for x in ps if x["id"] == pid), None)
        if old:
            old["tags"] = clean_tags(old.get("tags", []) + clean_tags(meta.get("tags")))
            for k in ("book", "book_id", "page", "era", "chapter"):
                if meta.get(k) is not None and old.get(k) in (None, ""):
                    old[k] = meta[k]
            _save_photos(ps)
            return old, False
        try:
            with Image.open(src) as im:
                im.load()
                w, h_ = im.size
                ext = ".png" if im.mode in ("RGBA", "LA", "P") and src.suffix.lower() == ".png" else ".jpg"
                d = repo_dir()
                if src.suffix.lower() in (".jpg", ".jpeg"):
                    shutil.copyfile(src, d / "photos" / f"{pid}.jpg")
                else:
                    (im.convert("RGBA") if ext == ".png" else im.convert("RGB")).save(d / "photos" / f"{pid}{ext}", quality=92)
                t = im.convert("RGB")
                t.thumbnail((360, 360))
                t.save(d / "thumbs" / f"{pid}.jpg", "JPEG", quality=82)
        except StitchError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StitchError(400, f"not a readable image: {src.name} ({exc})") from None
        rec = {"id": pid, "name": str(meta.get("name") or src.stem)[:120], "file": f"photos/{pid}{ext}", "w": w, "h": h_,
               "source": meta.get("source") or "upload", "origin": str(meta.get("origin") or "")[:400],
               "book": meta.get("book"), "book_id": meta.get("book_id"), "page": meta.get("page"), "era": meta.get("era"),
               "chapter": meta.get("chapter"), "tags": clean_tags(meta.get("tags")), "subjects": [], "added": now()}
        ps.append(rec)
        _save_photos(ps)
        return rec, True


def mutate_photo(pid: str, fn: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with _lock:
        ps = photos()
        p = next((x for x in ps if x["id"] == pid), None)
        if p is None:
            raise StitchError(404, f"photo not found: {pid}")
        fn(p)
        _save_photos(ps)
        return p


def delete_photo(pid: str) -> None:
    with _lock:
        ps = photos()
        p = next((x for x in ps if x["id"] == pid), None)
        if p is None:
            raise StitchError(404, f"photo not found: {pid}")
        _save_photos([x for x in ps if x["id"] != pid])
        (repo_dir() / p["file"]).unlink(missing_ok=True)
        (repo_dir() / "thumbs" / f"{pid}.jpg").unlink(missing_ok=True)


def clean_subject(s: dict[str, Any], sid: str) -> dict[str, Any]:
    from engine.stitch import norm_crop

    box = norm_crop(s)
    if box is None:
        raise StitchError(400, "a subject is a crop box {x, y, w, h} in fractions of the photo")
    out = {"id": sid, "label": " ".join(str(s.get("label") or "subject").split())[:80], **box}
    if s.get("drama") is not None:
        try:
            out["drama"] = max(0, min(10, int(round(float(s["drama"])))))
        except (TypeError, ValueError):
            pass
    if s.get("what"):
        out["what"] = str(s["what"])[:300]
    if s.get("ai"):
        out["ai"] = True
    return out


def next_subject_id(p: dict[str, Any]) -> str:
    taken = {s["id"] for s in p.get("subjects") or []}
    n = 1
    while f"s{n}" in taken:
        n += 1
    return f"s{n}"


def search(q: str = "", source: str | None = None, tag: str | None = None) -> list[dict[str, Any]]:
    words = [w for w in (q or "").lower().split() if w]
    out = []
    for p in photos():
        if source and p.get("source") != source:
            continue
        if tag and tag.lower() not in (t.lower() for t in p.get("tags") or []):
            continue
        hay = " ".join(str(x) for x in (p.get("name"), p.get("book"), p.get("page"), p.get("era"), p.get("chapter"), *(p.get("tags") or []),
                                         *(s.get("label", "") + " " + s.get("what", "") for s in p.get("subjects") or []))).lower()
        if all(w in hay for w in words):
            out.append(p)
    return out


# ---------------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------------


def projects_dir() -> Path:
    d = root() / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_dir(prid: str) -> Path:
    d = projects_dir() / check_id(prid, "project id")
    if not (d / "project.json").exists():
        raise StitchError(404, "project not found")
    return d


def load(prid: str) -> dict[str, Any]:
    return _read(project_dir(prid) / "project.json")


def save(p: dict[str, Any]) -> None:
    p["updated"] = now()
    _write(project_dir(p["id"]) / "project.json", p)


def source_pdf(prid: str) -> Path:
    return project_dir(prid) / "source.pdf"


def analysis(prid: str, refresh: bool = False) -> dict[str, Any]:
    from engine import stitch as E

    f = project_dir(prid) / "analysis.json"
    a = None if refresh else _read(f)
    if a is None:
        a = E.analyse(source_pdf(prid))
        _write(f, a)
    return a


def list_projects() -> list[dict[str, Any]]:
    out = []
    for d in sorted(projects_dir().iterdir()):
        try:
            p = _read(d / "project.json")
        except Exception:  # noqa: BLE001
            continue
        if p:
            out.append(summary(p))
    out.sort(key=lambda p: p.get("updated") or "", reverse=True)
    return out


def summary(p: dict[str, Any]) -> dict[str, Any]:
    return {"id": p["id"], "title": p.get("title", ""), "source_name": p.get("source_name"), "pages": p.get("pages"), "size": p.get("size"),
            "placements": len(p.get("placements") or []), "plates": len(p.get("plates") or []), "created": p.get("created"), "updated": p.get("updated")}


def create_project(pdf: Path, title: str | None, source_name: str) -> dict[str, Any]:
    import pymupdf as fitz

    try:
        doc = fitz.open(str(pdf))
        if not doc.is_pdf or len(doc) == 0:
            raise ValueError("no pages")
        size = [round(doc[0].rect.width, 2), round(doc[0].rect.height, 2)]
        count = len(doc)
        doc.close()
    except Exception as exc:  # noqa: BLE001
        raise StitchError(400, f"not a readable PDF: {exc}") from None
    with _lock:
        prid = f"{slug(title or Path(source_name).stem)[:24]}-{secrets.token_hex(3)}"
        d = projects_dir() / prid
        d.mkdir(parents=True)
        shutil.copyfile(pdf, d / "source.pdf")
        p = {"id": prid, "title": (title or Path(source_name).stem)[:160], "source_name": Path(source_name).name, "pages": count, "size": size,
             "placements": [], "plates": [], "suggestions": {}, "reviews": {}, "created": now(), "updated": now()}
        _write(d / "project.json", p)
    analysis(prid)
    return p


def delete_project(prid: str) -> None:
    with _lock:
        shutil.rmtree(project_dir(prid))


# history: the placements and plates as they were before each change -----------------

EDIT_KEYS = ("placements", "plates")


def history(prid: str) -> list[dict[str, Any]]:
    return _read(project_dir(prid) / "history.json", [])


def _next_seq(prid: str, h: list[dict[str, Any]]) -> int:
    f = project_dir(prid) / "history.seq"
    last = int(f.read_text() or 0) if f.exists() else 0
    seq = max(last, h[-1]["seq"] if h else 0) + 1
    f.write_text(str(seq))
    return seq


def mutate(prid: str, fn: Callable[[dict[str, Any]], Any], action: str, record: bool = True) -> tuple[dict[str, Any], Any]:
    """Load the project, apply `fn` (in place; its return value is passed back), save, and record the old placements
    and plates (one undo step) when they changed."""
    with _lock:
        p = load(prid)
        before = {k: copy.deepcopy(p.get(k) or []) for k in EDIT_KEYS}
        r = fn(p)
        after = {k: p.get(k) or [] for k in EDIT_KEYS}
        save(p)
        if record and after != before:
            h = history(prid)
            h.append({"seq": _next_seq(prid, h), "at": now(), "action": action, "before": before})
            _write(project_dir(prid) / "history.json", h[-HISTORY_CAP:])
        return p, r


def undo(prid: str) -> dict[str, Any]:
    with _lock:
        h = history(prid)
        if not h:
            raise StitchError(409, "nothing to undo")
        e = h.pop()
        p = load(prid)
        for k in EDIT_KEYS:
            p[k] = e["before"][k]
        save(p)
        _write(project_dir(prid) / "history.json", h)
        return {"undone": e["action"], "seq": e["seq"], "remaining": len(h), "project": p}
