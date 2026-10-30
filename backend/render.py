"""ORM -> engine views; page HTML (shared by the Pages screen and the PDF); the lock gate; artifacts; export."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from engine import typography as T
from engine.canvases import CANVASES, ensure_textures
from engine.comic import manuscript as MS
from engine.comic import layout as L
from engine.comic.enhance import upscale
from engine.comic.proof import compress_pdf

from . import db
from .models import Candidate, Canvas, Chapter, Character, Page, Panel, Silhouette, Volume

VOLUME_TITLES_HI = {1: "पहली पुस्तक", 2: "दूसरी पुस्तक", 3: "तीसरी पुस्तक"}


# ---------------------------------------------------------------------------------
# canvases
# ---------------------------------------------------------------------------------


def ensure_canvases(session: Session) -> None:
    """The eight canvases exist as rows and as texture PNGs under data/canvases/."""
    paths = ensure_textures(db.DATA_DIR / "canvases")
    existing = {c.key: c for c in session.scalars(select(Canvas)).all()}
    for spec in CANVASES:
        c = existing.get(spec["key"])
        if c is None:
            c = Canvas(key=spec["key"], name=spec["name"])
            session.add(c)
        c.name = spec["name"]
        c.paper_texture = db.rel(paths[spec["key"]])
        c.ink = spec["ink"]
        c.gutter = spec["gutter"]
        c.caption_style = spec["caption_style"]
        c.marginalia_style = spec["marginalia_style"]
        c.preview = db.rel(paths[spec["key"]])
    session.flush()


def canvas_view(c: Canvas | None) -> L.CanvasView:
    if c is None:
        return L.CanvasView()
    spec = next((x for x in CANVASES if x["key"] == c.key), {})
    return L.CanvasView(key=c.key, name=c.name, paper_texture=db.abs_path(c.paper_texture), texture_url=db.media_url(c.paper_texture), ink=c.ink, gutter=c.gutter,
                        caption_style=c.caption_style or {}, marginalia_style=c.marginalia_style or {}, finish=spec.get("finish", ""))


def canvas_by_key(session: Session, key: str | None) -> Canvas | None:
    return session.scalar(select(Canvas).where(Canvas.key == key)) if key else None


def canvas_for_page(session: Session, page: Page, override_key: str | None = None) -> Canvas | None:
    if override_key:
        c = canvas_by_key(session, override_key)
        if c:
            return c
    if page.canvas_override:
        c = session.get(Canvas, page.canvas_override)
        if c:
            return c
    vol = page.chapter.volume
    if vol.canvas_id:
        return session.get(Canvas, vol.canvas_id)
    return session.scalar(select(Canvas).where(Canvas.key == "parchment"))


# ---------------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------------


def candidate_path(session: Session, panel: Panel, prefer_enhanced: bool = False) -> tuple[Path | None, str | None]:
    """The selected candidate's file (absolute path, media URL); enhanced copy when asked and present."""
    if not panel.selected_candidate_id:
        return None, None
    c = session.get(Candidate, panel.selected_candidate_id)
    if c is None:
        return None, None
    if prefer_enhanced:
        enh = db.DATA_DIR / "enhanced" / f"{c.id}.png"
        if enh.exists():
            return enh, db.media_url(db.rel(enh))
    return db.abs_path(c.path), db.media_url(c.path)


def panel_view(session: Session, panel: Panel, prefer_enhanced: bool = False) -> L.PanelView:
    path, url = candidate_path(session, panel, prefer_enhanced)
    return L.PanelView(
        number=panel.page.number * 100 + panel.n, n=panel.n, kind=panel.kind, shape=panel.shape or {}, image_group=panel.image_group,
        text_state=panel.state, scale=panel.scale, beat=panel.beat, weight=panel.weight or 1.0,
        caption_en=panel.caption_en or "", caption_hi=panel.caption_hi or "", balloon_en=panel.balloon_en or "", balloon_hi=panel.balloon_hi or "",
        speaker=panel.speaker, image_path=path, image_url=url, characters=list(panel.characters or []),
        sfx=panel.sfx or "", text_colours=panel.text_colours or None, callout_shape=panel.callout_shape, balloon_shape=panel.balloon_shape,
    )


