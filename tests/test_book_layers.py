"""The Book section: a layered book package (paper / art / text) imported at runtime and edited page by page.

Everything here runs on a synthetic three-page package built inside the test (never the real book)."""

from __future__ import annotations

import glob
import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from backend import db

B = "/api/book"


def _chromium():
    return next(iter(sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome"))), None)


def _img(path: Path, colour: tuple[int, int, int], size: tuple[int, int] = (366, 538)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, colour)
    for x in range(0, size[0], 40):  # a little structure so the JPEG is not trivial
        for y in range(0, size[1], 40):
            im.putpixel((x, y), (255, 255, 255))
    im.save(path, "JPEG", quality=90)


def make_package(root: Path) -> Path:
    """A synthetic dharma-book/1 package: 3 pages + cover, one of each text style."""
    d = root / "synthetic_book"
    for i, c in enumerate([(120, 40, 20), (30, 60, 110), (40, 90, 50)], 1):
        _img(d / "art" / f"00{i}.jpg", c)
    _img(d / "art" / "cover.jpg", (90, 20, 20), (408, 612))
    frame = {"l": 104, "r": 104, "t": 170, "b": 200}

    def page(n: int, text: list[dict]) -> dict:
        return {"id": f"00{n}", "number": n, "era": "treta", "template": "S6040", "scene_type": "test",
                "paper": {"texture": "page_warm", "shloka": {"id": "gita-4-8", "lines": ["परित्राणाय साधूनां विनाशाय च दुष्कृताम् ।", "धर्मसंस्थापनार्थाय सम्भवामि युगे युगे ॥"], "source": "Bhagavad Gita 4.8"},
                          "figures": [{"name": "rama", "x": 6, "y": 2400, "h": 520, "opacity": 0.42, "mirror": False},
                                      {"name": "shivalinga", "x": 1740, "y": 1050, "h": 520, "opacity": 0.42, "mirror": True}]},
                "art": {"file": f"art/00{n}.jpg", "x": 104, "y": 170, "w": 1832, "h": 2690, "torn": True}, "text": text, "page_number": True}

    pages = [
        page(1, [{"kind": "header", "text": "BOOK ONE · 1 · Synthetic Night", "x": 140, "y": 206, "w": 955, "h": 170, "style": "header", "font": "Cinzel Decorative",
                  "id": "001-t1", "kicker": "BOOK ONE · 1", "title": "Synthetic Night"},
                 {"kind": "narration", "text": "Alpha narration on parchment.", "x": 140, "y": 394, "w": 741, "h": 176, "style": "parchment", "font": "EB Garamond", "id": "001-t2"}]),
        page(2, [{"kind": "dialogue", "text": "Beta speaks through glass.", "x": 140, "y": 1912, "w": 414, "h": 168, "tail": [347, 2460], "style": "glass", "font": "Martel", "id": "002-t1"}]),
        page(3, [{"kind": "narration", "text": "Gamma modern narration.", "x": 140, "y": 396, "w": 841, "h": 178, "style": "glass-narration", "font": "Inter Tight", "id": "003-t1"},
                 {"kind": "dialogue", "text": "Delta modern voice.", "x": 700, "y": 1500, "w": 500, "h": 170, "tail": [900, 1900], "style": "glass", "font": "Inter Tight", "id": "003-t2"}]),
    ]
    manifest = {"format": "dharma-book/1", "title": "Synthetic Test Book", "volume": "Volume Zero", "author": "Test Author", "page_px": [2040, 3060],
                "trim_mm": [170, 255], "bleed_mm": 3, "frame": frame, "styles": {}, "cover": {"file": "art/cover.jpg"}, "pages": pages}
    (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return d


def zip_package(d: Path, dst: Path, prefix: str = "") -> Path:
    with zipfile.ZipFile(dst, "w") as z:
        for f in d.rglob("*"):
            if f.is_file():
                z.write(f, prefix + f.relative_to(d).as_posix())
    return dst


@pytest.fixture()
def book(client, tmp_path):
    pkg = make_package(tmp_path)
    r = client.post(f"{B}/import", json={"path": str(pkg)})
    assert r.status_code == 200, r.text
    b = r.json()
    yield b
    client.delete(f"{B}/books/{b['id']}")


def wait_job(client, jid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "failed", "stopped"):
            return j
        time.sleep(0.3)
    raise AssertionError("job timed out")


# --- import ---------------------------------------------------------------------


def test_import_folder(client, book):
    assert book["title"] == "Synthetic Test Book" and book["pages"] == 3
    assert [p["id"] for p in book["pages_list"]] == ["001", "002", "003"]
    assert [p["number"] for p in book["pages_list"]] == [1, 2, 3]
    bdir = db.DATA_DIR / "books" / book["id"]
    assert (bdir / "art" / "002.jpg").exists() and (bdir / "art" / "cover.jpg").exists()
    assert any(b["id"] == book["id"] for b in client.get(f"{B}/books").json())
    p = client.get(f"{B}/books/{book['id']}/pages/002").json()
    assert p["layers"] == {"paper": True, "art": True, "text": True} and p["text"][0]["tail"] == [347, 2460]
    assert client.get(p["art_url"]).status_code == 200
    th = client.get(p["thumb"])
    assert th.status_code == 200 and th.headers["content-type"] == "image/jpeg"


def test_import_archive_upload_and_candidates(client, tmp_path, monkeypatch):
    pkg = make_package(tmp_path)
    arc = zip_package(pkg, tmp_path / "Cycle_of_Dharma_V1_V3.dharmabook", prefix="book_v3/")  # a top-level folder inside the archive
    r = client.post(f"{B}/import/upload", files={"file": (arc.name, arc.read_bytes(), "application/zip")})
    assert r.status_code == 200, r.text
    assert r.json()["pages"] == 3
    client.delete(f"{B}/books/{r.json()['id']}")
    # the import dialog offers packages found in ~/Downloads etc.; it does not import them
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    (home / "Downloads" / arc.name).write_bytes(arc.read_bytes())
    monkeypatch.setenv("HOME", str(home))
    before = len(client.get(f"{B}/books").json())
    c = client.get(f"{B}/import/candidates").json()
    assert [x["name"] for x in c["candidates"]] == ["Cycle_of_Dharma_V1_V3.dharmabook"] and c["candidates"][0]["preferred"]
    assert len(client.get(f"{B}/books").json()) == before
    r = client.post(f"{B}/import", json={"path": c["candidates"][0]["path"]})
    assert r.status_code == 200 and r.json()["pages"] == 3
    client.delete(f"{B}/books/{r.json()['id']}")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "manifest.json").write_text("{}")
    assert client.post(f"{B}/import", json={"path": str(bad)}).status_code == 400
    assert client.post(f"{B}/import", json={"path": str(tmp_path / 'missing')}).status_code == 404


# --- pages ----------------------------------------------------------------------


def test_add_duplicate_delete_reorder_undo(client, book):
    bid = book["id"]
    r = client.post(f"{B}/books/{bid}/pages", json={"mode": "blank", "after": "001"})
    assert r.status_code == 200
    blank = r.json()["page"]
    assert blank["number"] == 2 and blank["art"] is None and blank["text"] == []
    assert [p["number"] for p in r.json()["book"]["pages_list"]] == [1, 2, 3, 4]

    r = client.post(f"{B}/books/{bid}/pages", json={"mode": "duplicate", "source": "003"})
    dup = r.json()["page"]
    assert dup["number"] == 5 and [t["text"] for t in dup["text"]] == ["Gamma modern narration.", "Delta modern voice."]
    assert all(t["id"].startswith(dup["id"]) for t in dup["text"])

    buf = io.BytesIO()
    Image.new("RGB", (300, 450), (200, 150, 50)).save(buf, "PNG")
    r = client.post(f"{B}/books/{bid}/pages/from-image", files={"file": ("plate.png", buf.getvalue(), "image/png")}, data={"after": "002"})
    assert r.status_code == 200, r.text
    img = r.json()["page"]
    assert img["art"]["file"].endswith(".jpg") and img["art"]["w"] == 1832 and img["number"] == 4
    order = [p["id"] for p in r.json()["book"]["pages_list"]]
    assert order == ["001", blank["id"], "002", img["id"], "003", dup["id"]]

    r = client.delete(f"{B}/books/{bid}/pages/{blank['id']}")
    assert r.status_code == 200 and r.json()["pages"] == 5
    new = ["003", "001", "002", img["id"], dup["id"]]
    r = client.put(f"{B}/books/{bid}/order", json={"order": new})
    assert [p["id"] for p in r.json()["pages_list"]] == new and [p["number"] for p in r.json()["pages_list"]] == [1, 2, 3, 4, 5]
    assert client.put(f"{B}/books/{bid}/order", json={"order": new[:-1]}).status_code == 400

    # undo walks back: reorder, then the delete
    assert client.post(f"{B}/books/{bid}/undo").json()["undone"] == "reorder pages"
    r = client.post(f"{B}/books/{bid}/undo").json()
    assert r["undone"] == "delete page" and [p["id"] for p in r["book"]["pages_list"]][1] == blank["id"]
    # the page number on the render follows the order
    assert "data-number='3'" in client.get(f"{B}/books/{bid}/pages/002/render").text


# --- text boxes -----------------------------------------------------------------


def test_text_crud(client, book):
    bid = book["id"]
    r = client.post(f"{B}/books/{bid}/pages/002/text", json={"style": "parchment", "text": "A new caption.", "x": 300, "y": 600})
    assert r.status_code == 200, r.text
    tid = r.json()["created"]
    assert tid == "002-t2" and r.json()["text"][-1]["kind"] == "narration"
    # move, resize, restyle, font and size
    r = client.patch(f"{B}/books/{bid}/pages/002/text/{tid}", json={"x": 410, "y": 720})
    t = r.json()["text"][-1]
    assert (t["x"], t["y"]) == (410, 720)
    r = client.patch(f"{B}/books/{bid}/pages/002/text/{tid}", json={"w": 900, "h": 220, "style": "glass", "font": "Inter Tight", "size": 48, "align": "right", "tail": [600, 1200]})
    t = r.json()["text"][-1]
    assert (t["w"], t["h"], t["style"], t["font"], t["size"], t["align"], t["tail"]) == (900, 220, "glass", "Inter Tight", 48, "right", [600, 1200])
    r = client.patch(f"{B}/books/{bid}/pages/002/text/{tid}", json={"text": "Edited inline."})
    assert r.json()["text"][-1]["text"] == "Edited inline."
    html = client.get(f"{B}/books/{bid}/pages/002/render").text
    assert "Edited inline." in html and "font-family:'Inter Tight'" in html and f"data-for='{tid}'" in html
    assert client.patch(f"{B}/books/{bid}/pages/002/text/{tid}", json={"style": "neon"}).status_code == 400
    assert client.patch(f"{B}/books/{bid}/pages/002/text/{tid}", json={"font": "Comic Sans"}).status_code == 400
    assert client.patch(f"{B}/books/{bid}/pages/002/text/nope", json={"x": 1}).status_code == 404
    # header boxes keep kicker + title
    r = client.post(f"{B}/books/{bid}/pages/002/text", json={"style": "header", "kicker": "BOOK TWO · 3", "title": "Iron"})
    h = next(t for t in r.json()["text"] if t["id"] == r.json()["created"])
    assert h["kind"] == "header" and h["text"] == "BOOK TWO · 3 · Iron"
    r = client.delete(f"{B}/books/{bid}/pages/002/text/{tid}")
    assert [t["id"] for t in r.json()["text"]] == ["002-t1", h["id"]]
    # per-page history and undo
    hist = client.get(f"{B}/books/{bid}/pages/002/history").json()
    assert hist[0]["action"] == "delete text box" and len(hist) == 6
    r = client.post(f"{B}/books/{bid}/pages/002/undo").json()
    assert r["undone"] == "delete text box" and any(t["id"] == tid for t in r["page"]["text"])
    first = hist[-1]["seq"]  # the state before the first edit
    r = client.post(f"{B}/books/{bid}/pages/002/restore", json={"seq": first})
    assert [t["id"] for t in r.json()["text"]] == ["002-t1"]


# --- layers, paper, art ---------------------------------------------------------


def test_layer_toggles_and_render(client, book):
    bid = book["id"]
    html = client.get(f"{B}/books/{bid}/pages/001/render").text
    # real text, the painting as an <img>, the shloka in Devanagari, the figures, the fonts
    assert "Alpha narration on parchment." in html and "Synthetic Night" in html and "BOOK ONE · 1" in html
    assert "<img class='art-img'" in html and f"/media/books/{bid}/art/001.jpg" in html and "clip-path:polygon(" in html
    assert "परित्राणाय साधूनां" in html and "— Bhagavad Gita 4.8" in html and html.count("class='fig'") == 2 and "scaleX(-1)" in html
    assert "/api/book/fonts/CinzelDecorative-Bold.ttf" in html and "/api/book/fonts/TiroDevanagariHindi-Regular.ttf" in html
    glass = client.get(f"{B}/books/{bid}/pages/002/render").text
    assert "backdrop-filter:blur(" in glass and "class='tail'" in glass and "Beta speaks through glass." in glass
    assert "class='accent'" in client.get(f"{B}/books/{bid}/pages/003/render").text
    # hide text, then art, then paper
    r = client.put(f"{B}/books/{bid}/pages/001/layers", json={"text": False})
    assert r.json()["layers"] == {"paper": True, "art": True, "text": False}
    html = client.get(f"{B}/books/{bid}/pages/001/render").text
    assert "Alpha narration" not in html and "class='art-img'" in html
    client.put(f"{B}/books/{bid}/pages/001/layers", json={"art": False, "paper": False})
    html = client.get(f"{B}/books/{bid}/pages/001/render").text
    assert "class='art-img'" not in html and "परित्राणाय" not in html and "class='fig'" not in html
    client.put(f"{B}/books/{bid}/pages/001/layers", json={"art": True, "paper": True, "text": True})
    assert "Alpha narration" in client.get(f"{B}/books/{bid}/pages/001/render").text
    # print mode: bleed and crop marks
    pr = client.get(f"{B}/books/{bid}/pages/001/render?paper=print").text
    assert "width:176.0mm;height:261.0mm" in pr and "class='marks'" in pr
    # embedded render is self-contained
    emb = client.get(f"{B}/books/{bid}/pages/001/render?embed=true").text
    assert "data:image/jpeg;base64," in emb and "data:font/ttf;base64," in emb and "/media/" not in emb


def test_paper_and_art_edits(client, book):
    bid = book["id"]
    sh = client.get(f"{B}/shlokas").json()
    assert any(s["id"] == "gita-2-47" and s["meaning"] for s in sh)
    r = client.patch(f"{B}/books/{bid}/pages/003/paper", json={"shloka_id": "gita-2-47", "texture": "page_aged",
                                                                "figures": [{"name": "hanuman", "x": 10, "y": 100, "h": 300, "opacity": 0.3, "mirror": False}]})
    assert r.status_code == 200, r.text
    p = r.json()["paper"]
    assert p["shloka"]["id"] == "gita-2-47" and p["texture"] == "page_aged" and [f["name"] for f in p["figures"]] == ["hanuman"]
    html = client.get(f"{B}/books/{bid}/pages/003/render").text
    assert "कर्मण्येवाधिकारस्ते" in html and "page_aged.jpg" in html
    assert client.patch(f"{B}/books/{bid}/pages/003/paper", json={"figures": [{"name": "dragon"}]}).status_code == 400
    assert client.patch(f"{B}/books/{bid}/pages/003/paper", json={"shloka_id": None}).json()["paper"]["shloka"] is None
    assert {f["name"] for f in client.get(f"{B}/figures").json()} >= {"rama", "hanuman", "shivalinga"}
    assert "page_warm" in {t["name"] for t in client.get(f"{B}/textures").json()}
    assert client.get(f"{B}/fonts").json()[0]["house"] is True
    assert client.get(f"{B}/fonts/InterTightwght.ttf").status_code == 200
    # art: fit / crop / torn edge, replace
    r = client.patch(f"{B}/books/{bid}/pages/003/art", json={"fit": "contain", "focus": [0.2, 0.8], "torn": False})
    a = r.json()["art"]
    assert (a["fit"], a["focus"], a["torn"]) == ("contain", [0.2, 0.8], False)
    html = client.get(f"{B}/books/{bid}/pages/003/render").text
    assert "object-fit:contain" in html and "clip-path:polygon(" not in html
    buf = io.BytesIO()
    Image.new("RGB", (200, 300), (10, 200, 10)).save(buf, "JPEG")
    r = client.post(f"{B}/books/{bid}/pages/003/art", files={"file": ("new.jpg", buf.getvalue(), "image/jpeg")})
    assert r.json()["art"]["file"] == "art/003-1.jpg" and r.json()["art"]["fit"] == "contain"
    assert client.post(f"{B}/books/{bid}/pages/003/undo").json()["page"]["art"]["file"] == "art/003.jpg"


def test_export_package_roundtrip(client, book):
    bid = book["id"]
    client.put(f"{B}/books/{bid}/order", json={"order": ["002", "001", "003"]})
    client.patch(f"{B}/books/{bid}/pages/001/text/001-t2", json={"text": "Changed in the studio."})
    r = client.post(f"{B}/books/{bid}/export/package")
    assert r.status_code == 200 and r.json()["name"].endswith(".dharmabook")
    with zipfile.ZipFile(r.json()["path"]) as z:
        m = json.loads(z.read("manifest.json"))
        assert m["format"] == "dharma-book/1" and [p["id"] for p in m["pages"]] == ["002", "001", "003"]
        assert [p["number"] for p in m["pages"]] == [1, 2, 3]
        assert {"art/001.jpg", "art/002.jpg", "art/003.jpg", "art/cover.jpg"} <= set(z.namelist())
    back = client.post(f"{B}/import", json={"path": r.json()["path"]}).json()
    assert [p["id"] for p in back["pages_list"]] == ["002", "001", "003"]
    assert client.get(f"{B}/books/{back['id']}/pages/001").json()["text"][1]["text"] == "Changed in the studio."
    client.delete(f"{B}/books/{back['id']}")
    assert any(e["kind"] == "dharmabook" for e in client.get(f"{B}/books/{bid}/exports").json())


# --- PDF / PNG ------------------------------------------------------------------


@pytest.mark.skipif(_chromium() is None, reason="no Chromium to render the PDF")
@pytest.mark.parametrize("paper,size_mm", [("print", (176.0, 261.0)), ("screen", (170.0, 255.0))])
def test_pdf_export(client, book, paper, size_mm, monkeypatch):
    from pypdf import PdfReader

    from backend import book_api

    monkeypatch.setattr(book_api, "PDF_CHUNK", 2)  # a long book renders in parts that are joined: exercise the join

    r = client.post(f"{B}/books/{book['id']}/export/pdf", json={"paper": paper})
    assert r.status_code == 202
    j = wait_job(client, r.json()["job_id"])
    assert j["status"] == "done", j["log"]
    pdf = db.DATA_DIR / j["result"]["pdf"]
    rd = PdfReader(str(pdf))
    assert len(rd.pages) == 4  # cover + 3 pages
    for pg in rd.pages:
        w, h = float(pg.mediabox.width) / 72 * 25.4, float(pg.mediabox.height) / 72 * 25.4
        assert abs(w - size_mm[0]) < 0.6 and abs(h - size_mm[1]) < 0.6, (w, h)
    text = rd.pages[1].extract_text() + rd.pages[2].extract_text()
    assert "Alpha narration" in text and "Beta speaks" in text  # real, searchable text
    assert "Gamma modern narration" in rd.pages[3].extract_text()  # the second part, in order
    assert client.get(j["result"]["url"]).status_code == 200


@pytest.mark.skipif(_chromium() is None, reason="no Chromium to render the PNG")
def test_page_png(client, book):
    r = client.get(f"{B}/books/{book['id']}/pages/002/png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    im = Image.open(io.BytesIO(r.content))
    assert abs(im.size[0] - 2040) <= 2 and abs(im.size[1] - 3060) <= 2
