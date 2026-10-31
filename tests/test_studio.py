from __future__ import annotations

import shutil
import subprocess
import time

from sqlalchemy import select

from backend import db, jobs
from backend.models import Character, Page, Panel
from engine import agents
from engine.comic.proof import pdf_page_count


def wait_job(client, job_id: int, timeout: float = 600) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "stopped"):
            return j
        time.sleep(0.2)
    raise AssertionError("job timed out")


def test_seed(seeded, session):
    assert seeded["panels"] == 32 and seeded["pages"] == 10
    rama = session.scalar(select(Character).where(Character.form_key == "rama"))
    assert rama.locked and rama.primary_ref_id and rama.refs[0].approved
    assert "dark golden-brown skin" in rama.look
    assert session.scalar(select(Panel).where(Panel.n == 1).join(Page).where(Page.number == 1)).selected_candidate_id


def test_project_and_journey(client):
    p = client.get("/api/project").json()
    assert p["author"] == "Rachit Agarwal" and set(p["keys"]) == {"openai", "anthropic", "gemini", "topaz"}
    assert "Hanuman (hanuman/vanara)" in p["journey"]["chapter1_unlocked"]
    assert p["journey"]["step"] in ("manuscript", "models", "characters")
    assert len(client.get("/api/canvases").json()) == 11
    m = client.get("/api/models").json()
    assert set(m["roles"]) == {"script_writer", "prompt_writer", "critic", "image"}


def test_gate(client, session):
    # panel 2 of page 1 names hanuman/vanara, which is not locked
    pg = client.get("/api/pages?chapter_id=1").json()[0]
    page = client.get(f"/api/pages/{pg['id']}").json()
    panel = next(p for p in page["panels"] if "hanuman/vanara" in p["characters"])
    r = client.post(f"/api/panels/{panel['id']}/generate", json={"n": 1})
    assert r.status_code == 409 and "Hanuman (hanuman/vanara)" in r.json()["unlocked"]
    r = client.post(f"/api/pages/{pg['id']}/generate-all", json={"n": 1})
    assert r.status_code == 409 and r.json()["unlocked"]
    g = client.get(f"/api/pages/{pg['id']}/gate").json()
    assert g["ok"] is False and g["unlocked"]
    # the gate is per page (SPEC §6): Rama's own panel on page 5 is blocked while Ravana & co. are unlocked
    rama_panel = session.scalar(select(Panel).where(Panel.characters == ["rama"]))
    assert rama_panel is not None
    r = client.post(f"/api/panels/{rama_panel.id}/generate", json={"n": 1})
    assert r.status_code == 409
    # a lock needs an approved primary reference
    hanuman = next(c for c in client.get("/api/characters").json() if c["form_key"] == "hanuman/vanara")
    assert client.put(f"/api/characters/{hanuman['id']}", json={"locked": True}).status_code == 409
    _lock_all(client)
    assert client.get(f"/api/pages/{pg['id']}/gate").json()["ok"] is True
    r = client.post(f"/api/panels/{rama_panel.id}/generate", json={"n": 1})
    assert r.status_code == 202 and r.json()["job"]["kind"] == "panel"


def test_render_html(client):
    pages = client.get("/api/pages?chapter_id=1").json()
    for pg in pages[:3]:
        html = client.get(f"/api/pages/{pg['id']}/render?lang=hi").text
        assert html.count("<clipPath id='c") == len(pg["panels"])  # one clip per shard (callouts carry their own)
        assert "हिंदी अनुवाद लंबित" in html  # the Devanagari fallback for untranslated captions
        assert "@font-face" in html and "/api/fonts/TiroDevanagariHindi-Regular.ttf" in html  # the volume's Hindi narration face
    en = client.get(f"/api/pages/{pages[0]['id']}/render?lang=en&embed=true").text
    assert "The Last Night of Lanka" in en and "@font-face" in en and "data:image/jpeg" in en
    pr = client.get(f"/api/pages/{pages[0]['id']}/render?lang=en&paper=print").text
    assert "background-image:url(" not in pr  # print: only ink, no paper texture
    d = client.get(f"/api/pages/{pages[0]['id']}").json()
    assert 0 < d["balance"]["image"] <= 1 and set(d["balance"]) == {"image", "parchment", "ink"}


def test_shape_roundtrip(client):
    page = client.get("/api/pages/1").json()
    panel = page["panels"][1]
    shape = {"kind": "inset", "polygon_mm": [[60, 60], [100, 62], [98, 110], [58, 108]], "edge": "rim", "z": 5, "focal": {"x": 0.3, "y": 0.6, "scale": 1.4}}
    r = client.put(f"/api/panels/{panel['id']}", json={"shape": shape})
    assert r.status_code == 200
    got = r.json()["shape"]
    assert got["kind"] == "inset" and got["z"] == 5 and got["focal"] == {"x": 0.3, "y": 0.6, "scale": 1.4}
    assert got["polygon_mm"] == [[60.0, 60.0], [100.0, 62.0], [98.0, 110.0], [58.0, 108.0]] and r.json()["locked_shape"]
    again = client.get("/api/pages/1").json()["panels"][1]["shape"]
    assert again == got
    html = client.get("/api/pages/1/render").text
    assert "60.00,60.00 100.00,62.00" in html and "stroke-width='0.6'" in html  # inset: 0.6 mm ink rim
    # a re-cut keeps the author's locked shard
    client.post("/api/pages/1/recut")
    assert client.get("/api/pages/1").json()["panels"][1]["shape"] == got
    # the palette: a fresh rect in the same bbox
    r = client.put(f"/api/panels/{panel['id']}", json={"shape_kind": "rect"})
    assert r.json()["shape"]["kind"] == "rect" and len(r.json()["shape"]["polygon_mm"]) >= 8


