"""Image providers: Sunburst (OpenAI Images API, generate and edits-with-reference), Gemini (Interactions API),
and Pillow-painted dry-run placeholders when a key is missing, so the studio runs end to end without keys."""

from __future__ import annotations

import base64
import io
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont

from .settings import settings

OPENAI_IMAGES = "https://api.openai.com/v1/images"
GEMINI_INTERACTIONS = "https://generativelanguage.googleapis.com/v1beta/interactions"

PROVIDERS = ("sunburst", "gemini-nb21", "gemini-pro")
SUNBURST_SIZES = {"landscape": "1536x1024", "portrait": "1024x1536", "square": "1024x1024"}
GEMINI_ASPECT = {"landscape": "3:2", "portrait": "2:3", "square": "1:1"}
STATE_TINT = {"quiet": (120, 100, 70), "voice": (110, 90, 60), "rising": (90, 70, 60), "peak": (70, 30, 30), "ego": (90, 20, 20), "knowledge": (30, 50, 80)}


@dataclass
class ImageResult:
    png: bytes
    provider: str
    model: str
    cost_usd: float = 0.0
    dry_run: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


def orientation_of(aspect: float) -> str:
    if aspect > 1.15:
        return "landscape"
    if aspect < 0.87:
        return "portrait"
    return "square"


def normalise_provider(name: str | None) -> str:
    n = (name or "sunburst").lower()
    if n in ("gemini", "gemini-nb21", "nb21", "gemini-nano-banana-2.1"):
        return "gemini-nb21"
    if n in ("gemini-pro", "gemini-3-pro-image", "pro"):
        return "gemini-pro"
    return "sunburst"


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(Path(__file__).resolve().parent / "comic" / "fonts" / "Mukta-Regular.ttf"), size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def placeholder_png(label: str, prompt: str, orientation: str = "landscape", state: str = "quiet", seed: int = 0) -> bytes:
    """A Pillow-painted stand-in: a tinted gradient, the label and the first words of the scene."""
    w, h = {"landscape": (1536, 1024), "portrait": (1024, 1536), "square": (1024, 1024)}[orientation]
    base = STATE_TINT.get(state, (100, 80, 60))
    im = Image.new("RGB", (w, h), base)
    px = im.load()
    for y in range(h):
        k = 1.0 - 0.6 * (y / h)
        c = tuple(int(v * k) for v in base)
        for x in range(0, w, 1):
            px[x, y] = c
    d = ImageDraw.Draw(im)
    # a warm 'fire' disc and a cold 'moon' disc so the placeholder reads like the recipe's two lights
    d.ellipse([w * 0.1, h * 0.55, w * 0.45, h * 0.95], fill=(200, 110, 40))
    d.ellipse([w * 0.72, h * 0.08, w * 0.82, h * 0.08 + w * 0.1], fill=(170, 190, 220))
    d.text((40, 30), f"DRY RUN · {label}", fill=(240, 230, 210), font=_font(44))
    scene = prompt.split("SCENE:", 1)[-1].strip()
    y = 110
    for line in textwrap.wrap(scene, 54)[:14]:
        d.text((40, y), line, fill=(235, 225, 205), font=_font(30))
        y += 40
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------------
# Sunburst (OpenAI Images API)
# ---------------------------------------------------------------------------------


def _sunburst_cost(usage: dict[str, Any] | None) -> float:
    if not usage:
        return 0.0
    det = usage.get("input_tokens_details") or {}
    text_in = det.get("text_tokens", usage.get("input_tokens", 0))
    image_in = det.get("image_tokens", 0)
    out = usage.get("output_tokens", 0)
    return round(text_in / 1e6 * settings.sunburst_text_in_per_m + image_in / 1e6 * settings.sunburst_image_in_per_m + out / 1e6 * settings.sunburst_image_out_per_m, 5)


def sunburst_generate(prompt: str, orientation: str = "landscape", references: list[Path] | None = None, label: str = "", state: str = "quiet") -> ImageResult:
    """POST /v1/images/generations, or /v1/images/edits (multipart, image[] = reference PNGs) when references are attached."""
    size = SUNBURST_SIZES[orientation]
    model = settings.sunburst_model
    if settings.dry_run_sunburst:
        return ImageResult(placeholder_png(label or "sunburst", prompt, orientation, state), "sunburst", model, 0.0, True, {"size": size, "references": [str(r) for r in references or []]})
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    refs = [r for r in (references or []) if r.exists()]
    with httpx.Client(timeout=300, headers=headers) as cx:
        if refs:
            files = [("image[]", (r.name, r.read_bytes(), "image/png")) for r in refs]
            data = {"model": model, "prompt": prompt, "size": size, "quality": "high", "n": "1"}
            r = cx.post(f"{OPENAI_IMAGES}/edits", data=data, files=files)
        else:
            r = cx.post(f"{OPENAI_IMAGES}/generations", json={"model": model, "prompt": prompt, "size": size, "quality": "high", "n": 1})
        r.raise_for_status()
        body = r.json()
    b64 = body["data"][0]["b64_json"]
    return ImageResult(base64.b64decode(b64), "sunburst", model, _sunburst_cost(body.get("usage")), False, {"size": size, "usage": body.get("usage"), "references": [str(r) for r in refs]})