def title_block(page: Page) -> L.TitleBlock:
    ch = page.chapter
    vol = ch.volume
    proj = vol.project
    return L.TitleBlock(
        book_title=proj.title or "The Cycle of Dharma", volume_title=vol.title or f"Book {vol.number}",
        volume_title_hi=VOLUME_TITLES_HI.get(vol.number, ""), chapter_title=ch.title or "", chapter_number=ch.number,
        epigraph=page.epigraph or "", epigraph_hi=page.epigraph_hi or (page.epigraph or ""),
    )


def marginalia_views(session: Session, page: Page) -> list[L.MarginaliaView]:
    out = []
    for m in page.marginalia or []:
        sid = m.get("silhouette_id")
        s = session.get(Silhouette, sid) if sid else None
        if s is None:
            continue
        out.append(L.MarginaliaView(path=db.abs_path(s.path), url=db.media_url(s.path), x_mm=float(m.get("x_mm", 0)), y_mm=float(m.get("y_mm", 0)), w_mm=float(m.get("w_mm", 30)), h_mm=m.get("h_mm"), rotation=float(m.get("rotation", 0)), opacity=float(m.get("opacity", 0.85)), tint=m.get("tint")))
    return out


def volume_typography(vol: Volume | None) -> dict[str, Any]:
    """The volume's stored setting, completed with the defaults (what GET /api/volumes/{id}/typography returns)."""
    return T.merge((vol.typography if vol else None) or {})


def ensure_typography(session: Session) -> None:
    """Volume 1 starts on the default type (Illuminated manuscript, size L) when it has none stored yet, and moves once
    from the procedural Parchment to the painted parchment (the new default; the author can switch back on Canvas)."""
    from .models import Project

    painted = canvas_by_key(session, "parchment_painted")
    old = canvas_by_key(session, "parchment")
    for v in session.scalars(select(Volume).where(Volume.number == 1)).all():
        if not v.typography:
            v.typography = dict(T.DEFAULT_SETTING)
        proj = session.get(Project, v.project_id)
        flags = dict((proj.settings or {}) if proj else {})
        if painted and not flags.get("painted_default_applied"):
            if v.canvas_id in (None, old.id if old else None):
                v.canvas_id = painted.id
            flags["painted_default_applied"] = True
            if proj:
                proj.settings = flags


DEVOTIONAL = "Devotional"


def ensure_devotional_silhouettes(session: Session) -> int:
    """The manuscript layer's figures also live in the Silhouettes library (tag "Devotional"), keyed and inked."""
    from .models import Project

    proj = session.scalar(select(Project))
    if proj is None:
        return 0
    have = {s.path for s in session.scalars(select(Silhouette)).all()}
    d = db.DATA_DIR / "silhouettes"
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for fid in MS.figure_ids():
        dst = d / f"devotional_{fid}.png"
        if not dst.exists():
            dst.write_bytes(MS.figure_png(fid))
        rel = db.rel(dst)
        if rel not in have:
            tags = [DEVOTIONAL, MS.FIGURE_NAMES.get(fid, fid)] + [t for t in MS.FIGURE_TAGS.get(fid, ()) if t != "any"][:3]
            session.add(Silhouette(project_id=proj.id, path=rel, tags=tags, source="uploaded", prompt=f"devotional figure: {fid}"))
            n += 1
    return n


