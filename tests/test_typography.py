"""Typography (font catalog, presets, sizes, per-page override, embedded fonts in PDFs) and smart callout colours."""

from __future__ import annotations

import glob
import re
import shutil
import subprocess
import time

import pytest
from PIL import ImageFont

from backend import db
from engine import colour as C
from engine import typography as T


def wait_job(client, job_id: int, timeout: float = 900) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed", "stopped"):
            return j
        time.sleep(0.2)
    raise AssertionError("job timed out")


def _sizes(html: str, cls: str) -> list[float]:
    return [float(x) for x in re.findall(rf"<div class='{cls}'[^>]*font-size:([0-9.]+)mm", html)]


# --- catalog and presets ---------------------------------------------------------


def test_catalog_files_exist_and_load():
    assert len(T.CATALOG) >= 25
    for f in T.CATALOG:
        assert f.faces and f.script in ("latin", "devanagari", "both") and set(f.roles) <= set(T.ROLES) and f.note
        for face in f.faces:
            assert face.path.exists(), face.path
            assert ImageFont.truetype(str(face.path), 24).getname()[0]
        assert f.files["regular"]


def test_presets_reference_valid_fonts():
    assert {"illuminated-manuscript", "epic-cinema", "ancient-chronicle", "modern-clean"} <= set(T.PRESETS)
    for pid, p in T.PRESETS.items():
        for k in T.FONT_KEYS:
            f = T.FONTS[p[k]]
            assert f.covers("hi" if k.startswith("hi_") else "en"), (pid, k)
    im = T.PRESETS["illuminated-manuscript"]
    assert (im["title_font"], im["narration_font"], im["dialogue_font"]) == ("cinzel-decorative", "im-fell-english", "spectral")
    assert (im["hi_title_font"], im["hi_narration_font"], im["hi_dialogue_font"]) == ("yatra-one", "tiro-devanagari-hindi", "laila")
    assert T.DEFAULT_SETTING["preset"] == "illuminated-manuscript" and T.DEFAULT_SETTING["size"] == "L"


def test_fonts_api(client):
    fonts = client.get("/api/fonts").json()
    assert any(f["family"] == "Cinzel" and f["preview"]["latin"]["title"] for f in fonts)
    assert all("devanagari" in f["preview"] for f in fonts if f["script"] == "both")
    r = client.get("/api/fonts/YatraOne-Regular.ttf")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"] and len(r.content) > 10_000
    assert client.get("/api/fonts/..%2Fsettings.py").status_code == 404
    pr = client.get("/api/typography/presets").json()
    assert len(pr["presets"]) >= 4 and pr["sizes"]["L"] == 1.2 and "smart" in pr["colour_modes"]


# --- storage ----------------------------------------------------------------------


def test_volume_typography_roundtrip(client):
    v1 = client.get("/api/volumes/1/typography").json()
    assert v1["typography"]["preset"] == "illuminated-manuscript" and v1["typography"]["size"] == "L"
    r = client.put("/api/volumes/2/typography", json={"preset": "epic-cinema", "size": "XL", "narration_font": "eb-garamond"})
    assert r.status_code == 200
    got = client.get("/api/volumes/2/typography").json()
    assert got["typography"]["preset"] == "epic-cinema" and got["typography"]["size"] == "XL"
    assert got["resolved"]["fonts"]["narration_font"]["family"] == "EB Garamond"
    assert got["resolved"]["fonts"]["title_font"]["family"] == "Cinzel"
    # choosing a preset alone drops the per-role pick
    got = client.put("/api/volumes/2/typography", json={"preset": "modern-clean"}).json()
    assert got["resolved"]["fonts"]["narration_font"]["family"] == "Spectral"
    assert client.put("/api/volumes/2/typography", json={"title_font": "nope"}).status_code == 400
    assert client.put("/api/volumes/2/typography", json={"hi_title_font": "cinzel"}).status_code == 400  # no Devanagari
    assert client.put("/api/volumes/2/typography", json={"size": "XXL"}).status_code == 400


def test_migration_adds_columns_without_dropping(tmp_path):
    import sqlite3

    from sqlalchemy import create_engine

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE volume (id INTEGER PRIMARY KEY, project_id INTEGER, number INTEGER, title TEXT, canvas_id INTEGER, era_default TEXT)")
    con.execute("CREATE TABLE page (id INTEGER PRIMARY KEY, chapter_id INTEGER, number INTEGER)")
    con.execute("CREATE TABLE panel (id INTEGER PRIMARY KEY, page_id INTEGER, n INTEGER)")
    con.execute("INSERT INTO volume VALUES (1, 1, 1, 'Book One', NULL, 'treta')")
    con.commit()
    con.close()
    old = db.engine
    try:
        db.engine = create_engine(f"sqlite:///{path}")
        assert set(db.migrate()) == {"volume.typography", "page.typography_override", "panel.sfx", "panel.text_colours"}
        assert db.migrate() == []
    finally:
        db.engine.dispose()
        db.engine = old
    con = sqlite3.connect(path)
    assert con.execute("SELECT title, typography FROM volume").fetchall() == [("Book One", None)]


