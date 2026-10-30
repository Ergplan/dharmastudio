"""Manuscript import: PDF or text -> chapter detection by headings (Prologue, Chapter N, Interlude, Epilogue)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

HEADING = re.compile(r"^\s*(?:(PROLOGUE|EPILOGUE|INTERLUDE)(?:\s*[:.\-—–]\s*(.*))?|CHAPTER\s+([0-9IVXLC]+)(?:\s*[:.\-—–]\s*(.*))?)\s*$", re.I)
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def _roman(s: str) -> int | None:
    s = s.upper()
    if not s or any(ch not in ROMAN for ch in s):
        return None
    total, prev = 0, 0
    for ch in reversed(s):
        v = ROMAN[ch]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def extract_text(path: Path) -> tuple[str, list[int]]:
    """Text and the character offsets where each PDF page starts (for page ranges); text files are one page."""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        parts, offsets, pos = [], [], 0
        for page in reader.pages:
            t = page.extract_text() or ""
            offsets.append(pos)
            parts.append(t)
            pos += len(t) + 1
        return "\n".join(parts), offsets
    return path.read_text(encoding="utf-8", errors="replace"), [0]


def detect_chapters(text: str, page_offsets: list[int] | None = None) -> list[dict[str, Any]]:
    """[{number, title, text, pages_from, pages_to}] from headings; one chapter when none is found.
    The prologue is chapter 0; interludes and the epilogue continue the numbering."""
    lines = text.splitlines(keepends=True)
    marks: list[tuple[int, int, str]] = []  # (char offset, line index, title)
    pos = 0
    for i, line in enumerate(lines):
        m = HEADING.match(line.strip("﻿"))
        if m and len(line.strip()) < 80:
            kind, sub, num, sub2 = m.groups()
            if kind:
                title = kind.title() + (f" — {sub.strip()}" if sub else "")
            else:
                n = int(num) if num.isdigit() else _roman(num)
                title = f"Chapter {n}" + (f" — {sub2.strip()}" if sub2 else "")
            # a title on the next line ("Chapter 1\nThe Last Night of Lanka")
            if not (sub or sub2) and i + 1 < len(lines) and 0 < len(lines[i + 1].strip()) < 70 and not HEADING.match(lines[i + 1]):
                title += f" — {lines[i + 1].strip()}"
            marks.append((pos, i, title))
        pos += len(line)
    if not marks:
        return [{"number": 1, "title": "Chapter 1", "text": text.strip(), "pages_from": 1, "pages_to": max(1, len(page_offsets or [0]))}]

    def pdf_page(off: int) -> int:
        if not page_offsets:
            return 1
        n = 1
        for k, o in enumerate(page_offsets):
            if o <= off:
                n = k + 1
        return n

    out = []
    chapter_no = 0
    for k, (off, _li, title) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(text)
        body = text[off:end].strip()
        low = title.lower()
        if low.startswith("prologue"):
            number = 0
        else:
            m = re.match(r"chapter (\d+)", low)
            number = int(m.group(1)) if m else chapter_no + 1
        chapter_no = max(chapter_no, number)
        out.append({"number": number, "title": title, "text": body, "pages_from": pdf_page(off), "pages_to": pdf_page(max(off, end - 1))})
    # unique numbers: interludes between chapters get fractional-looking integer slots by renumbering duplicates
    seen: set[int] = set()
    for ch in out:
        while ch["number"] in seen:
            ch["number"] += 1
        seen.add(ch["number"])
    return out
