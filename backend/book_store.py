"""Book store: imported layered book packages, kept as JSON files in the data folder (never in the repo).

A package (`dharma-book/1`, or `/2` which adds `art.patches`) is a folder, or a .dharmabook / .zip of one, holding `manifest.json` plus the art files
it names (`art/<id>.jpg`, `art/cover.jpg`). Importing copies it into `<data>/books/<book id>/`:

    book.json            the manifest without its pages, plus `id`, `order` (page ids) and import details
    pages/<page id>.json one page: paper / art / text layers, `layers` visibility, `page_number`
    art/                 the paintings (replaced art is written under a new name, so undo can bring the old one back)
    history.json         the action log: every change stores the page as it was before (and the page order), so any
                         change can be undone and any earlier version of a page restored
    thumbs/ exports/     generated thumbnails and exports

The store is plain files (no tables), so a book never touches studio.db and can be deleted by removing its folder.
"""

from __future__ import annotations

import copy
import json
import re
import secrets
import shutil
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import db

FORMAT = "dharma-book/1"
PACKAGE_EXT = ".dharmabook"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
HISTORY_CAP = 400
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ART_RE = re.compile(r"^art/[A-Za-z0-9_.-]{1,120}$")

_lock = threading.RLock()


class BookError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def root() -> Path:
    d = db.DATA_DIR / "books"
    d.mkdir(parents=True, exist_ok=True)
    return d


def assets_dir() -> Path:
    d = root() / "_assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check_id(x: str, what: str = "id") -> str:
    if not ID_RE.match(str(x or "")) or str(x).startswith("_"):
        raise BookError(400, f"bad {what}: {x!r}")
    return str(x)


def book_dir(bid: str) -> Path:
    d = root() / _check_id(bid, "book id")
    if not (d / "book.json").exists():
        raise BookError(404, "book not found")
    return d


