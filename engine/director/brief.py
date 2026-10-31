"""The SCENE BRIEF — the only per-illustration input — and its deterministic validators (no model involved).

A brief names the manuscript chapter, the exact action, the characters present (studio Character form keys), the
setting (prefilled from the chapter's scene settings) and the dialogue / narration to reproduce. The master prompt
stays constant; the brief is the short scene-specific instruction added to it.

Validators:
- every line to reproduce must appear verbatim in the chapter's manuscript text (quotes, dashes and whitespace
  normalised; "..." / "…" marks an elision and each fragment must appear, in order). A line that is not in the
  manuscript blocks painting unless the author ticks "adapted, approved".
- every character key must exist in the studio (unknown names are rejected with suggestions);
- every character must be LOCKED (the studio's lock gate). If not, the Director offers to create the canonical
  reference sheet first and does not paint;
- the era palette is chosen automatically from the chapter (the author may override the age).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from . import guardrails as G

_DQUOTES = dict.fromkeys(map(ord, "\"“”„‟«»″"), None)
_SQUOTES = {ord(c): "'" for c in "‘’‚‛′`"}
_DASHES = {ord(c): "-" for c in "—–‒―‐‑−"}
ELLIPSIS = re.compile(r"\s*(?:\.\s*\.\s*\.|…)\s*")


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.translate(_DQUOTES).translate(_SQUOTES).translate(_DASHES)
    t = re.sub(r"\s*-\s*", " - ", t)  # "word—word" and "word - word" compare equal
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _strip_edges(t: str) -> str:
    return t.strip(" '-")


def fragments(line: str) -> list[str]:
    """A quoted line split at elisions ('...' or '…'), normalised; empty pieces dropped."""
    raw = unicodedata.normalize("NFKC", line or "")
    parts = [p for p in ELLIPSIS.split(raw) if p.strip()]
    return [f for f in (_strip_edges(normalise(p)) for p in parts) if f]


def is_verbatim(line: str, manuscript: str) -> bool:
    """True if the line (or each of its elided fragments, in order) appears in the manuscript text."""
    frags = fragments(line)
    if not frags:
        return False
    hay = normalise(manuscript)
    pos = 0
    for f in frags:
        i = hay.find(f, pos)
        if i < 0:
            return False
        pos = i + len(f)
    return True


def closest_passage(line: str, manuscript: str, width: int = 160) -> str:
    """The manuscript sentence most like a line that failed the check (shown under the red badge)."""
    sents = re.split(r"(?<=[.!?”])\s+", manuscript or "")
    best = difflib.get_close_matches(line, sents, n=1, cutoff=0.3)
    return (best[0] if best else "")[:width]


@dataclass
class Line:
    text: str
    kind: str = "dialogue"  # dialogue | narration
    speaker: str | None = None
    adapted_approved: bool = False


@dataclass
class SceneBrief:
    chapter_id: int
    action: str
    characters: list[str] = field(default_factory=list)  # studio form keys
    setting: str = ""
    lines: list[Line] = field(default_factory=list)
    page_id: int | None = None
    page_number: int | None = None
    age: str | None = None  # None/"auto" = from the chapter
    full_page: bool = False  # a full-page plate for a major revelation (master prompt §6)
    mode: str | None = None  # painted | shards for this run; None = the page's (or its volume's) mode

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "SceneBrief":
        lines = []
        for x in d.get("lines") or d.get("dialogue") or []:
            if isinstance(x, str):
                lines.append(Line(text=x))
            elif isinstance(x, dict) and (x.get("text") or "").strip():
                lines.append(Line(text=x["text"], kind=x.get("kind") or "dialogue", speaker=x.get("speaker") or None, adapted_approved=bool(x.get("adapted_approved"))))
        age = (d.get("age") or None)
        return cls(chapter_id=int(d["chapter_id"]), action=(d.get("action") or "").strip(), characters=[c.strip() for c in d.get("characters") or [] if c and c.strip()],
                   setting=(d.get("setting") or "").strip(), lines=lines, page_id=d.get("page_id"), page_number=d.get("page_number"),
                   age=None if age in (None, "", "auto") else age, full_page=bool(d.get("full_page")),
                   mode=d.get("mode") if d.get("mode") in ("painted", "shards") else None)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CharacterInfo:
    form_key: str
    name: str
    locked: bool
    character_id: int | None = None
    has_reference: bool = False


def suggest(name: str, known: list[CharacterInfo], n: int = 3) -> list[str]:
    keys = [c.form_key for c in known]
    low = name.strip().lower()
    out = [k for k in keys if k.split("/")[0] == low or k.startswith(low + "/")]
    by_name = [c.form_key for c in known if c.name.lower() == low]
    for k in by_name + difflib.get_close_matches(low, keys, n=n, cutoff=0.5):
        if k not in out:
            out.append(k)
    return out[:n + 2]


def validate(brief: SceneBrief, manuscript_text: str, characters: list[CharacterInfo], chapter_age: str, manuscript_label: str = "") -> dict[str, Any]:
    """The deterministic check of a brief. `can_paint` is False on any error; nothing is sent to a model here."""
    g = G.load()
    errors: list[str] = []
    warnings: list[str] = []
    no_manuscript = not (manuscript_text or "").strip()
    if no_manuscript:
        errors.append("No manuscript text for this chapter yet: drop the book PDF in Project → Manuscript, then direct the page.")
    if not brief.action:
        errors.append("Describe the exact action (what happens in this illustration).")
    lines_out = []
    for ln in brief.lines:
        ok = (not no_manuscript) and is_verbatim(ln.text, manuscript_text)
        status = "verbatim" if ok else ("adapted, approved" if ln.adapted_approved else "not in manuscript")
        if not ok and not ln.adapted_approved:
            errors.append(f"Not in manuscript: “{ln.text[:80]}” — use the exact words, or tick “adapted, approved”.")
        lines_out.append({**asdict(ln), "verbatim": ok, "status": status, "closest": "" if ok else closest_passage(ln.text, manuscript_text)})
    by_key = {c.form_key: c for c in characters}
    chars_out = []
    needs_reference: list[dict[str, Any]] = []
    if not brief.characters:
        warnings.append("No characters named: the panels will show setting only.")
    for key in brief.characters:
        c = by_key.get(key)
        if c is None:
            sug = suggest(key, characters)
            errors.append(f"Unknown character “{key}”." + (f" Did you mean {', '.join(sug)}?" if sug else ""))
            chars_out.append({"key": key, "exists": False, "locked": False, "name": key, "suggestions": sug})
            continue
        chars_out.append({"key": key, "exists": True, "locked": c.locked, "name": c.name, "character_id": c.character_id, "has_reference": c.has_reference, "suggestions": []})
        if not c.locked:
            needs_reference.append({"key": key, "name": c.name, "character_id": c.character_id, "has_reference": c.has_reference})
    if needs_reference:
        names = ", ".join(f"{x['name']} ({x['key']})" for x in needs_reference)
        errors.append(f"Locked characters only: {names} not locked. Create and approve the canonical reference sheet first (Characters).")
    age = brief.age if brief.age in G.AGES else chapter_age
    if brief.age and brief.age not in G.AGES:
        warnings.append(f"Unknown age “{brief.age}”; using the chapter's age.")
    a = g.ages.get(age)
    # Ravana with ten heads: remind the painter and the critic (master prompt §4)
    if any(k.startswith("ravana/ten") for k in brief.characters):
        warnings.append("Ravana with ten heads: the golden head is intelligence, the crimson head is ego — the critic counts heads.")
    return {
        "ok": not errors, "can_paint": not errors, "errors": errors, "warnings": warnings, "lines": lines_out, "characters": chars_out,
        "needs_reference": needs_reference, "no_manuscript": no_manuscript, "age": age, "age_source": "brief" if brief.age in G.AGES else "chapter",
        "age_name": a.name if a else age, "palette": a.palette if a else [], "palette_text": a.palette_text if a else "", "manuscript": manuscript_label,
    }
