"""`python -m backend.seed` — the project, volumes, canvases, characters (Rama locked with his reference),
Chapter 1 pages 1-10 with the 32 panels from engine/comic_chapter1.yaml, and the candidates in data/ch1_candidates/."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.comic.script import RAMA_LOOK, STATES, scale_of
from engine.settings import REPO_ROOT

from . import db, gen, render
from .models import Candidate, Canvas, Chapter, Character, CharacterRef, Page, Panel, Project, Volume

ENGINE = REPO_ROOT / "engine"
PICKS = {101: 1, 102: 0, 103: 0, 104: 1, 201: 0, 202: 1, 203: 1, 204: 0, 205: 1, 301: 0, 401: 0, 402: 1, 403: 1, 501: 1, 502: 0, 503: 1, 504: 1,
         601: 0, 602: 1, 603: 1, 604: 0, 701: 1, 702: 1, 703: 0, 801: 0, 802: 1, 803: 0, 901: 0, 1001: 0, 1002: 0, 1003: 0, 1004: 1}
VOLUMES = [(1, "The Fire That Was Not Destroyed", "parchment", "treta"), (2, "Book Two", "iron", "dwapara"), (3, "Book Three", "glass", "phala")]


def seed_project(session: Session) -> Project:
    proj = session.scalar(select(Project))
    if proj is None:
        proj = Project(title="The Cycle of Dharma", author="Rachit Agarwal", settings={"models": {}, "studio": "Rishikesh Studio"})
        session.add(proj)
        session.flush()
    return proj


def seed_volumes(session: Session, proj: Project) -> dict[int, Volume]:
    out = {}
    for num, title, canvas_key, era in VOLUMES:
        vol = session.scalar(select(Volume).where(Volume.project_id == proj.id, Volume.number == num))
        if vol is None:
            vol = Volume(project_id=proj.id, number=num, title=title, era_default=era)
            session.add(vol)
            session.flush()
        if vol.canvas_id is None:
            # volume 1 defaults to parchment; 2 and 3 only get a suggestion (the author picks on the Canvas screen)
            if num == 1:
                vol.canvas_id = session.scalar(select(Canvas.id).where(Canvas.key == canvas_key))
        out[num] = vol
    render.ensure_typography(session)
    return out


def seed_characters(session: Session, proj: Project) -> None:
    data = yaml.safe_load((ENGINE / "characters.yaml").read_text(encoding="utf-8"))
    for ch in data["characters"]:
        for form in ch.get("forms", []):
            key = form["key"]
            c = session.scalar(select(Character).where(Character.form_key == key))
            look = form.get("description", "")
            if key == "rama":
                look = RAMA_LOOK.strip()
            if c is None:
                c = Character(project_id=proj.id, name=ch["name"], form_key=key, look=look, locked=False)
                session.add(c)
                session.flush()
            elif not c.look:
                c.look = look
            if key == "rama":
                c.look = RAMA_LOOK.strip()
                src = ENGINE / "refs" / "rama_reference.png"
                if src.exists() and not c.refs:
                    dst = db.DATA_DIR / "refs" / f"c{c.id}" / "rama_reference.png"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    ref = CharacterRef(character_id=c.id, path=db.rel(dst), provider="upload", prompt="locked reference (engine/refs/rama_reference.png)", is_primary=True, approved=True)
                    session.add(ref)
                    session.flush()
                    c.primary_ref_id = ref.id
                c.locked = True
    session.flush()


def chapter_text_from_yaml(data: dict) -> str:
    """The book's sentences in reading order (the manuscript PDF replaces this through the Project screen)."""
    lines = []
    for ch in data["chapters"]:
        lines.append(f"## {ch['title']}\n")
        for pg in ch["pages"]:
            for p in pg["panels"]:
                if p.get("caption_en"):
                    lines.append(p["caption_en"])
                if p.get("balloon_en"):
                    lines.append(f'"{p["balloon_en"]}"' + (f" — {p['speaker']}" if p.get("speaker") else ""))
            lines.append("")
    return "\n".join(lines)