def _read(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def _write(p: Path, data: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


# ---------------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------------


def list_books() -> list[dict[str, Any]]:
    out = []
    for d in sorted(root().iterdir()):
        if d.name.startswith("_") or not (d / "book.json").exists():
            continue
        try:
            b = _read(d / "book.json")
        except Exception:  # noqa: BLE001
            continue
        out.append(summary(b))
    out.sort(key=lambda b: b.get("imported_at") or "", reverse=True)
    return out


def summary(b: dict[str, Any]) -> dict[str, Any]:
    return {"id": b["id"], "title": b.get("title", ""), "volume": b.get("volume", ""), "author": b.get("author", ""), "pages": len(b.get("order") or []),
            "imported_at": b.get("imported_at"), "source": b.get("source"), "updated_at": b.get("updated_at")}


def load_book(bid: str) -> dict[str, Any]:
    return _read(book_dir(bid) / "book.json")


def save_book(b: dict[str, Any]) -> None:
    b["updated_at"] = now()
    _write(book_dir(b["id"]) / "book.json", b)


def page_path(bid: str, pid: str) -> Path:
    return book_dir(bid) / "pages" / f"{_check_id(pid, 'page id')}.json"


def load_page(bid: str, pid: str) -> dict[str, Any]:
    p = page_path(bid, pid)
    if not p.exists():
        raise BookError(404, "page not found")
    return _read(p)


def save_page(bid: str, page: dict[str, Any]) -> None:
    _write(page_path(bid, page["id"]), page)


def pages(bid: str) -> list[dict[str, Any]]:
    b = load_book(bid)
    out = []
    for i, pid in enumerate(b.get("order") or []):
        try:
            p = load_page(bid, pid)
        except BookError:
            continue
        p["number"] = i + 1
        out.append(p)
    return out


def number_of(b: dict[str, Any], pid: str) -> int | None:
    order = b.get("order") or []
    return order.index(pid) + 1 if pid in order else None


# ---------------------------------------------------------------------------------
# normalising a page (import and every edit)
# ---------------------------------------------------------------------------------


def blank_page(pid: str, b: dict[str, Any]) -> dict[str, Any]:
    return {"id": pid, "number": 0, "era": None, "template": "BLANK", "scene_type": None,
            "paper": {"texture": "page_warm", "shloka": None, "figures": []},
            "art": None, "text": [], "page_number": True, "layers": {"paper": True, "art": True, "text": True}}


def frame_window(b: dict[str, Any]) -> dict[str, int]:
    W, H = (b.get("page_px") or [2040, 3060])[:2]
    f = b.get("frame") or {"l": 104, "r": 104, "t": 170, "b": 200}
    return {"x": int(f["l"]), "y": int(f["t"]), "w": int(W - f["l"] - f["r"]), "h": int(H - f["t"] - f["b"])}


def normalise_page(p: dict[str, Any]) -> dict[str, Any]:
    p = dict(p)
    paper = dict(p.get("paper") or {})
    paper.setdefault("texture", "page_warm")
    paper.setdefault("figures", [])
    paper.setdefault("shloka", None)
    p["paper"] = paper
    art = p.get("art")
    if art and not ART_RE.match(str(art.get("file") or "")):
        art = None
    if art and "patches" in art:
        art = dict(art)
        art["patches"] = normalise_patches(art.get("patches"))
    p["art"] = art or None
    p["text"] = [dict(t) for t in (p.get("text") or []) if isinstance(t, dict)]
    seen: set[str] = set()
    for t in p["text"]:
        tid = str(t.get("id") or "")
        if not ID_RE.match(tid) or tid in seen:
            t["id"] = next_text_id(p, seen)
        seen.add(t["id"])
    lay = p.get("layers") or {}
    p["layers"] = {k: bool(lay.get(k, True)) for k in ("paper", "art", "text")}
    p.setdefault("page_number", True)
    if p.get("status") not in PAGE_STATUSES:
        p["status"] = "draft"
    p["comments"] = normalise_comments(p.get("comments"))
    return p


PAGE_STATUSES = ("draft", "review", "approved")
COMMENT_STATUSES = ("open", "applied", "dismissed")
ANCHOR_LAYERS = ("text", "paper", "art", "page")


def normalise_patches(raw: Any) -> list[dict[str, Any]]:
    """`art.patches`: parchment cover-ups (page px) over boxes the painter left empty; `linked` = nearest text box id."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, x in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(x, dict):
            continue
        try:
            px, py, pw, ph = (round(float(x.get(k) or 0), 2) for k in ("x", "y", "w", "h"))
        except (TypeError, ValueError):
            continue
        if pw <= 0 or ph <= 0:
            continue
        pid = str(x.get("id") or "")
        if not ID_RE.match(pid) or pid in seen:
            n = i + 1
            while f"pa{n}" in seen:
                n += 1
            pid = f"pa{n}"
        seen.add(pid)
        linked = x.get("linked")
        out.append({"id": pid, "x": px, "y": py, "w": pw, "h": ph, "linked": str(linked) if linked else None, "hidden": bool(x.get("hidden"))})
    return out


def normalise_comments(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict) or not ID_RE.match(str(c.get("id") or "")) or c["id"] in seen:
            continue
        seen.add(c["id"])
        a = c.get("anchor") if isinstance(c.get("anchor"), dict) else {}
        anchor: dict[str, Any] = {"layer": a.get("layer") if a.get("layer") in ANCHOR_LAYERS else "page", "element": (str(a["element"])[:80] if a.get("element") else None),
                                  "x": _f(a.get("x")), "y": _f(a.get("y"))}
        r = a.get("rect")
        if isinstance(r, dict) and all(k in r for k in ("x", "y", "w", "h")):
            anchor["rect"] = {k: _f(r[k]) for k in ("x", "y", "w", "h")}
        out.append({"id": c["id"], "n": int(c.get("n") or len(out) + 1), "anchor": anchor, "text": str(c.get("text") or "")[:4000],
                    "status": c.get("status") if c.get("status") in COMMENT_STATUSES else "open", "created": c.get("created") or now(),
                    "result": c.get("result") if isinstance(c.get("result"), dict) else None})
    return out


def _f(v: Any) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def next_text_id(p: dict[str, Any], taken: set[str] | None = None) -> str:
    taken = set(taken or set()) | {str(t.get("id")) for t in p.get("text") or []}
    n = 1
    while f"{p['id']}-t{n}" in taken:
        n += 1
    return f"{p['id']}-t{n}"


def new_page_id(bid: str) -> str:
    d = book_dir(bid) / "pages"
    while True:
        pid = "p" + secrets.token_hex(3)
        if not (d / f"{pid}.json").exists():
            return pid


# ---------------------------------------------------------------------------------
# history (undo / versions)
# ---------------------------------------------------------------------------------


def _hist_path(bid: str) -> Path:
    return book_dir(bid) / "history.json"


def history(bid: str) -> list[dict[str, Any]]:
    p = _hist_path(bid)
    return _read(p) if p.exists() else []


def peek_seq(bid: str) -> int:
    """The seq the next history entry will get. Never reused (also after an undo), so a seq names one change for good."""
    h = history(bid)
    f = book_dir(bid) / "history.seq"
    last = int(f.read_text() or 0) if f.exists() else 0
    return max(last, h[-1]["seq"] if h else 0) + 1


def _record(bid: str, kind: str, action: str, pid: str | None, before: dict[str, Any] | None, order_before: list[str] | None) -> int:
    h = history(bid)
    seq = peek_seq(bid)
    (book_dir(bid) / "history.seq").write_text(str(seq))
    h.append({"seq": seq, "at": now(), "kind": kind, "action": action, "pid": pid, "before": before, "order_before": order_before})
    _write(_hist_path(bid), h[-HISTORY_CAP:])
    return seq


def history_entry(bid: str, seq: int) -> dict[str, Any] | None:
    return next((x for x in history(bid) if x["seq"] == seq), None)


def last_page_seq(bid: str, pid: str) -> int | None:
    """The seq of the page's most recent content change (what a page undo would revert)."""
    return next((e["seq"] for e in reversed(history(bid)) if e.get("pid") == pid and e["kind"] == "page"), None)


def page_history(bid: str, pid: str) -> list[dict[str, Any]]:
    return [{"seq": e["seq"], "at": e["at"], "action": e["action"], "kind": e["kind"]} for e in history(bid) if e.get("pid") == pid][::-1]


def _apply_undo(bid: str, e: dict[str, Any]) -> str | None:
    b = load_book(bid)
    if e["kind"] == "page":
        if e["before"]:
            save_page(bid, e["before"])
    elif e["kind"] == "add":
        page_path(bid, e["pid"]).unlink(missing_ok=True)
        b["order"] = e["order_before"]
    elif e["kind"] == "delete":
        save_page(bid, e["before"])
        b["order"] = e["order_before"]
    elif e["kind"] == "order":
        b["order"] = e["order_before"]
    if e["kind"] != "page":
        save_book(b)
    return e.get("pid")


def undo(bid: str, pid: str | None = None) -> dict[str, Any]:
    """Undo the most recent change (of `pid` only, when given: its last content edit). Returns {undone, pid}."""
    with _lock:
        h = history(bid)
        idx = None
        for i in range(len(h) - 1, -1, -1):
            if pid is None or (h[i].get("pid") == pid and h[i]["kind"] == "page"):
                idx = i
                break
        if idx is None:
            raise BookError(409, "nothing to undo")
        e = h.pop(idx)
        _apply_undo(bid, e)
        _write(_hist_path(bid), h)
        return {"undone": e["action"], "pid": e.get("pid"), "seq": e["seq"], "remaining": len(h)}


def restore(bid: str, pid: str, seq: int) -> dict[str, Any]:
    """Put a page back to how it was before history entry `seq` (recorded as a new change, so it can be undone)."""
    e = next((x for x in history(bid) if x["seq"] == seq and x.get("pid") == pid), None)
    if e is None or not e.get("before"):
        raise BookError(404, "version not found")
    old = e["before"]
    return mutate_page(bid, pid, lambda p: {**copy.deepcopy(old), "id": pid}, f"restore v{seq}")


# ---------------------------------------------------------------------------------
# changes
# ---------------------------------------------------------------------------------


def mutate_page(bid: str, pid: str, fn: Callable[[dict[str, Any]], dict[str, Any] | None], action: str) -> dict[str, Any]:
    """Load the page, apply `fn` (edits in place or returns a new page), normalise, save, record the old version."""
    return mutate_page_seq(bid, pid, lambda p, _seq: fn(p), action)


def mutate_page_seq(bid: str, pid: str, fn: Callable[[dict[str, Any], int], dict[str, Any] | None], action: str | Callable[[dict[str, Any]], str]) -> dict[str, Any]:
    """`mutate_page` where `fn(page, seq)` also learns the seq this change will be recorded under (one history step)."""
    with _lock:
        before = load_page(bid, pid)
        page = copy.deepcopy(before)
        seq = peek_seq(bid)
        r = fn(page, seq)
        page = normalise_page(r if r is not None else page)
        page["id"] = pid
        if page == before:
            return page
        save_page(bid, page)
        _record(bid, "page", action(page) if callable(action) else action, pid, before, None)
        b = load_book(bid)
        save_book(b)
        page["number"] = number_of(b, pid)
        return page


def add_page(bid: str, page: dict[str, Any], after: str | None = None, action: str = "add page") -> dict[str, Any]:
    with _lock:
        b = load_book(bid)
        order = list(b.get("order") or [])
        page = normalise_page(page)
        save_page(bid, page)
        new = list(order)
        if after and after in new:
            new.insert(new.index(after) + 1, page["id"])
        elif after == "start":
            new.insert(0, page["id"])
        else:
            new.append(page["id"])
        b["order"] = new
        save_book(b)
        _record(bid, "add", action, page["id"], None, order)
        page["number"] = number_of(b, page["id"])
        return page


def delete_page(bid: str, pid: str) -> dict[str, Any]:
    with _lock:
        b = load_book(bid)
        before = load_page(bid, pid)
        order = list(b.get("order") or [])
        b["order"] = [x for x in order if x != pid]
        save_book(b)
        page_path(bid, pid).unlink(missing_ok=True)
        _record(bid, "delete", "delete page", pid, before, order)
        return {"deleted": pid, "pages": len(b["order"])}


def set_order(bid: str, order: list[str]) -> list[str]:
    with _lock:
        b = load_book(bid)
        old = list(b.get("order") or [])
        if sorted(order) != sorted(old) or len(set(order)) != len(order):
            raise BookError(400, "order must list every page exactly once")
        if order == old:
            return old
        b["order"] = list(order)
        save_book(b)
        _record(bid, "order", "reorder pages", None, None, old)
        return b["order"]


def save_art_file(bid: str, data_path: Path, stem: str) -> str:
    """Store an image as art/<stem>-<n>.jpg (RGB JPEG q92). Returns the package-relative path."""
    from PIL import Image

    d = book_dir(bid) / "art"
    d.mkdir(parents=True, exist_ok=True)
    n = 1
    while (d / f"{stem}-{n}.jpg").exists():
        n += 1
    dst = d / f"{stem}-{n}.jpg"
    with Image.open(data_path) as im:
        im.convert("RGB").save(dst, "JPEG", quality=92)
    return f"art/{dst.name}"


# ---------------------------------------------------------------------------------
# import / export of packages
# ---------------------------------------------------------------------------------


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "book").lower()).strip("-")[:32] or "book"