def test_candidates_generate_and_select(client, session):
    rama_panel = session.scalar(select(Panel).where(Panel.characters == ["rama"]))
    before = len(client.get(f"/api/pages/{rama_panel.page_id}").json()["panels"][rama_panel.n - 1]["candidates"])
    r = client.post(f"/api/panels/{rama_panel.id}/generate", json={"provider": "sunburst", "n": 2, "feedback": "eyes open, wider"})
    assert r.status_code == 202
    j = wait_job(client, r.json()["job_id"])
    assert j["status"] == "done", j["log"]
    ids = j["result"]["candidate_ids"]
    assert len(ids) == 2
    panel = client.get(f"/api/pages/{rama_panel.page_id}").json()["panels"][rama_panel.n - 1]
    assert len(panel["candidates"]) == before + 2
    cand = next(c for c in panel["candidates"] if c["id"] == ids[-1])
    assert cand["qa"]["dry_run"] is True and cand["feedback_used"] == "eyes open, wider"
    assert "SCENE:" in cand["prompt_full"] and "Use the attached image(s)" in cand["prompt_full"] and "rama_reference" in " ".join(cand["qa"]["references"])
    assert (db.DATA_DIR / cand["path"]).exists()
    r = client.put(f"/api/panels/{rama_panel.id}/candidates/{ids[0]}", json={"rejected": True})
    assert r.status_code == 200 and r.json()["rejected"] is True
    r = client.post(f"/api/panels/{rama_panel.id}/select", json={"candidate_id": ids[-1]})
    assert r.status_code == 200 and r.json()["selected_candidate_id"] == ids[-1]
    assert client.get(f"/api/pages/{rama_panel.page_id}").json()["panels"][rama_panel.n - 1]["image_url"].endswith(cand["path"])


def test_scene_rewrite_fallback(client):
    scene = agents.scene_rewrite("Close-up: Rama's face, eyes closed, firelight.", "eyes open", {"caption_en": "x"})
    assert isinstance(scene, str) and scene and "eyes open" in scene.lower()
    before = client.get("/api/pages/1").json()["panels"][0]["scene"]
    r = client.post("/api/panels/1/rewrite", json={"feedback": "wider, no giants"})
    assert r.status_code == 200 and isinstance(r.json()["scene"], str) and r.json()["scene"] != before
    assert client.get("/api/pages/1").json()["panels"][0]["scene"] == before  # a proposal until the author accepts


def test_prompt_recipe(client, session):
    rama_panel = session.scalar(select(Panel).where(Panel.characters == ["rama"]))
    p = client.get(f"/api/panels/{rama_panel.id}/prompt").json()
    for key in ("Hindu graphic novel. Epic mythic graphic-novel page", "warm amber and copper", "Proportion rule", "Avoid:", "Rama, locked look", "Palette:", "SCENE:"):
        assert key in p["prompt"]
    assert "Advent Children" not in p["prompt"] and "FF7" not in p["prompt"]
    assert p["reference_names"] == ["Rama"]


def test_silhouettes_and_marginalia(client):
    r = client.post("/api/silhouettes/generate", json={"prompt": "", "tags": ["compass rose", "coastal map"], "n": 1})
    j = wait_job(client, r.json()["job_id"])
    assert j["status"] == "done", j["log"]
    sils = client.get("/api/silhouettes").json()
    assert sils and sils[-1]["tags"] == ["compass rose", "coastal map"] and "no text" in sils[-1]["prompt"]
    r = client.put("/api/pages/2", json={"marginalia": [{"silhouette_id": sils[-1]["id"], "x_mm": 120, "y_mm": 200, "w_mm": 30, "rotation": 10, "tint": "#b3261e"}]})
    assert r.status_code == 200 and r.json()["balance"]["ink"] > 0
    html = client.get("/api/pages/2/render").text
    assert "feColorMatrix type='matrix'" in html and "class='marginalia'" in html


