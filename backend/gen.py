"""Generation: the panel's full prompt (recipe + locked looks + scene), references from the lock, the provider call,
the Candidate row and the Ledger entry. Used by the worker (single panel, page, batch, character refs, silhouettes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from engine import agents, providers
from engine.comic import layout as L
from engine.comic.script import is_duel, look_paragraph, panel_prompt, reference_prefix

from . import db
from .models import Candidate, Character, CharacterRef, Ledger, Page, Panel, Silhouette


def _bbox_aspect(panel: Panel) -> float:
    poly = [(float(x), float(y)) for x, y in (panel.shape or {}).get("polygon_mm") or []]
    if len(poly) < 3:
        return 1.5
    x0, y0, x1, y1 = L._bbox(poly)
    return (x1 - x0) / max(1e-6, y1 - y0)


def orientation_for(panel: Panel) -> str:
    if panel.kind == "plate":
        return "portrait"
    return providers.orientation_of(_bbox_aspect(panel))


def characters_on(session: Session, panel: Panel) -> list[Character]:
    out = []
    for key in panel.characters or []:
        c = session.scalar(select(Character).where(Character.form_key == key))
        if c:
            out.append(c)
    return out


def primary_ref(session: Session, c: Character) -> Path | None:
    r = session.get(CharacterRef, c.primary_ref_id) if c.primary_ref_id else None
    if r is None:
        r = next((x for x in c.refs if x.is_primary), None) or next((x for x in c.refs if x.approved), None)
    p = db.abs_path(r.path) if r else None
    return p if (p and p.exists()) else None


def full_prompt(session: Session, panel: Panel, scene: str | None = None) -> tuple[str, list[Path], list[str]]:
    """(prompt, reference paths, names) for a panel: looks of the locked characters go into the prompt, their primary
    references are attached (edits-with-reference) with the identity prefix."""
    chars = characters_on(session, panel)
    looks = [look_paragraph(c.name, c.form_key, c.look) for c in chars if c.locked]
    refs, names = [], []
    for c in chars:
        if not c.locked:
            continue
        p = primary_ref(session, c)
        if p:
            refs.append(p)
            names.append(c.name)
    era = panel.page.chapter.volume.era_default or "treta"
    scene = scene if scene is not None else panel.scene
    body = panel_prompt(era, scene, panel.kind, duel=is_duel(list(panel.characters or []), scene), scale=panel.scale or "MS", looks=looks)
    return reference_prefix(names) + body, refs, names


def record_cost(session: Session, provider: str, usd: float, ref: str) -> None:
    if usd:
        session.add(Ledger(provider=provider, usd=usd, ref=ref))


def generate_candidate(session: Session, panel: Panel, provider: str, feedback: str = "", index: int = 0) -> Candidate:
    """One image for one panel; the candidate keeps its full prompt and the feedback that produced it."""
    prompt, refs, _names = full_prompt(session, panel)
    page = panel.page
    label = f"p{page.number}.{panel.n} #{index}"
    res = providers.generate_image(provider, prompt, orientation_for(panel), refs, label=label, state=panel.state)
    d = db.DATA_DIR / "candidates" / f"p{page.id}"
    d.mkdir(parents=True, exist_ok=True)
    cand = Candidate(panel_id=panel.id, path="", provider=res.provider, model=res.model, prompt_full=prompt, feedback_used=feedback or "", cost_usd=res.cost_usd, qa={"dry_run": res.dry_run, **res.meta})
    session.add(cand)
    session.flush()
    path = d / f"{page.number:03d}_{panel.n}_{cand.id}.png"
    path.write_bytes(res.png)
    cand.path = db.rel(path)
    record_cost(session, res.provider, res.cost_usd, f"candidate:{cand.id}")
    return cand


def select_candidate(session: Session, panel: Panel, cand: Candidate) -> None:
    panel.selected_candidate_id = cand.id
    page = panel.page
    if page.status in ("empty", "draft", "generating"):
        page.status = "review"


def run_critic(session: Session, panel: Panel, cands: list[Candidate]) -> int | None:
    """Score candidates and pre-select the best. Returns the chosen candidate id."""
    if not cands:
        return None
    chars = characters_on(session, panel)
    looks = [look_paragraph(c.name, c.form_key, c.look) for c in chars if c.locked]
    images = [p for p in (db.abs_path(c.path) for c in cands) if p and p.exists()]
    info = {"caption_en": panel.caption_en, "balloon_en": panel.balloon_en, "speaker": panel.speaker, "state": panel.state, "scale": panel.scale, "characters": panel.characters}
    data = agents.critic(panel.scene, info, looks, images)
    scores = {int(s.get("index", -1)): s for s in (data.get("scores") or []) if isinstance(s, dict)}
    for i, c in enumerate(cands):
        s = scores.get(i)
        if s:
            c.qa = {**(c.qa or {}), "critic_score": s.get("score"), "critic_notes": s.get("notes")}
    best = data.get("best")
    try:
        chosen = cands[int(best)] if best is not None else cands[0]
    except (ValueError, IndexError, TypeError):
        chosen = cands[0]
    select_candidate(session, panel, chosen)
    return chosen.id


def generate_character_ref(session: Session, c: Character, provider: str, index: int = 0) -> CharacterRef:
    """A reference candidate painted from the look paragraph (a neutral three-quarter portrait)."""
    look = look_paragraph(c.name, c.form_key, c.look) or f"{c.name}. "
    scene = f"Character reference sheet portrait of {c.name}: three-quarter view, chest-up, neutral expression, eyes open, plain dark background, one warm key light and one cool rim light; the whole face and attire clearly readable."
    prompt = panel_prompt("treta", scene, "shard", duel=False, scale="MCU", looks=[look])
    res = providers.generate_image(provider, prompt, "square", None, label=f"{c.name} ref #{index}", state="quiet")
    d = db.DATA_DIR / "refs" / f"c{c.id}"
    d.mkdir(parents=True, exist_ok=True)
    ref = CharacterRef(character_id=c.id, path="", provider=res.provider, prompt=prompt, is_primary=False, approved=False)
    session.add(ref)
    session.flush()
    path = d / f"{c.form_key.replace('/', '_')}_{ref.id}.png"
    path.write_bytes(res.png)
    ref.path = db.rel(path)
    record_cost(session, res.provider, res.cost_usd, f"ref:{ref.id}")
    return ref


def generate_silhouette(session: Session, project_id: int, prompt_text: str, index: int = 0, tags: list[str] | None = None) -> Silhouette:
    """Sunburst paints ink on white; the result is auto-keyed to a transparent PNG and tagged.
    With tags and no prompt (or a prompt that is itself a short tag list) the prompt_writer writes the prompt; an
    author's own prompt is kept and the ink-on-white technical line is appended when it is missing."""
    text = (prompt_text or "").strip()
    looks_like_tags = bool(text) and len(text) < 80 and "." not in text
    tags = [t.strip() for t in (tags or []) if t.strip()] or ([t.strip() for t in text.replace(";", ",").split(",") if t.strip()] if looks_like_tags else []) or ["compass rose"]
    if text and not looks_like_tags:
        prompt = text if "no text" in text.lower() else f"{text.rstrip('. ')}. Ink line drawing on pure white, no colour, no shading except hatching, no background, no frame, no text."
    else:
        prompt = agents.silhouette_prompt(tags)
    if providers.settings.dry_run_sunburst:
        png = providers.placeholder_silhouette(tags, seed=index)
        provider = "sunburst"
        cost = 0.0
    else:
        res = providers.sunburst_generate(prompt, "square", None, label="silhouette", state="quiet")
        png, provider, cost = res.png, res.provider, res.cost_usd
    keyed = providers.key_to_alpha(png)
    d = db.DATA_DIR / "silhouettes"
    d.mkdir(parents=True, exist_ok=True)
    s = Silhouette(project_id=project_id, path="", tags=tags, source="generated", prompt=prompt)
    session.add(s)
    session.flush()
    path = d / f"sil_{s.id}.png"
    path.write_bytes(keyed)
    s.path = db.rel(path)
    record_cost(session, provider, cost, f"silhouette:{s.id}")
    return s


def panel_info(panel: Panel) -> dict[str, Any]:
    return {"caption_en": panel.caption_en, "balloon_en": panel.balloon_en, "speaker": panel.speaker, "state": panel.state, "scale": panel.scale, "characters": list(panel.characters or []), "kind": panel.kind}


def page_has_unselected(page: Page) -> list[Panel]:
    return [p for p in page.panels if not p.selected_candidate_id]