# ---------------------------------------------------------------------------------
# Gemini (Interactions API)
# ---------------------------------------------------------------------------------


def gemini_generate(prompt: str, orientation: str = "landscape", pro: bool = False, label: str = "", state: str = "quiet") -> ImageResult:
    """POST /v1beta/interactions; the image is base64 at steps[].content[].data where type == "image"."""
    model = settings.gemini_pro_image_model if pro else settings.gemini_image_model
    name = "gemini-pro" if pro else "gemini-nb21"
    if settings.dry_run_gemini:
        return ImageResult(placeholder_png(label or name, prompt, orientation, state), name, model, 0.0, True, {"aspect_ratio": GEMINI_ASPECT[orientation]})
    body = {"model": model, "input": prompt, "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": GEMINI_ASPECT[orientation], "image_size": "2K"}}
    with httpx.Client(timeout=300) as cx:
        r = cx.post(GEMINI_INTERACTIONS, headers={"x-goog-api-key": settings.gemini_api_key or "", "Content-Type": "application/json"}, json=body)
        r.raise_for_status()
        data = r.json()
    b64 = None
    for step in data.get("steps", []) or []:
        for c in step.get("content", []) or []:
            if c.get("type") == "image" and c.get("data"):
                b64 = c["data"]
                break
        if b64:
            break
    if not b64:
        raise RuntimeError("Gemini returned no image")
    raw = base64.b64decode(b64)
    with Image.open(io.BytesIO(raw)) as im:  # normalise to PNG on disk
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "PNG")
    cost = settings.gemini_pro_cost_per_image if pro else settings.gemini_cost_per_image
    return ImageResult(buf.getvalue(), name, model, cost, False, {"aspect_ratio": GEMINI_ASPECT[orientation]})


def generate_image(provider: str, prompt: str, orientation: str, references: list[Path] | None = None, label: str = "", state: str = "quiet") -> ImageResult:
    p = normalise_provider(provider)
    if p == "sunburst":
        return sunburst_generate(prompt, orientation, references, label, state)
    return gemini_generate(prompt, orientation, pro=(p == "gemini-pro"), label=label, state=state)


def estimate_cost_per_image(provider: str) -> float:
    p = normalise_provider(provider)
    if p == "sunburst":
        return 0.04  # ≈ 1536x1024 high
    if p == "gemini-pro":
        return settings.gemini_pro_cost_per_image
    return 0.03


def key_to_alpha(png: bytes) -> bytes:
    """Auto-key an ink-on-white drawing to a transparent PNG (alpha = darkness, colour black)."""
    with Image.open(io.BytesIO(png)) as im:
        g = im.convert("L")
        # paper (>= ~232) goes fully transparent; ink darkness is lifted with a gamma so pencil hatching stays visible
        alpha = g.point(lambda v: 0 if v >= 232 else min(255, int(255 * ((232 - v) / 232) ** 0.55)))
        from PIL import ImageFilter

        # thicken fine pen lines by ~1 px at 1024 px so they survive downscaling to a 30-40 mm margin drawing
        alpha = alpha.filter(ImageFilter.MaxFilter(3))
        out = Image.new("RGBA", im.size, (0, 0, 0, 0))
        out.putalpha(alpha)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def placeholder_silhouette(tags: list[str], seed: int = 0) -> bytes:
    """Dry-run marginalia: an ink line drawing (a compass rose / bow / arcs) on white."""
    import math
    import random

    rng = random.Random(seed)
    w = h = 768
    im = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(im)
    cx, cy = w / 2, h / 2
    d.ellipse([cx - 300, cy - 300, cx + 300, cy + 300], outline=0, width=3)
    d.ellipse([cx - 200, cy - 200, cx + 200, cy + 200], outline=0, width=2)
    for i in range(8):
        a = math.radians(45 * i)
        d.line([(cx, cy), (cx + 290 * math.cos(a), cy + 290 * math.sin(a))], fill=0, width=2 if i % 2 == 0 else 1)
    for _ in range(60):  # hatching
        x = rng.uniform(cx - 180, cx + 180)
        d.line([(x, cy - 40), (x + 30, cy + 40)], fill=60, width=1)
    d.text((30, h - 60), ", ".join(tags)[:60], fill=0, font=_font(28))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()
