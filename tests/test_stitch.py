"""Stitch: graphic-novel art in the blank space of a typeset book PDF.

Everything runs on a synthetic PDF and synthetic images made inside the test (never the real book or its art)."""

from __future__ import annotations

import io
import time
from pathlib import Path

import pymupdf as fitz
import pytest
from PIL import Image, ImageDraw

from backend import stitch_api as SA
from backend import stitch_store as SS
from engine import stitch as E

A = "/api/stitch"
W, H = 432, 648
WORDS = ("Rama looked across the burning field and the vanara army waited in the ash while the chariots circled "
         "each other under a red sky and nobody spoke a word").split()


def _lines(n: int, seed: int) -> list[str]:
    out = []
    for i in range(n):
        k = (i * 7 + seed) % len(WORDS)
        out.append(" ".join((WORDS[k:] + WORDS[:k])[:9]))
    return out


def make_pdf() -> bytes:
    """Eight 6x9 pages: openers (deep top margin), full text pages, chapter ends (blank bottom), folios; the recto
    and verso text columns alternate like the paperback's."""
    doc = fitz.open()
    plan = ["opener", "text", "end", "opener", "text", "text", "end", "text"]
    for i, kind in enumerate(plan):
        n = i + 1
        pg = doc.new_page(width=W, height=H)
        x0 = 59 if n % 2 else 43
        if kind == "opener":
            pg.insert_text((x0 + 120, 165), f"{n}", fontsize=12)
            pg.insert_text((x0 + 60, 185), f"Chapter heading {n}", fontsize=16)
            y, count = 214, 22
        elif kind == "end":
            y, count = 66, 12
        else:
            y, count = 66, 31
        for j, line in enumerate(_lines(count, n)):
            pg.insert_text((x0, y + j * 17.25), line, fontsize=10.5)
        pg.insert_text((W / 2 - 4, 622), str(n), fontsize=9)   # folio
    return doc.tobytes()


def make_photo(path: Path, colour: tuple[int, int, int], size: tuple[int, int] = (600, 900)) -> Path:
    im = Image.new("RGB", size, colour)
    d = ImageDraw.Draw(im)
    for k in range(0, size[0], 37):   # some structure so crops differ
        d.line([(k, 0), (size[0] - k, size[1])], fill=(255 - colour[0], 200, 90), width=3)
    d.ellipse([size[0] * 0.3, size[1] * 0.3, size[0] * 0.6, size[1] * 0.5], fill=(220, 150, 110))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "JPEG", quality=88)
    return path


def wait_job(client, jid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "failed", "stopped"):
            return j
        time.sleep(0.3)
    raise AssertionError("job timed out")


@pytest.fixture()
def pdf_bytes():
    return make_pdf()


@pytest.fixture()
def project(client, pdf_bytes):
    r = client.post(f"{A}/projects/upload", files={"file": ("synthetic.pdf", pdf_bytes, "application/pdf")}, data={"title": "Synthetic"})
    assert r.status_code == 200, r.text
    p = r.json()
    yield p
    client.delete(f"{A}/projects/{p['id']}")


@pytest.fixture()
def photos(client, tmp_path):
    files = [make_photo(tmp_path / f"art{i}.jpg", c) for i, c in enumerate([(150, 40, 20), (30, 60, 140), (40, 110, 50), (120, 100, 30)])]
    r = client.post(f"{A}/repo/upload", files=[("files", (f.name, f.read_bytes(), "image/jpeg")) for f in files], data={"tags": "synthetic, test"})
    assert r.status_code == 200, r.text
    ids = r.json()["ids"]
    assert len(ids) == 4
    return ids


def slots_of(page: dict) -> dict[str, list[float]]:
    return {s["id"]: s["rect"] for s in page["slots"]}


def inside(r, box, tol=0.6) -> bool:
    return r[0] >= box[0] - tol and r[1] >= box[1] - tol and r[2] <= box[2] + tol and r[3] <= box[3] + tol


# --- analysis -------------------------------------------------------------------


