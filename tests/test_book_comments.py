"""Book comments: pins on page elements, applied by the LLM / image engine (both MOCKED: no network, no keys), patches
(art sub-layer), page review states and the progress of the comic. Synthetic package only (never the real book)."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from PIL import Image

from backend import book_comments as BC
from backend import db
from engine import providers
from tests.test_book_layers import make_package

B = "/api/book"


def wait_job(client, jid, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "failed", "stopped"):
            return j
        time.sleep(0.1)
    raise AssertionError("job timed out")


class FakeModel:
    """Stands in for Claude: returns the queued answers, remembers what it was asked."""

    def __init__(self) -> None:
        self.answers: list = []
        self.calls: list[dict] = []

    def __call__(self, system, user, images):
        self.calls.append({"system": system, "user": json.loads(user), "images": [Path(i).name for i in images]})
        assert images and all(Path(i).exists() for i in images)
        return self.answers.pop(0), {"provider": "anthropic", "model": "claude-mock", "cost_usd": 0.0123}


class FakeImages:
    """Stands in for Sunburst /v1/images/edits: paints the whole image magenta, remembers the mask."""

    def __init__(self, refuse_mask: bool = False) -> None:
        self.calls: list[dict] = []
        self.refuse_mask = refuse_mask

    def __call__(self, image_png, prompt, size, mask_png):
        self.calls.append({"prompt": prompt, "size": size, "mask": mask_png is not None})
        if mask_png is not None and self.refuse_mask:
            raise RuntimeError("400 mask not supported")
        w, h = (int(v) for v in size.split("x"))
        buf = io.BytesIO()
        Image.new("RGB", (w, h), (255, 0, 255)).save(buf, "PNG")
        return providers.ImageResult(buf.getvalue(), "sunburst", "gpt-image-mock", 0.21, False)


@pytest.fixture()
def model(monkeypatch):
    m = FakeModel()
    monkeypatch.setattr(BC, "ask_model", m)
    return m


@pytest.fixture()
def images(monkeypatch):
    f = FakeImages()
    monkeypatch.setattr(BC, "image_edit", f)
    return f


@pytest.fixture()
def book(client, tmp_path):
    pkg = make_package(tmp_path)
    m = json.loads((pkg / "manifest.json").read_text())
    m["format"] = "dharma-book/2"
    m["pages"][1]["art"]["patches"] = [{"id": "pa1", "x": 600, "y": 700, "w": 400, "h": 200, "linked": "002-t1"},
                                       {"id": "pa2", "x": 300, "y": 2400, "w": 300, "h": 150, "linked": None}]
    (pkg / "manifest.json").write_text(json.dumps(m, ensure_ascii=False))
    r = client.post(f"{B}/import", json={"path": str(pkg)})
    assert r.status_code == 200, r.text
    b = r.json()
    yield b
    client.delete(f"{B}/books/{b['id']}")


def add(client, bid, pid, anchor, text="please fix"):
    r = client.post(f"{B}/books/{bid}/pages/{pid}/comments", json={"anchor": anchor, "text": text})
    assert r.status_code == 200, r.text
    return r.json()["created"], r.json()


def apply(client, bid, pid, cid):
    r = client.post(f"{B}/books/{bid}/pages/{pid}/comments/{cid}/apply")
    assert r.status_code == 202, r.text
    return wait_job(client, r.json()["job_id"])


def comment(page, cid):
    return next(c for c in page["comments"] if c["id"] == cid)


# --- anchors --------------------------------------------------------------------


def test_anchor_for_every_layer(client, book):
    bid = book["id"]
    c1, _ = add(client, bid, "001", {"layer": "text", "element": "001-t2", "x": 300, "y": 450})
    c2, _ = add(client, bid, "001", {"layer": "paper", "element": "shloka", "x": 900, "y": 60})
    c3, _ = add(client, bid, "001", {"layer": "paper", "element": "figure:1", "x": 1800, "y": 1200})
    c4, _ = add(client, bid, "001", {"layer": "paper", "element": "folio", "x": 1900, "y": 2980})
    c5, _ = add(client, bid, "001", {"layer": "art", "x": 1000, "y": 1500, "rect": {"x": 900, "y": 1400, "w": 300, "h": 250}})
    c6, _ = add(client, bid, "002", {"layer": "art", "element": "patch:pa1", "x": 700, "y": 750})
    c7, pg = add(client, bid, "001", {"layer": "page", "x": 10, "y": 10}, "tighten the whole page")
    cs = {c["id"]: c for c in pg["comments"]}
    assert [cs[c]["n"] for c in (c1, c2, c3, c4, c5, c7)] == [1, 2, 3, 4, 5, 6]
    assert cs[c1]["anchor"]["element"] == "001-t2" and cs[c1]["status"] == "open"
    assert cs[c5]["anchor"]["rect"] == {"x": 900, "y": 1400, "w": 300, "h": 250}
    assert cs[c7]["anchor"] == {"layer": "page", "element": None, "x": 10, "y": 10}
    p2 = client.get(f"{B}/books/{bid}/pages/002").json()
    assert comment(p2, c6)["anchor"]["rect"] == {"x": 600, "y": 700, "w": 400, "h": 200}  # the patch's rectangle
    # bad anchors
    for a in ({"layer": "text", "element": "nope"}, {"layer": "paper", "element": "figure:9"}, {"layer": "art", "element": "patch:zz"}, {"layer": "sky"}):
        assert client.post(f"{B}/books/{bid}/pages/001/comments", json={"anchor": a, "text": "x"}).status_code == 400
    assert client.post(f"{B}/books/{bid}/pages/001/comments", json={"anchor": {"layer": "page"}, "text": " "}).status_code == 400
    # comments go through history; the render does not change (no new thumb)
    hist = client.get(f"{B}/books/{bid}/pages/001/history").json()
    assert hist[0]["action"].startswith("add comment")
    rev = pg["rev"]
    r = client.patch(f"{B}/books/{bid}/pages/001/comments/{c4}", json={"status": "dismissed"}).json()
    assert comment(r, c4)["status"] == "dismissed" and r["rev"] == rev
    r = client.delete(f"{B}/books/{bid}/pages/001/comments/{c3}").json()
    assert all(c["id"] != c3 for c in r["comments"])
    assert client.get(f"{B}/books/{bid}").json()["progress"]["open_comments"] == 5  # 4 open on page 1 (one dismissed, one deleted) + 1 on page 2


# --- text -----------------------------------------------------------------------


def test_text_patch_applies_one_step(client, book, model):
    bid = book["id"]
    cid, _ = add(client, bid, "001", {"layer": "text", "element": "001-t2", "x": 300, "y": 450}, "shorter, and move it down")
    model.answers.append({"summary": "Shortened caption 2; moved it down", "patch": {"text": "Alpha narration.", "y": 900, "size_px": 46}})
    j = apply(client, bid, "001", cid)
    assert j["status"] == "done", j["log"]
    asked = model.calls[0]["user"]
    assert asked["anchor"]["element"] == "001-t2" and asked["page"]["text_boxes"][1]["id"] == "001-t2"
    assert asked["next_page"] == ["Beta speaks through glass."] and "Inter Tight" in asked["fonts"] and "glass" in asked["styles"]["text_styles"]
    assert "16 words" in model.calls[0]["system"] and "Devanagari" in model.calls[0]["system"]
    p = client.get(f"{B}/books/{bid}/pages/001").json()
    t = p["text"][1]
    assert (t["text"], t["y"], t["size"]) == ("Alpha narration.", 900, 46)
    c = comment(p, cid)
    assert c["status"] == "applied" and c["result"]["summary"] == "Shortened caption 2; moved it down" and c["result"]["cost"] == pytest.approx(0.0123)
    seq = c["result"]["history_seq"]
    assert client.get(f"{B}/books/{bid}/pages/001/history").json()[0]["seq"] == seq
    assert "Alpha narration on parchment." in client.get(f"{B}/books/{bid}/pages/001/render?seq={seq}").text  # the before view
    assert j["cost_usd"] == pytest.approx(0.0123, abs=1e-4)
    assert f"comment {cid}" in json.dumps(client.get("/api/ledger").json())
    # one undo reverts the applied comment (text back, comment open again)
    r = client.post(f"{B}/books/{bid}/pages/001/comments/{cid}/revert").json()
    assert r["text"][1]["text"] == "Alpha narration on parchment." and comment(r, cid)["status"] == "open"
    # Revert still works when only comments changed after the apply (the other comments are kept) …
    model.answers.append({"summary": "Shortened caption 2", "patch": {"text": "Alpha."}})
    assert apply(client, bid, "001", cid)["status"] == "done"
    other, _ = add(client, bid, "001", {"layer": "page", "x": 0, "y": 0}, "later note")
    r = client.post(f"{B}/books/{bid}/pages/001/comments/{cid}/revert")
    assert r.status_code == 200, r.text
    assert r.json()["text"][1]["text"] == "Alpha narration on parchment." and comment(r.json(), cid)["status"] == "open" and comment(r.json(), other)["status"] == "open"
    # … but not after a real edit of the page
    model.answers.append({"summary": "Shortened caption 2", "patch": {"text": "Alpha."}})
    assert apply(client, bid, "001", cid)["status"] == "done"
    client.patch(f"{B}/books/{bid}/pages/001/text/001-t1", json={"x": 150})
    assert client.post(f"{B}/books/{bid}/pages/001/comments/{cid}/revert").status_code == 409


@pytest.mark.parametrize("answer,why", [
    ({"summary": "x", "patch": {"x": 1900, "w": 400}}, "leave the page"),
    ({"summary": "x", "patch": {"y": -20}}, "leave the page"),
    ({"summary": "x", "patch": {"tail": [5000, 10]}}, "outside the page"),
    ({"summary": "x", "patch": {"text": "राम"}}, "Devanagari"),
    ({"summary": "x", "patch": {"text": " ".join(["word"] * 30)}}, "words"),
    ({"summary": "x", "patch": {"color": "red"}}, "outside the schema"),
    ({"summary": "x", "patch": {"style": "neon"}}, "style must be"),
    ({"summary": "x", "id": "001-t1", "patch": {"text": "Other"}}, "other than"),
    ({"summary": "x", "patches": [{"target": "text:001-t1", "set": {"text": "Other"}}]}, "other than"),
])
def test_text_patch_validation(client, book, model, answer, why):
    bid = book["id"]
    cid, _ = add(client, bid, "001", {"layer": "text", "element": "001-t2", "x": 300, "y": 450})
    model.answers.append(answer)
    j = apply(client, bid, "001", cid)
    assert j["status"] == "failed" and why in j["log"]
    p = client.get(f"{B}/books/{bid}/pages/001").json()
    c = comment(p, cid)
    assert c["status"] == "open" and why in c["result"]["error"]
    assert p["text"][1]["text"] == "Alpha narration on parchment." and p["text"][0]["text"] == "BOOK ONE · 1 · Synthetic Night"


# --- paper ----------------------------------------------------------------------


def test_paper_patch_ids_only(client, book, model):
    bid = book["id"]
    cid, _ = add(client, bid, "003", {"layer": "paper", "element": "shloka", "x": 900, "y": 60}, "a shloka about duty")
    model.answers.append({"summary": "Chose Gita 2.47", "paper": {"shloka_id": "gita-2-47"}})
    assert apply(client, bid, "003", cid)["status"] == "done"
    assert "shloka_library" in model.calls[0]["user"] and any(s["id"] == "gita-2-47" for s in model.calls[0]["user"]["shloka_library"])
    p = client.get(f"{B}/books/{bid}/pages/003").json()
    assert p["paper"]["shloka"]["id"] == "gita-2-47" and "कर्मण्येवाधिकारस्ते" in " ".join(p["paper"]["shloka"]["lines"])
    # the model may not write Sanskrit, invent ids, or touch another element
    for ans, why in (({"summary": "x", "paper": {"shloka": {"lines": ["नया श्लोक"], "source": "made up"}}}, "never written"),
                     ({"summary": "x", "paper": {"shloka_id": "invented-1"}}, "unknown shloka"),
                     ({"summary": "x", "paper": {"texture": "page_aged"}}, "outside the comment's anchor")):
        c2, _ = add(client, bid, "003", {"layer": "paper", "element": "shloka", "x": 900, "y": 60})
        model.answers.append(ans)
        j = apply(client, bid, "003", c2)
        assert j["status"] == "failed" and why in j["log"], j["log"]
    # a figure by name from the library; texture by name
    c3, _ = add(client, bid, "003", {"layer": "paper", "element": "figure:0", "x": 20, "y": 2500})
    model.answers.append({"summary": "Swapped the figure for Hanuman", "paper": {"figure": {"name": "hanuman", "opacity": 0.3}}})
    assert apply(client, bid, "003", c3)["status"] == "done"
    f = client.get(f"{B}/books/{bid}/pages/003").json()["paper"]["figures"]
    assert f[0]["name"] == "hanuman" and f[0]["opacity"] == 0.3 and f[0]["y"] == 2400 and f[1]["name"] == "shivalinga"
    c4, _ = add(client, bid, "003", {"layer": "paper", "element": "figure:1", "x": 1800, "y": 1100})
    model.answers.append({"summary": "x", "paper": {"figure": {"name": "dragon"}}})
    assert apply(client, bid, "003", c4)["status"] == "failed"


# --- art ------------------------------------------------------------------------


def test_art_region_edit_versions_and_restore(client, book, images):
    bid = book["id"]
    bdir = db.DATA_DIR / "books" / bid
    before = Image.open(bdir / "art" / "001.jpg").convert("RGB")
    cid, _ = add(client, bid, "001", {"layer": "art", "x": 1000, "y": 1500, "rect": {"x": 900, "y": 1400, "w": 300, "h": 250}}, "add a burning torch")
    j = apply(client, bid, "001", cid)
    assert j["status"] == "done", j["log"]
    call = images.calls[0]
    assert call["mask"] and call["size"] == "1024x1536"
    assert "add a burning torch" in call["prompt"] and BC.HOUSE_STYLE in call["prompt"] and BC.NO_TEXT in call["prompt"]
    p = client.get(f"{B}/books/{bid}/pages/001").json()
    assert p["art"]["file"] == "art/001_v1.jpg" and (bdir / "art" / "001.jpg").exists()  # never overwritten
    new = Image.open(bdir / p["art"]["file"]).convert("RGB")
    assert new.size == before.size
    # only the region changed: its centre is magenta, a corner is the old painting
    W = p["art"]["w"]
    s = before.size[0] / W
    cx, cy = round((1050 - 104) * s), round((1525 - 170) * s)
    assert new.getpixel((cx, cy))[0] > 200 and new.getpixel((cx, cy))[1] < 60
    assert abs(new.getpixel((5, 5))[0] - before.getpixel((5, 5))[0]) < 12
    c = comment(p, cid)
    assert c["result"]["cost"] == pytest.approx(0.21) and "Repainted the marked region" in c["result"]["summary"]
    # a second edit: v2; restoring the version before the first brings 001.jpg back
    c2, _ = add(client, bid, "001", {"layer": "art", "x": 500, "y": 500}, "warmer firelight")
    assert apply(client, bid, "001", c2)["status"] == "done"
    assert not images.calls[1]["mask"]
    assert client.get(f"{B}/books/{bid}/pages/001").json()["art"]["file"] == "art/001_v2.jpg"
    r = client.post(f"{B}/books/{bid}/pages/001/restore", json={"seq": c["result"]["history_seq"]}).json()
    assert r["art"]["file"] == "art/001.jpg" and comment(r, cid)["status"] == "open"
    assert f"/media/books/{bid}/art/001.jpg" in client.get(f"{B}/books/{bid}/pages/001/render").text


def test_art_mask_refused_falls_back(client, book, monkeypatch):
    f = FakeImages(refuse_mask=True)
    monkeypatch.setattr(BC, "image_edit", f)
    bid = book["id"]
    cid, _ = add(client, bid, "001", {"layer": "art", "x": 1000, "y": 1500, "rect": {"x": 900, "y": 1400, "w": 300, "h": 250}})
    assert apply(client, bid, "001", cid)["status"] == "done"
    assert [c["mask"] for c in f.calls] == [True, False] and "Change ONLY the marked region" in f.calls[1]["prompt"]
    res = comment(client.get(f"{B}/books/{bid}/pages/001").json(), cid)["result"]
    assert any("refused the mask" in n for n in res["notes"])


def test_art_dry_run_without_key(client, book, monkeypatch):
    """No OpenAI key: the real provider paints a labelled placeholder region (no network); the flow still completes."""
    from engine.settings import settings

    monkeypatch.setattr(settings, "openai_api_key", None)
    bid = book["id"]
    cid, _ = add(client, bid, "002", {"layer": "art", "x": 700, "y": 750, "element": "patch:pa1"}, "repaint this patch area into the scene")
    assert apply(client, bid, "002", cid)["status"] == "done"
    p = client.get(f"{B}/books/{bid}/pages/002").json()
    assert p["art"]["file"] == "art/002_v1.jpg" and [x["id"] for x in p["art"]["patches"]] == ["pa2"]  # the patch is gone
    res = comment(p, cid)["result"]
    assert "removed the patch" in res["summary"] and any("dry run" in n for n in res["notes"])
    # one undo: the patch and the old painting come back
    r = client.post(f"{B}/books/{bid}/pages/002/undo").json()["page"]
    assert r["art"]["file"] == "art/002.jpg" and [x["id"] for x in r["art"]["patches"]] == ["pa1", "pa2"]


# --- page level -----------------------------------------------------------------


def test_page_level_multi_patch_is_one_undo(client, book, model):
    bid = book["id"]
    cid, _ = add(client, bid, "003", {"layer": "page", "x": 0, "y": 0}, "tighten everything")
    n_hist = len(client.get(f"{B}/books/{bid}/pages/003/history").json())
    model.answers.append({"summary": "Shortened both boxes; aged paper", "patches": [
        {"target": "text:003-t1", "set": {"text": "Gamma.", "x": 200}},
        {"target": "text:003-t2", "set": {"text": "Delta.", "align": "left"}},
        {"target": "paper", "set": {"texture": "page_aged"}},
        {"target": "figure:1", "set": None}]})
    assert apply(client, bid, "003", cid)["status"] == "done"
    p = client.get(f"{B}/books/{bid}/pages/003").json()
    assert [t["text"] for t in p["text"]] == ["Gamma.", "Delta."] and p["paper"]["texture"] == "page_aged" and len(p["paper"]["figures"]) == 1
    assert len(client.get(f"{B}/books/{bid}/pages/003/history").json()) == n_hist + 1
    r = client.post(f"{B}/books/{bid}/pages/003/undo").json()["page"]
    assert [t["text"] for t in r["text"]] == ["Gamma modern narration.", "Delta modern voice."] and r["paper"]["texture"] == "page_warm" and len(r["paper"]["figures"]) == 2
    assert comment(r, cid)["status"] == "open"
    # one bad patch rejects the whole answer
    model.answers.append({"summary": "x", "patches": [{"target": "text:003-t1", "set": {"text": "ok"}}, {"target": "text:003-t2", "set": {"w": 5000}}]})
    assert apply(client, bid, "003", cid)["status"] == "failed"
    assert client.get(f"{B}/books/{bid}/pages/003").json()["text"][0]["text"] == "Gamma modern narration."


def test_apply_all_open(client, book, model):
    bid = book["id"]
    a, _ = add(client, bid, "003", {"layer": "text", "element": "003-t1", "x": 0, "y": 0})
    b, _ = add(client, bid, "003", {"layer": "text", "element": "003-t2", "x": 0, "y": 0})
    model.answers += [{"summary": "one", "patch": {"text": "One."}}, {"summary": "two", "patch": {"text": "Two."}}]
    r = client.post(f"{B}/books/{bid}/pages/003/comments/apply-all")
    j = wait_job(client, r.json()["job_id"])
    assert j["status"] == "done" and len(j["result"]["applied"]) == 2
    p = client.get(f"{B}/books/{bid}/pages/003").json()
    assert [t["text"] for t in p["text"]] == ["One.", "Two."]
    # two history steps: the first undo reverts only the second comment
    r = client.post(f"{B}/books/{bid}/pages/003/undo").json()["page"]
    assert [t["text"] for t in r["text"]] == ["One.", "Delta modern voice."]
    assert client.post(f"{B}/books/{bid}/pages/003/comments/apply-all").status_code == 202  # b is open again


# --- patches --------------------------------------------------------------------


def test_patches_render_hide_remove(client, book):
    bid = book["id"]
    html = client.get(f"{B}/books/{bid}/pages/002/render").text
    assert html.count("class='patch'") == 2 and "data-patch='pa1'" in html and "page_warm.jpg" in html
    assert html.index("class='art-img'") < html.index("data-patch='pa1'")  # over the painting, under the text
    p = client.patch(f"{B}/books/{bid}/pages/002/art/patches/pa1", json={"hidden": True}).json()
    assert p["art"]["patches"][0]["hidden"] is True
    html = client.get(f"{B}/books/{bid}/pages/002/render").text
    assert "data-patch='pa1'" not in html and "data-patch='pa2'" in html
    p = client.delete(f"{B}/books/{bid}/pages/002/art/patches/pa2").json()
    assert [x["id"] for x in p["art"]["patches"]] == ["pa1"]
    assert client.delete(f"{B}/books/{bid}/pages/002/art/patches/nope").status_code == 404
    # the art layer off hides the patches too
    client.put(f"{B}/books/{bid}/pages/002/layers", json={"art": False, "paper": True, "text": True})
    client.patch(f"{B}/books/{bid}/pages/002/art/patches/pa1", json={"hidden": False})
    assert "class='patch'" not in client.get(f"{B}/books/{bid}/pages/002/render").text
    assert client.get(f"{B}/books/{bid}").json()["pages_list"][1]["patches"] == 1
    # the exported package carries them (format /2)
    m = __import__("backend.book_store", fromlist=["x"]).manifest(bid)
    assert m["format"] == "dharma-book/2" and m["pages"][1]["art"]["patches"][0]["id"] == "pa1"


def test_backward_compatible_without_patches(client, tmp_path):
    pkg = make_package(tmp_path)  # dharma-book/1, no patches, no status, no comments
    b = client.post(f"{B}/import", json={"path": str(pkg)}).json()
    try:
        p = client.get(f"{B}/books/{b['id']}/pages/001").json()
        assert "patches" not in p["art"] and p["status"] == "draft" and p["comments"] == []
        assert "class='patch'" not in client.get(f"{B}/books/{b['id']}/pages/001/render").text
        assert __import__("backend.book_store", fromlist=["x"]).manifest(b["id"])["format"] == "dharma-book/1"
        assert client.get(f"{B}/books/{b['id']}/pages/001/thumb").status_code == 200
    finally:
        client.delete(f"{B}/books/{b['id']}")


# --- approval -------------------------------------------------------------------


def test_approval_and_progress(client, book, monkeypatch):
    bid = book["id"]
    pr = client.get(f"{B}/books/{bid}/progress").json()
    assert (pr["pages"], pr["approved"], pr["open_comments"]) == (3, 0, 0) and [u["number"] for u in pr["unapproved"]] == [1, 2, 3]
    assert client.put(f"{B}/books/{bid}/pages/001/status", json={"status": "approved"}).json()["status"] == "approved"
    assert client.put(f"{B}/books/{bid}/pages/002/status", json={"status": "review"}).json()["status"] == "review"
    assert client.put(f"{B}/books/{bid}/pages/002/status", json={"status": "done"}).status_code == 400
    cid, _ = add(client, bid, "003", {"layer": "page", "x": 0, "y": 0})
    r = client.put(f"{B}/books/{bid}/pages/003/status", json={"status": "approved"})
    assert r.status_code == 409 and r.json()["detail"]["open_comments"] == 1  # approving with open comments asks first
    assert client.put(f"{B}/books/{bid}/pages/003/status", json={"status": "approved", "force": True}).json()["status"] == "approved"
    bk = client.get(f"{B}/books/{bid}").json()
    assert bk["progress"] == {"pages": 3, "approved": 2, "review": 1, "draft": 0, "open_comments": 1}
    assert [(p["status"], p["open_comments"]) for p in bk["pages_list"]] == [("approved", 0), ("review", 0), ("approved", 1)]
    # Finish: refused while a page is unapproved, lists it; forced -> PDF job + package
    from backend import book_api

    submitted = []
    monkeypatch.setattr(book_api, "export_pdf", lambda b, body, session: submitted.append(body) or {"job_id": 0, "job": {}})
    r = client.post(f"{B}/books/{bid}/finish", json={})
    assert r.status_code == 409 and r.json()["detail"]["unapproved"] == [{"id": "002", "number": 2}]
    r = client.post(f"{B}/books/{bid}/finish", json={"force": True})
    assert r.status_code == 202 and r.json()["package"]["name"].endswith(".dharmabook") and submitted == [{"paper": "print", "cover": True}]
    client.put(f"{B}/books/{bid}/pages/002/status", json={"status": "approved"})
    assert client.post(f"{B}/books/{bid}/finish", json={}).status_code == 202
