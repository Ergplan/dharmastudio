"""Background worker (one thread, a queue): generate / generate_all / refs / silhouettes / prefill / hindi /
propose_cast / export / batch. Job rows carry status, log, cost, progress and a cooperative stop flag; the UI polls."""

from __future__ import annotations

import queue
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from engine import agents, llm, providers
from engine.comic.script import STATES, scale_of

from . import db, gen, render
from .models import Chapter, Character, Job, Page, Panel, Project

_queue: "queue.Queue[int]" = queue.Queue()
_thread: threading.Thread | None = None
_lock = threading.Lock()


class Stopped(Exception):
    pass


class Ctx:
    """What a handler gets: the session, the job row, a logger and a stop check."""

    def __init__(self, session: Session, job: Job) -> None:
        self.session, self.job = session, job
        self.cost = 0.0

    def log(self, msg: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.job.log = (self.job.log or "") + f"[{stamp}] {msg}\n"
        self.session.commit()

    def progress(self, **kw: Any) -> None:
        self.job.progress = {**(self.job.progress or {}), **kw, "cost_so_far": round(self.cost, 4)}
        self.session.commit()

    def check_stop(self) -> None:
        self.session.refresh(self.job, attribute_names=["stop"])
        if self.job.stop:
            raise Stopped()

    def add_cost(self, usd: float) -> None:
        self.cost += float(usd or 0.0)
        self.job.cost_usd = round(self.cost, 4)


def sync_models(session: Session) -> None:
    proj = session.scalar(select(Project))
    llm.set_selected(((proj.settings or {}).get("models") or {}) if proj else {})


# ---------------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------------


def _generate_panel(ctx: Ctx, panel: Panel, provider: str, n: int, feedback: str = "") -> list:
    cands = []
    for i in range(max(1, n)):
        ctx.check_stop()
        c = gen.generate_candidate(ctx.session, panel, provider, feedback, i)
        ctx.add_cost(c.cost_usd)
        ctx.session.commit()
        ctx.log(f"p{panel.page.number}.{panel.n}: candidate {c.id} ({c.provider}{', dry-run' if c.qa.get('dry_run') else ''}) ${c.cost_usd:.4f}")
        cands.append(c)
    return cands


def h_generate(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any]:
    panel = ctx.session.get(Panel, ctx.job.ref_id)
    if panel is None:
        raise ValueError("panel not found")
    unlocked = render.panel_gate(ctx.session, panel)
    if unlocked:
        raise ValueError(f"gate: unlocked characters {unlocked}")
    page = panel.page
    if page.status == "approved":
        raise ValueError("page is approved; un-approve to regenerate")
    prev = page.status
    page.status = "generating"
    ctx.session.commit()
    ctx.progress(page=page.number, panel=panel.n, done=0, total=int(p.get("n", 2)))
    try:
        cands = _generate_panel(ctx, panel, p.get("provider", "sunburst"), int(p.get("n", 2)), p.get("feedback") or "")
    finally:
        page.status = "review" if (prev in ("empty", "draft", "generating") or prev == "review") else prev
        ctx.session.commit()
    ctx.progress(done=len(cands), total=len(cands))
    return {"candidate_ids": [c.id for c in cands], "page_id": page.id}


def h_generate_all(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any]:
    page = ctx.session.get(Page, ctx.job.ref_id)
    if page is None:
        raise ValueError("page not found")
    unlocked = render.page_gate(ctx.session, page)
    if unlocked:
        raise ValueError(f"gate: unlocked characters {unlocked}")
    if page.status == "approved":
        raise ValueError("page is approved; un-approve to regenerate")
    page.status = "generating"
    ctx.session.commit()
    targets = [x for x in page.panels if (p.get("all") or not x.selected_candidate_id)]
    ids = []
    try:
        for i, panel in enumerate(targets):
            ctx.progress(page=page.number, panel=panel.n, done=i, total=len(targets))
            ids += [c.id for c in _generate_panel(ctx, panel, p.get("provider", "sunburst"), int(p.get("n", 2)))]
    finally:
        page.status = "review"
        ctx.session.commit()
    ctx.progress(done=len(targets), total=len(targets))
    return {"candidate_ids": ids}


def h_refs(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any]:
    c = ctx.session.get(Character, ctx.job.ref_id)
    if c is None:
        raise ValueError("character not found")
    ids = []
    n = int(p.get("n", 2))
    for i in range(n):
        ctx.check_stop()
        r = gen.generate_character_ref(ctx.session, c, p.get("provider", "sunburst"), i)
        ctx.session.commit()
        ctx.log(f"{c.name}: reference {r.id}")
        ids.append(r.id)
        ctx.progress(done=i + 1, total=n)
    return {"ref_ids": ids}


def h_silhouettes(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any]:
    proj = ctx.session.scalar(select(Project))
    ids = []
    n = int(p.get("n", 1))
    for i in range(n):
        ctx.check_stop()
        s = gen.generate_silhouette(ctx.session, proj.id, p.get("prompt", ""), i, tags=p.get("tags") or None)
        ctx.session.commit()
        ctx.log(f"silhouette {s.id}: {', '.join(s.tags)}")
        ids.append(s.id)
        ctx.progress(done=i + 1, total=n)
    return {"silhouette_ids": ids}


def prefill_chapter(session: Session, chapter: Chapter, log: Callable[[str], None] = print, only_pages: list[int] | None = None) -> list[Page]:
    """The script_writer breaks the chapter text into pages/panels (captions verbatim); shapes by the auto-cut.
    Existing pages with panels are kept; only_pages limits creation to those numbers."""
    from engine.canvases import CANVASES  # noqa: F401  (textures exist by startup)

    envs = []
    try:
        import yaml

        from engine.settings import REPO_ROOT

        envs = [e["name"] for e in yaml.safe_load((REPO_ROOT / "engine" / "environments.yaml").read_text(encoding="utf-8"))["environments"]]
    except Exception:  # noqa: BLE001
        pass
    forms = [c.form_key for c in session.scalars(select(Character)).all()]
    existing = {pg.number: pg for pg in chapter.pages}
    first = chapter.pages_from or (min(existing) if existing else 1)
    want = None
    if chapter.pages_from and chapter.pages_to:
        want = chapter.pages_to - chapter.pages_from + 1
    data = agents.panel_script(chapter.title, chapter.text or "", first, want, envs, forms, chapter.volume.era_default or "treta")
    created: list[Page] = []
    for pg in data.get("pages", []) or []:
        num = int(pg.get("page", 0) or 0)
        if not num or (only_pages and num not in only_pages):
            continue
        page = existing.get(num)
        if page is None:
            page = Page(chapter_id=chapter.id, number=num, status="draft", seed=7)
            session.add(page)
            session.flush()
            existing[num] = page
        elif page.panels:
            continue  # the author's pages are never overwritten
        for i, pp in enumerate(pg.get("panels", []) or []):
            scene = pp.get("image") or pp.get("scene") or ""
            panel = Panel(
                page_id=page.id, n=int(pp.get("n") or i + 1), kind=pp.get("kind") if pp.get("kind") in ("shard", "plate") else "shard",
                scene=scene, scale=scale_of(scene, pp.get("scale")), state=pp.get("state") if pp.get("state") in STATES else "quiet",
                beat=pp.get("beat"), weight=float(pp.get("weight") or 1.0), characters=list(pp.get("characters") or []), environment=pp.get("environment"),
                source_page=str(pp.get("source_page") or ""), caption_en=pp.get("caption_en") or "", balloon_en=pp.get("balloon_en") or "",
                speaker=pp.get("speaker"), image_group=pp.get("image_group"), shape={},
            )
            session.add(panel)
        session.flush()
        session.expire(page, ["panels"])
        page.status = "draft" if page.panels else "empty"
        render.ensure_shapes(session, page, force=True)
        created.append(page)
        log(f"page {num}: {len(page.panels)} panels")
    session.commit()
    session.expire(chapter, ["pages"])
    return created


def h_prefill(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any]:
    ch = ctx.session.get(Chapter, ctx.job.ref_id)
    if ch is None:
        raise ValueError("chapter not found")
    pages = prefill_chapter(ctx.session, ch, ctx.log)
    if p.get("hindi", True):
        n = draft_hindi(ctx.session, ch, ctx.log)
        ctx.log(f"hindi drafts: {n}")
    return {"page_ids": [pg.id for pg in pages]}


def draft_hindi(session: Session, chapter: Chapter, log: Callable[[str], None] = print) -> int:
    panels = [p for pg in chapter.pages for p in pg.panels if (p.caption_en or p.balloon_en) and (p.hi_is_draft or not (p.caption_hi or p.balloon_hi))]
    if not panels:
        return 0
    data = agents.hindi_draft([{"id": p.id, "caption_en": p.caption_en, "balloon_en": p.balloon_en, "speaker": p.speaker} for p in panels])
    by_id = {int(it["id"]): it for it in (data.get("items") or []) if isinstance(it, dict) and "id" in it}
    n = 0
    for p in panels:
        it = by_id.get(p.id)
        if not it or not (it.get("caption_hi") or it.get("balloon_hi")):
            continue
        p.caption_hi = it.get("caption_hi") or p.caption_hi
        p.balloon_hi = it.get("balloon_hi") or p.balloon_hi
        p.hi_is_draft = True
        n += 1
    session.commit()
    return n


def h_hindi(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any]:
    ch = ctx.session.get(Chapter, ctx.job.ref_id)
    if ch is None:
        raise ValueError("chapter not found")
    return {"drafted": draft_hindi(ctx.session, ch, ctx.log)}


def h_propose_cast(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any]:
    proj = ctx.session.scalar(select(Project))
    chapters = ctx.session.scalars(select(Chapter).order_by(Chapter.volume_id, Chapter.number)).all()
    ch1 = next((c for c in chapters if c.number == 1), chapters[0] if chapters else None)
    manuscript = "\n\n".join(c.text or "" for c in chapters)
    data = agents.cast_proposal(manuscript, ch1.text if ch1 else "")
    existing = {c.form_key: c for c in ctx.session.scalars(select(Character)).all()}
    ids = []
    for item in data.get("characters", []) or []:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        forms = item.get("forms") or [{"form_key": name.lower().replace(" ", "-"), "look": item.get("look", "")}]
        for f in forms:
            key = (f.get("form_key") or name.lower()).strip().lower().replace(" ", "-")
            if key in existing:
                c = existing[key]
                if not c.look and f.get("look"):
                    c.look = f["look"]
                continue
            c = Character(project_id=proj.id, name=name, form_key=key, look=f.get("look") or "", locked=False)
            ctx.session.add(c)
            ctx.session.flush()
            existing[key] = c
            ids.append(c.id)
            ctx.log(f"cast: {name} ({key})")
    ctx.session.commit()
    return {"character_ids": ids}


def h_export(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any]:
    pages = render.export_pages(ctx.session, p.get("chapter_id"), p.get("volume_id"))
    approved = [pg for pg in pages if pg.status == "approved"]
    if not approved:
        raise ValueError("no approved pages to export")
    name = render.export_name(ctx.session, p.get("chapter_id"), p.get("volume_id"))
    langs = p.get("lang") or ["en"]
    if isinstance(langs, str):
        langs = [langs]
    outs = []
    for lang in langs:
        ctx.check_stop()
        ctx.log(f"export {name} {lang} paper={p.get('paper', 'screen')} pages={[pg.number for pg in approved]}")
        meta = render.build_export(ctx.session, approved, lang, p.get("paper", "screen"), bool(p.get("upscale")), name, ctx.log, print_texture=bool(p.get("print_texture")))
        ctx.add_cost(meta.get("cost_usd", 0.0))
        ctx.session.commit()
        ctx.log(f"pdf: {meta['pdf']}")
        outs.append(meta)
    if p.get("paper") == "print":  # printed QR codes: their short links are locked for ever
        from . import links

        locked = links.lock_for_pages(ctx.session, [pg.id for pg in approved])
        ctx.session.commit()
        if locked:
            ctx.log(f"print-locked links: {', '.join(locked)}")
    return {"exports": outs, "pdf": outs[0]["pdf"] if outs else None, "url": db.media_url(outs[0]["pdf"]) if outs else None}


def batch_pages(session: Session, chapter: Chapter, spec: Any) -> list[int]:
    """pages: [1,2,3] | {"next": 5} (the next N pages that are not approved, in order)."""
    if isinstance(spec, dict) and spec.get("next"):
        nums = [pg.number for pg in chapter.pages if pg.status != "approved"]
        if not nums:
            start = (chapter.pages[-1].number + 1) if chapter.pages else (chapter.pages_from or 1)
            nums = list(range(start, start + int(spec["next"])))
        return nums[: int(spec["next"])]
    if isinstance(spec, list):
        return [int(x) for x in spec]
    return [pg.number for pg in chapter.pages]


def h_batch(ctx: Ctx, p: dict[str, Any]) -> dict[str, Any]:
    ch = ctx.session.get(Chapter, int(p["chapter_id"]))
    if ch is None:
        raise ValueError("chapter not found")
    nums = batch_pages(ctx.session, ch, p.get("pages"))
    n_per = int(p.get("candidates_per_panel", 2))
    provider = providers.normalise_provider(p.get("provider") or llm.model_for("image"))
    total_panels = 0
    done_pages, skipped = [], []
    ctx.progress(page=None, panel=None, done=0, total=len(nums), pages=nums)
    for i, num in enumerate(nums):
        ctx.check_stop()
        page = next((pg for pg in ch.pages if pg.number == num), None)
        if page is None or not page.panels:
            if p.get("prefill_text", True):
                ctx.log(f"page {num}: no panels, prefilling from the chapter text")
                prefill_chapter(ctx.session, ch, ctx.log, only_pages=[num])
                ctx.session.refresh(ch)
                page = next((pg for pg in ch.pages if pg.number == num), None)
            if page is None or not page.panels:
                skipped.append({"page": num, "reason": "no panels"})
                ctx.log(f"page {num}: skipped (no panels)")
                continue
        unlocked = render.page_gate(ctx.session, page)
        if unlocked:
            skipped.append({"page": num, "reason": f"unlocked: {', '.join(unlocked)}"})
            ctx.log(f"page {num}: skipped, unlocked characters: {', '.join(unlocked)}")
            continue
        if page.status == "approved":
            skipped.append({"page": num, "reason": "approved"})
            ctx.log(f"page {num}: skipped (approved)")
            continue
        page.status = "generating"
        ctx.session.commit()
        try:
            for panel in gen.page_has_unselected(page):
                ctx.progress(page=num, panel=panel.n, done=i, total=len(nums))
                cands = _generate_panel(ctx, panel, provider, n_per)
                total_panels += 1
                if p.get("run_critic", True) and cands:
                    chosen = gen.run_critic(ctx.session, panel, cands)
                    ctx.session.commit()
                    ctx.log(f"p{num}.{panel.n}: critic pre-selected candidate {chosen}")
        except Stopped:
            page.status = "review" if any(x.selected_candidate_id for x in page.panels) else "draft"
            ctx.session.commit()
            raise
        page.status = "review"
        ctx.session.commit()
        done_pages.append(num)
        ctx.progress(page=num, panel=None, done=i + 1, total=len(nums))
        ctx.log(f"page {num}: review")
    return {"pages_done": done_pages, "skipped": skipped, "panels": total_panels}


HANDLERS: dict[str, Callable[[Ctx, dict[str, Any]], dict[str, Any]]] = {
    # kinds match the frontend's JobKind: panel | page | refs | silhouettes | prefill | hindi | propose | export | batch
    # (manuscript jobs are recorded already done by the upload route)
    "panel": h_generate, "page": h_generate_all, "refs": h_refs, "silhouettes": h_silhouettes,
    "prefill": h_prefill, "hindi": h_hindi, "propose": h_propose_cast, "export": h_export, "batch": h_batch,
}


# ---------------------------------------------------------------------------------
# worker
# ---------------------------------------------------------------------------------


def run_job(job_id: int) -> None:
    with db.session_scope() as session:
        job = session.get(Job, job_id)
        if job is None or job.status not in ("queued",):
            return
        sync_models(session)
        job.status = "running"
        session.commit()
        ctx = Ctx(session, job)
        try:
            ctx.log(f"start {job.kind}")
            result = HANDLERS[job.kind](ctx, dict(job.params or {}))
            job.result = result or {}
            job.status = "done"
            ctx.log("done")
        except Stopped:
            job.status = "stopped"
            ctx.log("stopped by the author")
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            job = session.get(Job, job_id)
            job.status = "failed"
            job.log = (job.log or "") + f"error: {exc}\n{traceback.format_exc()}\n"
        job.cost_usd = round(ctx.cost, 4)
        session.commit()


def _loop() -> None:
    while True:
        job_id = _queue.get()
        try:
            run_job(job_id)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        finally:
            _queue.task_done()


def start_worker() -> None:
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_loop, name="dharma-worker", daemon=True)
            _thread.start()


def submit(session: Session, kind: str, ref_id: int | None, params: dict[str, Any]) -> Job:
    job = Job(kind=kind, ref_id=ref_id, status="queued", params=params, progress={}, result={})
    session.add(job)
    session.commit()
    start_worker()
    _queue.put(job.id)
    return job


def run_inline(session: Session, kind: str, ref_id: int | None, params: dict[str, Any]) -> Job:
    """Run a job synchronously in the caller's thread (tests, seed)."""
    job = Job(kind=kind, ref_id=ref_id, status="queued", params=params, progress={}, result={})
    session.add(job)
    session.commit()
    run_job(job.id)
    session.expire_all()
    return session.get(Job, job.id)


def wait_idle(timeout: float = 600) -> None:
    import time

    t0 = time.time()
    while not _queue.empty() and time.time() - t0 < timeout:
        time.sleep(0.1)
    _queue.join()