def test_analyse_finds_opener_end_and_corner_slots(pdf_bytes):
    a = E.analyse(pdf_bytes)
    assert a["count"] == 8 and a["size"] == [W, H]
    kinds = [p["kind"] for p in a["pages"]]
    assert kinds == ["opener", "text", "end", "opener", "text", "text", "end", "text"]
    for p in a["pages"]:
        s = slots_of(p)
        assert p["folio"], "the page number is found and kept out of the text blocks"
        if p["kind"] == "opener":
            assert "top" in s and s["top"][3] < min(b[1] for b in p["blocks"])
            assert p["free_top"] > 100
        if p["kind"] == "end":
            assert "bottom" in s and s["bottom"][1] > max(b[3] for b in p["blocks"])
            assert p["free_bottom"] >= E.MIN_END_FREE
        if p["kind"] in ("text", "end"):
            c = s["corner"]
            assert (c[0] > W / 2) == (p["n"] % 2 == 1), "the icon goes in the outer corner (right on odd pages)"
            assert p["outer"] == ("right" if p["n"] % 2 else "left")
        for r in s.values():   # no slot touches text or the folio
            assert E._clear(r, p["blocks"] + p["folio"])
    assert a["pages"][1]["slots"] and "bottom" not in slots_of(a["pages"][1]), "a full page has no bottom slot"


# --- drawing --------------------------------------------------------------------


@pytest.mark.parametrize("style,slot,page,n", [("strip", "top", 1, 1), ("collage", "bottom", 3, 3), ("icon", "corner", 2, 1), ("torn", "bottom", 7, 1), ("torn", "top", 4, 1)])
def test_each_style_renders_inside_its_slot(pdf_bytes, tmp_path, style, slot, page, n):
    a = E.analyse(pdf_bytes)
    info = a["pages"][page - 1]
    rect = slots_of(info)[slot]
    ims = {f"p{i}": Image.open(make_photo(tmp_path / f"{i}.jpg", (40 * i + 30, 80, 120))) for i in range(4)}
    for tilt in (0, 4):
        pl = {"id": "x", "page": page, "rect": rect, "style": style, "pieces": [{"photo": f"p{i}"} for i in range(max(n, 2 if style == "collage" else 1))],
              "tilt": tilt, "size": 1.0, "sepia": 0.2, "seed": 11}
        r = E.render_placement(pl, ims.__getitem__)
        assert inside(r.rect, rect), (r.rect, rect)
        assert E._clear(list(r.rect), info["blocks"] + info["folio"])
        im = Image.open(io.BytesIO(r.png))
        assert im.mode == "RGBA" and im.getchannel("A").getextrema() == (0, 255)
        # roughly 300 dpi: the image is not upscaled past its pixels
        assert im.width / (r.rect[2] - r.rect[0]) >= E.DPI * 0.98
    small = E.render_placement({**pl, "size": 0.5}, ims.__getitem__)
    assert (small.rect[2] - small.rect[0]) < (r.rect[2] - r.rect[0])