def page_tags(page: Page) -> set[str]:
    """What chooses a page's verses and figures: its cast (panels + the book's chapter cast), states, beat, era, opener."""
    tags: set[str] = set()
    for p in page.panels:
        for k in p.characters or []:
            tags.add(k.split("/")[0].lower())
        if p.state:
            tags.add(p.state)
        if p.beat:
            tags.add(p.beat)
    if page.beat:
        tags.add(page.beat)
    ch = page.chapter
    vol = ch.volume
    if vol.era_default:
        tags.add(vol.era_default.lower())
    if page.is_opener:
        tags |= {"opener", "dharma"}
    try:
        from . import book_seed

        for e in book_seed.entry_for_chapter(ch):
            for c in e.get("cast") or []:
                tags.add(str(c.get("name", "")).split()[0].lower())
            for sset in e.get("scene_settings") or []:
                if sset.get("era"):
                    tags.add(str(sset["era"]).lower())
    except Exception:  # noqa: BLE001 - the book is optional (not in the public repo)
        pass
    return {t for t in tags if t}


def manuscript_spec(page: Page, ty: T.TypeSpec) -> MS.Spec:
    m = ty.manuscript or {}
    return MS.Spec(density=m.get("density", "light"), font=m.get("font", "tiro-devanagari-hindi"), opacity=float(m.get("opacity", 0.34)), rubric=bool(m.get("rubric", True)),
                   stored=dict(page.manuscript or {}), tags=page_tags(page))


def page_typography(page: Page) -> T.TypeSpec:
    return T.resolve(page.chapter.volume.typography or {}, page.typography_override or {})


def page_view(session: Session, page: Page, prefer_enhanced: bool = False) -> L.PageView:
    ty = page_typography(page)
    return L.PageView(number=page.number, panels=[panel_view(session, p, prefer_enhanced) for p in page.panels], beat=page.beat, is_opener=page.is_opener, title=title_block(page) if page.is_opener else None,
                      marginalia=marginalia_views(session, page), seed=page.seed or 7, typography=ty, ink_dissolve=page.ink_dissolve, manuscript=manuscript_spec(page, ty))


# ---------------------------------------------------------------------------------
# shapes
# ---------------------------------------------------------------------------------


def ensure_shapes(session: Session, page: Page, force: bool = False) -> int:
    """Auto-cut the page; keep author-edited (locked_shape) shards. Returns how many shapes changed."""
    views = [panel_view(session, p) for p in page.panels]
    shapes = L.auto_cut(views, page.seed or 7, page.number, page.beat, page.is_opener)
    n = 0
    for p in page.panels:
        if p.locked_shape and not force:
            continue
        if p.shape and p.shape.get("polygon_mm") and not force:
            continue
        s = shapes.get(page.number * 100 + p.n)
        if s:
            p.shape = s
            n += 1
    return n


def recut(session: Session, page: Page) -> int:
    """Re-cut: new shapes for every shard that is not locked (a fresh seed so the cut changes)."""
    page.seed = (page.seed or 7) + 1
    views = [panel_view(session, p) for p in page.panels]
    shapes = L.auto_cut(views, page.seed, page.number, page.beat, page.is_opener)
    n = 0
    for p in page.panels:
        if p.locked_shape:
            continue
        s = shapes.get(page.number * 100 + p.n)
        if s:
            p.shape = s
            n += 1
    return n


# ---------------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------------


def unlocked_names(session: Session, form_keys: list[str]) -> list[str]:
    """Characters named on a panel that are not locked (a form key with no Character row counts as unlocked)."""
    out: list[str] = []
    for key in form_keys or []:
        c = session.scalar(select(Character).where(Character.form_key == key))
        name = c.name if c else key
        if c is None or not c.locked:
            label = name if (c is None or c.form_key == name.lower()) else f"{name} ({c.form_key})"
            if label not in out:
                out.append(label)
    return out


def panel_gate(session: Session, panel: Panel) -> list[str]:
    return unlocked_names(session, list(panel.characters or []))


def page_gate(session: Session, page: Page) -> list[str]:
    keys: list[str] = []
    for p in page.panels:
        for k in p.characters or []:
            if k not in keys:
                keys.append(k)
    return unlocked_names(session, keys)


