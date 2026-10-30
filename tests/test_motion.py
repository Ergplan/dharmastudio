"""MOTION: Ken Burns clips, the 30 s assembly (audio / no audio), Seedance dry-run takes, moments, publish gate and the
site (watch page with exact Devanagari, manifest schema)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.motion import assemble as A
from engine.motion import ffmpeg as FF
from engine.motion import kenburns as KB

from motion_fixtures import motion_client, page_id, wait_job

ART = sorted((Path(__file__).resolve().parent.parent / "engine" / "seed_art").glob("*.jpg"))


@pytest.fixture(scope="module")
def c(client):
    return motion_client(client)


def test_health(c):
    h = c.get("/api/motion/health").json()
    assert h["ffmpeg"]["ok"] and h["zxing"] and h["ok"]


@pytest.mark.parametrize("move", KB.MOVES)
def test_kenburns_clip_duration_and_size(tmp_path, move):
    out = KB.render_clip(KB.Shot(ART[0], move, 5.0), tmp_path / f"{move}.mp4", (160, 90), quality="draft")
    info = FF.probe(out)
    assert (info["width"], info["height"]) == (160, 90)
    assert abs(info["duration"] - 5.0) < 0.05
    assert FF.count_frames(out) == 120


def _spec(size, **kw):
    shots = [A.ShotSpec(image=ART[i], move=m, duration=6) for i, m in enumerate(["push_in", "parallax", "pan"])]
    return A.FilmSpec(code="1-9", lang=kw.pop("lang", "en"), size=size, shots=shots, title="The Last Night of Lanka", subtitle="Book 1, page 9",
                      end_url="cycleofdharma.world/v/1-9", narration_text="The sea was silent. Rama stood at the water's edge.", quality="draft", **kw)


def test_assembly_is_exactly_30s_without_audio_sources(tmp_path):
    out = tmp_path / "a.mp4"
    info = A.assemble(_spec((192, 108)), out, tmp_path / "p.jpg")
    assert abs(info["duration"] - 30.0) < 0.05 and info["frames"] == 720
    assert FF.count_frames(out) == 720
    assert info["has_audio"] and info["audio_codec"] == "aac" and info["video_codec"] == "h264"  # a silent AAC track
    assert (tmp_path / "p.jpg").stat().st_size > 1000
    assert info["bytes"] < A.MAX_BYTES


def test_assembly_with_narration_and_ducked_music(tmp_path):
    narr, music = tmp_path / "n.mp3", tmp_path / "m.mp3"
    FF.run(["-f", "lavfi", "-i", "sine=frequency=330:duration=9", str(narr)])
    FF.run(["-f", "lavfi", "-i", "sine=frequency=110:duration=4", str(music)])
    spec = _spec((108, 192), lang="hi", narration_audio=narr, music=music, word_times=[("राम", 0.1, 0.6), ("ने", 0.7, 0.9), ("देखा", 1.0, 1.6)])
    spec.narration_text = "राम ने देखा"
    info = A.assemble(spec, tmp_path / "b.mp4", narr_dur=9.0)
    assert abs(info["duration"] - 30.0) < 0.05 and info["has_audio"]
    assert (info["width"], info["height"]) == (108, 192)
    assert info["cues"][0]["start"] == pytest.approx(1.6, abs=0.01)  # word timing + the 1.5 s title card
    g = A.audio_graph(spec, 9.0)[1]
    assert "0.1995" in g  # music ducked by -14 dB under the narration


def test_timeline_scales_shots_to_30s():
    spec = _spec((64, 36))
    spec.shots = spec.shots * 2  # 6 x 6 s = 36 s of shots
    segs = A.plan(spec)
    assert segs[-1][1] + segs[-1][2] == 720
    assert sum(A.shot_seconds(spec)) == pytest.approx(30 - 1.5 - 2 + 7 * 0.5, abs=0.05)


def test_moment_seedance_render_publish_and_site(c, session):
    pid = page_id(c, 9)
    r = c.post("/api/moments", json={"page_id": pid, "title_hi": "लंका की अंतिम रात"})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["code"] == "1-9" and m["status"] == "draft" and len(m["shots"]) >= 1
    assert m["narration_en"]  # captions joined
    assert c.post("/api/moments", json={"page_id": pid}).status_code == 409
    # Seedance dry run: job -> take -> sent to the moment
    panel_id = m["shots"][0]["panel_id"]
    est = c.get("/api/seedance/estimate", params={"provider": "fal", "duration": 5, "resolution": "1080p"}).json()
    assert "usd_if_live" in est
    r = c.post("/api/seedance/takes", json={"panel_id": panel_id, "duration": 5, "camera": "push_in", "provider": "fal", "dry_size": [128, 72]})
    assert r.status_code == 202, r.text
    take = r.json()["take"]
    assert "Keep the locked characters' faces and attire exactly" in take["prompt"]
    j = wait_job(c, r.json()["job_id"])
    assert j["status"] == "done", j["log"]
    t = c.get(f"/api/seedance/takes/{take['id']}").json()
    assert t["status"] == "done" and t["dry_run"] and t["url"].endswith(".mp4")
    m = c.post(f"/api/seedance/takes/{take['id']}/send", json={"moment_id": m["id"]}).json()["moment"]
    assert any(s.get("take_id") == take["id"] and s["source"] == "seedance" for s in m["shots"])
    # shot duration rules
    assert c.put(f"/api/moments/{m['id']}", json={"shots": [{"panel_id": panel_id, "duration_s": 12}]}).status_code == 422
    # render (tiny), approve
    assert c.post(f"/api/moments/{m['id']}/approve").status_code == 409
    j = wait_job(c, c.post(f"/api/moments/{m['id']}/render", json={"size": "tiny"}).json()["job_id"])
    assert j["status"] == "done", j["log"]
    m = c.get(f"/api/moments/{m['id']}").json()
    assert m["status"] == "review" and set(m["outputs"]) >= {"en_16x9", "en_9x16", "hi_16x9", "hi_9x16", "poster"}
    for k, v in m["render_meta"]["variants"].items():
        assert abs(v["duration"] - 30.0) < 0.05, k
    assert c.post(f"/api/moments/{m['id']}/approve").json()["status"] == "approved"
    # an untested QR blocks publishing
    q = c.post(f"/api/moments/{m['id']}/qr", json={"test": False}).json()["qr"]
    assert not q["tested"]
    r = c.post(f"/api/moments/{m['id']}/publish", json={"deploy": False})
    assert r.status_code == 409 and "decode test" in r.json()["detail"]
    assert c.post(f"/api/qr/{q['id']}/test").json()["tested"]
    r = c.post(f"/api/moments/{m['id']}/publish", json={"deploy": False})
    assert r.status_code == 200, r.text
    j = wait_job(c, r.json()["job_id"])
    assert j["status"] == "done", j["log"]
    # the preview site: watch page with the page's verse in exact Devanagari, Hindi caption, OG tags
    from backend import db, site_gen

    man = json.loads((db.DATA_DIR / "site" / "preview" / "manifest.json").read_text())
    site_gen.validate_manifest(man)
    mo = next(x for x in man["moments"] if x["code"] == "1-9")
    page = c.get("/site-preview/v/1-9/")
    assert page.status_code == 200
    html = page.text
    assert "लंका की अंतिम रात" in html and "og:video" in html and "From The Cycle of Dharma — Book 1, page 9" in html
    if mo["verse"]:
        for line in mo["verse"]["lines"]:
            assert line in html  # exact Devanagari, byte for byte
    hi_caption = m["narration_hi"]
    if hi_caption:
        assert hi_caption.split()[0] in html
    assert c.get("/site-preview/v/does-not-exist/").status_code == 404
    assert c.get("/site-preview/robots.txt").status_code == 200
    assert "<loc>https://cycleofdharma.world/v/1-9</loc>" in c.get("/site-preview/sitemap.xml").text


def test_watch_page_devanagari_verse_exact():
    from backend import site_gen
    from engine.comic import manuscript as MS

    v = MS.verses()[0]
    mo = {"code": "1-1", "title_en": "T", "title_hi": "", "volume": 1, "chapter": 1, "chapter_title": "C", "page": 1, "caption_en": "c", "caption_hi": "क",
          "verse": {"id": v["id"], "source": v["source"], "lines": v["lines"], "iast": v.get("iast", ""), "meaning": v["meaning"]},
          "media": {k: f"/m/{k}" for k in ("en_16x9", "en_9x16", "hi_16x9", "hi_9x16", "poster")}, "duration_s": 30.0, "published_at": None}
    man = {"site_url": "https://cycleofdharma.world", "book": {"author": "Rachit Agarwal"}}
    html = site_gen.watch_html(man, mo, "", {"imfell": "a.woff2", "imfell-italic": "b.woff2", "tiro": "c.woff2", "spectral": "d.woff2"})
    for line in v["lines"]:
        assert line in html


def test_site_publish_to_blob_uses_stable_pathnames(c, session, monkeypatch, tmp_path):
    from backend import site_gen

    calls = []

    class FakeClient:
        def put(self, url, params=None, content=None, headers=None):  # noqa: ANN001
            calls.append((params["pathname"], headers))

            class R:
                status_code = 200

                def raise_for_status(self):
                    pass

                def json(self):
                    return {"url": f"https://abc.public.blob.vercel-storage.com/{params['pathname']}", "pathname": params["pathname"]}

            return R()

        def post(self, url, json=None, headers=None):  # noqa: ANN001
            calls.append(("REVALIDATE " + url, headers))

            class R:
                status_code = 200

            return R()

    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_test")
    monkeypatch.setenv("REVALIDATE_SECRET", "s3cret")
    monkeypatch.setattr(site_gen, "publish_state_path", lambda: tmp_path / "state.json")
    res = site_gen.publish(session, client=FakeClient())
    names = [x[0] for x in calls]
    assert "moments/1-9/en-16x9.mp4" in names and "moments/1-9/poster.jpg" in names and "manifest.json" in names
    assert calls[0][1]["x-add-random-suffix"] == "0" and calls[0][1]["x-allow-overwrite"] == "1"
    assert res["revalidate"]["ok"] and res["manifest_url"].endswith("/manifest.json")
    # second publish: unchanged media skipped (sha1)
    calls.clear()
    res2 = site_gen.publish(session, client=FakeClient())
    assert res2["uploaded"] == [] and res2["skipped"] >= 5
    assert [x[0] for x in calls if not x[0].startswith("REVALIDATE")] == ["manifest.json"]