def test_crop_follows_the_subject():
    im = Image.new("RGB", (400, 400), (0, 0, 255))
    im.paste((255, 0, 0), (0, 0, 200, 200))
    out = E.fit_crop(im, {"x": 0.05, "y": 0.05, "w": 0.3, "h": 0.3}, 100, 100)
    r, g, b = out.getpixel((50, 50))
    assert r > 200 and b < 60
    assert E.norm_crop({"x": 0.9, "y": -1, "w": 0.5, "h": 2}) == {"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0}


# --- repo -----------------------------------------------------------------------


def test_repo_upload_folder_search_and_subjects(client, photos, tmp_path):
    folder = tmp_path / "chosen"
    make_photo(folder / "B02.jpg", (90, 10, 10))
    make_photo(folder / "B03.jpg", (10, 90, 10))
    (folder / "notes.txt").write_text("not an image")
    r = client.post(f"{A}/repo/import-folder", json={"path": str(folder), "tags": "chosen"})
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 2
    again = client.post(f"{A}/repo/import-folder", json={"path": str(folder)}).json()
    assert again["added"] == 0 and again["already"] == 2, "a photo is identified by its content"
    found = client.get(f"{A}/repo", params={"q": "b02"}).json()["photos"]
    assert [p["name"] for p in found] == ["B02"] and "chosen" in found[0]["tags"]
    assert client.get(f"{A}/repo", params={"tag": "synthetic"}).json()["photos"]
    ph = photos[0]
    r = client.post(f"{A}/repo/{ph}/subjects", json={"label": "Rama's face", "x": 0.3, "y": 0.3, "w": 0.3, "h": 0.2})
    assert r.status_code == 200
    s = r.json()["subjects"][-1]
    assert s["label"] == "Rama's face" and s["id"].startswith("s")
    r = client.patch(f"{A}/repo/{ph}/subjects/{s['id']}", json={"x": 0.9, "w": 0.5})
    assert r.json()["subjects"][-1]["x"] == 0.5, "the box is kept inside the photo"
    assert client.get(f"{A}/repo", params={"q": "rama face"}).json()["photos"][0]["id"] == ph
    assert client.post(f"{A}/repo/{ph}/subjects", json={"label": "bad", "x": "a"}).status_code == 400
    assert client.delete(f"{A}/repo/{ph}/subjects/{s['id']}").status_code == 200
    assert client.post(f"{A}/repo/import-folder", json={"path": str(tmp_path / "nope")}).status_code == 404
    r = client.post(f"{A}/repo/upload", files=[("files", ("x.txt", b"hello", "text/plain"))])
    assert r.json()["added"] == 0 and r.json()["skipped"]


def test_repo_import_from_book(client, tmp_path):
    from tests.test_book_layers import make_package

    pkg = make_package(tmp_path)
    b = client.post("/api/book/import", json={"path": str(pkg)}).json()
    try:
        books = client.get(f"{A}/repo/books").json()
        assert any(x["id"] == b["id"] for x in books)
        r = client.post(f"{A}/repo/import-book", json={"book_id": b["id"]})
        assert r.status_code == 200, r.text
        assert r.json()["added"] + r.json()["already"] == 3
        mine = [p for p in client.get(f"{A}/repo").json()["photos"] if p.get("book_id") == b["id"]]
        assert sorted(p["page"] for p in mine) == [1, 2, 3]
        assert all(p["era"] == "treta" and p["book"] == "Synthetic Test Book" for p in mine)
        assert mine[0]["chapter"] and "Synthetic Night" in mine[0]["chapter"]
    finally:
        client.delete(f"/api/book/books/{b['id']}")


def test_find_subjects_mocked(client, photos, monkeypatch):
    seen = {}

    def fake(system, user, images):
        seen["images"] = [Path(i).suffix for i in images]
        return {"crops": [{"label": "the chariot", "what": "a gold chariot", "drama": 9, "x": 0.1, "y": 0.1, "w": 0.4, "h": 0.3},
                          {"subject": "flames", "drama": 7, "x": 0.5, "y": 0.6, "w": 0.6, "h": 0.6},
                          {"label": "too small", "x": 0.1, "y": 0.1, "w": 0.01, "h": 0.01}, "junk"]}

    monkeypatch.setattr(SA, "ask_vision", fake)
    r = client.post(f"{A}/repo/{photos[1]}/find-subjects")
    assert r.status_code == 200, r.text
    props = r.json()["proposals"]
    assert [p["label"] for p in props] == ["the chariot", "flames"] and seen["images"] == [".jpg"]
    assert props[1]["x"] + props[1]["w"] <= 1.0
    assert client.get(f"{A}/repo/{photos[1]}").json()["subjects"] == [], "proposals are not saved until kept"
    kept = client.post(f"{A}/repo/{photos[1]}/subjects/bulk", json={"subjects": props}).json()["subjects"]
    assert len(kept) == 2 and kept[0]["drama"] == 9 and kept[0]["ai"]


def test_find_subjects_without_key(client, photos, monkeypatch):
    from engine.settings import settings

    monkeypatch.setattr(settings, "openai_api_key", None)
    r = client.post(f"{A}/repo/{photos[0]}/find-subjects")
    assert r.status_code == 400 and "OPENAI_API_KEY" in r.json()["detail"]


# --- placements, plates, export ---------------------------------------------------


def test_placements_validation_undo_and_preview(client, project, photos):
    pid = project["id"]
    pl = project["pages_list"]
    assert [p["kind"] for p in pl][:3] == ["opener", "text", "end"]
    assert {s["id"] for s in pl[0]["slots"]} == {"top"}
    r = client.post(f"{A}/projects/{pid}/placements", json={"page": 2, "slot": "bottom", "pieces": [photos[0]]})
    assert r.status_code == 400 and "no slot" in r.json()["detail"]
    r = client.post(f"{A}/projects/{pid}/placements", json={"page": 3, "slot": "bottom", "style": "collage", "pieces": [photos[0]]})
    assert r.status_code == 400 and "2–4" in r.json()["detail"]
    r = client.post(f"{A}/projects/{pid}/placements", json={"page": 2, "rect": [50, 100, 300, 300], "pieces": [photos[0]]})
    assert r.status_code == 400 and "text" in r.json()["detail"]
    r = client.post(f"{A}/projects/{pid}/placements", json={"page": 1, "slot": "top", "pieces": [{"photo": "phnope"}]})
    assert r.status_code == 404
    r = client.post(f"{A}/projects/{pid}/placements", json={"page": 1, "slot": "top", "pieces": [photos[0]]})
    assert r.status_code == 200, r.text
    first = r.json()["placement"]
    assert first["style"] == "strip" and first["rect"] == slots_of(r.json()["page"])["top"]
    sub = client.post(f"{A}/repo/{photos[1]}/subjects", json={"label": "face", "x": 0.3, "y": 0.3, "w": 0.3, "h": 0.2}).json()["subjects"][-1]
    r = client.post(f"{A}/projects/{pid}/placements", json={"page": 3, "slot": "bottom", "style": "collage", "size": 0.8,
                                                           "pieces": [photos[0], {"photo": photos[1], "subject": sub["id"]}, photos[2]]})
    assert r.status_code == 200, r.text
    col = r.json()["placement"]
    assert col["pieces"][1]["crop"] == {k: sub[k] for k in ("x", "y", "w", "h")}, "a subject brings its crop box"
    # reorder and remove a piece, re-tilt
    r = client.patch(f"{A}/projects/{pid}/placements/{col['id']}", json={"pieces": [col["pieces"][2], col["pieces"][0]], "tilt": 2.5, "sepia": 0.4})
    assert r.status_code == 200 and [x["photo"] for x in r.json()["placement"]["pieces"]] == [photos[2], photos[0]]
    # placing on a filled slot replaces it
    client.post(f"{A}/projects/{pid}/placements", json={"page": 1, "slot": "top", "style": "torn", "pieces": [photos[3]]})
    v = client.get(f"{A}/projects/{pid}").json()
    assert len([x for x in v["placements_list"] if x["page"] == 1]) == 1
    assert v["pages_list"][0]["slots"][0]["filled"]
    png = client.get(f"{A}/projects/{pid}/pages/3/preview.png", params={"dpi": 60})
    plain = client.get(f"{A}/projects/{pid}/pages/3/preview.png", params={"dpi": 60, "art": 0})
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG" and png.content != plain.content
    assert client.get(v["pages_list"][2]["thumb"]).headers["content-type"] == "image/jpeg"
    # undo: the replace, then the patch
    r = client.post(f"{A}/projects/{pid}/undo").json()
    assert [x["style"] for x in r["project"]["placements_list"] if x["page"] == 1] == ["strip"]
    r = client.post(f"{A}/projects/{pid}/undo").json()
    assert len(next(x for x in r["project"]["placements_list"] if x["page"] == 3)["pieces"]) == 3
    hist = client.get(f"{A}/projects/{pid}/history").json()
    assert hist[0]["action"].startswith("place art on page 3")
    assert client.delete(f"{A}/projects/{pid}/placements/{col['id']}").status_code == 200
    assert client.delete(f"{A}/repo/{photos[0]}").status_code == 409, "a placed photo cannot be deleted"


def test_plates_insert_as_a_pair_and_keep_sides(client, project, photos, pdf_bytes):
    pid = project["id"]
    items = [{"photo": photos[0], "caption": "Two chariots circle each other."}, {"photo": photos[1], "caption": "Rama released the arrow."}]
    assert client.post(f"{A}/projects/{pid}/plates", json={"after": 2, "items": items}).status_code == 400
    assert client.post(f"{A}/projects/{pid}/plates", json={"after": 3, "items": items[:1]}).status_code == 400
    r = client.post(f"{A}/projects/{pid}/plates", json={"after": 3, "items": items})
    assert r.status_code == 200, r.text
    pp = r.json()["plate"]
    assert client.post(f"{A}/projects/{pid}/plates", json={"after": 3, "items": items}).status_code == 409
    assert client.get(f"{A}/projects/{pid}/plates/{pp['id']}/1/preview.png", params={"dpi": 40}).content[:4] == b"\x89PNG"
    project_json = SS.load(pid)
    data, errors = E.render(SS.source_pdf(pid), project_json, SA.load_photo)
    assert not errors
    out, src = fitz.open(stream=data), fitz.open(stream=pdf_bytes)
    assert len(out) == len(src) + 2
    # pages 4 and 5 are the plates (left, right); every later page keeps its side and its text
    for k in (3, 4):
        assert out[k].get_image_info() and len(out[k].get_image_info()) == 1
    assert "Two chariots circle each other." in out[3].get_text() and "Rama released the arrow." in out[4].get_text()
    for i in range(len(src)):
        j = i if i < 3 else i + 2
        assert (j + 1) % 2 == (i + 1) % 2
        assert out[j].get_text() == src[i].get_text()
        assert out[j].rect == src[i].rect
    # the plate art is inside the page
    for k in (3, 4):
        assert inside(out[k].get_image_info()[0]["bbox"], (0, 0, W, H))


def test_export_keeps_text_and_size(client, project, photos, pdf_bytes):
    pid = project["id"]
    a = E.analyse(pdf_bytes)
    jobs = [{"page": 1, "slot": "top", "pieces": [photos[0]]},
            {"page": 2, "slot": "corner", "pieces": [photos[1]]},
            {"page": 3, "slot": "bottom", "style": "collage", "pieces": photos[:4]},
            {"page": 7, "slot": "bottom", "style": "torn", "pieces": [photos[2]], "tilt": -3}]
    for j in jobs:
        assert client.post(f"{A}/projects/{pid}/placements", json=j).status_code == 200
    client.post(f"{A}/projects/{pid}/plates", json={"after": 5, "items": [{"photo": photos[0], "caption": "one"}, {"photo": photos[3], "caption": "two"}]})
    r = client.post(f"{A}/projects/{pid}/export")
    assert r.status_code == 202, r.text
    j = wait_job(client, r.json()["job_id"])
    assert j["status"] == "done", j.get("log")
    res = j["result"]
    assert res["pages"] == 10 and not res["errors"]
    out = fitz.open(str(SS.project_dir(pid) / "exports" / Path(res["pdf"]).name))
    src = fitz.open(stream=pdf_bytes)
    mapping = {i: (i if i < 5 else i + 2) for i in range(len(src))}
    for i, j_ in mapping.items():
        assert out[j_].get_text() == src[i].get_text(), "the text is untouched and extractable"
        assert out[j_].rect == src[i].rect
        info = a["pages"][i]
        for im in out[j_].get_image_info():
            assert E._clear([round(v, 2) - 0 for v in im["bbox"]], info["blocks"] + info["folio"]), f"art covers text on page {i + 1}"
            slot_rects = [s["rect"] for s in info["slots"]]
            assert any(inside(im["bbox"], s, 1.0) for s in slot_rects)
    assert [len(out[mapping[i]].get_image_info()) for i in (0, 1, 2, 3, 6)] == [1, 1, 1, 0, 1]
    exps = client.get(f"{A}/projects/{pid}/exports").json()
    assert exps and exps[0]["name"].endswith(".pdf")


def test_import_path_and_bad_pdf(client, tmp_path, pdf_bytes):
    f = tmp_path / "book.pdf"
    f.write_bytes(pdf_bytes)
    r = client.post(f"{A}/projects/import", json={"path": str(f)})
    assert r.status_code == 200 and r.json()["pages"] == 8
    client.delete(f"{A}/projects/{r.json()['id']}")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    assert client.post(f"{A}/projects/import", json={"path": str(bad)}).status_code == 400
    assert client.post(f"{A}/projects/import", json={"path": str(tmp_path / "none.pdf")}).status_code == 404


# --- AI: suggest and review (mocked) ---------------------------------------------


def test_suggest_never_applies_until_accepted(client, project, photos, monkeypatch):
    pid = project["id"]
    calls = []

    def fake(role, system, user, images=None):
        calls.append(role)
        return {"picks": [{"slot": "bottom", "pieces": [{"photo": photos[0]}, {"photo": photos[1], "subject": "nope"}], "why": "the chariots"},
                          {"slot": "corner", "pieces": [{"photo": photos[2]}], "why": "Rama"},
                          {"slot": "top", "pieces": [{"photo": photos[2]}]},           # page 3 has no top slot
                          {"slot": "bottom", "pieces": [{"photo": "phmissing"}]}]}     # unknown photo

    monkeypatch.setattr(SA, "ask_llm", fake)
    r = client.post(f"{A}/projects/{pid}/suggest", json={"page": 3})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["slot"] for i in items] == ["bottom", "corner"] and calls == ["prompt_writer"]
    assert items[0]["style"] == "collage" and len(items[0]["pieces"]) == 2
    assert r.json()["page"]["placements"] == [], "nothing is placed before Accept"
    r = client.post(f"{A}/projects/{pid}/suggestions/3/0/accept")
    assert r.status_code == 200, r.text
    assert len(r.json()["page"]["placements"]) == 1 and r.json()["page"]["suggestions"]["items"][0]["accepted"]
    assert client.post(f"{A}/projects/{pid}/suggest", json={"page": 99}).status_code == 404


