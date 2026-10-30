"""Upscale selected images for print with the Topaz Image API (Wonder 3.5), falling back to Lanczos so the export
still runs end to end without a key (dry-run)."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import httpx
from PIL import Image

from ..settings import settings

TOPAZ_BASE = "https://api.topazlabs.com/image/v1"
TOPAZ_ENDPOINT = {  # model -> endpoint (per developer.topazlabs.com)
    "Wonder 3.5": "enhance-gen/async", "Redefine": "enhance-gen/async", "Standard Max": "enhance-gen/async",
    "Bloom 2": "enhance-gen/async", "Detail Faces": "enhance-gen/async",
    "Standard V2": "enhance/async", "High Fidelity V3": "enhance/async",
}
PRINT_LONG_EDGE_PX = 3200  # 26 cm at 300 dpi plus bleed and shard over-frame


def topaz_upscale(src: Path, dst: Path, out_width: int, model: str | None = None, timeout_s: int = 900) -> dict | None:
    """Submit to the Topaz Image API, poll /status, fetch /download. Returns None (no raise) on any failure.
    Verified 2026-10-30: snake_case form fields are honoured (camelCase is silently ignored and returns a same-size
    JPEG); a User-Agent header is required or Cloudflare answers 403."""
    key = settings.topaz_api_key
    if not key:
        return None
    model = model or settings.topaz_model
    endpoint = TOPAZ_ENDPOINT.get(model, "enhance-gen/async")
    headers = {"X-API-Key": key, "User-Agent": "dharma-studio/1.0"}
    with Image.open(src) as im:
        w, h = im.size
    form = {"model": model, "output_width": str(out_width), "output_height": str(round(h * out_width / w)), "output_format": "png"}
    try:
        with httpx.Client(timeout=120, headers=headers) as cx, open(src, "rb") as fh:
            r = cx.post(f"{TOPAZ_BASE}/{endpoint}", files={"image": (src.name, fh, "image/png")}, data=form)
            if r.status_code == 429:
                time.sleep(5)
                fh.seek(0)
                r = cx.post(f"{TOPAZ_BASE}/{endpoint}", files={"image": (src.name, fh, "image/png")}, data=form)
            r.raise_for_status()
            pid = r.json()["process_id"]
            t0, wait = time.time(), 2.0
            while time.time() - t0 < timeout_s:
                st = cx.get(f"{TOPAZ_BASE}/status/{pid}").json().get("status")
                if st == "Completed":
                    break
                if st in ("Failed", "Cancelled"):
                    return None
                time.sleep(wait)
                wait = min(wait * 1.5, 15)
            else:
                return None
            url = cx.get(f"{TOPAZ_BASE}/download/{pid}").json()["download_url"]
            data = cx.get(url, follow_redirects=True).content
        tmp = dst.with_suffix(".part")
        tmp.write_bytes(data)
        Image.open(tmp).verify()
        tmp.replace(dst)
        return {"tool": "topaz-api", "model": model, "process_id": pid, "dst": str(dst), "cost_usd": settings.topaz_cost_per_image}
    except Exception:  # noqa: BLE001
        return None


def _factor(src: Path, target_long_edge: int = PRINT_LONG_EDGE_PX) -> float:
    with Image.open(src) as im:
        long_edge = max(im.size)
    return max(1.0, min(4.0, target_long_edge / long_edge))


def upscale(src: Path, dst: Path, target_long_edge: int = PRINT_LONG_EDGE_PX) -> dict:
    """Returns {"tool", "factor", "dst", "cost_usd"}. Topaz when a key exists, else Lanczos (dry-run)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    factor = _factor(src, target_long_edge)
    if factor <= 1.05:
        shutil.copy2(src, dst)
        return {"tool": "none", "factor": 1.0, "dst": str(dst), "cost_usd": 0.0}
    with Image.open(src) as im:
        out_w = int(im.size[0] * factor)
    cloud = topaz_upscale(src, dst, out_w)
    if cloud:
        cloud["factor"] = round(factor, 2)
        return cloud
    with Image.open(src) as im:
        w, h = im.size
        im.resize((int(w * factor), int(h * factor)), Image.LANCZOS).save(dst)
    return {"tool": "lanczos", "factor": round(factor, 2), "dst": str(dst), "cost_usd": 0.0}
