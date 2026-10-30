"""The canvas library: paper textures generated procedurally with Pillow (warm mottled noise, fibres, darker torn
edges), each under 1 MB, written to data/canvases/<key>.png at startup if missing."""

from __future__ import annotations

import random
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

SEPIA = "#3a2d1a"

# key -> (name, base RGB, mottle RGB, fibre RGB, ink, gutter, caption_style, marginalia_style, notes)
PAINTED = Path(__file__).resolve().parent / "textures"
_PAINTED_CAPTION = {"text": SEPIA, "box": "rgba(239,228,201,0.55)", "border": "0.2mm solid " + SEPIA, "font": "serif", "textured": True}

CANVASES: list[dict[str, Any]] = [
    # painted parchment sheets (Sunburst): the page is the texture, scaled to the page; shards get a torn paper rim
    {"key": "parchment_painted", "name": "Parchment (painted)", "painted": "page_warm.jpg", "finish": "painted", "base": (231, 196, 139),
     "ink": SEPIA, "gutter": "paper", "caption_style": dict(_PAINTED_CAPTION, box_print="#ead2a4"), "marginalia_style": {"tint": SEPIA, "opacity": 0.85, "style": "pencil-sketch"},
     "era_hint": "Volume 1 default: a painted parchment sheet with burnt, stained edges; torn paper rims on the shards; callouts are parchment scraps."},
    {"key": "aged_vellum", "name": "Aged vellum", "painted": "page_aged.jpg", "finish": "painted", "base": (181, 124, 56),
     "ink": "#2a1a10", "gutter": "paper", "caption_style": dict(_PAINTED_CAPTION, text="#2a1a10", box_print="#dcb98a"), "marginalia_style": {"tint": "#2a1a10", "opacity": 0.85, "style": "charcoal"},
     "era_hint": "Darker, foxed vellum with heavy edge burn — Lanka, the war chapters."},
    {"key": "pale_parchment", "name": "Pale parchment", "painted": "page_light.jpg", "finish": "painted", "base": (237, 222, 192),
     "ink": SEPIA, "gutter": "paper", "caption_style": dict(_PAINTED_CAPTION, box_print="#efe2c4"), "marginalia_style": {"tint": SEPIA, "opacity": 0.8, "style": "pencil-sketch"},
     "era_hint": "A pale, clean sheet — quiet chapters and interludes."},
    {"key": "parchment", "name": "Parchment", "base": (232, 214, 178), "mottle": (196, 166, 118), "fibre": (170, 140, 96), "edge": (120, 86, 48),
     "ink": SEPIA, "gutter": "paper", "caption_style": {"text": SEPIA, "box": "rgba(239,228,201,0.55)", "border": "0.2mm solid " + SEPIA, "font": "serif", "textured": True},
     "marginalia_style": {"tint": SEPIA, "opacity": 0.85, "style": "pencil-sketch"}, "era_hint": "Volume 1 default: warm, mottled, torn margins; the paper is the gutter, sepia ink edges."},
    {"key": "palm_leaf", "name": "Palm-leaf (Treta)", "base": (214, 190, 132), "mottle": (176, 146, 86), "fibre": (140, 112, 60), "edge": (100, 76, 36),
     "ink": "#4a2e12", "gutter": "paper", "caption_style": {"text": "#4a2e12", "box": "rgba(226,206,150,0.55)", "border": "0.2mm solid #4a2e12", "font": "serif", "textured": True},
     "marginalia_style": {"tint": "#4a2e12", "opacity": 0.8, "style": "stylus"}, "era_hint": "Treta chapters."},
    {"key": "burnt_vellum", "name": "Burnt vellum (Lanka)", "base": (190, 150, 104), "mottle": (130, 84, 46), "fibre": (96, 60, 30), "edge": (40, 22, 10),
     "ink": "#2a1a10", "gutter": "paper", "caption_style": {"text": "#2a1a10", "box": "rgba(214,178,128,0.55)", "border": "0.2mm solid #2a1a10", "font": "serif", "textured": True},
     "marginalia_style": {"tint": "#2a1a10", "opacity": 0.85, "style": "charcoal"}, "era_hint": "Lanka burning."},
    {"key": "indigo_night", "name": "Indigo night", "base": (22, 34, 58), "mottle": (36, 54, 90), "fibre": (60, 80, 120), "edge": (8, 12, 24),
     "ink": "#d9d2c0", "gutter": "#0e1a26", "caption_style": {"text": "#d9d2c0", "box": "rgba(14,26,38,0.75)", "border": "0.2mm solid #d9d2c0", "font": "serif", "textured": False},
     "marginalia_style": {"tint": "#d9d2c0", "opacity": 0.6, "style": "silverpoint"}, "era_hint": "Ocean and sky chapters."},
    {"key": "iron", "name": "Iron (Dwapara)", "base": (96, 52, 40), "mottle": (140, 72, 50), "fibre": (60, 32, 24), "edge": (30, 16, 12),
     "ink": "#1a0d0a", "gutter": "#3b1f17", "caption_style": {"text": "#f2ede3", "box": "rgba(26,13,10,0.8)", "border": "0.2mm solid #1a0d0a", "font": "serif", "textured": False},
     "marginalia_style": {"tint": "#1a0d0a", "opacity": 0.8, "style": "rust"}, "era_hint": "Dwapara, red mud (suggested for Volume 2)."},
    {"key": "glass", "name": "Glass (Phala / Core)", "base": (228, 236, 242), "mottle": (200, 214, 226), "fibre": (214, 222, 230), "edge": (170, 190, 206),
     "ink": "#c9a227", "gutter": "#e8f0f5", "caption_style": {"text": "#1a2430", "box": "rgba(255,255,255,0.7)", "border": "0.2mm solid #c9a227", "font": "sans", "textured": False},
     "marginalia_style": {"tint": "#c9a227", "opacity": 0.7, "style": "gold-ui-lines"}, "era_hint": "Phala and the Core, cool white-blue with gold UI lines (suggested for Volume 3)."},
    {"key": "khadi", "name": "Khadi (Girgaon / Resistance)", "base": (226, 218, 198), "mottle": (200, 190, 166), "fibre": (176, 166, 140), "edge": (130, 120, 96),
     "ink": "#2b2b2b", "gutter": "paper", "caption_style": {"text": "#2b2b2b", "box": "rgba(236,230,214,0.6)", "border": "0.2mm solid #2b2b2b", "font": "serif", "textured": True},
     "marginalia_style": {"tint": "#2b2b2b", "opacity": 0.8, "style": "pencil"}, "era_hint": "Cotton weave."},
    {"key": "white", "name": "Plain white (proof)", "base": (250, 250, 248), "mottle": (244, 244, 242), "fibre": (240, 240, 238), "edge": (230, 230, 228),
     "ink": "#000000", "gutter": "paper", "caption_style": {"text": "#161210", "box": "#efe4c9", "border": "none", "font": "serif", "textured": False},
     "marginalia_style": {"tint": "#000000", "opacity": 0.8, "style": "line"}, "era_hint": "Office proof."},
]