def seed_chapter1(session: Session, vol: Volume) -> Chapter:
    data = yaml.safe_load((ENGINE / "comic_chapter1.yaml").read_text(encoding="utf-8"))
    ch = session.scalar(select(Chapter).where(Chapter.volume_id == vol.id, Chapter.number == 1))
    if ch is None:
        ch = Chapter(volume_id=vol.id, number=1, title="The Last Night of Lanka", text=chapter_text_from_yaml(data), pages_from=1, pages_to=10)
        session.add(ch)
        session.flush()
    existing = {pg.number: pg for pg in ch.pages}
    for part in data["chapters"]:
        for pg in part["pages"]:
            num = int(pg["page"])
            page = existing.get(num)
            if page is None:
                page = Page(chapter_id=ch.id, number=num, status="draft", seed=7, is_opener=(num == 1), epigraph=str(pg.get("epigraph") or part.get("epigraph") or ""), epigraph_hi=str(pg.get("epigraph_hi") or ""))
                session.add(page)
                session.flush()
                existing[num] = page
            if page.panels:
                continue
            for p in pg["panels"]:
                scene = p["image"]
                session.add(Panel(
                    page_id=page.id, n=int(p["n"]), kind=p.get("kind", "shard"), scene=scene, scale=scale_of(scene, p.get("scale")),
                    state=p.get("state") if p.get("state") in STATES else "quiet", beat=p.get("beat"), weight=float(p.get("weight", 1.0)),
                    characters=list(p.get("characters") or []), environment=p.get("environment"), source_page=str(p.get("source_page", "")),
                    caption_en=p.get("caption_en", "") or "", balloon_en=p.get("balloon_en", "") or "", speaker=p.get("speaker"),
                    caption_hi=p.get("caption_hi", "") or "", balloon_hi=p.get("balloon_hi", "") or "", hi_is_draft=bool(p.get("hi_is_draft", False)),
                    image_group=p.get("image_group"), shape={},
                ))
            session.flush()
            session.expire(page, ["panels"])
            render.ensure_shapes(session, page, force=True)
    session.flush()
    session.expire(ch, ["pages"])
    return ch


def seed_candidates(session: Session, ch: Chapter) -> int:
    src_dir = db.DATA_DIR / "ch1_candidates"
    n = 0
    for page in ch.pages:
        for panel in page.panels:
            if panel.candidates:
                continue
            number = page.number * 100 + panel.n
            prompt, _refs, _names = gen.full_prompt(session, panel)
            for k in (0, 1):
                f = src_dir / f"{number:04d}_{k}.png"
                if not f.exists():
                    continue
                c = Candidate(panel_id=panel.id, path=db.rel(f), provider="sunburst", model="gpt-image-2.5-sunburst", prompt_full=prompt, feedback_used="", cost_usd=0.0, qa={"imported": True, "index": k})
                session.add(c)
                session.flush()
                if PICKS.get(number) == k:
                    panel.selected_candidate_id = c.id
                n += 1
        if any(p.selected_candidate_id for p in page.panels):
            page.status = "review"
    session.flush()
    return n


GENERATED = ("candidates", "refs", "silhouettes", "exports", "artifacts", "enhanced", "manuscript")


def run(reset: bool = False) -> dict[str, int]:
    """Seed (idempotent). --reset drops and recreates every table in place (a running server keeps working) and
    clears the generated media folders; data/ch1_candidates and the canvas textures are kept."""
    if reset:
        from .models import Base

        Base.metadata.drop_all(db.engine)
        for sub in GENERATED:
            shutil.rmtree(db.DATA_DIR / sub, ignore_errors=True)
    db.init_db()
    with db.session_scope() as session:
        render.ensure_canvases(session)
        proj = seed_project(session)
        vols = seed_volumes(session, proj)
        seed_characters(session, proj)
        ch = seed_chapter1(session, vols[1])
        cands = seed_candidates(session, ch)
        panels = sum(len(pg.panels) for pg in ch.pages)
        return {"pages": len(ch.pages), "panels": panels, "candidates": cands, "characters": len(session.scalars(select(Character)).all())}


if __name__ == "__main__":
    out = run(reset="--reset" in sys.argv)
    print(f"seeded: {out}  (db: {db.DB_PATH})")