def _lock_all(client):
    """Lock every character named in Chapter 1: upload a reference, approve it, make it primary, lock."""
    keys = {k for pg in client.get("/api/pages?chapter_id=1").json() for p in pg["panels"] for k in p["characters"]}
    png = (db.DATA_DIR / "ch1_candidates" / "0101_0.png").read_bytes()
    for c in client.get("/api/characters").json():
        if c["locked"] or c["form_key"] not in keys:
            continue
        refs = client.post(f"/api/characters/{c['id']}/refs/upload", files=[("files", ("ref.png", png, "image/png"))]).json()
        client.put(f"/api/characters/{c['id']}/refs/{refs[0]['id']}", json={"approved": True, "is_primary": True})
        assert client.put(f"/api/characters/{c['id']}", json={"locked": True}).json()["locked"]


def test_director_batch_dry_run(client, session):
    _lock_all(client)
    pages = client.get("/api/pages?chapter_id=1").json()
    p1, p2 = pages[0], pages[1]
    for pg in (p1, p2):
        full = client.get(f"/api/pages/{pg['id']}").json()
        for panel in full["panels"]:
            client.post(f"/api/panels/{panel['id']}/select", json={"candidate_id": None})
        client.put(f"/api/pages/{pg['id']}", json={"status": "draft"})
    est = client.get("/api/director/estimate", params={"chapter_id": 1, "pages": "1,2", "candidates_per_panel": 2}).json()
    assert est["panels"] == 9 and est["images"] == 18 and est["usd"] == 0.0
    r = client.post("/api/director/batch", json={"chapter_id": 1, "pages": [1, 2], "candidates_per_panel": 2, "provider": "sunburst", "run_critic": True})
    assert r.status_code == 202
    j = wait_job(client, r.json()["job_id"])
    assert j["status"] == "done", j["log"]
    assert j["result"]["pages_done"] == [1, 2] and j["progress"]["done"] == 2
    for pg in (p1, p2):
        full = client.get(f"/api/pages/{pg['id']}").json()
        assert full["status"] == "review"
        for panel in full["panels"]:
            fresh = [c for c in panel["candidates"] if c["qa"].get("dry_run")]
            assert len(fresh) >= 2 and panel["selected_candidate_id"] in [c["id"] for c in fresh]


def test_stop_batch(client):
    _lock_all(client)
    r = client.post("/api/director/batch", json={"chapter_id": 1, "pages": {"next": 3}, "candidates_per_panel": 1})
    jid = r.json()["job_id"]
    assert r.json()["job"]["kind"] == "batch"
    client.post(f"/api/jobs/{jid}/stop")
    j = wait_job(client, jid)
    assert j["status"] in ("stopped", "done")


def test_approve_artifacts_and_export(client):
    _lock_all(client)
    pages = client.get("/api/pages?chapter_id=1").json()
    r = client.post("/api/export", json={"chapter_id": 1, "lang": ["en"], "paper": "print"})
    assert r.status_code == 409 and r.json()["unapproved"]
    est = client.post("/api/export/estimate", json={"chapter_id": 1, "lang": ["en"], "paper": "print", "upscale": False}).json()
    assert est["total"] == 10 and est["approved"] + est["unapproved"] == 10
    for pg in pages:
        r = client.put(f"/api/pages/{pg['id']}", json={"status": "approved"})
        assert r.status_code == 200 and r.json()["artifact"].endswith(f"page-{pg['number']:03d}-en.html")
        assert (db.DATA_DIR / r.json()["artifacts"]["hi"]).exists()
    assert client.post("/api/pages/1/recut").status_code == 409  # frozen
    r = client.post("/api/export", json={"chapter_id": 1, "lang": ["en"], "paper": "print", "upscale": False})
    assert r.status_code == 202
    j = wait_job(client, r.json()["job_id"], timeout=900)
    assert j["status"] == "done", j["log"]
    pdf = db.DATA_DIR / j["result"]["pdf"]
    rec = client.get("/api/exports").json()[0]
    assert rec["status"] == "done" and rec["files"][0]["url"].startswith("/media/exports/") and rec["files"][0]["bytes"] > 100_000
    assert client.get(rec["files"][0]["url"]).status_code == 200
    assert pdf.exists() and pdf.stat().st_size > 100_000
    if shutil.which("pdfinfo"):
        out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
        assert "Pages:          10" in out.replace("Pages:           10", "Pages:          10")
    else:
        assert pdf_page_count(pdf) == 10
    assert rec["files"][0]["pages"] == list(range(1, 11))
    assert client.get("/api/ledger").json()["total"] == 0.0


def test_updater_routes(client, monkeypatch):
    from backend import updater

    v = client.get("/api/app/version").json()
    assert "build" in v and v["updatable"] is False  # source checkout never self-updates
    monkeypatch.setattr(updater, "current", lambda: {"build": 5, "sha": "abc", "updatable": True, "desktop": True, "app_path": "/x"})

    class R:
        def raise_for_status(self): ...
        def json(self): return {"build": 7, "sha": "def"}

    monkeypatch.setattr(updater.httpx, "get", lambda *a, **k: R())
    chk = client.get("/api/app/update/check").json()
    assert chk["available"] is True and chk["latest"]["build"] == 7
    monkeypatch.setattr(updater.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    assert client.get("/api/app/update/check").json()["available"] is False
    assert client.post("/api/app/update/apply").json()["ok"] in (True, False)