# --- render -----------------------------------------------------------------------


def test_render_embeds_only_used_fonts(client):
    html = client.get("/api/pages/1/render?lang=en&embed=true").text  # the opener: title + narration (+ epigraph)
    faces = re.findall(r"@font-face\{font-family:'([^']+)'", html)
    assert "Cinzel Decorative" in faces and "IM FELL English" in faces
    assert "Yatra One" not in faces and "Laila" not in faces and "Bangers" not in faces
    assert "font-family:'Cinzel Decorative'" in html and "font-family:'IM FELL English'" in html
    live = client.get("/api/pages/2/render?lang=hi").text
    assert "url('/api/fonts/TiroDevanagariHindi-Regular.ttf')" in live and "data:font/ttf" not in live
    assert "Cinzel" not in re.findall(r"@font-face\{font-family:'([^']+)'", live)
    # a balloon pulls in the dialogue face; a page without one does not
    pages = client.get("/api/pages?chapter_id=1").json()
    with_bal = next((p for p in pages if any(x["balloon_en"] for x in p["panels"])), None)
    if with_bal:
        assert "Spectral" in re.findall(r"@font-face\{font-family:'([^']+)'", client.get(f"/api/pages/{with_bal['id']}/render").text)


def test_size_scale(client):
    client.put("/api/volumes/1/typography", json={"size": "M"})
    m = _sizes(client.get("/api/pages/2/render").text, "cap")
    client.put("/api/volumes/1/typography", json={"size": "L"})
    big = _sizes(client.get("/api/pages/2/render").text, "cap")
    assert m and big and all(b > a for a, b in zip(m, big))
    assert min(big) > 2.9 * 1.3  # one step above the original 2.9 mm caption at L


def test_page_override_wins(client):
    r = client.put("/api/pages/3", json={"typography_override": {"preset": "ancient-chronicle", "size": "XL"}})
    assert r.status_code == 200 and r.json()["typography"]["fonts"]["narration_font"]["family"] == "EB Garamond"
    html = client.get("/api/pages/3/render").text
    assert "font-family:'EB Garamond'" in html and "IM FELL English" not in html
    hi = client.get("/api/pages/3/render?lang=hi").text
    assert "font-family:'Gotu'" in hi
    r = client.put("/api/pages/3", json={"typography_override": None})
    assert r.json()["typography_override"] is None and "IM FELL English" in client.get("/api/pages/3/render").text


def test_sfx_field(client):
    panel = client.get("/api/pages/2").json()["panels"][0]
    assert panel["sfx"] == ""
    r = client.put(f"/api/panels/{panel['id']}", json={"sfx": "KRAKA-THOOM"})
    assert r.status_code == 200 and r.json()["sfx"] == "KRAKA-THOOM"
    html = client.get("/api/pages/2/render").text
    assert "class='sfx'" in html and "KRAKA-THOOM" in html and "MedievalSharp" in html
    client.put(f"/api/panels/{panel['id']}", json={"sfx": ""})
    assert "class='sfx'" not in client.get("/api/pages/2/render").text


# --- callouts and colours -----------------------------------------------------------


def test_callouts_are_rounded_shards(client):
    html = client.get("/api/pages/2/render").text
    caps = re.findall(r"<div class='cap'.*?</div>", html)
    assert caps
    for cap in caps:
        d = re.search(r"<path d='([^']+)'", cap).group(1)
        assert d.startswith("M") and d.count("Q") >= 5 and d.endswith("Z")  # 5-7 vertices, each rounded
        assert "stroke-width='0.35'" in cap
        w = float(re.search(r"width:([0-9.]+)mm;height", cap).group(1))
        assert w >= 46
    assert "drop-shadow" in html
    pr = client.get("/api/pages/2/render?paper=print").text
    assert "drop-shadow" not in pr and "<path d='M" in pr


def test_smart_contrast_chapter1(client):
    client.put("/api/volumes/1/typography", json={"colour_mode": "smart"})
    n = 0
    for pid in range(1, 6):
        for lang in ("en", "hi"):
            html = client.get(f"/api/pages/{pid}/render?lang={lang}").text
            for bg, fg, mode in re.findall(r"class='(?:cap|bal)' data-bg='(#[0-9a-f]{6})' data-fg='(#[0-9a-f]{6})' data-contrast='[0-9.]+' data-colour='(\w+)'", html):
                assert mode == "smart"
                assert C.contrast(bg, fg) >= 7.0, (pid, lang, bg, fg)
                n += 1
    assert n >= 10


