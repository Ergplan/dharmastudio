"""The Art Director inside the studio: chapters by manuscript number, brief checks against the database (the studio's
lock gate), the run record, and the worker jobs `art_director` (one page, or the next N pages of a chapter) and
`art_cover` (paint a volume's poster art). The thinking lives in engine/director/; this module touches the DB.

A run, step by step (each step appended to DirectorRun.steps and the job log):
  check  -> the brief's deterministic validation (verbatim lines, character keys, locked characters)
  plan   -> the script_writer's page plan (3-5 panels with hierarchy, callouts verbatim) or the deterministic fallback
  layout -> panels written to the page, shapes from the auto-cut by hierarchy weight
  prompt -> per panel: condensed master prompt + locked looks + brief + shot (linted: no text, full negative list)
  paint  -> N candidates per panel with the image model (locked references attached)
  critic -> deterministic checks + the critic's 10-point test per candidate
  revise -> up to `retries` repaints with the critic's fix_prompt; the best is pre-selected; failures are flagged
  assemble -> callouts set from the plan, page status "review" (never approved by the agent)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from engine import llm, providers
from engine.comic.script import look_paragraph
from engine.director import agent as A
from engine.director import chapters as CH
from engine.director import cover as CV
from engine.director import guardrails as G
from engine.director.brief import CharacterInfo, Line, SceneBrief, validate

from . import db, gen, jobs, render
from .director_models import DirectorCover, DirectorRun
from .models import Candidate, Chapter, Character, CharacterRef, Page, Panel, Volume

DEFAULTS = {"candidates": 2, "retries": 2, "budget_usd": 3.0, "run_critic": True, "provider": None}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------------------------------------------
# chapters (keyed by manuscript number)
# ---------------------------------------------------------------------------------------------------------------


def manuscript_of(ch: Chapter) -> CH.ManuscriptChapter:
    vol = ch.volume
    return CH.resolve(vol.number, ch.number, ch.title, ch.pages_from, ch.pages_to, ch.text or "")


def chapter_age(ch: Chapter, mc: CH.ManuscriptChapter | None = None) -> dict[str, str]:
    mc = mc or manuscript_of(ch)
    return CH.age_for(mc, None)


def chapter_summary(session: Session, ch: Chapter) -> dict[str, Any]:
    mc = manuscript_of(ch)
    age = chapter_age(ch, mc)
    a = G.load().ages[age["age"]]
    statuses = [p.status for p in ch.pages]
    return {"id": ch.id, "volume": ch.volume.number, "studio_number": ch.number, "manuscript_number": mc.manuscript_number, "kind": mc.kind,
            "title": mc.title, "label": mc.label, "age": age["age"], "age_source": age["source"], "era": age["era"], "age_name": a.name,
            "palette": a.palette, "has_text": bool((mc.text or "").strip()), "from_book": mc.from_book, "pages": len(statuses),
            "review": statuses.count("review"), "approved": statuses.count("approved")}


def chapters_grouped(session: Session) -> dict[str, Any]:
    vols = session.scalars(select(Volume).order_by(Volume.number)).all()
    out = []
    for v in vols:
        lo, hi = CH.volume_range(v.number)
        title = CH.book_title(v.number, v.title or "")
        chs = sorted(v.chapters, key=lambda c: c.number)
        out.append({"volume_id": v.id, "volume": v.number, "book": f"Book {CH.NUMBER_WORDS.get(v.number, v.number).title()}", "title": title,
                    "range": [lo, hi] if lo else None, "chapters": [chapter_summary(session, c) for c in chs]})
    return {"books": out, "has_book": CH.has_book(), "guardrails_sha": G.load().sha256}


def characters_info(session: Session) -> list[CharacterInfo]:
    out = []
    for c in session.scalars(select(Character).order_by(Character.id)).all():
        has_ref = any(r.approved for r in c.refs)
        out.append(CharacterInfo(form_key=c.form_key, name=c.name, locked=bool(c.locked), character_id=c.id, has_reference=has_ref))
    return out


def cast_keys(session: Session, mc: CH.ManuscriptChapter) -> list[dict[str, Any]]:
    """The chapter's cast with the studio form keys for each name (and their lock state)."""
    infos = characters_info(session)
    out = []
    for c in mc.cast:
        keys = [{"key": i.form_key, "locked": i.locked, "character_id": i.character_id} for i in infos if i.name == c["name"]]
        out.append({"name": c["name"], "mentions": c.get("mentions", 0), "keys": keys})
    return out