def _validate_manifest(m: Any) -> dict[str, Any]:
    if not isinstance(m, dict) or not str(m.get("format", "")).startswith("dharma-book/"):
        raise BookError(400, "not a dharma-book package (manifest.json with format dharma-book/1)")
    if not isinstance(m.get("pages"), list):
        raise BookError(400, "manifest has no pages")
    return m


def _install(m: dict[str, Any], art_src: Callable[[str], Path | None], source: str) -> dict[str, Any]:
    """Create a book from a validated manifest; `art_src(rel)` gives a readable file for a package path or None."""
    bid = f"{_slug(m.get('title', 'book'))}-{secrets.token_hex(3)}"
    d = root() / bid
    tmp = root() / f"_import-{bid}"
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "pages").mkdir(parents=True)
    (tmp / "art").mkdir()
    order: list[str] = []
    copied: set[str] = set()

    def take(rel: str | None) -> bool:
        if not rel or not ART_RE.match(rel) or Path(rel).suffix.lower() not in IMAGE_EXT:
            return False
        if rel in copied:
            return True
        src = art_src(rel)
        if not src:
            return False
        shutil.copyfile(src, tmp / rel)
        copied.add(rel)
        return True

    for raw in m["pages"]:
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("id") or "")
        if not ID_RE.match(pid) or pid.startswith("_") or pid in order:
            pid = "p" + secrets.token_hex(3)
        page = dict(raw, id=pid)
        if page.get("art") and not take((page["art"] or {}).get("file")):
            page["art"] = None
        page = normalise_page(page)
        _write(tmp / "pages" / f"{pid}.json", page)
        order.append(pid)
    meta = {k: v for k, v in m.items() if k != "pages"}
    cover = (meta.get("cover") or {}).get("file")
    if cover and not take(cover):
        meta["cover"] = None
    meta.update({"id": bid, "order": order, "imported_at": now(), "updated_at": now(), "source": source, "format": m.get("format", FORMAT)})
    _write(tmp / "book.json", meta)
    tmp.rename(d)
    return summary(meta)


