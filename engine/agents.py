"""The text agents: panel_script, hindi_draft, scene_rewrite, silhouette_prompt, cast_proposal, critic.
Each calls engine.llm.ask_json with its role and has a fallback so the studio works without keys."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import llm
from .claude_agent import load_prompt
from .comic.script import fallback_pages, silhouette_prompt_text


def panel_script(chapter_title: str, chapter_text: str, first_page: int, pages: int | None, environments: list[str], character_forms: list[str], era: str = "treta") -> dict[str, Any]:
    """script_writer: break the chapter text into pages/panels (captions verbatim)."""
    pages = pages or max(1, int(round(len((chapter_text or "").split()) / 180)))
    user = llm.dumps({"title": chapter_title, "era": era, "first_page": first_page, "pages": pages, "chapter_text": (chapter_text or "")[:80000], "environments": environments, "character_forms": character_forms})
    return llm.ask_json("script_writer", load_prompt("panel_script"), user, fallback=lambda: fallback_pages(chapter_text, first_page, pages), max_tokens=16000)


def hindi_draft(items: list[dict[str, Any]]) -> dict[str, Any]:
    """script_writer: Hindi drafts for the translator; rows are flagged hi_is_draft by the caller."""
    user = llm.dumps(items)
    return llm.ask_json("script_writer", load_prompt("hindi_draft"), user, fallback=lambda: {"items": [{"id": it["id"], "caption_hi": "", "balloon_hi": ""} for it in items]}, max_tokens=16000)


def _fallback_rewrite(scene: str, feedback: str) -> str:
    """No key: fold the feedback into the scene line so the author's note still reaches the painter."""
    fb = (feedback or "").strip().rstrip(".")
    scene = (scene or "").strip()
    if not fb:
        return scene
    low = fb.lower()
    if "eyes open" in low and "eyes" in scene.lower():
        scene = re.sub(r"eyes (closed|downcast|shut)", "eyes open", scene, flags=re.I)
    return f"{scene.rstrip('. ')}. Direction: {fb}."


def scene_rewrite(scene: str, feedback: str, panel: dict[str, Any]) -> str:
    """prompt_writer: rewrite the SCENE line from the author's feedback; returns the new scene string."""
    user = llm.dumps({"scene": scene, "feedback": feedback, "panel": panel})
    data = llm.ask_json("prompt_writer", load_prompt("scene_rewrite"), user, fallback=lambda: {"scene": _fallback_rewrite(scene, feedback)}, max_tokens=1200)
    out = (data or {}).get("scene") if isinstance(data, dict) else None
    return (out or _fallback_rewrite(scene, feedback)).strip()


def silhouette_prompt(tags: list[str]) -> str:
    """prompt_writer: tags -> an ink-on-white line-drawing prompt."""
    user = llm.dumps({"tags": tags})
    data = llm.ask_json("prompt_writer", load_prompt("silhouette_prompt"), user, fallback=lambda: {"prompt": silhouette_prompt_text(tags)}, max_tokens=600)
    out = (data or {}).get("prompt") if isinstance(data, dict) else None
    return (out or silhouette_prompt_text(tags)).strip()


def _fallback_cast(text: str) -> dict[str, Any]:
    """No key: capitalised names that recur in the text become a cast list with an empty look."""
    words = re.findall(r"\b[A-Z][a-z]{2,}\b", text or "")
    stop = {"The", "And", "But", "Then", "When", "There", "That", "This", "His", "Her", "They", "She", "Chapter", "Prologue", "Book", "One", "Two", "Three", "Nobody", "All", "Every", "By", "In", "It", "He", "Nine", "Eight", "Its"}
    counts: dict[str, int] = {}
    for w in words:
        if w not in stop:
            counts[w] = counts.get(w, 0) + 1
    names = [w for w, c in sorted(counts.items(), key=lambda kv: -kv[1]) if c >= 3][:12]
    return {"characters": [{"name": n, "forms": [{"form_key": n.lower(), "look": ""}], "in_chapter_1": True} for n in names]}


def cast_proposal(manuscript_text: str, chapter1_text: str) -> dict[str, Any]:
    """script_writer: propose the cast (name, forms, first look paragraph) from the manuscript."""
    user = llm.dumps({"chapter_1": (chapter1_text or "")[:40000], "manuscript_excerpt": (manuscript_text or "")[:60000]})
    return llm.ask_json("script_writer", load_prompt("cast_proposal"), user, fallback=lambda: _fallback_cast(chapter1_text or manuscript_text), max_tokens=12000)


def critic(scene: str, panel: dict[str, Any], looks: list[str], images: list[Path]) -> dict[str, Any]:
    """critic: score candidates; the fallback prefers the first (never auto-approves a page)."""
    user = llm.dumps({"scene": scene, "panel": panel, "looks": looks, "candidates": len(images)})
    fb = lambda: {"scores": [{"index": i, "score": 50, "notes": "no critic key: unscored"} for i in range(len(images))], "best": 0}  # noqa: E731
    return llm.ask_json("critic", load_prompt("critic"), user, images=images, fallback=fb, max_tokens=2000)