# ---------------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------------


def page_html(session: Session, page: Page, lang: str = "en", paper: str = "screen", embed: bool = False, prefer_enhanced: bool = False, canvas_key: str | None = None,
              faces: set | None = None, print_texture: bool = False, items: list | None = None) -> str:
    """One page's <section>. Adds the faces it uses to `faces` (for the document's @font-face rules) and the manuscript
    layer's placements to `items`."""
    ensure_shapes(session, page)
    opts = L.RenderOptions(lang=lang, paper=paper, embed=embed, print_texture=print_texture)
    cv = canvas_view(canvas_for_page(session, page, canvas_key))
    view = page_view(session, page, prefer_enhanced)
    out = L.page_html(view, cv, opts)
    if faces is not None:
        faces |= T.faces_of(L.used_fonts(view, lang))
    if items is not None:
        items.extend(view.manuscript_items)
    return out


def manuscript_state(session: Session, page: Page) -> dict[str, Any]:
    """The layer as placed (auto or by hand), for the Pages screen's outlines."""
    items: list = []
    page_html(session, page, items=items)
    ty = page_typography(page)
    return {"auto": (page.manuscript or {}).get("auto", True) is not False, "density": ty.manuscript.get("density"), "font": ty.manuscript.get("font"),
            "verses": [i.json() for i in items if i.kind == "verse"], "figures": [i.json() for i in items if i.kind == "figure"], "tags": sorted(page_tags(page))}


def page_document(session: Session, page: Page, lang: str = "en", paper: str = "screen", embed: bool = False, prefer_enhanced: bool = False, canvas_key: str | None = None,
                  print_texture: bool = False) -> str:
    """A standalone HTML document for one page (the live render and the stored artifact)."""
    opts = L.RenderOptions(lang=lang, paper=paper, embed=embed, print_texture=print_texture)
    faces: set = set()
    body = page_html(session, page, lang, paper, embed, prefer_enhanced, canvas_key, faces, print_texture)
    return L.book_html([body], f"{page.chapter.volume.project.title} · p{page.number} · {lang}", opts, faces)


def page_manifest(session: Session, page: Page) -> dict[str, Any]:
    ensure_shapes(session, page)
    return L.layout_manifest(page_view(session, page))


def balance(session: Session, page: Page) -> dict[str, Any]:
    ensure_shapes(session, page)
    return L.balance_of(page_view(session, page))


# ---------------------------------------------------------------------------------
# artifacts (written on approve) and export
# ---------------------------------------------------------------------------------


def artifact_dir(page: Page) -> Path:
    ch = page.chapter
    return db.DATA_DIR / "artifacts" / f"vol{ch.volume.number}" / f"ch{ch.number}"


