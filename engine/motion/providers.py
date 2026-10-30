"""Seedance image-to-video behind one interface: fal.ai (FAL_KEY) or BytePlus ModelArk (BYTEPLUS_API_KEY).

fal.ai queue API (REST):   POST https://queue.fal.run/{model}  (Authorization: Key $FAL_KEY)
                           -> {request_id, status_url, response_url}; GET status_url until COMPLETED; GET response_url
                           -> {video: {url}, seed}
BytePlus ModelArk (v3):    POST {base}/contents/generations/tasks  (Authorization: Bearer $BYTEPLUS_API_KEY)
                           {model, content: [{type: text}, {type: image_url, role: first_frame}], ratio, duration,
                           resolution, seed, camera_fixed, watermark: false}
                           GET {base}/contents/generations/tasks/{id} until status succeeded -> content.video_url

Model ids and per-second price estimates are settings (they change); the estimate is shown before every run.
Without a key the run is a DRY RUN: a placeholder clip rendered from the still with a slow zoom and a "DRY RUN" mark,
so the flow (job -> take -> compare -> send to moment) is fully testable.
"""

from __future__ import annotations

import base64
import io
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx
from PIL import Image

from . import kenburns as KB

PROVIDERS = ("fal", "byteplus")
RESOLUTIONS = ("720p", "1080p")
ASPECTS = ("16:9", "9:16", "adaptive")
CAMERA_PRESETS = {
    "push_in": "slow push in toward the subject",
    "pull_out": "slow pull out revealing the surroundings",
    "pan": "slow lateral pan across the scene",
    "orbit": "gentle partial orbit around the subject",
    "crane": "slow crane move rising over the scene",
    "static": "locked-off camera; only subtle breathing motion in the scene (wind, water, cloth, firelight)",
}
DEFAULTS = {
    "fal_model": "bytedance/seedance-2.5/image-to-video",
    "byteplus_model": "dreamina-seedance-2-0-260128",
    "byteplus_base": "https://ark.ap-southeast.bytepluses.com/api/v3",
    # USD per second of output (estimates; edit in settings when the price list changes)
    "rate": {"fal": {"720p": 0.07, "1080p": 0.15}, "byteplus": {"720p": 0.05, "1080p": 0.11}},
}


def keys() -> dict[str, bool]:
    from engine.settings import settings

    return {"fal": bool(getattr(settings, "fal_api_key", None) or os.environ.get("FAL_KEY")),
            "byteplus": bool(getattr(settings, "byteplus_api_key", None) or os.environ.get("BYTEPLUS_API_KEY"))}


def _key(provider: str) -> str | None:
    from engine.settings import settings

    if provider == "fal":
        return getattr(settings, "fal_api_key", None) or os.environ.get("FAL_KEY")
    return getattr(settings, "byteplus_api_key", None) or os.environ.get("BYTEPLUS_API_KEY")


def _conf(name: str) -> Any:
    from engine.settings import settings

    return getattr(settings, f"seedance_{name}", None) or DEFAULTS[name]


@dataclass
class SeedanceRequest:
    image: Path
    prompt: str
    duration: int = 5
    resolution: str = "1080p"
    aspect: str = "16:9"
    seed: int | None = None
    camera: str = "push_in"
    provider: str = "fal"

    def normalised(self) -> "SeedanceRequest":
        self.duration = int(min(10, max(5, int(self.duration))))
        self.resolution = self.resolution if self.resolution in RESOLUTIONS else "1080p"
        self.aspect = self.aspect if self.aspect in ASPECTS else "16:9"
        self.provider = self.provider if self.provider in PROVIDERS else "fal"
        self.camera = self.camera if self.camera in CAMERA_PRESETS else "push_in"
        return self