def test_colour_mode_roundtrip_and_pin(client):
    r = client.put("/api/volumes/1/typography", json={"colour_mode": "custom", "colours": {st: {"box": "#102030", "text": "#F0E0D0", "border": "#aa8800"} for st in T.STATES}})
    assert r.status_code == 200 and r.json()["typography"]["colour_mode"] == "custom"
    assert r.json()["typography"]["colours"]["quiet"]["text"] == "#f0e0d0"
    html = client.get("/api/pages/2/render").text
    assert "data-bg='#102030' data-fg='#f0e0d0'" in html
    client.put("/api/volumes/1/typography", json={"colour_mode": "state"})
    assert "data-colour='state'" in client.get("/api/pages/2/render").text
    assert client.put("/api/volumes/1/typography", json={"colour_mode": "neon"}).status_code == 400
    client.put("/api/volumes/1/typography", json={"colour_mode": "smart", "colours": None})
    assert client.get("/api/volumes/1/typography").json()["typography"]["colour_mode"] == "smart"
    panel = client.get("/api/pages/2").json()["panels"][0]
    pal = client.get(f"/api/panels/{panel['id']}/palette").json()
    assert pal["swatches"] and all(s["contrast"] >= 7 for s in pal["swatches"])
    r = client.put(f"/api/panels/{panel['id']}", json={"text_colours": {"box": "#223344", "text": "#ffffff"}})
    assert r.json()["text_colours"] == {"box": "#223344", "text": "#ffffff"}
    assert "data-bg='#223344' data-fg='#ffffff'" in client.get("/api/pages/2/render").text
    assert client.put(f"/api/panels/{panel['id']}", json={"text_colours": {"box": "red"}}).status_code == 400
    assert client.put(f"/api/panels/{panel['id']}", json={"text_colours": {"mode": "auto"}}).json()["text_colours"] is None


def test_colour_maths():
    assert round(C.contrast("#000000", "#ffffff"), 1) == 21.0
    assert C.lab_to_rgb(C.rgb_to_lab((120, 40, 200))) == (120, 40, 200)
    for st in C.STATE_BOX:
        for pal in ([], [((10, 20, 30), 0.6), ((200, 120, 40), 0.4)], [((240, 240, 235), 1.0)]):
            got = C.smart(pal, st)
            assert C.contrast(got["box"], got["text"]) >= 7.0, (st, got)
    assert C.lch(C.hex_to_rgb(C.smart([], "ego")["box"]))[0] < 20


def _chromium():
    return next(iter(sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome"))), None)


@pytest.mark.skipif(_chromium() is None, reason="no Chromium for layout measurement")
def test_text_never_clipped(client):
    """Every callout's text fits inside its box, and every box inside the page — all presets, XL, EN and HI."""
    from playwright.sync_api import sync_playwright

    js = """() => { const bad = []; for (const sec of document.querySelectorAll('section.page')) { const pr = sec.getBoundingClientRect();
      for (const el of sec.querySelectorAll('.cap,.bal')) { const r = el.getBoundingClientRect(); const s = el.querySelector('span').getBoundingClientRect();
        if (s.top < r.top - 1 || s.bottom > r.bottom + 1 || s.left < r.left - 1 || s.right > r.right + 1) bad.push(['text', sec.dataset.page, el.textContent.slice(0, 30), r.height, s.height]);
        if (r.left < pr.left || r.right > pr.right || r.top < pr.top || r.bottom > pr.bottom) bad.push(['page', sec.dataset.page, el.textContent.slice(0, 30)]); } } return bad; }"""
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=_chromium())
        pg = b.new_page()
        try:
            for preset in T.PRESETS:
                client.put("/api/volumes/1/typography", json={"preset": preset, "size": "XL"})
                for lang in ("en", "hi"):
                    for pid in range(1, 11):
                        pg.set_content(client.get(f"/api/pages/{pid}/render?lang={lang}&embed=true&paper=print").text)
                        pg.evaluate("document.fonts.ready")
                        assert pg.evaluate(js) == [], (preset, lang, pid)
        finally:
            client.put("/api/volumes/1/typography", json={"preset": "illuminated-manuscript", "size": "L"})
            b.close()


# --- export -----------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("pdffonts") is None, reason="pdffonts not installed")
def test_export_embeds_chosen_fonts(client):
    from tests.test_studio import _lock_all

    _lock_all(client)
    client.put("/api/volumes/1/typography", json={"preset": "illuminated-manuscript", "size": "L"})
    for pid in (1, 2):
        client.put(f"/api/pages/{pid}", json={"status": "approved"})
    for lang, want in (("en", ("CinzelDecorative", "IM_FELL_English")), ("hi", ("YatraOne", "TiroDevaHindi"))):
        r = client.post("/api/export", json={"chapter_id": 1, "lang": [lang], "paper": "print", "upscale": False, "allow_partial": True})
        assert r.status_code == 202, r.text
        j = wait_job(client, r.json()["job_id"])
        assert j["status"] == "done", j["log"]
        pdf = db.DATA_DIR / j["result"]["pdf"]
        out = subprocess.run(["pdffonts", str(pdf)], capture_output=True, text=True).stdout
        for name in want:
            assert name in out, (lang, name, out)
        if lang == "en":
            assert "Yatra" not in out and "Laila" not in out