def import_path(path: str | Path) -> dict[str, Any]:
    """Import a package folder, its manifest.json, or a .dharmabook / .zip archive."""
    p = Path(str(path)).expanduser()
    if not p.exists():
        raise BookError(404, f"not found: {p}")
    if p.is_file() and p.name == "manifest.json":
        p = p.parent
    with _lock:
        if p.is_dir():
            mf = p / "manifest.json"
            if not mf.exists():
                raise BookError(400, "the folder has no manifest.json")
            m = _validate_manifest(_read(mf))

            def src(rel: str) -> Path | None:
                f = (p / rel).resolve()
                return f if f.is_file() and p.resolve() in f.parents else None

            return _install(m, src, str(p))
        if zipfile.is_zipfile(p):
            return import_zip(p, str(p))
    raise BookError(400, "expected a package folder, a .dharmabook or a .zip")


def import_zip(zpath: Path, source: str) -> dict[str, Any]:
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        mfs = sorted((n for n in names if n == "manifest.json" or n.endswith("/manifest.json")), key=len)
        if not mfs:
            raise BookError(400, "the archive has no manifest.json")
        prefix = mfs[0][: -len("manifest.json")]
        if ".." in prefix or prefix.startswith("/"):
            raise BookError(400, "unsafe archive")
        m = _validate_manifest(json.loads(z.read(mfs[0]).decode("utf-8")))
        work = Path(tempfile.mkdtemp(prefix="book-import-", dir=root()))
        try:
            def src(rel: str) -> Path | None:
                name = prefix + rel
                if name not in names:
                    return None
                out = work / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as fi, open(out, "wb") as fo:
                    shutil.copyfileobj(fi, fo)
                return out

            with _lock:
                return _install(m, src, source)
        finally:
            shutil.rmtree(work, ignore_errors=True)