def first_page_number(ch: Chapter) -> int:
    nums = [p.number for p in ch.pages]
    return min(nums) if nums else (ch.pages_from or 1)


def next_page_number(ch: Chapter) -> int:
    nums = [p.number for p in ch.pages]
    return (max(nums) + 1) if nums else (ch.pages_from or 1)


def chapter_detail(session: Session, ch: Chapter) -> dict[str, Any]:
    mc = manuscript_of(ch)
    s = chapter_summary(session, ch)
    text = mc.text or ""
    return {**s, "manuscript": mc.to_json(), "setting": mc.setting, "paragraphs": [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()],
            "cast": cast_keys(session, mc), "no_manuscript": not text.strip(),
            "pages_list": [{"id": p.id, "number": p.number, "status": p.status, "panels": len(p.panels)} for p in ch.pages],
            "next_page_number": next_page_number(ch), "passages": len(passages(text))}


# ---------------------------------------------------------------------------------------------------------------
# brief
# ---------------------------------------------------------------------------------------------------------------


def check_brief(session: Session, brief: SceneBrief) -> dict[str, Any]:
    ch = session.get(Chapter, brief.chapter_id)
    if ch is None:
        raise ValueError("chapter not found")
    mc = manuscript_of(ch)
    age = chapter_age(ch, mc)
    res = validate(brief, mc.text, characters_info(session), age["age"], mc.label)
    res["chapter_age"] = age
    res["manuscript_number"] = mc.manuscript_number
    if brief.page_id:
        pg = session.get(Page, brief.page_id)
        if pg is not None and pg.status == "approved":
            res["errors"].append("This page is approved (frozen): un-approve it on the Pages screen before directing it again.")
            res["ok"] = res["can_paint"] = False
    return res


