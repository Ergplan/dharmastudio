"""Motion demo: Chapter 1 pages 9 and 6 become QR moments (Ken Burns), rendered EN + HI x 16:9 + 9:16 at full quality,
with tested QRs placed on the pages, the site built, and screenshots of the studio and the Next.js watch page.

  # a studio on a spare port with its own data dir (never the author's), then:
  .venv/bin/python scripts/motion_demo.py --url http://127.0.0.1:8790 [--size full|preview] [--web]

Outputs: docs/demo/*.mp4 + posters + site.zip (git-ignored except posters), docs/screens/{motion_editor,qr_builder,
links,seedance_builder,site_watch_page_mobile,site_watch_page_desktop,page9_with_qr}.png
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "docs" / "demo"
SCREENS = ROOT / "docs" / "screens"

# Hindi narration for the demo pages (drafts for the author's translator; the English is the book's text)
PAGES = {
    9: {"title_en": "The Line of Gold", "title_hi": "स्वर्ण रेखा",
        "narration_hi": "वह बाण स्वर्ण की ऐसी उज्ज्वल रेखा बनकर रणभूमि के पार गया कि वानरों ने अपनी आँखें ढक लीं और दीवारों पर खड़े राक्षस चीख उठे।"},
    6: {"title_en": "The Arrow of Agastya", "title_hi": "अगस्त्य का बाण",
        "narration_hi": "उस दृष्टि में विभीषण ने समझ लिया कि भाई से विश्वासघात के लिए उसका न्याय नहीं हो रहा था; सत्य के लिए उसे धन्यवाद दिया जा रहा था। "
                        "राम ने अपने तूणीर में हाथ डाला और वह बाण निकाला जो ऋषि अगस्त्य ने वर्षों पहले वन में उन्हें ठीक इसी घड़ी के लिए दिया था। "
                        "जब राम ने उसे प्रत्यंचा पर चढ़ाया, रणभूमि की हवा थम गई। समुद्र पर धुआँ हवा में ठहर गया। मीनारों की लपटें बाण की ओर ज़रा-सी झुक गईं, जैसे फूल सूर्य की ओर झुकता है।"},
}


def call(base: str, method: str, path: str, body: dict | None = None, timeout: int = 600) -> dict:
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def wait(base: str, job_id: int, label: str) -> dict:
    t0 = time.time()
    while True:
        j = call(base, "GET", f"/api/jobs/{job_id}")
        if j["status"] in ("done", "failed", "stopped"):
            print(f"  {label}: {j['status']} in {time.time() - t0:.0f} s")
            if j["status"] != "done":
                print(j["log"][-2000:])
                sys.exit(1)
            return j
        time.sleep(2)


def chromium() -> str:
    hits = sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome"))
    if not hits:
        sys.exit("no Chromium under /opt/pw-browsers")
    return hits[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8790")
    ap.add_argument("--size", default="full")
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--web", action="store_true", help="build + start web/ (next start) for the watch-page screenshots")
    ap.add_argument("--web-port", type=int, default=3790)
    ap.add_argument("--no-shots", action="store_true", help="skip the screenshots")
    ap.add_argument("--shots-only", action="store_true", help="only the screenshots (moments already rendered and published)")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    DEMO.mkdir(parents=True, exist_ok=True)
    SCREENS.mkdir(parents=True, exist_ok=True)

    pages = call(base, "GET", "/api/pages?chapter_id=1")
    pid = {p["number"]: p["id"] for p in pages}
    if a.shots_only:
        ms = {m["page"]: m for m in call(base, "GET", "/api/moments")}
        shots(base, ms, pid, a)
        return
    moments = {}
    for n, meta in PAGES.items():
        m = call(base, "GET", f"/api/pages/{pid[n]}/moment")
        if not m:
            m = call(base, "POST", "/api/moments", {"page_id": pid[n], **{k: meta[k] for k in ("title_en", "title_hi")}})
        m = call(base, "PUT", f"/api/moments/{m['id']}", {"title_en": meta["title_en"], "title_hi": meta["title_hi"],
                                                         "narration_hi": m["narration_hi"] or meta["narration_hi"]})
        moments[n] = m
        print(f"page {n}: moment {m['id']} /v/{m['code']} · {len(m['shots'])} shots · {m['timing']}")

    # a Seedance dry-run take on page 9 (for the builder screenshot; the moments stay Ken Burns)
    p9 = next(p for p in pages if p["number"] == 9)
    if not call(base, "GET", f"/api/seedance/takes?panel_id={p9['panels'][0]['id']}"):
        r = call(base, "POST", "/api/seedance/takes", {"panel_id": p9["panels"][0]["id"], "duration": 5, "camera": "push_in", "provider": "fal", "resolution": "1080p", "aspect": "16:9"})
        wait(base, r["job_id"], "seedance dry run")

    if not a.skip_render:
        for n, m in moments.items():
            r = call(base, "POST", f"/api/moments/{m['id']}/render", {"size": a.size})
            wait(base, r["job_id"], f"render page {n}")
    for n, m in moments.items():
        m = call(base, "GET", f"/api/moments/{m['id']}")
        if m["status"] == "review":
            m = call(base, "POST", f"/api/moments/{m['id']}/approve")
        q = call(base, "POST", f"/api/moments/{m['id']}/qr", {"test": True, "style": {"module": "rounded", "emblem": "om" if n == 9 else "chakra", "size_mm": 22, "label": "en"}})["qr"]
        assert q["tested"], q
        call(base, "POST", f"/api/moments/{m['id']}/qr", {"test": False, "place": True})
        r = call(base, "POST", f"/api/moments/{m['id']}/publish", {"deploy": False})
        wait(base, r["job_id"], f"publish page {n} (site preview)")
        m = call(base, "GET", f"/api/moments/{m['id']}")
        moments[n] = m
        meta = m["render_meta"].get("variants", {})
        for key, url in m["outputs"].items():
            src = Path(os.environ.get("DHARMA_DATA_DIR", ROOT / "data")) / url.replace("/media/", "", 1)
            dst = DEMO / f"{m['code']}-{key.replace('_', '-')}{src.suffix}"
            shutil.copyfile(src, dst)
        print(f"page {n}: " + ", ".join(f"{k} {v['duration']:.2f}s {v['bytes'] / 1e6:.1f}MB" for k, v in meta.items()))
    z = call(base, "POST", "/api/site/export")
    shutil.copyfile(Path(os.environ.get("DHARMA_DATA_DIR", ROOT / "data")) / z["url"].replace("/media/", "", 1), DEMO / "site.zip")
    print(f"site.zip {z['bytes'] / 1e6:.1f} MB")
    if not a.no_shots:
        shots(base, moments, pid, a)


def shots(base: str, moments: dict, pid: dict, a: argparse.Namespace) -> None:
    from playwright.sync_api import sync_playwright

    web = None
    if a.web:
        env = {**os.environ, "MANIFEST_URL": f"{base}/site-preview/manifest.json", "SITE_URL": "https://cycleofdharma.world", "PORT": str(a.web_port)}
        subprocess.run(["npm", "run", "build"], cwd=ROOT / "web", env=env, check=True, capture_output=True)
        web = subprocess.Popen(["npx", "next", "start", "-p", str(a.web_port)], cwd=ROOT / "web", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{a.web_port}/", timeout=2)
                break
            except Exception:  # noqa: BLE001
                time.sleep(1)
    m9 = moments[9]
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=chromium())
            pg = b.new_page(viewport={"width": 1500, "height": 940})
            pg.goto(f"{base}/#/motion?tab=moments&m={m9['id']}")
            pg.wait_for_selector("[data-testid=shot]", timeout=30000)
            pg.wait_for_timeout(1500)
            pg.screenshot(path=str(SCREENS / "motion_editor.png"))
            pg.goto(f"{base}/#/motion?tab=qr&q={m9['qr_id']}")
            pg.wait_for_timeout(2500)
            pg.screenshot(path=str(SCREENS / "qr_builder.png"))
            pg.goto(f"{base}/#/motion?tab=links")
            pg.wait_for_selector("[data-testid=link-row]")
            pg.wait_for_timeout(800)
            pg.screenshot(path=str(SCREENS / "links.png"))
            pg.goto(f"{base}/#/motion?tab=seedance")
            pg.wait_for_timeout(1000)
            pg.select_option("select >> nth=1", label="page 9")
            pg.wait_for_timeout(500)
            pg.locator("button[title] img[alt='panel 1']").first.click()
            pg.wait_for_selector("[data-testid=take]")
            pg.wait_for_timeout(1500)
            pg.screenshot(path=str(SCREENS / "seedance_builder.png"))
            # page 9 as printed-on-screen with its QR
            pp = b.new_page(viewport={"width": 760, "height": 1140})
            pp.goto(f"{base}/api/pages/{pid[9]}/render?lang=en")
            pp.wait_for_timeout(2500)
            pp.screenshot(path=str(SCREENS / "page9_with_qr.png"), full_page=True)
            watch = f"http://127.0.0.1:{a.web_port}/v/{m9['code']}" if web else f"{base}/site-preview/v/{m9['code']}/"
            d = b.new_page(viewport={"width": 1366, "height": 900})
            d.goto(watch + "?lang=en")
            d.wait_for_timeout(2500)
            d.screenshot(path=str(SCREENS / "site_watch_page_desktop.png"), full_page=True)
            mob = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
            mob.goto(watch + "?lang=hi")
            mob.wait_for_timeout(2500)
            mob.screenshot(path=str(SCREENS / "site_watch_page_mobile.png"), full_page=True)
            b.close()
    finally:
        if web:
            os.killpg(web.pid, signal.SIGTERM)
    print("screenshots saved to docs/screens/")


if __name__ == "__main__":
    main()