def manifest(bid: str) -> dict[str, Any]:
    """The book as a dharma-book/1 manifest (pages in the current order, numbered)."""
    b = load_book(bid)
    meta = {k: v for k, v in b.items() if k not in ("id", "order", "imported_at", "updated_at", "source")}
    meta["pages"] = pages(bid)
    # dharma-book/2 adds art.patches (cover-ups over empty boxes, art.file the clean painting); /1 has none
    meta["format"] = "dharma-book/2" if any((p.get("art") or {}).get("patches") for p in meta["pages"]) else FORMAT
    return meta


def export_package(bid: str) -> Path:
    d = book_dir(bid)
    m = manifest(bid)
    out = d / "exports"
    out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dst = out / f"{_slug(m.get('title', 'book'))}-{stamp}{PACKAGE_EXT}"
    files = {pg["art"]["file"] for pg in m["pages"] if pg.get("art") and pg["art"].get("file")}
    if (m.get("cover") or {}).get("file"):
        files.add(m["cover"]["file"])
    tmp = dst.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        z.writestr("manifest.json", json.dumps(m, ensure_ascii=False, indent=1))
        for rel in sorted(files):
            f = d / rel
            if f.exists():
                z.write(f, rel)
    tmp.replace(dst)
    return dst


def delete_book(bid: str) -> None:
    with _lock:
        shutil.rmtree(book_dir(bid))


def set_comment_result(bid: str, pid: str, cid: str, result: dict[str, Any]) -> None:
    """Record a failed apply on a comment without a history step (nothing on the page changed)."""
    with _lock:
        page = load_page(bid, pid)
        for c in page.get("comments") or []:
            if c.get("id") == cid:
                c["result"] = result
        save_page(bid, page)