def passages(text: str, words_per_page: int = 180) -> list[str]:
    """The chapter split into page-sized passages (paragraph boundaries), in order."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    out, cur, n = [], [], 0
    for p in paras:
        cur.append(p)
        n += len(p.split())
        if n >= words_per_page:
            out.append("\n\n".join(cur))
            cur, n = [], 0
    if cur:
        out.append("\n\n".join(cur))
    return out


def auto_brief(session: Session, ch: Chapter, page_number: int) -> SceneBrief | None:
    """For "Direct next N pages": the next manuscript passage becomes the brief (action = its opening sentences;
    characters = the chapter cast named in it, preferring locked forms; setting from scene settings; no extra lines)."""
    mc = manuscript_of(ch)
    ps = passages(mc.text)
    idx = page_number - first_page_number(ch)
    if idx < 0 or idx >= len(ps):
        return None
    passage = ps[idx]
    sents = A.sentences(passage)
    action = " ".join(re.sub(r"[“”\"]", "", s) for s in sents[:2])[:400]
    infos = characters_info(session)
    keys: list[str] = []
    for c in mc.cast:
        if not re.search(r"\b" + re.escape(c["name"]) + r"\b", passage):
            continue
        forms = [i for i in infos if i.name == c["name"]]
        pick = next((i for i in forms if i.locked), None) or (forms[0] if forms else None)
        if pick and pick.form_key not in keys:
            keys.append(pick.form_key)
    return SceneBrief(chapter_id=ch.id, action=action, characters=keys[:4], setting=mc.setting[:900], lines=[], page_number=page_number)


# ---------------------------------------------------------------------------------------------------------------
# run record
# ---------------------------------------------------------------------------------------------------------------


def j_run(r: DirectorRun, full: bool = True) -> dict[str, Any]:
    base = {"id": r.id, "kind": r.kind, "parent_id": r.parent_id, "status": r.status, "chapter_id": r.chapter_id, "page_id": r.page_id, "page_number": r.page_number,
            "job_id": r.job_id, "manuscript": r.manuscript or {}, "cost_usd": round(r.cost_usd or 0.0, 4), "estimate": r.estimate or {}, "settings": r.settings or {},
            "flags": r.flags or [], "guardrails_sha": r.guardrails_sha, "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None, "brief": r.brief or {}}
    if full:
        base.update(check=r.check or {}, plan=r.plan or {}, prompts=r.prompts or [], candidates=r.candidates or [], steps=r.steps or [])
    else:
        base.update(panels=len((r.plan or {}).get("panels") or []), candidates_n=len(r.candidates or []))
    return base


def _step(session: Session, run: DirectorRun, step: str, msg: str, ctx: Any = None, **data: Any) -> None:
    run.steps = [*(run.steps or []), {"t": utcnow().strftime("%H:%M:%S"), "step": step, "msg": msg, **({"data": data} if data else {})}]
    if ctx is not None:
        ctx.log(f"[director run {run.id}] {step}: {msg}")
    else:
        session.commit()


def image_provider(settings: dict[str, Any]) -> str:
    return providers.normalise_provider(settings.get("provider") or llm.model_for("image"))


def is_dry(provider: str) -> bool:
    return providers.settings.dry_run_sunburst if provider == "sunburst" else providers.settings.dry_run_gemini


def estimate_for(session: Session, brief: SceneBrief, settings: dict[str, Any]) -> dict[str, Any]:
    st = {**DEFAULTS, **{k: v for k, v in settings.items() if v is not None}}
    provider = image_provider(st)
    panels = 1 if brief.full_page else 4
    if brief.page_id:
        pg = session.get(Page, brief.page_id)
        if pg is not None and pg.panels and not brief.full_page:
            panels = max(3, min(5, len(pg.panels)))
    per = 0.0 if is_dry(provider) else providers.estimate_cost_per_image(provider)
    est = A.estimate(panels, int(st["candidates"]), int(st["retries"]), per, bool(st["run_critic"]), llm.is_available("script_writer"), llm.is_available("critic"))
    est.update(provider=provider, dry_run=is_dry(provider), budget_usd=float(st["budget_usd"]), critic_live=llm.is_available("critic"), planner_live=llm.is_available("script_writer"),
               critic_model=llm.model_for("critic"), planner_model=llm.model_for("script_writer"))
    return est


def create_run(session: Session, brief: SceneBrief, settings: dict[str, Any], kind: str = "page", parent_id: int | None = None) -> tuple[DirectorRun, dict[str, Any]]:
    st = {**DEFAULTS, **{k: v for k, v in settings.items() if v is not None}}
    st["provider"] = image_provider(st)
    check = check_brief(session, brief)
    ch = session.get(Chapter, brief.chapter_id)
    mc = manuscript_of(ch)
    run = DirectorRun(kind=kind, parent_id=parent_id, status="queued" if check["can_paint"] else "blocked", chapter_id=ch.id, page_id=brief.page_id, page_number=brief.page_number,
                      manuscript={"label": mc.label, "number": mc.manuscript_number, "title": mc.title, "book": mc.book_title, "volume": mc.volume},
                      brief=brief.to_json(), check=check, settings=st, estimate=estimate_for(session, brief, st), guardrails_sha=G.load().sha256, steps=[], prompts=[], candidates=[], flags=[])
    session.add(run)
    session.flush()
    run.steps = [{"t": utcnow().strftime("%H:%M:%S"), "step": "check", "msg": "brief valid" if check["can_paint"] else "blocked: " + "; ".join(check["errors"])}]
    session.commit()
    return run, check


# ---------------------------------------------------------------------------------------------------------------
# executing a page run
# ---------------------------------------------------------------------------------------------------------------


class BudgetExceeded(Exception):
    pass


def _page_for(session: Session, ch: Chapter, brief: SceneBrief) -> Page:
    if brief.page_id:
        pg = session.get(Page, brief.page_id)
        if pg is None:
            raise ValueError("page not found")
        return pg
    num = brief.page_number or next_page_number(ch)
    pg = next((p for p in ch.pages if p.number == num), None)
    if pg is None:
        pg = Page(chapter_id=ch.id, number=num, status="draft", seed=7, marginalia=[])
        session.add(pg)
        session.flush()
        session.expire(ch, ["pages"])
    return pg


def write_plan(session: Session, page: Page, plan: dict[str, Any]) -> list[Panel]:
    """Panels from the plan (reused by position; extra panels removed); shapes from the auto-cut by hierarchy weight.
    Candidates of reused panels are kept (history); the selection is cleared so the new paint is chosen."""
    existing = sorted(page.panels, key=lambda p: p.n)
    want = plan.get("panels") or []
    keep: list[Panel] = []
    for i, pp in enumerate(want):
        panel = existing[i] if i < len(existing) else None
        if panel is None:
            panel = Panel(page_id=page.id, n=i + 1, shape={})
            session.add(panel)
        panel.n = i + 1
        panel.kind = "plate" if pp.get("role") == "plate" else "shard"
        panel.scene = pp.get("scene") or ""
        panel.scale = pp.get("scale") or "MS"
        panel.state = pp.get("state") or "quiet"
        panel.beat = pp.get("beat")
        panel.weight = A.ROLE_WEIGHT.get(pp.get("role") or "narrative", 1.0)
        panel.characters = list(pp.get("characters") or [])
        new_cap, new_bal = pp.get("narration") or "", pp.get("dialogue") or ""
        if (new_cap, new_bal) != (panel.caption_en or "", panel.balloon_en or ""):
            panel.caption_hi, panel.balloon_hi, panel.hi_is_draft = "", "", False  # the Hindi follows the new English
        panel.caption_en, panel.balloon_en = new_cap, new_bal
        panel.speaker = pp.get("speaker") if panel.balloon_en else None
        panel.selected_candidate_id = None
        if not panel.locked_shape:
            panel.shape = {}
        keep.append(panel)
    for extra in existing[len(want):]:
        session.delete(extra)
    page.beat = plan.get("page_beat") or page.beat
    session.flush()
    session.expire(page, ["panels"])
    render.ensure_shapes(session, page)
    session.flush()
    return sorted(page.panels, key=lambda p: p.n)


def _locked_chars(session: Session, panel: Panel) -> list[Character]:
    return [c for c in gen.characters_on(session, panel) if c.locked]


def paint(session: Session, panel: Panel, prompt: str, refs: list[Path], provider: str, run: DirectorRun, attempt: int, idx: int, fix: str) -> Candidate:
    """One image for one panel, recorded as a Candidate with its full prompt and the fix that produced it."""
    page = panel.page
    res = providers.generate_image(provider, prompt, gen.orientation_for(panel), refs, label=f"director p{page.number}.{panel.n} a{attempt}#{idx}", state=panel.state)
    d = db.DATA_DIR / "candidates" / f"p{page.id}"
    d.mkdir(parents=True, exist_ok=True)
    cand = Candidate(panel_id=panel.id, path="", provider=res.provider, model=res.model, prompt_full=prompt, feedback_used=fix or "", cost_usd=res.cost_usd,
                     qa={"dry_run": res.dry_run, "director_run": run.id, "attempt": attempt, **res.meta})
    session.add(cand)
    session.flush()
    path = d / f"{page.number:03d}_{panel.n}_{cand.id}_dir.png"
    path.write_bytes(res.png)
    cand.path = db.rel(path)
    gen.record_cost(session, res.provider, res.cost_usd, f"director:{run.id}:candidate:{cand.id}")
    return cand


def execute_run(session: Session, run: DirectorRun, ctx: Any) -> dict[str, Any]:
    st = run.settings or {}
    brief = SceneBrief.from_json(run.brief)
    ch = session.get(Chapter, run.chapter_id)
    mc = manuscript_of(ch)
    age = (run.check or {}).get("age") or chapter_age(ch, mc)["age"]
    provider = st.get("provider") or image_provider(st)
    n_cand, retries, budget = int(st.get("candidates", 2)), int(st.get("retries", 2)), float(st.get("budget_usd", 3.0))
    run_critic = bool(st.get("run_critic", True))
    per_image = 0.0 if is_dry(provider) else providers.estimate_cost_per_image(provider)
    run.status = "running"
    session.commit()

    # re-check the gate at run time (a character may have been unlocked since the brief was checked)
    unlocked = render.unlocked_names(session, brief.characters)
    if unlocked:
        run.status = "blocked"
        _step(session, run, "check", f"blocked at run time: not locked: {', '.join(unlocked)}", ctx)
        return {"status": "blocked", "unlocked": unlocked}

    page = _page_for(session, ch, brief)
    if page.status == "approved":
        run.status = "blocked"
        _step(session, run, "check", "page is approved (frozen)", ctx)
        return {"status": "blocked"}
    run.page_id, run.page_number = page.id, page.number
    infos = {i.form_key: i for i in characters_info(session)}
    names = {k: infos[k].name for k in brief.characters if k in infos}

    # PLAN
    _step(session, run, "plan", f"planning {mc.label} p.{page.number} with {llm.model_for('script_writer')}" + ("" if llm.is_available("script_writer") else " (no key: deterministic plan)"), ctx)
    plan = A.plan_page(mc.text, brief, mc.label, age, cast_names=[c["name"] for c in mc.cast], character_names=names)
    run.plan = plan
    _step(session, run, "plan", f"{len(plan['panels'])} panels ({', '.join(p['role'] for p in plan['panels'])}); source: {plan.get('source')}", ctx,
          failures=plan.get("failures") or [])

    # LAYOUT
    page.status = "generating"
    panels = write_plan(session, page, plan)
    session.commit()
    _step(session, run, "layout", f"page {page.number}: {len(panels)} panels written, shapes cut by hierarchy (beat {page.beat})", ctx)

    flags: list[dict[str, Any]] = []
    cand_log: list[dict[str, Any]] = list(run.candidates or [])
    prompts_log: list[dict[str, Any]] = list(run.prompts or [])
    hashes: list[int] = []
    text_cost = A.PLAN_USD if llm.is_available("script_writer") else 0.0
    spent = {"img": 0.0, "text": text_cost}
    stopped = False
    try:
        for panel, pp in zip(panels, plan["panels"]):
            chars = _locked_chars(session, panel)
            looks = [look_paragraph(c.name, c.form_key, c.look) for c in chars]
            refs: list[tuple[str, Path]] = []
            for c in chars:
                p = gen.primary_ref(session, c)
                if p:
                    refs.append((c.name, p))
            plate = panel.kind == "plate"
            fix = ""
            best: dict[str, Any] | None = None
            panel_cands: list[dict[str, Any]] = []
            for attempt in range(retries + 1):
                comp = A.compose_prompt(age, pp, brief, mc.label, looks, [n for n, _ in refs], [c.name for c in chars] + list(names.values()), plate=plate, fix=fix)
                lint = A.lint_prompt(comp["prompt"], pp)
                prompts_log.append({"panel": panel.n, "panel_id": panel.id, "attempt": attempt, "prompt": comp["prompt"], "chars": comp["chars"], "lint": lint,
                                    "sections": list(comp["parts"].keys()), "references": [n for n, _ in refs]})
                run.prompts = list(prompts_log)
                _step(session, run, "prompt", f"p{page.number}.{panel.n} attempt {attempt}: {comp['chars']} chars, refs {[n for n, _ in refs] or 'none'}" + (f", lint: {lint}" if lint else ""), ctx)
                for i in range(max(1, n_cand)):
                    ctx.check_stop()
                    crit_cost = A.CRITIC_USD if (run_critic and llm.is_available("critic")) else 0.0
                    if spent["img"] + spent["text"] + per_image + crit_cost > budget + 1e-9:
                        raise BudgetExceeded()
                    c = paint(session, panel, comp["prompt"], [p for _, p in refs], provider, run, attempt, i, fix)
                    spent["img"] += c.cost_usd
                    ctx.add_cost(c.cost_usd)
                    session.commit()
                    path = db.abs_path(c.path)
                    det = A.deterministic_checks(path, gen.orientation_for(panel), hashes, bool((c.qa or {}).get("dry_run")))
                    if run_critic:
                        crit = A.critique(path, refs, pp, brief, age, mc.label, looks)
                        if crit.get("judged"):
                            spent["text"] += A.CRITIC_USD
                    else:
                        crit = {"judged": False, "scores": {}, "violations": [], "fix_prompt": "", "note": "critic off for this run"}
                    v = A.verdict(crit, det)
                    entry = {"panel": panel.n, "panel_id": panel.id, "candidate_id": c.id, "path": c.path, "url": db.media_url(c.path), "attempt": attempt,
                             "checks": det, "critic": crit, "verdict": v, "dry_run": bool((c.qa or {}).get("dry_run")), "cost_usd": c.cost_usd}
                    c.qa = {**(c.qa or {}), "director": {"checks": det["checks"], "critic": crit, "verdict": v}, "critic_score": v.get("mean"),
                            "critic_notes": "; ".join(v.get("reasons") or [])[:500]}
                    panel_cands.append(entry)
                    cand_log.append(entry)
                    run.candidates = list(cand_log)
                    run.cost_usd = round(spent["img"] + spent["text"], 4)
                    _step(session, run, "critic", f"p{page.number}.{panel.n} cand {c.id}: " + ("PASS" if v["pass"] else ("unjudged" if not v["judged"] else "fail")) +
                          (f" mean {v['mean']}" if v.get("mean") is not None else "") + (f" — {'; '.join(v['reasons'][:3])}" if v["reasons"] and v["judged"] else ""), ctx)
                best = max(panel_cands, key=A.rank_key)
                if best["verdict"]["pass"] or not best["verdict"].get("retry") or attempt == retries:
                    break
                fix = best["critic"].get("fix_prompt") or "; ".join(best["verdict"]["reasons"][:4])
                _step(session, run, "revise", f"p{page.number}.{panel.n}: retry {attempt + 1}/{retries} with fix: {fix[:200]}", ctx)
            if best is not None:
                chosen = session.get(Candidate, best["candidate_id"])
                gen.select_candidate(session, panel, chosen)
                hashes.append(best["checks"]["dhash"])
                for e in cand_log:
                    if e["panel_id"] == panel.id:
                        e["selected"] = e["candidate_id"] == chosen.id
                run.candidates = list(cand_log)
                if not best["verdict"]["pass"]:
                    flags.append({"panel": panel.n, "panel_id": panel.id, "candidate_id": chosen.id, "reasons": best["verdict"]["reasons"]})
                session.commit()
                _step(session, run, "select", f"p{page.number}.{panel.n}: pre-selected candidate {chosen.id}" + ("" if best["verdict"]["pass"] else " — FLAGGED for the author"), ctx)
    except BudgetExceeded:
        run.status = "budget"
        stopped = True
        _step(session, run, "budget", f"budget cap ${budget:.2f} reached; remaining panels flagged", ctx)
    except jobs.Stopped:
        run.status = "stopped"
        stopped = True
        _step(session, run, "stop", "stopped by the author", ctx)
    # flag every panel that has no selection
    for panel in sorted(page.panels, key=lambda p: p.n):
        if not panel.selected_candidate_id and not any(f["panel_id"] == panel.id for f in flags):
            flags.append({"panel": panel.n, "panel_id": panel.id, "candidate_id": None, "reasons": ["not painted (" + (run.status if stopped else "no candidate") + ")"]})
    run.flags = flags
    run.cost_usd = round(spent["img"] + spent["text"], 4)
    # ASSEMBLE
    page.status = "review" if any(p.selected_candidate_id for p in page.panels) else "draft"
    session.commit()
    if not stopped:
        run.status = "done"
    _step(session, run, "assemble", f"page {page.number} → {page.status}; {len(flags)} panel(s) flagged for the author; cost ${run.cost_usd:.4f}", ctx)
    session.commit()
    if run.status == "stopped":
        raise jobs.Stopped()
    return {"status": run.status, "page_id": page.id, "flags": len(flags)}


def h_art_director(ctx: Any, p: dict[str, Any]) -> dict[str, Any]:
    session: Session = ctx.session
    run = session.get(DirectorRun, int(p["run_id"]))
    if run is None:
        raise ValueError("director run not found")
    if run.kind == "chapter":
        return execute_chapter(session, run, ctx)
    try:
        res = execute_run(session, run, ctx)
    except jobs.Stopped:
        raise
    except Exception as exc:
        session.rollback()
        run = session.get(DirectorRun, int(p["run_id"]))
        run.status = "failed"
        run.steps = [*(run.steps or []), {"t": utcnow().strftime("%H:%M:%S"), "step": "error", "msg": str(exc)[:500]}]
        session.commit()
        raise
    return {"run_id": run.id, **res}


def execute_chapter(session: Session, parent: DirectorRun, ctx: Any) -> dict[str, Any]:
    """Direct the next N pages: each page gets an automatic brief from the next manuscript passage and its own run."""
    ch = session.get(Chapter, parent.chapter_id)
    st = parent.settings or {}
    n = int(st.get("next", 3))
    nums = [p.number for p in sorted(ch.pages, key=lambda p: p.number) if p.status not in ("approved", "review")]
    start = next_page_number(ch)
    while len(nums) < n:
        nums.append(start)
        start += 1
    nums = nums[:n]
    parent.status = "running"
    _step(session, parent, "plan", f"directing pages {nums}", ctx)
    done, skipped = [], []
    spent = 0.0
    for i, num in enumerate(nums):
        ctx.check_stop()
        ctx.progress(page=num, done=i, total=len(nums))
        brief = auto_brief(session, ch, num)
        if brief is None:
            skipped.append({"page": num, "reason": "end of the chapter's manuscript"})
            _step(session, parent, "check", f"page {num}: no more manuscript passages", ctx)
            break
        sub_settings = {**st, "budget_usd": max(0.0, float(st.get("budget_usd", 3.0)) - spent)}
        run, check = create_run(session, brief, sub_settings, kind="page", parent_id=parent.id)
        run.job_id = parent.job_id
        session.commit()
        if not check["can_paint"]:
            skipped.append({"page": num, "reason": "; ".join(check["errors"]), "run_id": run.id})
            _step(session, parent, "check", f"page {num}: skipped — {'; '.join(check['errors'])[:200]}", ctx)
            continue
        try:
            res = execute_run(session, run, ctx)
        except jobs.Stopped:
            parent.status = "stopped"
            parent.cost_usd = round(spent + (run.cost_usd or 0.0), 4)
            _step(session, parent, "stop", f"stopped by the author during page {num}", ctx)
            raise
        finally:
            spent += run.cost_usd or 0.0
            parent.cost_usd = round(spent, 4)
            session.commit()
        done.append({"page": num, "run_id": run.id, **res})
        if run.status == "budget":
            parent.status = "budget"
            break
    if parent.status == "running":
        parent.status = "done"
    parent.flags = [{"page": d["page"], "run_id": d["run_id"], "flags": d.get("flags", 0)} for d in done]
    _step(session, parent, "assemble", f"{len(done)} page(s) directed, {len(skipped)} skipped", ctx)
    ctx.progress(done=len(nums), total=len(nums))
    return {"run_id": parent.id, "pages": done, "skipped": skipped}


# ---------------------------------------------------------------------------------------------------------------
# covers
# ---------------------------------------------------------------------------------------------------------------


def cover_dir(volume: Volume) -> Path:
    d = db.DATA_DIR / "covers" / f"vol{volume.number}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cover_row(session: Session, volume: Volume) -> DirectorCover:
    c = session.scalar(select(DirectorCover).where(DirectorCover.volume_id == volume.id))
    if c is None:
        c = DirectorCover(volume_id=volume.id, publisher=default_publisher(session), art_candidates=[], exports={}, facts={})
        session.add(c)
        session.flush()
    return c


def default_publisher(session: Session) -> str:
    from .models import Project

    proj = session.scalar(select(Project))
    s = (proj.settings or {}) if proj else {}
    return s.get("publisher") or s.get("studio") or "Rishikesh Studio"


def volume_chapters(volume: Volume) -> list[CH.ManuscriptChapter]:
    return [CH.resolve(volume.number, c.number, c.title, c.pages_from, c.pages_to, c.text or "") for c in sorted(volume.chapters, key=lambda c: c.number)]


def volume_line_for(volume: Volume) -> str:
    return CH.volume_line(volume.number, CH.book_title(volume.number, volume.title or ""))


def j_cover(session: Session, volume: Volume) -> dict[str, Any]:
    c = cover_row(session, volume)
    lo, hi = CH.volume_range(volume.number)
    text = CV.cover_text(volume_line_for(volume), c.publisher or default_publisher(session))
    ex = c.exports or {}
    return {"volume_id": volume.id, "volume": volume.number, "title": CH.book_title(volume.number, volume.title or ""), "range": [lo, hi] if lo else None,
            "text": text.to_json(), "prompt": c.prompt, "prompt_source": c.prompt_source, "facts": c.facts or {},
            "art_path": c.art_path, "art_url": db.media_url(c.art_path), "art_candidates": [{**a, "url": db.media_url(a.get("path"))} for a in c.art_candidates or []],
            "reference_path": c.reference_path, "reference_url": db.media_url(c.reference_path), "publisher": c.publisher,
            "exports": {k: (db.media_url(v) if isinstance(v, str) and k in ("png", "pdf", "svg", "thumb") else v) for k, v in ex.items()},
            "svg": CV.svg_markup(text, art_href=db.media_url(c.art_path) or "")}


def compose_cover(session: Session, volume: Volume) -> DirectorCover:
    c = cover_row(session, volume)
    res = CV.poster_prompt(volume.number, volume_chapters(volume))
    c.prompt, c.prompt_source, c.facts = res["prompt"], res["source"], res["facts"]
    session.commit()
    return c


def h_art_cover(ctx: Any, p: dict[str, Any]) -> dict[str, Any]:
    session: Session = ctx.session
    volume = session.get(Volume, int(p["volume_id"]))
    c = cover_row(session, volume)
    if not c.prompt:
        compose_cover(session, volume)
    provider = providers.normalise_provider(p.get("provider") or llm.model_for("image"))
    refs: list[Path] = []
    for name in (c.facts or {}).get("principal", [])[:6]:
        for ch_row in session.scalars(select(Character).where(Character.name == name, Character.locked.is_(True))).all():
            r = gen.primary_ref(session, ch_row)
            if r and r not in refs:
                refs.append(r)
                break
    out = []
    n = int(p.get("n", 2))
    for i in range(n):
        ctx.check_stop()
        res = providers.generate_image(provider, c.prompt, "portrait", refs[:4], label=f"cover vol {volume.number} #{i}", state="knowledge")
        path = cover_dir(volume) / f"art_{int(utcnow().timestamp())}_{i}.png"
        path.write_bytes(res.png)
        gen.record_cost(session, res.provider, res.cost_usd, f"cover:vol{volume.number}")
        ctx.add_cost(res.cost_usd)
        item = {"path": db.rel(path), "provider": res.provider, "dry_run": res.dry_run, "cost_usd": res.cost_usd}
        c.art_candidates = [*(c.art_candidates or []), item]
        if not c.art_path:
            c.art_path = item["path"]
        session.commit()
        ctx.log(f"cover vol {volume.number}: art {path.name}{' (dry run)' if res.dry_run else ''}")
        ctx.progress(done=i + 1, total=n)
        out.append(item)
    return {"art": out}


def typeset_cover(session: Session, volume: Volume, art: str = "painted") -> dict[str, Any]:
    c = cover_row(session, volume)
    src = None
    if art == "painted" and c.art_path:
        src = db.abs_path(c.art_path)
    elif art == "reference" and c.reference_path:
        src = db.abs_path(c.reference_path)
    text = CV.cover_text(volume_line_for(volume), c.publisher or default_publisher(session))
    res = CV.typeset(src, text, cover_dir(volume), stem=f"cover_vol{volume.number}")
    c.exports = {"png": db.rel(res["png"]), "pdf": db.rel(res["pdf"]), "svg": db.rel(res["svg"]), "thumb": db.rel(res["thumb"]), "size_px": res["size_px"], "ppi": res["ppi"],
                 "mm": res["mm"], "art": art if src else "none", "text": res["text"], "at": utcnow().isoformat()}
    session.commit()
    return c.exports


# ---------------------------------------------------------------------------------------------------------------
# job registration (the worker's handler table lives in backend/jobs.py)
# ---------------------------------------------------------------------------------------------------------------

jobs.HANDLERS.setdefault("art_director", h_art_director)
jobs.HANDLERS.setdefault("art_cover", h_art_cover)

__all__ = ["CharacterInfo", "Line", "SceneBrief", "DirectorRun", "DirectorCover", "CharacterRef"]