TEX_W, TEX_H = 680, 1040  # ~ 170x260 mm at 4 px/mm; keeps every PNG well under 1 MB


def _noise_layer(w: int, h: int, rng: random.Random, cells: int, blur: float) -> Image.Image:
    small = Image.new("L", (cells, int(cells * h / w)))
    small.putdata([rng.randint(0, 255) for _ in range(small.size[0] * small.size[1])])
    return small.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(blur))


def paint_texture(spec: dict[str, Any], seed: int = 11) -> Image.Image:
    rng = random.Random(seed + sum(spec["base"]))
    w, h = TEX_W, TEX_H
    base, mottle, fibre, edge = (Image.new("RGB", (w, h), c) for c in (spec["base"], spec["mottle"], spec["fibre"], spec["edge"]))
    # warm mottling: two octaves of blurred noise
    m1 = _noise_layer(w, h, rng, 12, 14)
    m2 = _noise_layer(w, h, rng, 48, 4)
    mask = Image.blend(m1, m2, 0.45).point(lambda v: int(v * 0.55))
    img = Image.composite(mottle, base, mask)
    # fibres: short thin strokes
    fib = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(fib)
    for _ in range(2600):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        L, a = rng.uniform(6, 40), rng.uniform(-0.5, 0.5) + (0 if rng.random() < 0.6 else 1.5708)
        import math

        d.line([(x, y), (x + L * math.cos(a), y + L * math.sin(a))], fill=rng.randint(40, 120), width=1)
    fib = fib.filter(ImageFilter.GaussianBlur(0.6))
    img = Image.composite(fibre, img, fib)
    # darker torn edges: a vignette with a noisy rim
    vig = Image.new("L", (w, h), 0)
    dv = ImageDraw.Draw(vig)
    for i in range(18):
        k = 255 - i * 13
        dv.rectangle([i * 2, i * 2, w - 1 - i * 2, h - 1 - i * 2], outline=max(0, k))
    vig = vig.filter(ImageFilter.GaussianBlur(10))
    rim = _noise_layer(w, h, rng, 60, 2).point(lambda v: int(v * 0.5))
    vig = Image.composite(vig, Image.new("L", (w, h), 0), rim.point(lambda v: 255 - v))
    vig = vig.point(lambda v: int(v * 0.6))
    img = Image.composite(edge, img, vig)
    # a few ink stains / speckles
    sp = Image.new("L", (w, h), 0)
    ds = ImageDraw.Draw(sp)
    for _ in range(140):
        x, y, r = rng.uniform(0, w), rng.uniform(0, h), rng.uniform(0.6, 2.4)
        ds.ellipse([x - r, y - r, x + r, y + r], fill=rng.randint(30, 110))
    img = Image.composite(edge, img, sp.filter(ImageFilter.GaussianBlur(0.8)))
    return img


def ensure_textures(out_dir: Path) -> dict[str, Path]:
    """Generate the procedural textures if missing and copy the painted sheets; return {key: path}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for spec in CANVASES:
        if spec.get("painted"):
            src = PAINTED / spec["painted"]
            p = out_dir / f"{spec['key']}.jpg"
            if not p.exists() or p.stat().st_size != src.stat().st_size:
                shutil.copyfile(src, p)
            paths[spec["key"]] = p
            continue
        p = out_dir / f"{spec['key']}.png"
        if not p.exists():
            im = paint_texture(spec)
            im.save(p, "PNG", optimize=True)
            if p.stat().st_size > 1_000_000:  # safety: quantise if a texture ever grows past 1 MB
                im.convert("P", palette=Image.ADAPTIVE, colors=128).save(p, "PNG", optimize=True)
        paths[spec["key"]] = p
    return paths