@dataclass
class TakeResult:
    path: Path
    provider: str
    model: str
    cost_usd: float
    seed: int | None
    dry_run: bool
    remote_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def estimate(provider: str, duration: int, resolution: str) -> dict[str, Any]:
    rate = (_conf("rate").get(provider) or {}).get(resolution, 0.15)
    usd = round(rate * int(duration), 3)
    dry = not keys().get(provider)
    return {"provider": provider, "usd": 0.0 if dry else usd, "usd_if_live": usd, "per_second": rate, "dry_run": dry,
            "note": "dry run (no key): a placeholder clip, no cost" if dry else f"≈ ${usd:.2f} for {duration} s at {resolution}"}


def _data_uri(path: Path, max_side: int = 2048) -> str:
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _download(url: str, out: Path) -> None:
    with httpx.stream("GET", url, timeout=600, follow_redirects=True) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)


def _size_for(aspect: str, resolution: str, image: Path) -> tuple[int, int]:
    h = 720 if resolution == "720p" else 1080
    if aspect == "adaptive":
        with Image.open(image) as im:
            aspect = "16:9" if im.width >= im.height else "9:16"
    return (round(h * 16 / 9) // 2 * 2, h) if aspect == "16:9" else (h, round(h * 16 / 9) // 2 * 2)


def run(req: SeedanceRequest, out: Path, progress: Callable[[float, str], None] | None = None, force_dry: bool = False,
        dry_size: tuple[int, int] | None = None, poll_s: float = 4.0, timeout_s: float = 900) -> TakeResult:
    req.normalised()
    say = progress or (lambda f, m: None)
    out.parent.mkdir(parents=True, exist_ok=True)
    key = _key(req.provider)
    if force_dry or not key:
        size = dry_size or _size_for(req.aspect, "720p", req.image)
        size = (max(64, size[0] // 2 * 2), max(64, size[1] // 2 * 2))
        say(0.05, "dry run: rendering a placeholder clip")
        KB.render_clip(KB.Shot(req.image, req.camera if req.camera in KB.MOVES else "push_in", req.duration, mark="DRY RUN"), out, size,
                       quality="draft", progress=lambda f: say(0.05 + 0.9 * f, "dry run"))
        return TakeResult(out, req.provider, "dry-run", 0.0, req.seed, True, meta={"size": list(size)})
    if req.provider == "fal":
        return _run_fal(req, key, out, say, poll_s, timeout_s)
    return _run_byteplus(req, key, out, say, poll_s, timeout_s)


def _run_fal(req: SeedanceRequest, key: str, out: Path, say: Callable[[float, str], None], poll_s: float, timeout_s: float) -> TakeResult:
    model = _conf("fal_model")
    body: dict[str, Any] = {"prompt": req.prompt, "image_url": _data_uri(req.image), "resolution": req.resolution, "duration": str(req.duration),
                            "aspect_ratio": "auto" if req.aspect == "adaptive" else req.aspect, "generate_audio": False}
    if req.seed is not None:
        body["seed"] = int(req.seed)
    h = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=120) as c:
        r = c.post(f"https://queue.fal.run/{model}", json=body, headers=h)
        r.raise_for_status()
        sub = r.json()
        rid = sub.get("request_id", "")
        status_url = sub.get("status_url") or f"https://queue.fal.run/{model}/requests/{rid}/status"
        resp_url = sub.get("response_url") or f"https://queue.fal.run/{model}/requests/{rid}"
        say(0.1, f"fal queued {rid}")
        t0 = time.time()
        while True:
            s = c.get(status_url, headers=h).json()
            st = s.get("status")
            if st == "COMPLETED":
                break
            if st in ("FAILED", "ERROR") or s.get("error"):
                raise RuntimeError(f"fal: {s}")
            if time.time() - t0 > timeout_s:
                raise TimeoutError("fal: timed out")
            say(min(0.85, 0.1 + (time.time() - t0) / 240), f"fal {st or 'waiting'}" + (f" (#{s.get('queue_position')})" if s.get("queue_position") is not None else ""))
            time.sleep(poll_s)
        res = c.get(resp_url, headers=h).json()
    url = (res.get("video") or {}).get("url")
    if not url:
        raise RuntimeError(f"fal: no video in the result: {res}")
    say(0.9, "downloading the take")
    _download(url, out)
    return TakeResult(out, "fal", model, estimate("fal", req.duration, req.resolution)["usd_if_live"], res.get("seed", req.seed), False, rid, {"video_url": url})


def _run_byteplus(req: SeedanceRequest, key: str, out: Path, say: Callable[[float, str], None], poll_s: float, timeout_s: float) -> TakeResult:
    model = _conf("byteplus_model")
    base = _conf("byteplus_base").rstrip("/")
    body: dict[str, Any] = {
        "model": model,
        "content": [{"type": "text", "text": req.prompt}, {"type": "image_url", "image_url": {"url": _data_uri(req.image)}, "role": "first_frame"}],
        "ratio": req.aspect, "duration": req.duration, "resolution": req.resolution, "watermark": False, "camera_fixed": req.camera == "static",
        "generate_audio": False,
    }
    if req.seed is not None:
        body["seed"] = int(req.seed)
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=120) as c:
        r = c.post(f"{base}/contents/generations/tasks", json=body, headers=h)
        r.raise_for_status()
        tid = r.json().get("id")
        say(0.1, f"BytePlus task {tid}")
        t0 = time.time()
        while True:
            s = c.get(f"{base}/contents/generations/tasks/{tid}", headers=h).json()
            st = s.get("status")
            if st == "succeeded":
                break
            if st in ("failed", "cancelled", "expired"):
                raise RuntimeError(f"BytePlus: {s.get('error') or st}")
            if time.time() - t0 > timeout_s:
                raise TimeoutError("BytePlus: timed out")
            say(min(0.85, 0.1 + (time.time() - t0) / 240), f"BytePlus {st}")
            time.sleep(poll_s)
    url = (s.get("content") or {}).get("video_url")
    if not url:
        raise RuntimeError(f"BytePlus: no video_url: {s}")
    say(0.9, "downloading the take")
    _download(url, out)
    return TakeResult(out, "byteplus", model, estimate("byteplus", req.duration, req.resolution)["usd_if_live"], s.get("seed", req.seed), False, tid,
                      {"video_url": url, "usage": s.get("usage")})


# ---------------------------------------------------------------------------------
# the motion prompt (prompt_writer role, template fallback)
# ---------------------------------------------------------------------------------

LOCK_LINE = "Keep the locked characters' faces and attire exactly as in the image; no text, no letters, no captions, no watermark."

SYSTEM = ("You write image-to-video motion prompts for Seedance from a still comic panel. One paragraph, under 70 words: "
          "the camera move, what moves in the scene (water, cloth, fire, hair, light), the mood; never add new characters, "
          "never change faces or costumes, never ask for text. End with the lock line verbatim. "
          'Return JSON {"prompt": "..."}')


def template_prompt(scene: str, camera: str, characters: list[str] | None = None) -> str:
    cam = CAMERA_PRESETS.get(camera, CAMERA_PRESETS["push_in"])
    who = f" {', '.join(characters)} hold their pose and expression, breathing subtly." if characters else ""
    scene = (scene or "").strip().rstrip(".")
    return f"Cinematic {cam}. {scene + '. ' if scene else ''}Natural motion only: drifting smoke, moving water, cloth and hair in the wind, flickering light.{who} {LOCK_LINE}"


def write_prompt(scene: str, camera: str, characters: list[str] | None = None) -> dict[str, Any]:
    from engine import llm

    fb = {"prompt": template_prompt(scene, camera, characters), "source": "template"}
    user = f"SCENE: {scene}\nCAMERA: {CAMERA_PRESETS.get(camera, camera)}\nCHARACTERS (locked): {', '.join(characters or []) or 'none'}\nLOCK LINE: {LOCK_LINE}"
    try:
        res = llm.ask_json("prompt_writer", SYSTEM, user, fallback=lambda: fb)
    except Exception:  # noqa: BLE001
        res = fb
    p = (res or {}).get("prompt") if isinstance(res, dict) else None
    if not p:
        return fb
    if LOCK_LINE not in p:
        p = p.rstrip() + " " + LOCK_LINE
    return {"prompt": p, "source": res.get("source", "model") if isinstance(res, dict) else "model"}
