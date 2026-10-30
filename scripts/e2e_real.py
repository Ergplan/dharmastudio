"""End-to-end pass through every screen against the REAL backend (not the mock).

    .venv/bin/python scripts/e2e_real.py [--base http://localhost:8787] [--shots docs/screens]

Expects a freshly seeded studio (python -m backend.seed --reset) running in dry-run (no keys needed).
Logs every network response >= 400, every console error and page error; exits non-zero if any occurred or a step
failed. Saves screenshots of every screen to <shots>/real_*.png.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def api(base: str, method: str, path: str, body: object | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
        return json.loads(raw) if r.headers.get("content-type", "").startswith("application/json") else raw.decode()


def wait_job(base: str, job_id: int, timeout: float = 300) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = api(base, "GET", f"/api/jobs/{job_id}")
        if j["status"] in ("done", "failed", "stopped"):
            return j
        time.sleep(0.4)
    raise TimeoutError(f"job {job_id}")


class Run:
    def __init__(self, base: str, shots: Path) -> None:
        self.base, self.shots = base, shots
        self.errors: list[str] = []
        self.steps: list[str] = []

    def ok(self, msg: str) -> None:
        self.steps.append(msg)
        print(f"  ok  {msg}", flush=True)

    def shot(self, page: Page, name: str) -> None:
        page.wait_for_timeout(700)
        p = self.shots / f"real_{name}.png"
        page.screenshot(path=str(p))
        print(f"  shot {p.relative_to(ROOT)}", flush=True)

    def check(self, cond: bool, msg: str) -> None:
        if not cond:
            raise AssertionError(msg)
        self.ok(msg)


def hook(page: Page, run: Run) -> None:
    def on_response(r):  # noqa: ANN001
        if r.status >= 400:
            run.errors.append(f"HTTP {r.status} {r.request.method} {r.url}")
            print(f"  !!  HTTP {r.status} {r.request.method} {r.url}", flush=True)

    def on_console(m):  # noqa: ANN001
        if m.type == "error":
            run.errors.append(f"console: {m.text}")
            print(f"  !!  console: {m.text}", flush=True)

    page.on("response", on_response)
    page.on("console", on_console)
    page.on("pageerror", lambda e: (run.errors.append(f"pageerror: {e}"), print(f"  !!  pageerror: {e}", flush=True)))


def goto(page: Page, run: Run, route: str) -> None:
    page.goto(f"{run.base}/#/{route}")
    page.wait_for_load_state("networkidle")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8787")
    ap.add_argument("--shots", default=str(ROOT / "docs" / "screens"))
    a = ap.parse_args()
    shots = Path(a.shots)
    shots.mkdir(parents=True, exist_ok=True)
    run = Run(a.base, shots)
    base = a.base
    ref_png = ROOT / "engine" / "refs" / "rama_reference.png"

    exe = next(iter(sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome"))), None)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception:  # noqa: BLE001
            browser = pw.chromium.launch(executable_path=exe)
        ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, accept_downloads=True)
        page = ctx.new_page()
        hook(page, run)
        try:
            # ---------------- Project ----------------
            print("Project", flush=True)
            goto(page, run, "project")
            page.get_by_text("Onboarding journey").wait_for()
            run.check(page.get_by_text("Cost ledger").is_visible(), "project: stepper, keys and ledger render")
            page.get_by_role("button", name="Models").first.click()
            page.wait_for_timeout(400)
            run.check(page.locator("select").count() >= 4, "project: models step shows the four role selectors")
            run.shot(page, "project")

            # ---------------- Characters ----------------
            print("Characters", flush=True)
            chars = api(base, "GET", "/api/characters")
            ash = next(c for c in chars if c["form_key"] == "ashwasena")
            goto(page, run, f"characters/{ash['id']}")
            page.get_by_text("Reference images").wait_for()
            lock_btn = page.locator("button[title='Approve a primary reference first']")
            run.check(lock_btn.count() == 1 and lock_btn.is_disabled(), "characters: lock is disabled without an approved primary")
            page.locator("input[type=file][accept='image/*']").set_input_files(str(ref_png))
            page.locator("button[title='Approve']").first.wait_for(timeout=10000)
            page.locator("button[title='Approve']").first.click()
            page.wait_for_timeout(500)
            page.locator("button[title='Make primary']").first.click()
            page.locator("button[title='Lock']").wait_for(timeout=10000)
            page.locator("button[title='Lock']").click()
            page.locator("button[title='Unlock']").wait_for(timeout=10000)
            run.check(next(c for c in api(base, "GET", "/api/characters") if c["id"] == ash["id"])["locked"], "characters: upload → approve → primary → lock (Ashwasena)")
            # Hanuman (baba) for page 2 through the API, same steps
            hb = next(c for c in chars if c["form_key"] == "hanuman/baba")
            rama = next(c for c in chars if c["form_key"] == "rama")
            req = urllib.request.Request(f"{base}/api/characters/{hb['id']}/refs/upload", method="POST")
            boundary = "----e2e"
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"ref.png\"\r\nContent-Type: image/png\r\n\r\n").encode() + ref_png.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
            req.data = body
            req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
            rid = json.loads(urllib.request.urlopen(req).read())[0]["id"]
            api(base, "PUT", f"/api/characters/{hb['id']}/refs/{rid}", {"approved": True, "is_primary": True})
            api(base, "PUT", f"/api/characters/{hb['id']}", {"locked": True})
            goto(page, run, f"characters/{rama['id']}")
            page.get_by_text("Reference images").wait_for()
            run.shot(page, "characters")

            # ---------------- Canvas ----------------
            print("Canvas", flush=True)
            goto(page, run, "canvas")
            vols = api(base, "GET", "/api/volumes")
            page.get_by_text("Iron (Dwapara)", exact=True).nth(1).click()  # volume 2's row
            page.wait_for_timeout(600)
            run.check(api(base, "GET", "/api/volumes")[1]["canvas_id"] is not None, "canvas: picking Iron sets volume 2's canvas")
            page.get_by_text("Burnt vellum (Lanka)", exact=True).first.hover()
            page.wait_for_timeout(1500)
            run.check(page.frame_locator("iframe").first.locator("section.page").count() == 1, "canvas: hover renders the preview page")
            run.shot(page, "canvas")
            page.mouse.move(5, 5)
            assert vols[0]["canvas_key"] == "parchment"

            # ---------------- Script ----------------
            print("Script", flush=True)
            goto(page, run, "script")
            cap = page.locator("label:has-text('Caption EN') textarea").first
            cap.wait_for()
            original = cap.input_value()
            cap.fill(original + " [e2e]")
            page.wait_for_timeout(1800)
            p1 = api(base, "GET", "/api/pages?chapter_id=1")[0]["panels"][0]
            run.check(p1["caption_en"].endswith("[e2e]"), "script: caption edit autosaves (PUT /api/panels)")
            run.shot(page, "script")
            cap.fill(original)
            page.wait_for_timeout(1500)
            run.check(api(base, "GET", "/api/pages?chapter_id=1")[0]["panels"][0]["caption_en"] == original, "script: caption restored")

            # ---------------- Silhouettes (needed for marginalia) ----------------
            print("Silhouettes", flush=True)
            goto(page, run, "silhouettes")
            page.locator("label:has-text('Tags') input").fill("compass, map")
            page.locator("label:has-text('Prompt') textarea").fill("Fine monochrome ink drawing of an ornamental compass rose over a coastal map fragment")
            with page.expect_response(lambda r: "/api/silhouettes/generate" in r.url) as resp:
                page.get_by_role("button", name="Generate").first.click()
            jid = resp.value.json()["job_id"]
            run.check(wait_job(base, jid)["status"] == "done", "silhouettes: generate job (dry-run) done")
            page.wait_for_timeout(2500)
            run.check(len(api(base, "GET", "/api/silhouettes")) >= 1 and page.locator("img[src*='/media/silhouettes/']").count() >= 1, "silhouettes: new silhouette listed with its image")
            run.shot(page, "silhouettes")

            # ---------------- Pages ----------------
            print("Pages", flush=True)
            pages = {p["number"]: p for p in api(base, "GET", "/api/pages?chapter_id=1")}
            # make pages 2-3 need the director: clear their selections (the seed picked every panel)
            for num in (2, 3):
                for pn in pages[num]["panels"]:
                    api(base, "POST", f"/api/panels/{pn['id']}/select", {"candidate_id": None})
            goto(page, run, "pages")
            page.get_by_text("Page 1").first.wait_for()
            thumbs = page.locator("div.w-\\[196px\\] button.rounded-md")

            def open_page(num: int) -> None:
                thumbs.nth(num - 1).click()
                page.get_by_text(f"Page {num}", exact=True).wait_for()
                page.wait_for_timeout(800)

            # regenerate on page 3 (plate, no characters) → new candidates → select
            open_page(3)
            page.keyboard.press("1")
            page.get_by_role("button", name="Regenerate 2").wait_for()
            before = len(api(base, "GET", f"/api/pages/{pages[3]['id']}")["panels"][0]["candidates"])
            page.locator("textarea[placeholder='What should change?']").fill("wider, no giants")
            with page.expect_response(lambda r: r.url.endswith("/generate") and r.request.method == "POST") as resp:
                page.get_by_role("button", name="Regenerate 2").click()
            j = wait_job(base, resp.value.json()["job_id"])
            run.check(j["status"] == "done", "pages: regenerate job (dry-run) done")
            page.wait_for_timeout(3500)
            panel3 = api(base, "GET", f"/api/pages/{pages[3]['id']}")["panels"][0]
            run.check(len(panel3["candidates"]) == before + 2 and panel3["candidates"][-1]["feedback_used"] == "wider, no giants", "pages: two new candidates with the feedback recorded")
            newest = panel3["candidates"][-1]
            page.locator(f"img[src$='{newest['path'].split('/')[-1]}']").first.click()
            page.wait_for_timeout(1200)
            run.check(api(base, "GET", f"/api/pages/{pages[3]['id']}")["panels"][0]["selected_candidate_id"] == newest["id"], "pages: clicking a candidate selects it")
            # rewrite scene → accept
            page.locator("textarea[placeholder='What should change?']").fill("eyes open, a single gold line of light")
            page.get_by_role("button", name="Rewrite scene only").click()
            page.get_by_role("button", name="Accept").wait_for(timeout=15000)
            page.get_by_role("button", name="Accept").click()
            page.wait_for_timeout(1200)
            run.check("Direction: eyes open" in api(base, "GET", f"/api/pages/{pages[3]['id']}")["panels"][0]["scene"], "pages: rewrite scene → accept stores the new scene")
            run.shot(page, "pages")

            # shard editor on page 4: drag a vertex, save, re-render
            open_page(4)
            page.get_by_role("button", name="Shards").click()
            page.wait_for_timeout(600)
            page.keyboard.press("1")
            page.wait_for_timeout(500)
            v = page.locator("svg circle.cursor-grab").first
            box = v.bounding_box()
            assert box, "no vertex handle"
            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.move(cx + 12, cy + 18, steps=6)
            page.mouse.up()
            page.wait_for_timeout(300)
            with page.expect_response(lambda r: "/api/panels/" in r.url and r.request.method == "PUT"):
                page.get_by_role("button", name="Save (1)").click()
            page.wait_for_timeout(1500)
            p4 = api(base, "GET", f"/api/pages/{pages[4]['id']}")["panels"][0]
            run.check(p4["shape"]["kind"] == "custom" and p4["shape"]["polygon_mm"] != pages[4]["panels"][0]["shape"]["polygon_mm"], "pages: shard vertex drag + Save stores the edited polygon (kind custom)")
            html = api(base, "GET", f"/api/pages/{pages[4]['id']}/render")
            x0, y0 = p4["shape"]["polygon_mm"][0]
            run.check(f"{x0:.2f},{y0:.2f}" in html, "pages: render uses the saved polygon")
            run.shot(page, "pages_shards")
            page.get_by_role("button", name="Shards").click()

            # marginalia on page 2: drop a silhouette, save
            open_page(2)
            page.get_by_role("button", name="Marginalia").click()
            page.wait_for_timeout(800)
            card = page.locator("div[draggable=true]").first
            stage = page.locator("svg.select-none").first
            sb = stage.bounding_box()
            assert sb
            card.drag_to(stage, target_position={"x": sb["width"] * 0.93, "y": sb["height"] * 0.5})
            page.wait_for_timeout(500)
            with page.expect_response(lambda r: f"/api/pages/{pages[2]['id']}" in r.url and r.request.method == "PUT"):
                page.locator("button.btn-primary:has-text('Save')").first.click()
            page.wait_for_timeout(1200)
            pg2 = api(base, "GET", f"/api/pages/{pages[2]['id']}")
            run.check(len(pg2["marginalia"]) == 1 and pg2["balance"]["ink"] > 0, "pages: marginalia drop + save (balance ink > 0)")
            run.check("class='marginalia'" in api(base, "GET", f"/api/pages/{pages[2]['id']}/render"), "pages: render draws the marginalia layer")
            run.shot(page, "pages_marginalia")
            page.get_by_role("button", name="Marginalia").click()

            # director: estimate + batch on pages 2-3 + progress
            page.get_by_role("button", name="Director").click()
            modal = page.locator("[role=dialog]")
            nums = modal.locator("input[type=number]")
            nums.nth(0).fill("2")
            nums.nth(1).fill("3")
            modal.get_by_text("images across").wait_for(timeout=10000)
            est_text = modal.get_by_text("images across").inner_text()
            run.check("on pages 2, 3" in est_text, f"pages: director estimate ({est_text.strip()})")
            run.shot(page, "pages_director")
            with page.expect_response(lambda r: "/api/director/batch" in r.url) as resp:
                modal.get_by_role("button", name="Run batch").click()
            bj = resp.value.json()
            seen_progress = False
            t0 = time.time()
            while time.time() - t0 < 300:
                j = api(base, "GET", f"/api/jobs/{bj['job_id']}")
                if isinstance(j["progress"], dict) and j["progress"]["done"] > 0:
                    seen_progress = True
                if j["status"] in ("done", "failed", "stopped"):
                    break
                time.sleep(0.3)
            run.check(j["status"] == "done" and j["result"]["pages_done"] == [2, 3], f"pages: director batch done ({j['result']})")
            run.check(seen_progress or j["progress"]["done"] == 2, "pages: batch progress reported page by page")
            page.wait_for_timeout(3500)
            st = {p["number"]: p for p in api(base, "GET", "/api/pages?chapter_id=1")}
            run.check(st[2]["status"] == "review" and st[3]["status"] == "review" and all(p["selected_candidate_id"] for p in st[2]["panels"]), "pages: pages 2-3 in review with critic pre-selections")

            # approve page 2 → artifact
            open_page(2)
            page.get_by_role("button", name="Approve").click()
            page.get_by_text("artifact saved").wait_for(timeout=15000)
            art = api(base, "GET", f"/api/pages/{pages[2]['id']}")["artifact"]
            run.check(bool(art) and urllib.request.urlopen(f"{base}/media/{art}").status == 200, f"pages: approve page 2 → artifact {art}")
            run.shot(page, "pages_approved")

            # ---------------- Export ----------------
            print("Export", flush=True)
            goto(page, run, "export")
            page.get_by_text("pages approved").wait_for(timeout=15000)
            run.check("1 of 10" in page.get_by_text("pages approved").inner_text().replace("\n", " ") or "1of10" in page.get_by_text("pages approved").inner_text().replace(" ", ""), "export: estimate shows 1 of 10 approved")
            page.locator("button.uppercase:has-text('hi')").click()  # EN only (faster)
            page.wait_for_timeout(600)
            with page.expect_response(lambda r: r.url.endswith("/api/export") and r.request.method == "POST") as resp:
                page.locator("button.btn-primary:has-text('Export')").click()
            r = resp.value
            run.check(r.status == 202, "export: POST /api/export with allow_partial accepted")
            j = wait_job(base, r.json()["job_id"], timeout=600)
            run.check(j["status"] == "done", "export: job done")
            page.wait_for_timeout(2500)
            goto(page, run, "export")
            link = page.locator("a[download]").first
            link.wait_for(timeout=15000)
            href = link.get_attribute("href")
            with page.expect_download() as dl:
                link.click()
            path = dl.value.path()
            data = Path(path).read_bytes() if path else b""
            run.check(data[:5] == b"%PDF-" and len(data) > 50_000, f"export: download link works ({href}, {len(data) // 1024} KB)")
            run.shot(page, "export")
        except Exception as exc:  # noqa: BLE001
            run.errors.append(f"STEP FAILED: {exc!r}")
            print(f"  !!  STEP FAILED: {exc!r}", flush=True)
            try:
                page.screenshot(path=str(shots / "real_failure.png"))
            except Exception:  # noqa: BLE001
                pass
        browser.close()

    print(f"\n{len(run.steps)} checks passed; {len(run.errors)} errors")
    for e in run.errors:
        print("  -", e)
    return 1 if run.errors else 0


if __name__ == "__main__":
    sys.exit(main())
