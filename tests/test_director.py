"""The Art Director: guardrails parsed from the master prompt, the age of each chapter, the verbatim validator, the lock
gate, a dry-run "Direct this page" end to end, and the cover typesetting with the exact title strings."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select

from backend import book_seed, db
from backend import director as D
from backend.director_models import DirectorRun
from backend.models import Chapter, Character, Page, Volume
from engine.director import agent as A
from engine.director import chapters as CH
from engine.director import cover as CV
from engine.director import guardrails as G
from engine.director.brief import SceneBrief, is_verbatim

needs_book = pytest.mark.skipif(not book_seed.book_json_path().exists(), reason="no local copy of the book")


@pytest.fixture(scope="module")
def dclient(client):
    """The studio app with the Art Director router (included by backend/api.py; added here if a branch lacks it)."""
    from backend.api import app
    from backend.director_api import router

    if not any(getattr(r, "path", "").startswith("/api/art-director") for r in app.routes):
        n = len(app.router.routes)
        app.include_router(router)
        added = app.router.routes[n:]
        del app.router.routes[n:]
        app.router.routes[0:0] = added  # ahead of the SPA catch-all
    return client


def wait(client, jid, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "failed", "stopped"):
            return j
        time.sleep(0.2)
    raise AssertionError("job timeout")


# --- guardrails ---------------------------------------------------------------------------------------------------


def test_guardrails_parse_all_sections():
    g = G.load()
    assert sorted(g.sections) == list(range(1, 13))
    titles = [g.sections[i].title for i in range(1, 13)]
    assert titles[0] == "CINEMATIC VISUAL QUALITY" and titles[3] == "THREE AGES — DISTINCT VISUAL IDENTITIES" and titles[11] == "FINAL QUALITY TEST"
    assert "PROJECT" in g.preamble and "CORE CREATIVE PHILOSOPHY" in g.preamble and g.final_command.startswith("Create an unforgettable")
    assert g.raw == G.MASTER_PATH.read_text(encoding="utf-8")  # the raw text is kept verbatim
    # ages, palettes, visual language
    assert set(g.ages) == {"treta", "dwapara", "kali"}
    assert g.ages["treta"].palette == ["ember orange", "molten gold", "charcoal black", "weathered bronze", "smoky crimson"]
    assert "Kurukshetra" in g.ages["dwapara"].visual_language and "data centres" in g.ages["kali"].visual_language
    # character directives
    assert g.ravana_heads == {"golden": "intelligence", "crimson": "ego"}
    assert any("composure and restraint" in d["text"] for d in g.characters["Rama"])
    assert any("ten heads" in d["text"] for d in g.characters["Ravana"])
    assert any("Arjuna’s flag" in d["text"] for d in g.characters["Hanuman"]) and any(d["age"] == "all" for d in g.characters["Hanuman"])
    assert {"Krishna", "Arjuna", "Karna", "Kalki"} <= set(g.characters)
    assert any("light, composition and consciousness" in d["text"] for d in g.characters["Kalki"])
    # page architecture, parchment, typography
    assert g.page_architecture["min_panels"] == 3 and g.page_architecture["max_panels"] == 5 and len(g.page_architecture["hierarchy"]) == 3
    assert "major revelations" in g.page_architecture["full_page_for"]
    assert len(g.parchment["texture"]) == 6 and len(g.parchment["shards"]) == 6
    assert g.typography["series_title"] == "THE CYCLE OF DHARMA" and g.typography["author_credit"] == "RACHIT AGARWAL"
    # negatives and the final quality test
    assert len(g.negatives) == 17 and g.negatives[0] == "No cartoon styling." and g.negatives[-1] == "No unreadable or misspelled title typography."
    assert len(g.quality_test) == 10 and g.quality_test[0].startswith("Does the composition tell") and g.quality_test[9].startswith("Would the image remain")


def test_guardrails_api(dclient):
    r = dclient.get("/api/art-director/guardrails").json()
    assert len(r["sections"]) == 12 and len(r["negatives"]) == 17 and len(r["quality_test"]) == 10
    assert r["raw"].startswith("THE CYCLE OF DHARMA")


def test_condensed_prompt_keeps_negatives_and_never_asks_for_text():
    brief = SceneBrief(chapter_id=1, action="Rama fits Agastya's arrow", characters=["rama"], setting='Lanka "burned like a mountain of embers".')
    panel = {"role": "dominant", "scale": "WS", "beat": "revelation", "scene": "Rama draws the bow", "dialogue": "Ravana, I give you one more chance to return Sita"}
    comp = A.compose_prompt("treta", panel, brief, "Chapter 1 — The Last Night of Lanka", ["Rama, locked look: calm."], ["Rama"], ["Rama"])
    p = comp["prompt"]
    assert all(n in p for n in G.load().negatives)
    assert "ember orange" in p and "composure and restraint" in p and "No text in the image" in p
    assert "Ravana, I give you" not in p and '"' not in p
    assert A.lint_prompt(p, panel) == []
    assert "s2_parchment" not in comp["parts"]  # parchment texture only for full-page plates
    assert "s2_parchment" in A.compose_prompt("treta", panel, brief, "x", [], [], [], plate=True)["parts"]


# --- ages ---------------------------------------------------------------------------------------------------------


def test_age_chapter_one_by_keywords(session):
    ch = session.scalar(select(Chapter).join(Volume).where(Volume.number == 1, Chapter.number == 1))
    assert D.chapter_age(ch)["age"] == "treta"
    assert CH.keyword_age("Kurukshetra, Arjuna and Karna on their chariots") == "dwapara"
    assert CH.keyword_age("the Index fell on every screen in Pune") == "kali"


@needs_book
def test_age_mapping_by_manuscript_chapter():
    assert CH.age_for_manuscript_number(1) == "treta"
    assert CH.age_for_manuscript_number(5) == "dwapara"
    assert CH.age_for_manuscript_number(22) == "kali"
    assert CH.age_for_manuscript_number(35) == "kali"
    assert CH.age_for_manuscript_number(41) == "kali"
    assert CH.manuscript_entry(22)["title"] == "The Price of a Prayer" and CH.manuscript_entry(41)["title"] == "One Per Cent"
    assert CH.volume_range(2) == (22, 41)


@needs_book
def test_volume_two_chapters_keyed_by_manuscript_number(dclient):
    with db.session_scope() as s:
        book_seed.ensure(s)
    books = dclient.get("/api/art-director/chapters").json()["books"]
    two = next(b for b in books if b["volume"] == 2)
    assert two["range"] == [22, 41] and two["title"] == "The Remembrance Index"
    nums = [c["manuscript_number"] for c in two["chapters"]]
    assert nums == list(range(22, 42))
    first = two["chapters"][0]
    assert first["studio_number"] == 1 and first["label"] == "Chapter 22 — The Price of a Prayer" and first["age"] == "kali"
    assert two["chapters"][-1]["label"] == "Chapter 41 — One Per Cent"


# --- the brief ----------------------------------------------------------------------------------------------------


def test_verbatim_validator(session):
    ch = session.scalar(select(Chapter).join(Volume).where(Volume.number == 1, Chapter.number == 1))
    text = D.manuscript_of(ch).text
    real = A.sentences(text)[0]
    assert is_verbatim(real, text)
    assert is_verbatim("“" + real.replace("“", "").replace("”", "") + "”", text)  # quotes normalised
    assert not is_verbatim("Ravana laughed and danced upon the golden towers of Ayodhya.", text)
    infos = D.characters_info(session)
    from engine.director.brief import Line, validate

    ok = validate(SceneBrief(chapter_id=ch.id, action="x", characters=["rama"], lines=[Line(real, "narration")]), text, infos, "treta")
    assert ok["lines"][0]["verbatim"] and ok["can_paint"]
    bad = validate(SceneBrief(chapter_id=ch.id, action="x", characters=["rama"], lines=[Line("An invented line nobody wrote.")]), text, infos, "treta")
    assert not bad["can_paint"] and bad["lines"][0]["status"] == "not in manuscript"
    approved = validate(SceneBrief(chapter_id=ch.id, action="x", characters=["rama"], lines=[Line("An invented line nobody wrote.", adapted_approved=True)]), text, infos, "treta")
    assert approved["can_paint"] and approved["lines"][0]["status"] == "adapted, approved"
    unknown = validate(SceneBrief(chapter_id=ch.id, action="x", characters=["hanumann"]), text, infos, "treta")
    assert not unknown["can_paint"] and unknown["characters"][0]["exists"] is False and unknown["characters"][0]["suggestions"]


def test_lock_gate_stops_painting(dclient, session):
    ch = session.scalar(select(Chapter).join(Volume).where(Volume.number == 1, Chapter.number == 1))
    rav = session.scalar(select(Character).where(Character.form_key == "ravana/ten-heads"))
    assert rav is not None and not rav.locked
    before = len(session.scalars(select(DirectorRun)).all())
    r = dclient.post("/api/art-director/direct", json={"brief": {"chapter_id": ch.id, "action": "Ravana's ten heads turn", "characters": ["ravana/ten-heads"]}})
    assert r.status_code == 409
    body = r.json()
    assert body["needs_reference"][0]["key"] == "ravana/ten-heads" and body["run"]["status"] == "blocked"
    session.expire_all()
    runs = session.scalars(select(DirectorRun)).all()
    assert len(runs) == before + 1 and runs[-1].job_id is None and not runs[-1].candidates


def test_no_manuscript_is_handled(dclient, session):
    v1 = session.scalar(select(Volume).where(Volume.number == 1))
    empty = Chapter(volume_id=v1.id, number=900, title="Empty", text="")
    session.add(empty)
    session.commit()
    try:
        chk = dclient.post("/api/art-director/brief/check", json={"chapter_id": empty.id, "action": "anything", "characters": ["rama"]}).json()
        assert chk["no_manuscript"] and not chk["can_paint"] and "Project → Manuscript" in chk["errors"][0]
        assert dclient.post("/api/art-director/direct-chapter", json={"chapter_id": empty.id, "next": 1}).status_code == 409
    finally:
        session.delete(empty)
        session.commit()


# --- direct this page (dry run) -----------------------------------------------------------------------------------


def test_direct_page_dry_run_end_to_end(dclient, session):
    ch1 = session.scalar(select(Chapter).join(Volume).where(Volume.number == 1, Chapter.number == 1))
    # a scratch copy of Chapter 1 so the seeded pages stay as they are for the other tests
    tmp = Chapter(volume_id=ch1.volume_id, number=901, title=ch1.title, text=ch1.text, pages_from=None, pages_to=None)
    session.add(tmp)
    session.commit()
    text = D.manuscript_of(tmp).text
    line = next(s for s in A.sentences(text) if 30 < len(s) < 200 and "“" not in s)
    try:
        brief = {"chapter_id": tmp.id, "action": "Rama fits Agastya's arrow to the bow as the wind drops", "characters": ["rama"],
                 "setting": "Night before the burning walls of Lanka.", "lines": [{"text": line, "kind": "narration"}], "page_number": 1}
        est = dclient.post("/api/art-director/estimate", json={"brief": brief, "settings": {"candidates": 2}}).json()
        assert est["images"] == 8 and est["usd"] == 0.0 and est["dry_run"]
        r = dclient.post("/api/art-director/direct", json={"brief": brief, "settings": {"candidates": 2, "retries": 2}})
        assert r.status_code == 202, r.text
        j = wait(dclient, r.json()["job_id"])
        assert j["status"] == "done", j["log"]
        run = dclient.get(f"/api/art-director/runs/{r.json()['run']['id']}").json()
        assert run["status"] == "done" and run["page_id"]
        steps = [s["step"] for s in run["steps"]]
        for s in ("check", "plan", "layout", "prompt", "critic", "select", "assemble"):
            assert s in steps, steps
        panels_plan = run["plan"]["panels"]
        assert 3 <= len(panels_plan) <= 5 and [p["role"] for p in panels_plan].count("dominant") == 1 and panels_plan[-1]["role"] == "detail"
        page = dclient.get(f"/api/pages/{run['page_id']}").json()
        assert page["status"] == "review" and len(page["panels"]) == len(panels_plan)
        said = []
        for p in page["panels"]:
            assert p["selected_candidate_id"], p
            for t in (p["caption_en"], p["balloon_en"]):
                if t:
                    assert is_verbatim(t, text), t
                    said.append(t)
        assert line in said  # the brief's line is on the page
        assert len(run["candidates"]) == 2 * len(panels_plan)  # unjudged in dry run: no blind retries
        for c in run["candidates"]:
            assert c["critic"]["judged"] is False and c["checks"]["checks"] and c["verdict"]["pass"] is False
        assert {f["panel"] for f in run["flags"]} == {p["n"] for p in panels_plan}  # unjudged = flagged for the author, never silently accepted
        for pr in run["prompts"]:
            assert pr["lint"] == [] and "STRICT NEGATIVE DIRECTIONS" in pr["prompt"]
        assert dclient.get("/api/art-director/runs", params={"page_id": run["page_id"]}).json()[0]["id"] == run["id"]
    finally:
        session.expire_all()
        for pg in session.scalars(select(Page).where(Page.chapter_id == tmp.id)).all():
            session.delete(pg)
        session.delete(session.get(Chapter, tmp.id))
        session.commit()


def test_critic_verdict_rules():
    det_ok = {"checks": [{"check": "size", "ok": True, "detail": ""}], "ok": True}
    good = {"judged": True, "scores": {str(i): 8 for i in range(1, 11)}, "violations": [], "fix_prompt": ""}
    assert A.verdict(good, det_ok)["pass"]
    weak = {**good, "scores": {**good["scores"], "2": 4}}
    v = A.verdict(weak, det_ok)
    assert not v["pass"] and v["failed_points"] == [2] and v["retry"]
    viol = {**good, "violations": [{"rule": "No anime or manga styling.", "detail": "anime eyes"}]}
    assert not A.verdict(viol, det_ok)["pass"]
    det_bad = {"checks": [{"check": "no text in image", "ok": False, "detail": "read: LANKA"}], "ok": False}
    assert not A.verdict(good, det_bad)["pass"]


def test_plan_check_rejects_invented_callouts():
    text = "Lanka burned like a mountain of embers. The arrow crossed in a line of gold."
    brief = SceneBrief(chapter_id=1, action="the arrow", characters=["rama"])
    plan = {"panels": [{"role": "dominant", "narration": "Lanka burned like a mountain of embers.", "characters": ["rama"], "scene": "x"},
                       {"role": "narrative", "dialogue": "I am the king of all the worlds!", "characters": ["rama"], "scene": "y"},
                       {"role": "detail", "narration": "The arrow crossed in a line of gold.", "characters": ["ravana/ten-heads"], "scene": "z"}]}
    fails = A.check_plan(plan, text, brief)
    assert any("not verbatim" in f for f in fails) and any("outside the brief" in f for f in fails)
    fb = A.fallback_plan(text, brief)
    assert A.check_plan(fb, text, brief) == [] or all("panels required" in f for f in A.check_plan(fb, text, brief))


# --- covers -------------------------------------------------------------------------------------------------------


def test_cover_typesetting_exact_strings(tmp_path):
    t = CV.cover_text("VOLUME TWO — THE REMEMBRANCE INDEX", "Rishikesh Studio")
    res = CV.typeset(None, t, tmp_path, stem="v2")
    got = CV.svg_strings(res["svg"].read_text(encoding="utf-8"))
    assert got["title"] == "THE CYCLE OF DHARMA"
    assert got["volume"] == "VOLUME TWO — THE REMEMBRANCE INDEX"
    assert got["author"] == "RACHIT AGARWAL" and got["publisher"] == "RISHIKESH STUDIO"
    from PIL import Image

    with Image.open(res["png"]) as im:
        assert im.size == (2000, 3000)  # 2:3 at 300 ppi
    assert res["pdf"].read_bytes()[:4] == b"%PDF"
    assert "Cinzel" in res["lines"][0]["font"]


def test_cover_api_compose_paint_typeset(dclient, session):
    v2 = session.scalar(select(Volume).where(Volume.number == 2))
    c = dclient.post(f"/api/art-director/covers/{v2.id}/compose").json()
    assert "No text in the image" in c["prompt"] and all(n in c["prompt"] for n in G.load().negatives)
    j = wait(dclient, dclient.post(f"/api/art-director/covers/{v2.id}/paint", json={"n": 1}).json()["job_id"])
    assert j["status"] == "done", j["log"]
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (600, 900), (40, 30, 60)).save(buf, "PNG")
    up = dclient.post(f"/api/art-director/covers/{v2.id}/reference", files={"file": ("cover.png", buf.getvalue(), "image/png")}).json()
    assert up["reference_url"].startswith("/media/covers/")
    out = dclient.post(f"/api/art-director/covers/{v2.id}/typeset", json={"art": "painted"}).json()
    assert out["exports"]["png"].endswith(".png") and out["exports"]["pdf"].endswith(".pdf") and out["text"]["title"] == "THE CYCLE OF DHARMA"
    assert out["exports"]["text"]["volume_line"].startswith("VOLUME TWO")


# --- the model paths, with stand-in models ------------------------------------------------------------------------


def test_plan_reasks_once_then_repairs_invented_lines():
    text = "Lanka burned like a mountain of embers. The arrow crossed the field in a line of gold. Ravana fell."
    brief = SceneBrief(chapter_id=1, action="the arrow crosses the field", characters=["rama"])
    calls = []

    def ask(role, system, user, images=None, fallback=None, max_tokens=0):
        calls.append(role)
        assert "MASTER ART-DIRECTION PROMPT" in system and "STRICT NEGATIVE DIRECTIONS" in system  # the master prompt, verbatim
        return {"page_beat": "action", "panels": [
            {"role": "dominant", "scale": "WS", "scene": "the field", "characters": ["rama"], "narration": "Lanka burned like a mountain of embers."},
            {"role": "narrative", "scale": "MS", "scene": "the arrow", "characters": ["rama"], "dialogue": "I shall end you tonight!", "speaker": "Rama"},
            {"role": "narrative", "scale": "MS", "scene": "the king", "characters": ["rama"], "narration": "Ravana fell."},
            {"role": "detail", "scale": "CU", "scene": "the arrow head", "characters": []}]}

    plan = A.plan_page(text, brief, "Chapter 1", "treta", ask=ask)
    assert calls == ["script_writer", "script_writer"]  # asked, then re-asked once with the failures
    assert plan["source"] == "model+repair" and plan["attempts"] == 2
    for p in plan["panels"]:
        for t in (p["narration"], p["dialogue"]):
            assert not t or is_verbatim(t, text)


def test_revision_loop_uses_the_critics_fix(dclient, session, monkeypatch):
    seen = {"n": 0}

    def fake_critique(image, references, panel, brief, age, chapter_label, looks, ask=None):
        seen["n"] += 1
        bad = seen["n"] % 2 == 1  # every first paint fails, its revision passes
        sc = {str(i): (4 if bad and i == 2 else 8) for i in range(1, 11)}
        return {"judged": True, "scores": sc, "violations": [{"rule": "No randomly changing character designs.", "detail": "face differs from the reference"}] if bad else [],
                "fix_prompt": "match Rama's reference face exactly" if bad else ""}

    monkeypatch.setattr(A, "critique", fake_critique)
    ch1 = session.scalar(select(Chapter).join(Volume).where(Volume.number == 1, Chapter.number == 1))
    tmp = Chapter(volume_id=ch1.volume_id, number=902, title=ch1.title, text=ch1.text)
    session.add(tmp)
    session.commit()
    try:
        brief = {"chapter_id": tmp.id, "action": "Rama fits Agastya's arrow to the bow", "characters": ["rama"], "page_number": 1}
        r = dclient.post("/api/art-director/direct", json={"brief": brief, "settings": {"candidates": 1, "retries": 2}})
        j = wait(dclient, r.json()["job_id"])
        assert j["status"] == "done", j["log"]
        run = dclient.get(f"/api/art-director/runs/{r.json()['run']['id']}").json()
        n_panels = len(run["plan"]["panels"])
        assert len(run["candidates"]) == 2 * n_panels  # first paint + one revision per panel
        assert sum(1 for s in run["steps"] if s["step"] == "revise") == n_panels
        revised = [p for p in run["prompts"] if p["attempt"] == 1]
        assert revised and all("match Rama's reference face exactly" in p["prompt"] for p in revised)
        assert run["flags"] == []  # every panel passed after its revision
        for c in run["candidates"]:
            assert c["selected"] == (c["attempt"] == 1)
    finally:
        session.expire_all()
        for pg in session.scalars(select(Page).where(Page.chapter_id == tmp.id)).all():
            session.delete(pg)
        session.delete(session.get(Chapter, tmp.id))
        session.commit()
