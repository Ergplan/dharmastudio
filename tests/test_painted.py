"""Painted-page mode: the prompt (house style verbatim, lettering, pacing, header, locked looks, panels with exact box
texts), the box-text rules (verbatim, at most 14 words), the text check (a stand-in critic), the dry run end to end,
the auto-repaint loop, "Edit box text", and the full-bleed PDF export of a painted page."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from backend import db
from backend import director as D
from backend import render
from backend.models import Chapter, Page, Volume
from engine.comic import layout as L
from engine.comic import script as S
from engine.director import agent as A
from engine.director import painted as P

HOUSE = ("Hindu graphic novel. Epic mythic graphic-novel page rendered in a richly textured parchment-and-ink style, with torn panel edges, "
         "cinematic firelight, storm-dark skies, burning Lanka, layered narration boxes, and serif typography.")
MS_TEXT = ("Lanka burned like a mountain of embers, and the sea below it was black with ash. The arrow crossed the field in a line of gold. "
           "“Return her,” Rama said. Ravana laughed from ten throats at once.")


def wait(client, jid, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "failed", "stopped"):
            return j
        time.sleep(0.2)
    raise AssertionError("job timeout")


def spec(**kw):
    s = {"header": None, "looks": [], "references": [], "panels": [
        {"n": 1, "shot": "wide shot", "scene": "Lanka burns under a storm sky", "characters": [], "boxes": [{"kind": "narration", "text": "Lanka burned like a mountain of embers"}]},
        {"n": 2, "shot": "close-up", "scene": "Rama, the bow drawn", "characters": ["rama"], "boxes": [{"kind": "speech", "speaker": "Rama", "text": "“Return her,”"}]},
        {"n": 3, "shot": "medium shot", "scene": "the arrow", "characters": [], "boxes": [{"kind": "narration", "text": "The arrow crossed the field in a line of gold."}]}]}
    s.update(kw)
    return s


@pytest.fixture()
def scratch_chapter(session):
    """A scratch copy of Chapter 1 in Volume 1 (painted by default) so the seeded pages stay as they are."""
    ch1 = session.scalar(select(Chapter).join(Volume).where(Volume.number == 1, Chapter.number == 1))
    tmp = Chapter(volume_id=ch1.volume_id, number=950, title=ch1.title, text=ch1.text)
    session.add(tmp)
    session.commit()
    yield tmp
    session.expire_all()
    for pg in session.scalars(select(Page).where(Page.chapter_id == tmp.id)).all():
        session.delete(pg)
    session.delete(session.get(Chapter, tmp.id))
    session.commit()


# --- the prompt ---------------------------------------------------------------------------------------------------


def test_house_style_is_the_authors_sentence():
    assert P.HOUSE_STYLE == HOUSE
    assert "at most 14 words per box" in P.TYPOGRAPHY and "no other text anywhere except the given box texts and the chapter header" in P.TYPOGRAPHY
    assert P.PACING.startswith("Fast-paced and readable: 3 to 5 panels")


def test_prompt_contains_house_style_verbatim_header_looks_and_panels(session):
    sp = spec(header=P.header_text(1, 1, "The Last Night of Lanka"))
    looks, refs = D.painted_cast(session, sp)  # Rama's locked look from the Character table (the lock)
    sp["looks"], sp["references"] = looks, [n for n, _ in refs]
    prompt = P.build_page_prompt(sp, MS_TEXT)
    assert prompt.startswith(HOUSE + "\n" + P.TYPOGRAPHY + "\n" + P.PACING)
    assert "It opens with the header “BOOK ONE · 1 — The Last Night of Lanka”" in prompt
    for k in ("top-knot", "tilak", "saffron", "rudraksha", "OPEN", "no crown"):
        assert k in prompt, k
    a = prompt.index("Panel 1 (wide shot): Lanka burns under a storm sky. Narration box: “Lanka burned like a mountain of embers”")
    b = prompt.index("Panel 2 (close-up): Rama, the bow drawn. Speech balloon (Rama): “Return her,”")
    c = prompt.index("Panel 3 (medium shot): the arrow. Narration box: “The arrow crossed the field in a line of gold.”")
    assert a < b < c
    assert "Final Fantasy" not in prompt and "Advent" not in prompt


def test_comic_script_uses_the_house_style_not_ff7():
    assert S.COMIC_STYLE.startswith(HOUSE)
    for bad in ("Final Fantasy", "FF7", "Advent Children"):
        assert bad not in S.COMIC_STYLE
    assert "no text" in S.panel_prompt("treta", "Rama on the shore", "shard")


def test_box_over_14_words_is_rejected_with_split_advice():
    long = "Lanka burned like a mountain of embers, and the sea below it was black with ash."
    assert P.word_count(long) == 16
    sp = spec()
    sp["panels"][0]["boxes"][0]["text"] = long
    with pytest.raises(P.BoxTextError) as e:
        P.build_page_prompt(sp, MS_TEXT)
    assert "16 words" in str(e.value) and "split it" in str(e.value)


def test_non_verbatim_box_is_rejected_and_clause_trims_are_allowed():
    sp = spec()
    sp["panels"][2]["boxes"][0]["text"] = "The arrow flew across the field like gold."
    with pytest.raises(P.BoxTextError) as e:
        P.build_page_prompt(sp, MS_TEXT)
    assert "not a verbatim manuscript excerpt" in str(e.value)
    assert P.is_verbatim_excerpt("Lanka burned like a mountain of embers…", MS_TEXT)
    assert P.is_verbatim_excerpt("Lanka burned… the sea below it was black with ash.", MS_TEXT)
    assert P.is_verbatim_excerpt("the sea below it was black with ash", MS_TEXT)
    assert not P.is_verbatim_excerpt("rned like a mountain", MS_TEXT)  # trims fall on word boundaries
    fitted = P.fit_box("Lanka burned like a mountain of embers, and the sea below it was black with ash.")
    assert P.word_count(fitted) <= 14 and P.is_verbatim_excerpt(fitted, MS_TEXT)


# --- the text check (stand-in critic) -----------------------------------------------------------------------------


def _ask_with(texts, seen=None):
    def ask(system, user, images, fallback):
        if seen is not None:
            seen.append((system, user, images))
        return {"texts": [{"text": t} for t in texts], "boxes": []}
    return ask


def test_text_check_pass(tmp_path):
    img = tmp_path / "p.png"
    Image.new("RGB", (1024, 1536), "white").save(img)
    sp = spec(header="BOOK ONE · 1 — The Last Night of Lanka")
    seen = []
    painted = ["BOOK ONE · 1", "The Last Night of Lanka", "LANKA BURNED LIKE A MOUNTAIN OF EMBERS", "\"Return her,\"",
               "The arrow crossed the field", "in a line of gold."]  # header in two pieces, case, quotes, a box split over two lines
    v = P.verify_text(img, sp, ask=_ask_with(painted, seen))
    assert v["judged"] and v["pass"], v
    assert all(b["match"] for b in v["boxes"]) and v["extra"] == []
    system, user, images = seen[0]
    assert "Transcribe EVERY piece of lettered text" in system and images == [img]
    assert "Lanka burned like a mountain of embers" in user
    assert P.verdict(v)["pass"]


def test_text_check_fail_on_misspelling_missing_and_extra(tmp_path):
    img = tmp_path / "p.png"
    Image.new("RGB", (1024, 1536), "white").save(img)
    sp = spec()
    v = P.verify_text(img, sp, ask=_ask_with(["Lanka burnd like a mountain of embers", "Return her,", "The arrow crossed the field in a line of gold."]))
    assert not v["pass"] and [b["match"] for b in v["boxes"]] == [False, True, True]
    assert v["boxes"][0]["found"] == "Lanka burnd like a mountain of embers"
    fix = P.correction_for(v)
    assert "must read exactly “Lanka burned like a mountain of embers”" in fix and "burnd" in fix
    v2 = P.verify_text(img, sp, ask=_ask_with(["Lanka burned like a mountain of embers", "Return her—", "The arrow crossed the field in a line of gold.", "LANKA"]))
    assert not v2["pass"] and v2["extra"] == ["LANKA"] and v2["boxes"][1]["match"] is False  # "—" is not ","
    assert "remove the stray text “LANKA”" in P.correction_for(v2)
    vd = P.verdict(v2)
    assert not vd["pass"] and vd["retry"] and any("extra text" in r for r in vd["reasons"])
    # dashes and curly quotes normalise
    assert P.norm_text("“Ravana—now”") == P.norm_text('"ravana - NOW"')


def test_text_check_without_a_model_is_unjudged(tmp_path):
    img = tmp_path / "p.png"
    Image.new("RGB", (1024, 1536), "white").save(img)
    v = P.verify_text(img, spec(), ask=lambda system, user, images, fallback: fallback())
    assert v["judged"] is False and v["pass"] is False and "flagged" in v["note"]
    assert P.verdict(v) == {"pass": False, "judged": False, "reasons": [v["note"]], "retry": False}


# --- the studio: modes, dry run, repaint loop, edit box text, export ----------------------------------------------


def test_volume_one_defaults_to_painted(client, session):
    v1 = session.scalar(select(Volume).where(Volume.number == 1))
    v2 = session.scalar(select(Volume).where(Volume.number == 2))
    assert render.volume_mode(v1) == "painted" and render.volume_mode(v2) == "shards"
    st = client.get("/api/art-director/painted/style").json()
    assert st["house_style"] == HOUSE and st["max_box_words"] == 14 and st["size"] == [1024, 1536] and st["text_model_default"] == "gpt-6.1-sol"
    r = client.put(f"/api/art-director/volumes/{v2.id}/mode", json={"mode": "painted"}).json()
    assert r["page_mode"] == "painted"
    assert client.put(f"/api/art-director/volumes/{v2.id}/mode", json={"mode": None}).json()["page_mode"] == "shards"
    assert client.put(f"/api/art-director/volumes/{v2.id}/mode", json={"mode": "cartoon"}).status_code == 400
    books = client.get("/api/art-director/chapters").json()["books"]
    assert books[0]["page_mode"] == "painted"


def test_painted_brief_rejects_a_long_line(client, scratch_chapter):
    text = D.manuscript_of(scratch_chapter).text
    long = next(s for s in A.sentences(text) if P.word_count(s) > 16 and "“" not in s)
    chk = client.post("/api/art-director/brief/check", json={"chapter_id": scratch_chapter.id, "action": "Lanka burns", "characters": ["rama"],
                                                             "lines": [{"text": long, "kind": "narration"}]}).json()
    assert chk["mode"] == "painted" and not chk["can_paint"]
    assert any("split it into two lines" in e for e in chk["errors"])
    r = client.post("/api/art-director/direct", json={"brief": {"chapter_id": scratch_chapter.id, "action": "Lanka burns", "characters": ["rama"],
                                                                 "lines": [{"text": long, "kind": "narration"}]}})
    assert r.status_code == 409 and "words" in r.json()["detail"]
    # the same line is fine for the shard compositor (typeset captions)
    ok = client.post("/api/art-director/brief/check", json={"chapter_id": scratch_chapter.id, "action": "Lanka burns", "characters": ["rama"], "mode": "shards",
                                                            "lines": [{"text": long, "kind": "narration"}]}).json()
    assert ok["mode"] == "shards" and ok["can_paint"]


def test_painted_dry_run_end_to_end(client, session, scratch_chapter):
    text = D.manuscript_of(scratch_chapter).text
    line = next(s for s in A.sentences(text) if 4 <= P.word_count(s) <= 14 and "“" not in s)
    brief = {"chapter_id": scratch_chapter.id, "action": "Rama fits Agastya's arrow to the bow as Lanka burns", "characters": ["rama"],
             "setting": "Night before the burning walls of Lanka.", "lines": [{"text": line, "kind": "narration"}], "page_number": 1}
    est = client.post("/api/art-director/estimate", json={"brief": brief, "settings": {"candidates": 1}}).json()
    assert est["mode"] == "painted" and est["images"] == 1 and est["dry_run"] and est["usd"] == 0.0
    r = client.post("/api/art-director/direct", json={"brief": brief, "settings": {"candidates": 1, "retries": 2}})
    assert r.status_code == 202, r.text
    j = wait(client, r.json()["job_id"])
    assert j["status"] == "done", j["log"]
    run = client.get(f"/api/art-director/runs/{r.json()['run']['id']}").json()
    assert run["status"] == "done" and run["settings"]["mode"] == "painted"
    steps = [s["step"] for s in run["steps"]]
    for s in ("check", "plan", "layout", "prompt", "critic", "select", "assemble"):
        assert s in steps, steps
    sp = run["plan"]["painted"]
    assert sp["header"] == P.header_text(1, D.manuscript_of(scratch_chapter).manuscript_number or 950, D.manuscript_of(scratch_chapter).title)
    boxes = P.boxes_of(sp)
    assert boxes and all(P.word_count(b["text"]) <= 14 and P.is_verbatim_excerpt(b["text"], text) for b in boxes)
    assert any(b["text"] == P.clean_box_text(line) for b in boxes)  # the author's line is lettered as given
    assert len(run["prompts"]) == 1 and run["prompts"][0]["prompt"].startswith(HOUSE)  # unjudged: no blind repaints
    (c,) = run["candidates"]
    assert c["mode"] == "painted" and c["dry_run"] and c["selected"] and c["verification"]["judged"] is False
    assert run["flags"] and run["flags"][0]["candidate_id"] == c["candidate_id"]  # flagged for the author, never silently accepted
    path = db.DATA_DIR / c["path"]
    with Image.open(path) as im:
        assert im.size == (1024, 1536)
    page = client.get(f"/api/pages/{run['page_id']}").json()
    assert page["status"] == "review" and page["page_mode"] == "painted" and page["thumb"] == c["url"]  # never approved by the agent
    html = client.get(f"/api/pages/{run['page_id']}/render").text
    assert "data-mode='painted'" in html and c["url"] in html
    st = client.get(f"/api/art-director/pages/{run['page_id']}/painted").json()
    assert st["selected_id"] == c["candidate_id"] and len(st["boxes"]) == len(boxes) and st["candidates"][0]["verification"]["judged"] is False
    # the author switches this page to shards: the compositor renders it again
    client.put(f"/api/art-director/pages/{run['page_id']}/mode", json={"mode": "shards"})
    assert "data-mode='painted'" not in client.get(f"/api/pages/{run['page_id']}/render").text
    client.put(f"/api/art-director/pages/{run['page_id']}/mode", json={"mode": None})


def test_failed_text_check_repaints_with_a_correction(client, session, scratch_chapter, monkeypatch):
    calls = {"n": 0}

    def fake_verify(path, sp, dry, model):
        calls["n"] += 1
        exp = P.boxes_of(sp)
        texts = [b["text"] for b in exp]
        if calls["n"] < 3:  # the first two paintings misspell the first box and add a stray word
            texts[0] = texts[0].replace("a", "e", 1) + "x"
            texts.append("LANKA")
        return {"judged": True, "model": model or "gpt-6.1-sol", "transcription": texts, **P.compare(exp, sp.get("header"), texts)}

    monkeypatch.setattr(D, "verify_painted", fake_verify)
    brief = {"chapter_id": scratch_chapter.id, "action": "Rama fits Agastya's arrow to the bow", "characters": ["rama"], "page_number": 2}
    r = client.post("/api/art-director/direct", json={"brief": brief, "settings": {"candidates": 1, "retries": 2, "text_model": "gpt-5.5"}})
    j = wait(client, r.json()["job_id"])
    assert j["status"] == "done", j["log"]
    run = client.get(f"/api/art-director/runs/{r.json()['run']['id']}").json()
    assert [c["attempt"] for c in run["candidates"]] == [0, 1, 2]  # painted, then repainted twice; all kept
    assert [c["verdict"]["pass"] for c in run["candidates"]] == [False, False, True]
    assert sum(1 for s in run["steps"] if s["step"] == "revise") == 2
    assert all("Lettering correction from the proofreader" in p["prompt"] and "remove the stray text “LANKA”" in p["prompt"] for p in run["prompts"][1:])
    assert run["candidates"][0]["verification"]["transcription"] and run["candidates"][0]["verification"]["extra"] == ["LANKA"]
    assert [c["selected"] for c in run["candidates"]] == [False, False, True] and run["flags"] == []
    page = client.get(f"/api/pages/{run['page_id']}").json()
    assert page["status"] == "review"  # passed, still never auto-approved
    st = client.get(f"/api/art-director/pages/{run['page_id']}/painted").json()
    assert len(st["candidates"]) == 3 and st["selected_id"] == run["candidates"][2]["candidate_id"]


def test_edit_box_text_repaints_and_rechecks_only(client, session, scratch_chapter):
    brief = {"chapter_id": scratch_chapter.id, "action": "Rama fits Agastya's arrow to the bow", "characters": ["rama"], "page_number": 3}
    r = client.post("/api/art-director/direct", json={"brief": brief, "settings": {"candidates": 1, "retries": 0}})
    assert wait(client, r.json()["job_id"])["status"] == "done"
    pid = client.get(f"/api/art-director/runs/{r.json()['run']['id']}").json()["page_id"]
    st = client.get(f"/api/art-director/pages/{pid}/painted").json()
    b0 = st["boxes"][0]
    text = D.manuscript_of(scratch_chapter).text
    long = next(s for s in A.sentences(text) if P.word_count(s) > 16 and "“" not in s)
    bad = client.post(f"/api/art-director/pages/{pid}/painted/boxes", json={"boxes": [{"panel": b0["panel"], "box": b0["box"], "text": long}]})
    assert bad.status_code == 422 and "split it" in bad.json()["errors"][0]
    invented = client.post(f"/api/art-director/pages/{pid}/painted/boxes", json={"boxes": [{"panel": b0["panel"], "box": b0["box"], "text": "Nobody ever wrote this line."}]})
    assert invented.status_code == 422 and "verbatim" in invented.json()["errors"][0]
    new = P.fit_box(next(s for s in A.sentences(text) if 5 <= P.word_count(s) <= 14 and "“" not in s and P.clean_box_text(s) != b0["text"]))
    ok = client.post(f"/api/art-director/pages/{pid}/painted/boxes", json={"boxes": [{"panel": b0["panel"], "box": b0["box"], "text": new}], "settings": {"candidates": 1, "retries": 0}})
    assert ok.status_code == 202, ok.text
    assert wait(client, ok.json()["job_id"])["status"] == "done"
    run2 = client.get(f"/api/art-director/runs/{ok.json()['run']['id']}").json()
    steps = [s["step"] for s in run2["steps"]]
    assert "plan" not in steps and "prompt" in steps and "critic" in steps  # repaint + text check only
    assert f"“{new}”" in run2["prompts"][0]["prompt"]
    st2 = client.get(f"/api/art-director/pages/{pid}/painted").json()
    assert st2["boxes"][0]["text"] == P.clean_box_text(new), (st2["boxes"][0]["text"], new)
    assert len(st2["candidates"]) == 2 and st2["selected_id"] == 2
    panel = next(p for p in client.get(f"/api/pages/{pid}").json()["panels"] if p["n"] == b0["panel"])
    assert new in (panel["caption_en"], panel["balloon_en"])
    # the author can still pick the first painting, and re-run only the text check on it
    assert client.post(f"/api/art-director/pages/{pid}/painted/select", json={"candidate_id": 1}).json()["selected_id"] == 1
    rv = client.post(f"/api/art-director/pages/{pid}/painted/verify", json={"candidate_id": 1}).json()
    assert rv["verdict"]["judged"] is False


def test_painted_page_exports_full_bleed(client, session, scratch_chapter):
    brief = {"chapter_id": scratch_chapter.id, "action": "Lanka burns under a storm-dark sky", "characters": ["rama"], "page_number": 4}
    r = client.post("/api/art-director/direct", json={"brief": brief, "settings": {"candidates": 1, "retries": 0}})
    assert wait(client, r.json()["job_id"])["status"] == "done"
    pid = client.get(f"/api/art-director/runs/{r.json()['run']['id']}").json()["page_id"]
    assert client.put(f"/api/pages/{pid}", json={"status": "approved"}).status_code == 200
    session.expire_all()
    pg = session.get(Page, pid)
    html = render.page_html(session, pg, paper="print", embed=True)
    W, H = L.PAGE_W + 2 * L.BLEED, L.PAGE_H + 2 * L.BLEED
    assert (W, H) == (176.0, 266.0)
    assert f"<image class='painted' x='-3.0' y='-3.0' width='{W}' height='{H}' preserveAspectRatio='xMidYMid slice'" in html
    assert "<line" in html  # crop marks
    meta = render.build_export(session, [pg], "en", "print", True, "painted-test", log=lambda *_: None)
    assert (db.DATA_DIR / "enhanced" / f"painted_{pid}_{pg.painted['selected_id']}.png").exists()  # upscaled for print
    from pypdf import PdfReader

    rd = PdfReader(str(db.DATA_DIR / meta["pdf"]))
    assert len(rd.pages) == 1
    box = rd.pages[0].mediabox
    mm = 72 / 25.4
    assert abs(float(box.width) - W * mm) < 1.5 and abs(float(box.height) - H * mm) < 1.5
    art = Path(db.DATA_DIR / pg.artifacts["en"]).read_text(encoding="utf-8")
    assert "data-mode='painted'" in art and "data:image/jpeg;base64," in art
    client.put(f"/api/pages/{pid}", json={"status": "review"})