def test_review_flags_and_accepts_replacement(client, project, photos, monkeypatch):
    pid = project["id"]
    a = client.post(f"{A}/projects/{pid}/placements", json={"page": 3, "slot": "bottom", "style": "collage", "pieces": photos[:2]}).json()["placement"]
    b = client.post(f"{A}/projects/{pid}/placements", json={"page": 3, "slot": "corner", "pieces": [photos[2]]}).json()["placement"]
    seen = {}

    def fake(role, system, user, images=None):
        seen["role"], seen["images"] = role, images
        return {"items": [{"placement": a["id"], "ok": True, "issue": ""},
                          {"placement": b["id"], "ok": False, "issue": "Ravana is not in this chapter", "replace": {"piece": 0, "photo": photos[3]}},
                          {"placement": "plzzz", "ok": False}]}

    monkeypatch.setattr(SA, "ask_llm", fake)
    r = client.post(f"{A}/projects/{pid}/review", json={"page": 3})
    assert r.status_code == 200, r.text
    assert seen["role"] == "critic" and seen["images"] and Path(seen["images"][0]).suffix == ".png"
    rows = r.json()["items"]
    assert [x["ok"] for x in rows] == [True, False] and rows[1]["replace"]["photo"] == photos[3]
    v = client.get(f"{A}/projects/{pid}").json()
    assert v["pages_list"][2]["flags"] == 1
    assert next(x for x in v["placements_list"] if x["id"] == b["id"])["pieces"][0]["photo"] == photos[2], "not applied without Accept"
    r = client.post(f"{A}/projects/{pid}/reviews/3/1/accept")
    assert r.status_code == 200, r.text
    assert r.json()["placement"]["pieces"][0]["photo"] == photos[3]
    assert client.post(f"{A}/projects/{pid}/reviews/3/0/accept").status_code == 404
    # the whole book as a job
    r = client.post(f"{A}/projects/{pid}/review", json={})
    assert r.status_code == 200 and "job_id" in r.json()
    j = wait_job(client, r.json()["job_id"])
    assert j["status"] == "done" and j["result"]["pages"] == [3]


def test_ai_without_keys_is_a_clear_error(client, project, photos, monkeypatch):
    from engine import llm

    monkeypatch.setattr(llm, "is_available", lambda role: False)
    r = client.post(f"{A}/projects/{project['id']}/suggest", json={"page": 3})
    assert r.status_code == 400 and "key" in r.json()["detail"]
