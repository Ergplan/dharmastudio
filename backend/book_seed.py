"""Load the bundled book (engine/book/book.json + The_Cycle_of_Dharma.pdf) into the studio, so a fresh install
starts with the whole manuscript split into its three books and 63 entries — no upload, no model run.

Idempotent: chapters are matched by their printed page range; existing chapters (and their pages, panels and
candidates) are never deleted or overwritten except for empty text/title fields. The Prologue and Chapter 1 share
the studio's Chapter 1 ("The Last Night of Lanka"), as in the hand-made panel script.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend import db
from backend.models import Chapter, Project, Volume
from engine.settings import REPO_ROOT

# The book is never bundled or committed (the repo is public): the author drops the PDF into the studio once and
# backend/book_import.py writes <data>/manuscript/book.json on that Mac. engine/book/ is a gitignored dev copy.
DEV_DIR = Path(getattr(sys, "_MEIPASS", REPO_ROOT)) / "engine" / "book"


def book_json_path() -> Path:
    local = db.DATA_DIR / "manuscript" / "book.json"
    return local if local.exists() else DEV_DIR / "book.json"


BOOK_JSON = DEV_DIR / "book.json"  # kept for the tests' dev copy
BOOK_PDF = DEV_DIR / "The_Cycle_of_Dharma.pdf"


def book() -> dict[str, Any]:
    p = book_json_path()
    key = (str(p), p.stat().st_mtime if p.exists() else 0)
    if _cache.get("key") != key:
        _cache["key"] = key
        _cache["data"] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"books": {}, "entries": []}
    return _cache["data"]


_cache: dict[str, Any] = {}


def import_manuscript(pdf: Path, session: Session) -> dict[str, Any]:
    """Author dropped the book PDF: split it on this Mac (no model) and load every chapter into the studio."""
    import yaml

    from backend import book_import
    from engine.settings import REPO_ROOT as _R

    root = Path(getattr(sys, "_MEIPASS", _R))
    chars_file = root / "engine" / "characters.yaml"
    characters = yaml.safe_load(chars_file.read_text(encoding="utf-8")).get("characters", []) if chars_file.exists() else []
    settings_file = DEV_DIR / "scene_settings.yaml"
    films = yaml.safe_load(settings_file.read_text(encoding="utf-8")).get("films", []) if settings_file.exists() else []
    data = book_import.import_pdf(pdf, characters, films)
    book_import.write(data, db.DATA_DIR)
    res = ensure(session, pdf_path=pdf)
    res["entries"] = len(data["entries"])
    res["words"] = sum(e["words"] for e in data["entries"])
    return res


def entry_label(e: dict[str, Any]) -> str:
    if e["kind"] == "chapter":
        return e["title"]
    if e["kind"] == "interlude":
        return f"Interlude: {e['title']}"
    return e["title"] if e["kind"] in ("epilogue", "glossary") else e["kind"].title()


def comic_chapters() -> list[dict[str, Any]]:
    """The studio's chapter list: Prologue + Chapter 1 merged, every other entry its own chapter, numbered per volume.
    The glossary is reference text, not a comic chapter."""
    out: list[dict[str, Any]] = []
    entries = [e for e in book()["entries"] if e["kind"] != "glossary"]
    i = 0
    counters = {1: 0, 2: 0, 3: 0}
    while i < len(entries):
        e = entries[i]
        vol = max(1, e["book"])
        if e["kind"] == "prologue" and i + 1 < len(entries) and entries[i + 1]["kind"] == "chapter" and entries[i + 1]["number"] == 1:
            nxt = entries[i + 1]
            counters[vol] += 1
            out.append({"volume": vol, "number": counters[vol], "title": nxt["title"], "pages": [e["pages"][0], nxt["pages"][1]],
                        "text": "PROLOGUE — The Voice\n\n" + e["text"] + "\n\n1 — " + nxt["title"] + "\n\n" + nxt["text"], "entries": [e, nxt]})
            i += 2
            continue
        counters[vol] += 1
        out.append({"volume": vol, "number": counters[vol], "title": entry_label(e), "pages": e["pages"], "text": e["text"], "entries": [e]})
        i += 1
    return out


def ensure(session: Session, pdf_path: Path | None = None) -> dict[str, int]:
    proj = session.scalars(select(Project)).first()
    if proj is None or not book()["entries"]:
        return {"created": 0, "updated": 0}
    vols = {v.number: v for v in session.scalars(select(Volume)).all()}
    for n, title in book()["books"].items():
        v = vols.get(int(n))
        if v is not None and (not v.title or v.title.startswith("Volume")):
            v.title = title
    created = updated = 0
    existing = session.scalars(select(Chapter)).all()
    for c in comic_chapters():
        v = vols.get(c["volume"])
        if v is None:
            continue
        hit = next((x for x in existing if x.volume_id == v.id and (x.pages_from == c["pages"][0] or (x.number == c["number"] and x.title == c["title"]))), None)
        if hit is None and c["volume"] == 1 and c["number"] == 1:
            hit = next((x for x in existing if x.volume_id == v.id and x.number == 1), None)
        if hit is None:
            session.add(Chapter(volume_id=v.id, number=c["number"], title=c["title"], text=c["text"], pages_from=c["pages"][0], pages_to=c["pages"][1]))
            created += 1
        else:
            hit.text = c["text"]  # the book is the source of truth for chapter text
            hit.pages_from, hit.pages_to = c["pages"]
            hit.title = hit.title or c["title"]
            updated += 1
    # the manuscript itself, kept on this Mac so the journey's first step is done
    src = pdf_path or (BOOK_PDF if BOOK_PDF.exists() else None)
    if src is not None:
        dst = db.DATA_DIR / "manuscript" / src.name
        if not dst.exists() or src.resolve() != dst.resolve():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.resolve() != dst.resolve():
                shutil.copy2(src, dst)
        proj.manuscript_pdf = db.rel(dst)
    s = dict(proj.settings or {})
    s["book"] = {"source": "local", "entries": len(book()["entries"]), "words": sum(e["words"] for e in book()["entries"])}
    proj.settings = s
    session.flush()
    return {"created": created, "updated": updated}


def entry_for_chapter(ch: Chapter) -> list[dict[str, Any]]:
    """Book entries (text, scene settings, cast) behind a studio chapter, by printed page range."""
    return [e for e in book()["entries"] if ch.pages_from and ch.pages_to and e["pages"][0] >= ch.pages_from and e["pages"][1] <= ch.pages_to]


if __name__ == "__main__":
    db.init_db()
    with db.session_scope() as s:
        print(ensure(s))