def write_artifacts(session: Session, page: Page) -> dict[str, str]:
    """Self-contained HTML per language (fonts, images and the canvas texture embedded) at
    data/artifacts/vol{V}/ch{C}/page-{NNN}-{lang}.html; the paths go into Page.artifacts."""
    d = artifact_dir(page)
    d.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    for lang in ("en", "hi"):
        p = d / f"page-{page.number:03d}-{lang}.html"
        p.write_text(page_document(session, page, lang=lang, paper="screen", embed=True), encoding="utf-8")
        out[lang] = db.rel(p)
    out["written_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    page.artifacts = out
    return out


def export_pages(session: Session, chapter_id: int | None, volume_id: int | None) -> list[Page]:
    if chapter_id:
        ch = session.get(Chapter, chapter_id)
        return list(ch.pages) if ch else []
    if volume_id:
        vol = session.get(Volume, volume_id)
        return [p for ch in (vol.chapters if vol else []) for p in ch.pages]
    return []


def export_name(session: Session, chapter_id: int | None, volume_id: int | None) -> str:
    if chapter_id:
        ch = session.get(Chapter, chapter_id)
        return f"vol{ch.volume.number}-ch{ch.number}" if ch else f"ch{chapter_id}"
    vol = session.get(Volume, volume_id) if volume_id else None
    return f"vol{vol.number}" if vol else "export"


def build_export(session: Session, pages: list[Page], lang: str, paper: str, upscale_images: bool, name: str, log=print, print_texture: bool = False) -> dict[str, Any]:  # noqa: ANN001
    """Assemble approved pages in order into a PDF (EN or HI), optional Topaz upscale of the selected images,
    compress. Returns {pdf, html, pages, cost_usd}."""
    out_dir = db.DATA_DIR / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    cost = 0.0
    if upscale_images:
        for pg in pages:
            for p in pg.panels:
                if not p.selected_candidate_id:
                    continue
                c = session.get(Candidate, p.selected_candidate_id)
                if c is None:
                    continue
                src = db.abs_path(c.path)
                dst = db.DATA_DIR / "enhanced" / f"{c.id}.png"
                if src and src.exists() and not dst.exists():
                    r = upscale(src, dst)
                    cost += float(r.get("cost_usd") or 0.0)
                    log(f"upscale p{pg.number}.{p.n}: {r['tool']} x{r['factor']}")
    opts = L.RenderOptions(lang=lang, paper=paper, embed=True, print_texture=print_texture)
    faces: set = set()
    htmls = [page_html(session, pg, lang=lang, paper=paper, embed=True, prefer_enhanced=upscale_images, faces=faces, print_texture=print_texture) for pg in pages]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = f"{name}-{lang}" + ("-print" if paper == "print" else "") + f"-{stamp}"
    pdf = out_dir / f"{base}.pdf"
    _last = {"pct": -1}

    def _engine_progress(frac: float, msg: str) -> None:  # first export on a Mac without Chrome fetches the PDF engine
        pct = int(frac * 10)
        if pct != _last["pct"]:
            _last["pct"] = pct
            log(msg)

    L.render_pdf(L.book_html(htmls, f"The Cycle of Dharma · {base}", opts, faces), pdf, progress=_engine_progress)
    try:
        compress_pdf(pdf)
    except Exception as exc:  # noqa: BLE001
        log(f"compress skipped: {exc}")
    manifest = [page_manifest(session, pg) for pg in pages]
    (out_dir / f"{base}.layout.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    meta = {"name": base, "pdf": db.rel(pdf), "html": db.rel(pdf.with_suffix(".html")), "manifest": db.rel(out_dir / f"{base}.layout.json"), "lang": lang, "paper": paper, "pages": [pg.number for pg in pages], "upscale": upscale_images, "cost_usd": round(cost, 4), "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out_dir / f"{base}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def export_record(job: Any) -> dict[str, Any]:
    """An export Job as a history record: scope, languages, paper, files (name, url, bytes), cost, status."""
    p = job.params or {}
    files = []
    for meta in (job.result or {}).get("exports", []) or []:
        pdf = db.abs_path(meta.get("pdf"))
        files.append({"name": Path(meta["pdf"]).name, "url": db.media_url(meta["pdf"]), "bytes": pdf.stat().st_size if pdf and pdf.exists() else 0, "lang": meta.get("lang"), "pages": meta.get("pages")})
    return {"id": job.id, "job_id": job.id, "created_at": job.created_at.isoformat() if job.created_at else None, "scope": p.get("scope") or ("chapter" if p.get("chapter_id") else "volume"),
            "lang": p.get("lang") or ["en"], "paper": p.get("paper", "print"), "upscale": bool(p.get("upscale")), "files": files, "cost_usd": job.cost_usd or 0.0, "status": job.status}


def copy_into(src: Path, sub: str, name: str) -> Path:
    d = db.DATA_DIR / sub
    d.mkdir(parents=True, exist_ok=True)
    dst = d / name
    shutil.copy2(src, dst)
    return dst
