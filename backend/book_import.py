"""Turn the author's book PDF into the studio's book data, on this Mac, with no model call.

Reads the CONTENTS page(s) for the structure (Prologue, BOOK ONE/TWO/THREE: titles, numbered chapters,
Interludes, Epilogue, Glossary with their printed page numbers), then extracts each entry's text with pypdf's
layout mode so paragraph indents survive, and joins wrapped lines back into the book's real paragraphs. Scene
settings (if the studio has them) and the cast (from the character bible, by name) are attached per entry.
The result is written to <data>/manuscript/book.json and never leaves the machine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

WORDNUM = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "I": 1, "II": 2, "III": 3, "IV": 4}
DOTS = re.compile(r"\s*\.{3,}\s*")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip()


def parse_contents(reader: PdfReader, max_pages: int = 20) -> tuple[list[dict[str, Any]], dict[int, str], dict[int, int]]:
    """Return (entries, book titles, book title pages) from the contents table."""
    lines: list[str] = []
    started = False
    for i in range(min(max_pages, len(reader.pages))):
        t = reader.pages[i].extract_text(extraction_mode="layout") or ""
        if not started and re.search(r"C\s*O\s*N\s*T\s*E\s*N\s*T\s*S", t):
            started = True
        if started:
            lines += t.splitlines()
            if re.search(r"(?i)glossary|epilogue", t) and i > 0:
                # the contents usually ends on the page that lists the epilogue/glossary
                if re.search(r"(?i)^\s*(glossary|epilogue)\b.*\d+\s*$", t, re.M):
                    break
    entries: list[dict[str, Any]] = []
    books: dict[int, str] = {}
    book_pages: dict[int, int] = {}
    book = 0
    for raw in lines:
        if "." * 3 not in raw:
            continue
        left, _, right = DOTS.split(raw.strip(), maxsplit=1)[0], None, DOTS.split(raw.strip(), maxsplit=1)[-1]
        m = re.fullmatch(r"\s*(\d+)\s*", right or "")
        if not m:
            continue
        page = int(m.group(1))
        left = _norm(left)
        bm = re.match(r"(?i)^(?:BOOK|PART|VOLUME)\s+([A-Z]+|\d+)\s*[:.\-–]\s*(.+)$", left)
        if bm:
            book = WORDNUM.get(bm.group(1).upper(), int(bm.group(1)) if bm.group(1).isdigit() else book + 1)
            books[book] = bm.group(2).strip().title().replace(" The ", " the ").replace(" Was ", " Was ")
            book_pages[book] = page
            continue
        cm = re.match(r"^(\d{1,3})\s+(.+)$", left)
        if cm:
            entries.append({"kind": "chapter", "number": int(cm.group(1)), "title": cm.group(2).strip(), "book": book, "start": page})
            continue
        km = re.match(r"(?i)^(interlude|prologue|epilogue|glossary|afterword|foreword|appendix)\s*[:\-–]?\s*(.*)$", left)
        if km:
            kind = km.group(1).lower()
            title = km.group(2).strip() or kind.title()
            entries.append({"kind": kind, "number": None, "title": title, "book": book, "start": page})
    return entries, books, book_pages


def _paragraphs(reader: PdfReader, a: int, b: int) -> list[str]:
    paras: list[str] = []
    cur = ""
    for n in range(a, b + 1):
        lines = (reader.pages[n - 1].extract_text(extraction_mode="layout") or "").splitlines()
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and re.fullmatch(r"\s*\d{1,3}\s*", lines[-1]):
            lines.pop()  # folio
        for ln in lines:
            if not ln.strip():
                if cur:
                    paras.append(cur)
                    cur = ""
                continue
            indent = len(ln) - len(ln.lstrip())
            s = re.sub(r"\s{2,}", " ", ln.strip())
            if indent >= 2 and cur:
                paras.append(cur)
                cur = s
            elif cur:
                cur = cur[:-1] + s if cur.endswith("-") and not cur.endswith(" -") else cur + " " + s
            else:
                cur = s
    if cur:
        paras.append(cur)
    return [p.strip() for p in paras if p.strip()]


def _strip_heading(ps: list[str], e: dict[str, Any]) -> list[str]:
    title = _norm(e["title"])
    while ps:
        head = _norm(ps[0])
        if re.fullmatch(r"[A-Z](\s?[A-Z])+", head.replace(" ", "")) and len(head.replace(" ", "")) <= 12 and head.replace(" ", "").isupper():
            ps.pop(0)
        elif re.fullmatch(r"\d(\s?\d){0,2}", head) or head == title or head.startswith(title) and len(head) <= len(title) + 2:
            ps.pop(0)
        elif e["kind"] in ("epilogue", "prologue") and head in ("The Voice",):
            e["subtitle"] = head
            ps.pop(0)
        else:
            break
    return ps


def import_pdf(pdf: Path, characters: list[dict[str, Any]] | None = None, scene_settings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    reader = PdfReader(str(pdf))
    n_pages = len(reader.pages)
    toc, books, book_pages = parse_contents(reader)
    if len(toc) < 3:
        raise ValueError("no contents table found in the PDF")
    meta = reader.metadata or {}
    out = []
    starts = [e["start"] for e in toc]
    for i, e in enumerate(toc):
        end = (starts[i + 1] - 1) if i + 1 < len(toc) else n_pages
        for tp in book_pages.values():
            if e["start"] < tp <= end:
                end = tp - 1
        ps = _strip_heading(_paragraphs(reader, e["start"], end), e)
        text = "\n\n".join(ps)
        out.append({"kind": e["kind"], "number": e["number"], "title": e["title"], "book": e["book"], "book_title": books.get(e["book"], ""),
                    "pages": [e["start"], end], "paragraphs": ps, "text": text, "words": len(text.split()), "scene_settings": [], "cast": []})
    for e in out:  # the prologue opens Book One in the studio
        if e["kind"] == "prologue" and e["book"] == 0:
            e["book"] = 1
    if characters:
        attach_cast(out, characters)
    if scene_settings:
        attach_settings(out, scene_settings)
    return {"title": str(meta.get("/Title") or "The Cycle of Dharma"), "author": str(meta.get("/Author") or ""), "source_pdf": pdf.name,
            "pdf_pages": n_pages, "books": {str(k): v for k, v in books.items()}, "entries": out}


ALIASES = {"Hanuman": ["Hanuman", "vanara", "Maruti", "Anjaneya"], "Ravana": ["Ravana", "Dashanan", "tenth head"], "Rama": ["Rama", "Raghava", "Prabhu"],
           "Krishna": ["Krishna", "Keshava", "Madhava"], "Arjuna": ["Arjuna", "Partha"], "Shiva": ["Shiva", "Mahadeva", "Rudra"]}


def attach_cast(entries: list[dict[str, Any]], characters: list[dict[str, Any]]) -> None:
    for e in entries:
        cast = []
        for c in characters:
            names = ALIASES.get(c["name"], [c["name"]])
            n = sum(len(re.findall(r"\b" + re.escape(a) + r"\b", e["text"])) for a in names)
            if n:
                cast.append({"name": c["name"], "mentions": n, "forms": [f["key"] for f in c.get("forms", [])]})
        e["cast"] = sorted(cast, key=lambda x: -x["mentions"])


def attach_settings(entries: list[dict[str, Any]], films: list[dict[str, Any]]) -> None:
    for f in films:
        for s in f.get("sequences", []):
            spec = str(s.get("chapters", ""))
            for e in entries:
                if _matches(spec, e):
                    e["scene_settings"].append({"film": int(f["number"]), "sequence": int(s["number"]), "title": s["title"], "era": s.get("era"), "setting": s.get("setting_text", "")})


def _matches(spec: str, e: dict[str, Any]) -> bool:
    for part in re.split(r"[,;&]| and ", spec):
        part = part.strip().lower()
        m = re.match(r"(?:ch(?:apters?)?\.?\s*)?(\d+)\s*[-–]\s*(\d+)$", part)
        if m and e["kind"] == "chapter" and int(m[1]) <= e["number"] <= int(m[2]):
            return True
        m = re.match(r"(?:ch(?:apters?)?\.?\s*)?(\d+)$", part)
        if m and e["kind"] == "chapter" and e["number"] == int(m[1]):
            return True
        if e["kind"] in ("prologue", "epilogue") and e["kind"] in part:
            return True
        if e["kind"] == "interlude" and part.startswith("interlude"):
            rest = part.split(":", 1)[-1].strip() if ":" in part else ""
            if not rest or rest in e["title"].lower() or e["title"].lower() in rest:
                return True
    return False


def write(book: dict[str, Any], data_dir: Path) -> Path:
    out = data_dir / "manuscript" / "book.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
