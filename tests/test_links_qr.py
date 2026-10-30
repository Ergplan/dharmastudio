"""LINKS (codes, lock rule, CSV, manifest/redirects) and the QR BUILDER (decode at 150/300 dpi, exports, placement)."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from engine import qr as Q

from motion_fixtures import motion_client, page_id

URL = "https://cycleofdharma.world/v/1-9"


@pytest.fixture(scope="module")
def c(client):
    return motion_client(client)


# ---------------------------------------------------------------------------------
# engine: decode + exports
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize("module", Q.MODULES)
@pytest.mark.parametrize("emblem", ["none", "om", "chakra", "lotus"])
def test_qr_decodes_at_150_and_300_dpi(module, emblem):
    res = Q.decode_test(URL, Q.QRStyle(module=module, emblem=emblem, size_mm=20, label="hi" if emblem == "om" else "en"))
    assert res["ok"], res
    assert set(res["dpis"]) == {"300", "150"}
    assert all(v["read"] == URL for v in res["dpis"].values())


def test_qr_emblem_area_capped_and_min_size():
    st = Q.QRStyle(emblem="chakra", emblem_scale=0.9).normalised()
    sym = Q.encode(URL, "H")
    x, y, side = Q.emblem_box(sym, st)
    assert side * side <= Q.MAX_EMBLEM_AREA * sym.n * sym.n
    assert Q.QRStyle(size_mm=8).normalised().size_mm == Q.MIN_MM
    with pytest.raises(ValueError):
        Q.validate_size(12)


def test_qr_exports_valid():
    st = Q.QRStyle(module="rounded", emblem="om", size_mm=24)
    svg = Q.svg(URL, st)
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg") and root.get("width") == "24.000mm"
    assert svg.count("<path") > 3  # finders + typeset label + ॐ as outlines
    png = Q.png(URL, st, 600)
    im = Image.open(io.BytesIO(png))
    w, h = Q.dimensions(URL, st)
    assert abs(im.width - w / 25.4 * 600) <= 2 and abs(im.height - h / 25.4 * 600) <= 2
    assert round(im.info["dpi"][0]) == 600
    assert Q.pdf(URL, st)[:5] == b"%PDF-"
    # the PNG export itself reads back
    bg = Image.new("RGB", im.size, "white")
    bg.paste(im, mask=im.getchannel("A"))
    assert URL in Q.decode(bg)


def test_qr_wrong_url_never_passes():
    st = Q.QRStyle()
    res = Q.decode_test(URL, st)
    assert res["ok"]
    assert not Q.decode_test(URL + "x", st)["dpis"]["300"]["read"] == URL


# ---------------------------------------------------------------------------------
# links API
# ---------------------------------------------------------------------------------


def test_link_code_rules(c):
    pid = page_id(c, 4)
    for bad in ("Has-Caps", "-x", "x-", "a b", "v", "api", "", "x" * 41):
        r = c.get("/api/links/check-code", params={"code": bad})
        assert r.status_code == 200 and not r.json()["ok"], bad
    r = c.post("/api/links", json={"target_type": "page", "target_ref": str(pid)})
    assert r.status_code == 201, r.text
    link = r.json()
    assert link["code"] == "1-4" and link["short_url"] == "https://cycleofdharma.world/v/1-4"
    # collision
    r = c.post("/api/links", json={"target_type": "page", "target_ref": str(pid), "code": "1-4"})
    assert r.status_code == 409
    assert c.get("/api/links/check-code", params={"code": "1-4"}).json()["suggestion"] == "1-4-2"
    # vanity code + rename while unprinted
    r = c.put(f"/api/links/{link['id']}", json={"code": "lanka-night"})
    assert r.status_code == 200 and r.json()["code"] == "lanka-night"
    # broken: missing target
    r = c.post("/api/links", json={"target_type": "page", "target_ref": "99999"})
    assert r.status_code == 404
    c.delete(f"/api/links/{link['id']}")


def test_print_lock_rule(c):
    r = c.post("/api/links", json={"target_type": "url", "target_ref": "https://example.org/a", "code": "printed-one"})
    assert r.status_code == 201
    lid = r.json()["id"]
    assert c.post(f"/api/links/{lid}/lock").json()["print_locked"]
    # code can never change, link never deleted, never unlocked
    assert c.put(f"/api/links/{lid}", json={"code": "renamed"}).status_code == 409
    assert c.delete(f"/api/links/{lid}").status_code == 409
    assert c.put(f"/api/links/{lid}", json={"print_locked": False}).status_code == 409
    # destination and enabled may change
    r = c.put(f"/api/links/{lid}", json={"destination_override": "https://www.youtube.com/watch?v=abc", "enabled": False})
    assert r.status_code == 200
    j = r.json()
    assert j["code"] == "printed-one" and j["resolved"]["kind"] == "coming_soon"
    r = c.put(f"/api/links/{lid}", json={"enabled": True})
    assert r.json()["resolved"] == {"kind": "redirect", "destination": "https://www.youtube.com/watch?v=abc", "label": "302 → override"}
    csv = c.get("/api/links/export.csv").text
    assert csv.splitlines()[0] == "code,url,volume,page,title,locked,enabled"
    assert "printed-one,https://cycleofdharma.world/v/printed-one" in csv


def test_manifest_links_and_redirect_kinds(c, session):
    from backend import site_gen

    r = c.post("/api/links", json={"target_type": "url", "target_ref": "https://example.org/b", "code": "off-for-now"})
    lid = r.json()["id"]
    c.put(f"/api/links/{lid}", json={"enabled": False})
    man = site_gen.build_manifest(session, lambda code, key, rel: f"https://blob.example/{code}/{key}")
    site_gen.validate_manifest(man)
    by = {x["code"]: x for x in man["links"]}
    assert by["off-for-now"]["kind"] == "coming_soon" and by["off-for-now"]["destination"] is None
    assert by["printed-one"]["kind"] == "redirect" and by["printed-one"]["destination"].startswith("https://www.youtube.com/")


# ---------------------------------------------------------------------------------
# QR API: tested gate, placement, print lock on export
# ---------------------------------------------------------------------------------


def test_qr_record_test_place_and_lock(c, session):
    pid = page_id(c, 7)
    r = c.post("/api/qr", json={"target_type": "page", "target_ref": str(pid), "style": {"module": "dots", "emblem": "lotus", "size_mm": 22}})
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["code"] == "1-7" and not q["tested"]
    assert c.post("/api/qr", json={"link_id": q["link_id"], "style": {"size_mm": 15}}).status_code == 422
    # untested: cannot be placed or approved
    assert c.post(f"/api/qr/{q['id']}/place", json={"page_id": pid}).status_code == 409
    assert c.post(f"/api/qr/{q['id']}/approve").status_code == 409
    q = c.post(f"/api/qr/{q['id']}/test").json()
    assert q["tested"] and q["test"]["dpis"]["150"]["ok"]
    r = c.post(f"/api/qr/{q['id']}/place", json={"page_id": pid})
    assert r.status_code == 201
    pl = r.json()["placement"]
    # inside the trim, in the lower half, on the outer side (page 7 is a recto: right)
    assert 0 <= pl["x_mm"] and pl["x_mm"] + pl["w_mm"] <= 170 and pl["y_mm"] > 130 and pl["x_mm"] > 85
    # a style change makes it untested again
    q2 = c.put(f"/api/qr/{q['id']}", json={"style": {"module": "square"}}).json()
    assert not q2["tested"]
    c.post(f"/api/qr/{q['id']}/test")
    # move/resize the element, 20 mm minimum
    assert c.put(f"/api/page-qr/{pl['id']}", json={"w_mm": 12}).status_code == 422
    assert c.put(f"/api/page-qr/{pl['id']}", json={"x_mm": 120, "y_mm": 200, "w_mm": 24}).json()["w_mm"] == 24
    els = c.get(f"/api/pages/{pid}/qr").json()
    assert els and els[0]["code"] == "1-7" and els[0]["tested"]
    # the page render carries the QR; a print export locks the link
    html = c.get(f"/api/pages/{pid}/render", params={"paper": "print"}).text
    assert "motion/qr/qr" in html
    from backend import links

    assert links.lock_for_pages(session, [pid]) == ["1-7"]
    session.commit()
    assert c.get(f"/api/links/{q['link_id']}").json()["print_locked"]
    for ex in ("svg", "png", "pdf"):
        r = c.get(f"/api/qr/{q['id']}/export.{ex}")
        assert r.status_code == 200 and len(r.content) > 500


def test_live_render_route(c):
    r = c.post("/api/qr/render", json={"code": "1-9", "style": {"emblem": "om", "label": "hi"}, "test": True})
    assert r.status_code == 200
    j = r.json()
    assert j["png"].startswith("data:image/png;base64,") and j["test"]["ok"]
