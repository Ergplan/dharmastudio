"""Studio chapter -> manuscript chapter, and the age (Treta / Dwapara / Kali) each chapter is painted in.

The studio numbers chapters 1..N inside each volume; the Director always shows and keys by the MANUSCRIPT chapter
number and title (Volume Two = Book Two, The Remembrance Index, manuscript chapters 22-41). The book data comes from
backend.book_seed.book() — the local book.json written when the author drops the PDF into Project -> Manuscript (or
the gitignored dev copy). Without it the Director still works from the chapter text stored in the studio, falls
back to keywords for the age, and says that the manuscript has not been imported yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# scene_settings[].era (the production breakdown) -> the master prompt's three ages
ERA_TO_AGE = {
    "treta": "treta",
    "dwapara": "dwapara",
    # everything after Krishna's departure is Kali Yuga: Somnath 1026, the ashram, Girgaon, फल, the resistance, the core
    "prabhas": "kali", "ashram": "kali", "phala": "kali", "resistance": "kali", "core": "kali", "girgaon": "kali", "dhanushkodi": "kali",
}

AGE_KEYWORDS = {
    "treta": ["lanka", "ravana", "rama", "sita", "vibhishana", "lakshmana", "agastya", "vanara", "ashoka", "trikuta", "rakshasa", "kumbhakarna", "indrajit", "ayodhya"],
    "dwapara": ["kurukshetra", "arjuna", "krishna", "karna", "bhishma", "drona", "pandava", "kaurava", "gandiva", "chariot", "ashwasena", "duryodhana", "yudhishthira", "dwarka"],
    "kali": ["फल", "phala", "somnath", "prabhas", "ghazni", "mahmud", "sultan", "ashram", "index", "screen", "data", "server", "network", "terminal", "credits", "setu", "pune", "mumbai", "girgaon", "phone", "drone", "city", "camp", "algorithm", "core", "kalki", "meera", "neel", "anaya", "vikram"],
}

NUMBER_WORDS = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE"}


@dataclass
class ManuscriptChapter:
    volume: int
    book_title: str
    studio_number: int
    manuscript_number: int | None
    kind: str  # chapter | interlude | prologue+chapter | epilogue | studio (no book data)
    title: str
    label: str
    text: str
    scene_settings: list[dict[str, Any]] = field(default_factory=list)
    cast: list[dict[str, Any]] = field(default_factory=list)
    eras: list[str] = field(default_factory=list)
    from_book: bool = False

    @property
    def setting(self) -> str:
        return "\n\n".join(s.get("setting", "") for s in self.scene_settings if s.get("setting"))

    def to_json(self) -> dict[str, Any]:
        return {"volume": self.volume, "book_title": self.book_title, "studio_number": self.studio_number, "manuscript_number": self.manuscript_number,
                "kind": self.kind, "title": self.title, "label": self.label, "setting": self.setting, "cast": self.cast, "eras": self.eras,
                "from_book": self.from_book, "words": len(self.text.split())}


def _book() -> dict[str, Any]:
    try:
        from backend import book_seed

        return book_seed.book()
    except Exception:  # noqa: BLE001
        return {"books": {}, "entries": []}


def _comic_chapters() -> list[dict[str, Any]]:
    try:
        from backend import book_seed

        return book_seed.comic_chapters() if _book().get("entries") else []
    except Exception:  # noqa: BLE001
        return []


def label_for(entries: list[dict[str, Any]], fallback_title: str) -> tuple[int | None, str, str, str]:
    """(manuscript number, kind, title, label) for the book entries behind a studio chapter."""
    chs = [e for e in entries if e.get("kind") == "chapter"]
    if chs:
        e = chs[-1]
        kind = "prologue+chapter" if any(x.get("kind") == "prologue" for x in entries) else "chapter"
        pre = "Prologue & " if kind == "prologue+chapter" else ""
        return int(e["number"]), kind, e["title"], f"{pre}Chapter {e['number']} — {e['title']}"
    if entries:
        e = entries[0]
        kind = e.get("kind", "chapter")
        name = {"interlude": "Interlude", "epilogue": "Epilogue", "prologue": "Prologue"}.get(kind, kind.title())
        title = e.get("title") or fallback_title
        return None, kind, title, (f"{name} — {title}" if title and title != name else name)
    return None, "studio", fallback_title, fallback_title


def resolve(volume: int, studio_number: int, title: str, pages_from: int | None, pages_to: int | None, text: str) -> ManuscriptChapter:
    """Find the manuscript entries behind a studio chapter: by printed page range, then by (volume, number)."""
    book = _book()
    book_title = (book.get("books") or {}).get(str(volume), "")
    entries: list[dict[str, Any]] = []
    comic = _comic_chapters()
    hit = None
    if pages_from:
        hit = next((c for c in comic if c["volume"] == volume and c["pages"][0] == pages_from), None)
    if hit is None:
        hit = next((c for c in comic if c["volume"] == volume and c["number"] == studio_number and (not title or c["title"] == title)), None)
    if hit is None:
        hit = next((c for c in comic if c["volume"] == volume and c["number"] == studio_number), None)
    if hit is not None:
        entries = hit["entries"]
    num, kind, mtitle, label = label_for(entries, title)
    ms_text = "\n\n".join(e.get("text", "") for e in entries) if entries else ""
    settings = [s for e in entries for s in (e.get("scene_settings") or [])]
    cast: list[dict[str, Any]] = []
    for e in entries:
        for c in e.get("cast") or []:
            if not any(x["name"] == c["name"] for x in cast):
                cast.append(c)
    return ManuscriptChapter(volume=volume, book_title=book_title, studio_number=studio_number, manuscript_number=num, kind=kind,
                             title=mtitle or title, label=label, text=ms_text or (text or ""), scene_settings=settings, cast=cast,
                             eras=[s.get("era", "") for s in settings], from_book=bool(entries))


def manuscript_entry(number: int) -> dict[str, Any] | None:
    """A manuscript chapter by its own number (e.g. 22 -> The Price of a Prayer)."""
    return next((e for e in _book().get("entries", []) if e.get("kind") == "chapter" and e.get("number") == number), None)


def keyword_age(text: str, default: str = "kali") -> str:
    low = (text or "").lower()
    scores = {age: sum(len(re.findall(r"\b" + re.escape(k) + r"\b", low)) if k.isascii() else low.count(k) for k in kws) for age, kws in AGE_KEYWORDS.items()}
    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0] if best[1] > 0 else default


def age_from_eras(eras: list[str]) -> str | None:
    """One distinct mapped era -> that age. Mixed lists (montages, the interludes' shared breakdown) -> None."""
    ages = {ERA_TO_AGE[e] for e in eras if e in ERA_TO_AGE}
    return ages.pop() if len(ages) == 1 else None


def age_for(mc: ManuscriptChapter, volume_default: str | None = None) -> dict[str, str]:
    """{age, source, era}: scene_settings era first, then keywords over the chapter text."""
    a = age_from_eras(mc.eras)
    if a:
        return {"age": a, "source": "scene_settings", "era": next(e for e in mc.eras if e in ERA_TO_AGE)}
    default = ERA_TO_AGE.get(volume_default or "", "kali") if volume_default else ("treta" if mc.volume == 1 else "kali")
    return {"age": keyword_age(mc.text, default), "source": "keywords", "era": mc.eras[0] if mc.eras else ""}


def age_for_manuscript_number(number: int) -> str | None:
    e = manuscript_entry(number)
    if e is None:
        return None
    a = age_from_eras([s.get("era", "") for s in e.get("scene_settings") or []])
    return a or keyword_age(e.get("text", ""))


def volume_line(volume: int, title: str) -> str:
    """'VOLUME TWO — THE REMEMBRANCE INDEX' (master prompt §7: volume numbers and subtitles consistent)."""
    return f"VOLUME {NUMBER_WORDS.get(volume, str(volume))} — {title.upper()}" if title else f"VOLUME {NUMBER_WORDS.get(volume, str(volume))}"


def book_title(volume: int, fallback: str = "") -> str:
    return (_book().get("books") or {}).get(str(volume)) or fallback


def volume_range(volume: int) -> tuple[int | None, int | None]:
    nums = [e["number"] for e in _book().get("entries", []) if e.get("kind") == "chapter" and e.get("book") == volume]
    return (min(nums), max(nums)) if nums else (None, None)


def has_book() -> bool:
    return bool(_book().get("entries"))
