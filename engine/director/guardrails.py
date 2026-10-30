"""The author's MASTER ART-DIRECTION PROMPT, parsed into rules the Art Director enforces.

The raw text of engine/director/master_prompt.md is the constant style authority: it is never edited by the studio,
never paraphrased away, and is shown in full in the Director's guardrail panel and attached in full to every
planning and critic call. This module only *reads* it into structured parts so the agent can (a) build a faithful
condensed image prompt (image models ignore very long prompts), (b) give the critic its exact 10-point test and
negative list, and (c) check page architecture and typography deterministically.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MASTER_PATH = Path(__file__).resolve().parent / "master_prompt.md"

AGES = ("treta", "dwapara", "kali")
AGE_NAMES = {"treta": "Treta Yuga", "dwapara": "Dwapara Yuga", "kali": "Kali Yuga"}
CHARACTERS = ("Rama", "Ravana", "Hanuman", "Krishna", "Arjuna", "Karna", "Kalki")

_HEADING = re.compile(r"^(\d{1,2})\.\s+([A-Z0-9][A-Z0-9 ,'’&—\-]+)$")
_AGE_HEADING = re.compile(r"^(TRETA|DWAPARA|KALI) YUGA\s+[—-]\s+(.+)$")
_CAPS_LINE = re.compile(r"^[A-Z][A-Z ’'—\-]+$")


@dataclass
class Section:
    number: int | None
    title: str
    text: str  # verbatim body (between this heading and the next)

    @property
    def bullets(self) -> list[str]:
        return [ln[2:].strip() for ln in self.text.splitlines() if ln.startswith("* ")]

    @property
    def paragraphs(self) -> list[str]:
        return [p.strip() for p in re.split(r"\n\s*\n", self.text) if p.strip()]


@dataclass
class AgeRules:
    key: str
    name: str
    subtitle: str
    palette: list[str]
    palette_text: str
    visual_language: str
    directives: dict[str, list[str]]  # character -> sentences (verbatim)
    general: list[str]  # the age's other sentences (verbatim)
    text: str


@dataclass
class Guardrails:
    raw: str
    sha256: str
    preamble: dict[str, str]
    sections: dict[int, Section]
    ages: dict[str, AgeRules]
    characters: dict[str, list[dict[str, str]]]
    ravana_heads: dict[str, str]
    page_architecture: dict[str, Any]
    parchment: dict[str, Any]
    typography: dict[str, Any]
    negatives: list[str]
    quality_test: list[str]
    final_command: str
    extras: dict[str, Any] = field(default_factory=dict)

    def section(self, n: int) -> Section:
        return self.sections[n]

    def to_json(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "raw": self.raw,
            "preamble": self.preamble,
            "sections": [{"number": s.number, "title": s.title, "text": s.text, "bullets": s.bullets} for s in self.sections.values()],
            "ages": {k: {"key": a.key, "name": a.name, "subtitle": a.subtitle, "palette": a.palette, "palette_text": a.palette_text,
                         "visual_language": a.visual_language, "directives": a.directives, "general": a.general} for k, a in self.ages.items()},
            "characters": self.characters,
            "ravana_heads": self.ravana_heads,
            "page_architecture": self.page_architecture,
            "parchment": self.parchment,
            "typography": self.typography,
            "negatives": self.negatives,
            "quality_test": self.quality_test,
            "final_command": self.final_command,
        }


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        flat = " ".join(ln.strip() for ln in para.splitlines() if ln.strip())
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat) if s.strip() and not s.strip().endswith(":")]
    return out


def _split_list(text: str) -> list[str]:
    text = text.strip().rstrip(".")
    parts = re.split(r",\s*|\s+and\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _who(sentence: str) -> str | None:
    s = sentence.strip()
    for name in CHARACTERS:
        if s.startswith(name) or s.startswith(name + "’") or s.startswith(name + "'"):
            return name
    low = s.lower()
    if low.startswith("the golden head") or low.startswith("the crimson head") or low.startswith("their colours"):
        return "Ravana"
    return None


def parse(raw: str) -> Guardrails:
    lines = raw.splitlines()
    # --- split into the preamble blocks (PROJECT, CORE CREATIVE PHILOSOPHY), numbered sections, final command
    blocks: list[tuple[int | None, str, list[str]]] = [(None, "TITLE", [])]
    for ln in lines:
        s = ln.strip()
        if s == "⸻":
            continue
        m = _HEADING.match(s)
        if m:
            blocks.append((int(m.group(1)), m.group(2).strip(), []))
            continue
        if s in ("PROJECT", "CORE CREATIVE PHILOSOPHY", "FINAL CREATIVE COMMAND"):
            blocks.append((None, s, []))
            continue
        blocks[-1][2].append(ln.rstrip())
    preamble: dict[str, str] = {}
    sections: dict[int, Section] = {}
    final_command = ""
    for num, title, body in blocks:
        text = "\n".join(body).strip()
        if num is None:
            if title == "FINAL CREATIVE COMMAND":
                final_command = text
            else:
                preamble[title] = text
        else:
            sections[num] = Section(num, title, text)

    # --- §4 the three ages
    ages: dict[str, AgeRules] = {}
    if 4 in sections:
        cur: list[Any] | None = None
        chunks: list[list[Any]] = []
        for ln in sections[4].text.splitlines():
            m = _AGE_HEADING.match(ln.strip())
            if m:
                cur = [m.group(1).lower(), m.group(2).strip(), []]
                chunks.append(cur)
            elif cur is not None:
                cur[2].append(ln)
        for key, subtitle, body in chunks:
            text = "\n".join(body).strip()
            pal = re.search(r"^Palette:\s*(.+)$", text, re.M)
            vis = re.search(r"^Visual language:\s*(.+)$", text, re.M)
            directives: dict[str, list[str]] = {}
            general: list[str] = []
            for para in re.split(r"\n\s*\n", text):
                p = para.strip()
                if not p or p.startswith("Palette:") or p.startswith("Visual language:"):
                    continue
                for sent in _sentences(p):
                    who = _who(sent)
                    if who:
                        directives.setdefault(who, []).append(sent)
                    else:
                        general.append(sent)
            ages[key] = AgeRules(key, AGE_NAMES[key], subtitle, _split_list(pal.group(1)) if pal else [], pal.group(1).strip() if pal else "",
                                 vis.group(1).strip() if vis else "", directives, general, text)

    # --- characters: §4 directives per age + §5 consistency sentences that name a character
    characters: dict[str, list[dict[str, str]]] = {}
    for a in ages.values():
        for who, sents in a.directives.items():
            for s in sents:
                characters.setdefault(who, []).append({"age": a.key, "text": s})
    if 5 in sections:
        for sent in _sentences(sections[5].text):
            who = _who(sent)
            if who:
                characters.setdefault(who, []).append({"age": "all", "text": sent})
    heads = {m.group(1).lower(): m.group(2).lower() for m in re.finditer(r"The (\w+) head represents (?:Ravana[’']s|his) (\w+)", raw)}

    # --- §6 page architecture
    arch: dict[str, Any] = {"min_panels": 3, "max_panels": 5}
    if 6 in sections:
        t = sections[6].text
        m = re.search(r"(\d+)\s*[–-]\s*(\d+)\s+panels", t)
        if m:
            arch["min_panels"], arch["max_panels"] = int(m.group(1)), int(m.group(2))
        arch["hierarchy"] = sections[6].bullets
        arch["roles"] = {"dominant": [1, 1], "narrative": [2, 3], "detail": [1, 1]}
        fp = re.search(r"full-page or double-page illustrations for ([^.]+)\.", t)
        arch["full_page_for"] = _split_list(fp.group(1)) if fp else []
        arch["rules"] = _sentences(re.sub(r"^\* .*$", "", t, flags=re.M))

    # --- §2 parchment and §3 shards
    parchment: dict[str, Any] = {}
    if 2 in sections:
        parchment["texture"] = sections[2].bullets
        parchment["rules"] = [s for s in _sentences(re.sub(r"^\* .*$", "", sections[2].text, flags=re.M))]
    if 3 in sections:
        parchment["shards"] = sections[3].bullets
        parchment["shard_rules"] = [s for s in _sentences(re.sub(r"^\* .*$", "", sections[3].text, flags=re.M))]

    # --- §7 typography (exact strings)
    typo: dict[str, Any] = {}
    if 7 in sections:
        t = sections[7].text
        m = re.search(r"Use the exact series title:\s*\n\s*\n?\s*([^\n]+)", t)
        typo["series_title"] = m.group(1).strip() if m else "THE CYCLE OF DHARMA"
        m = re.search(r"Author credit:\s*\n\s*\n?\s*([^\n]+)", t)
        typo["author_credit"] = m.group(1).strip() if m else "RACHIT AGARWAL"
        typo["rules"] = [s for s in _sentences(t) if typo["series_title"] not in s and typo["author_credit"] not in s]
        typo["rules"].append("Volume numbers and subtitles must remain consistent.")

    negatives = [ln.strip() for ln in sections[11].text.splitlines() if ln.strip().startswith("No ")] if 11 in sections else []
    quality = [re.sub(r"^\d+\.\s*", "", ln.strip()) for ln in sections[12].text.splitlines() if re.match(r"^\d+\.\s", ln.strip())] if 12 in sections else []

    g = Guardrails(raw=raw, sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(), preamble=preamble, sections=sections, ages=ages,
                   characters=characters, ravana_heads=heads, page_architecture=arch, parchment=parchment, typography=typo,
                   negatives=negatives, quality_test=quality, final_command=final_command)
    if 8 in sections:
        g.extras["volume_two"] = {"text": sections[8].text, "tensions": sections[8].bullets}
    if 9 in sections:
        fmt = re.search(r"Format:\s*([^\n]+)", sections[9].text)
        g.extras["poster"] = {"text": sections[9].text, "format": fmt.group(1).strip() if fmt else "", "aspect": [2, 3]}
    return g


_cache: dict[str, Any] = {}


def load(path: Path | None = None) -> Guardrails:
    """The parsed master prompt, cached by file mtime (the file itself is the authority)."""
    p = path or MASTER_PATH
    key = (str(p), p.stat().st_mtime)
    if _cache.get("key") != key:
        _cache["key"] = key
        _cache["g"] = parse(p.read_text(encoding="utf-8"))
    return _cache["g"]


def raw_text() -> str:
    return load().raw
