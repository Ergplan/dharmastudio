"""Smart caption colours: each callout's box, text and border colours come from the panel's own palette.

Procedure (no external API; Pillow only)
- Sample the panel image under the callout's box (`palette`): crop the region, resize it small and median-cut it to five
  colours with their weights. Cached per image (path + mtime) and region.
- Narration on paper (quiet / voice / rising on a paper canvas, or any light box): take the dominant warm or neutral
  tone, pull it halfway toward the canvas paper, blend in ~30 % of the state colour, then set L* to ~90 and drop chroma.
- Dark states (peak / ego / knowledge): take a palette colour, blend in ~30 % of the state colour (ego crimson,
  knowledge indigo-gold) and darken it to L* ~15, keeping its hue.
- Text: start from the state's ink (sepia, cream, crimson for ego, gold for knowledge) and step its lightness away from
  the box until the WCAG contrast is >= 7:1 (computed, not assumed).
- Border/accent: the palette's most saturated colour (blended with the state colour), at a low alpha.

Modes (the volume typography's `colour_mode`): "smart" (default), "state" (the fixed table), "custom" (the author's
hex per state). A panel may pin its own {box, text, border}.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

RGB = tuple[int, int, int]

# the old fixed table (mode "state"), and the state colours smart mode blends in
STATE_BOX = {"quiet": "#efe4c9", "rising": "#4a4a4c", "peak": "#0b0b0d", "ego": "#2a0a0a", "knowledge": "#0e1a26", "voice": "#efe4c9"}
STATE_TEXT = {"quiet": "#161210", "rising": "#f2ede3", "peak": "#f2ede3", "ego": "#b3261e", "knowledge": "#d4a017", "voice": "#5a3a1a"}
STATE_ACCENT = {"quiet": "#3a2d1a", "rising": "#3a2d1a", "peak": "#8a8580", "ego": "#b3261e", "knowledge": "#d4a017", "voice": "#5a3a1a"}
DARK_STATES = ("peak", "ego", "knowledge")
MODES = ("smart", "state", "custom")
MIN_CONTRAST = 7.0
STATE_BLEND = 0.3


# ---------------------------------------------------------------------------------
# colour maths: sRGB <-> CIE L*a*b* (D65), WCAG contrast
# ---------------------------------------------------------------------------------


def hex_to_rgb(h: str) -> RGB:
    h = (h or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"not a hex colour: {h!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(c: RGB) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in c)


def is_hex(h: Any) -> bool:
    try:
        hex_to_rgb(str(h))
        return str(h).startswith("#")
    except ValueError:
        return False


def _lin(v: float) -> float:
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _gam(v: float) -> float:
    v = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return max(0.0, min(255.0, v * 255))


def luminance(c: RGB) -> float:
    r, g, b = (_lin(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: RGB | str, b: RGB | str) -> float:
    a = hex_to_rgb(a) if isinstance(a, str) else a
    b = hex_to_rgb(b) if isinstance(b, str) else b
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


_WX, _WY, _WZ = 0.95047, 1.0, 1.08883


def rgb_to_lab(c: RGB) -> tuple[float, float, float]:
    r, g, b = (_lin(x) for x in c)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / _WX
    y = (0.2126 * r + 0.7152 * g + 0.0722 * b) / _WY
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / _WZ

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def lab_to_rgb(lab: tuple[float, float, float]) -> RGB:
    L, a, b = lab
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def finv(t: float) -> float:
        return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787

    x, y, z = finv(fx) * _WX, finv(fy) * _WY, finv(fz) * _WZ
    r = 3.2406 * x - 1.5372 * y - 0.4986 * z
    g = -0.9689 * x + 1.8758 * y + 0.0415 * z
    bl = 0.0557 * x - 0.2040 * y + 1.0570 * z
    return tuple(int(round(_gam(max(0.0, v)))) for v in (r, g, bl))  # type: ignore[return-value]


def lch(c: RGB) -> tuple[float, float, float]:
    L, a, b = rgb_to_lab(c)
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def from_lch(L: float, C: float, h: float) -> RGB:
    return lab_to_rgb((L, C * math.cos(math.radians(h)), C * math.sin(math.radians(h))))


def mix(a: RGB, b: RGB, t: float) -> RGB:
    """Blend in Lab: t=0 -> a, t=1 -> b."""
    la, lb = rgb_to_lab(a), rgb_to_lab(b)
    return lab_to_rgb(tuple(x + (y - x) * t for x, y in zip(la, lb)))  # type: ignore[arg-type]


def with_lightness(c: RGB, L: float, max_chroma: float | None = None) -> RGB:
    _, C, h = lch(c)
    if max_chroma is not None:
        C = min(C, max_chroma)
    return from_lch(L, C, h)


def ensure_contrast(fg: RGB, bg: RGB, target: float = MIN_CONTRAST) -> RGB:
    """Step the text's lightness away from the box (keeping hue, easing chroma) until contrast >= target."""
    if contrast(fg, bg) >= target:
        return fg
    Lb = rgb_to_lab(bg)[0]
    L, C, h = lch(fg)
    step = -2.0 if Lb >= 50 else 2.0
    for _ in range(60):
        L = max(0.0, min(100.0, L + step))
        C *= 0.97
        cand = from_lch(L, C, h)
        if contrast(cand, bg) >= target:
            return cand
    return (0, 0, 0) if Lb >= 50 else (255, 255, 255)


# ---------------------------------------------------------------------------------
# palette extraction
# ---------------------------------------------------------------------------------


@lru_cache(maxsize=2048)
def _palette(path: str, mtime: float, region: tuple[float, float, float, float], k: int) -> tuple[tuple[RGB, float], ...]:
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        W, H = im.size
        x0, y0, x1, y1 = region
        box = (int(max(0, min(W - 1, x0 * W))), int(max(0, min(H - 1, y0 * H))), int(max(1, min(W, x1 * W))), int(max(1, min(H, y1 * H))))
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            box = (0, 0, W, H)
        small = im.crop(box).resize((48, 48))
    q = small.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette() or []
    counts = sorted(q.getcolors() or [], reverse=True)
    total = sum(n for n, _ in counts) or 1
    return tuple(((pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]), n / total) for n, i in counts)


def palette(path: Path | str | None, region: tuple[float, float, float, float] = (0, 0, 1, 1), k: int = 5) -> list[tuple[RGB, float]]:
    """Up to k colours (rgb, weight) of the image under `region` (fractions of the image, x0,y0,x1,y1)."""
    if not path or not Path(path).exists():
        return []
    p = Path(path)
    r = tuple(round(min(1.0, max(0.0, v)) * 20) / 20 for v in region)  # 5 % grid: stable cache keys
    if r[2] <= r[0] or r[3] <= r[1]:
        r = (0.0, 0.0, 1.0, 1.0)
    return list(_palette(str(p), p.stat().st_mtime, r, k))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------
# the colour choice
# ---------------------------------------------------------------------------------


def _warm_or_neutral(c: RGB) -> bool:
    L, C, h = lch(c)
    return C < 14 or 20 <= h <= 110


def _accent(pal: list[tuple[RGB, float]], state: str, light_box: bool) -> str:
    base = max((c for c, _ in pal), key=lambda c: lch(c)[1]) if pal else hex_to_rgb(STATE_ACCENT[state])
    acc = mix(base, hex_to_rgb(STATE_ACCENT.get(state, "#3a2d1a")), 0.35 if state not in ("ego", "knowledge") else 0.55)
    _, C, h = lch(acc)
    acc = from_lch(38 if light_box else 62, max(18.0, min(C, 55.0)), h)
    return f"rgba({acc[0]},{acc[1]},{acc[2]},{0.7 if light_box else 0.8})"


def smart(pal: list[tuple[RGB, float]], state: str, paper: str = "#e8d6b2", ink: str = "#3a2d1a", light: bool | None = None, kind: str = "caption") -> dict[str, Any]:
    """{box, text, border, contrast, palette} for one callout. `light` forces a light (parchment) box; by default
    dark states get dark boxes and every other state a light one. kind="balloon" keeps the box paler and quieter."""
    state = state if state in STATE_BOX else "quiet"
    light = (state not in DARK_STATES) if light is None else light
    paper_rgb, state_box = hex_to_rgb(paper), hex_to_rgb(STATE_BOX[state])
    if light:
        cands = [(c, w) for c, w in pal if _warm_or_neutral(c)] or pal
        base = max(cands, key=lambda t: t[1])[0] if cands else paper_rgb
        tone = mix(base, paper_rgb, 0.5)
        tone = mix(tone, paper_rgb if state_box == hex_to_rgb("#4a4a4c") else state_box, STATE_BLEND)
        box = with_lightness(tone, 93.0 if kind == "balloon" else 90.0, max_chroma=7.0 if kind == "balloon" else 12.0)
        text_seed = hex_to_rgb(ink if state != "voice" else STATE_TEXT["voice"])
    else:
        cands = sorted(pal, key=lambda t: -t[1])
        base = cands[0][0] if cands else state_box
        tone = mix(base, hex_to_rgb(STATE_ACCENT[state] if state in ("ego", "knowledge") else STATE_BOX[state]), STATE_BLEND)
        _, C, h = lch(tone)
        box = from_lch(12.0 if state in ("ego", "knowledge") else 15.0, min(C, 22.0), h)
        text_seed = hex_to_rgb(STATE_TEXT[state])
    text = ensure_contrast(text_seed, box)
    return {"box": rgb_to_hex(box), "text": rgb_to_hex(text), "border": _accent(pal, state, light), "contrast": round(contrast(text, box), 2),
            "palette": [rgb_to_hex(c) for c, _ in pal]}


def fixed(state: str, light_paper: bool, paper_box: str | None = None, paper_text: str | None = None) -> dict[str, Any]:
    """Mode "state": the old table (narration on paper canvases is sepia on a parchment box)."""
    state = state if state in STATE_BOX else "quiet"
    if light_paper and state in ("quiet", "voice", "rising"):
        box, text = paper_box or "#efe3c6", paper_text or "#3a2d1a"
    else:
        box, text = STATE_BOX[state] if state != "ego" else "#0b0b0d", STATE_TEXT[state]
    return {"box": box, "text": text, "border": STATE_ACCENT[state], "contrast": round(contrast(box, text), 2), "palette": []}


def custom(colours: dict[str, Any] | None, state: str) -> dict[str, Any] | None:
    c = (colours or {}).get(state) or {}
    if not (is_hex(c.get("box")) and is_hex(c.get("text"))):
        return None
    border = c.get("border") if is_hex(c.get("border")) else STATE_ACCENT.get(state, "#3a2d1a")
    return {"box": c["box"], "text": c["text"], "border": border, "contrast": round(contrast(c["box"], c["text"]), 2), "palette": []}


def pinned(override: dict[str, Any] | None) -> dict[str, Any] | None:
    """A panel's own pick {box, text, border?}; None when the panel is on auto."""
    if not override or override.get("mode") == "auto":
        return None
    if not (is_hex(override.get("box")) and is_hex(override.get("text"))):
        return None
    border = override.get("border") if is_hex(override.get("border")) else "#3a2d1a"
    return {"box": override["box"], "text": override["text"], "border": border, "contrast": round(contrast(override["box"], override["text"]), 2), "palette": []}


def swatches(pal: list[tuple[RGB, float]], paper: str = "#e8d6b2") -> list[dict[str, Any]]:
    """Picker suggestions from a panel's palette: a light and a dark box per palette colour, each with its best text."""
    out = []
    for c, _ in pal:
        for L, cap in ((90.0, 12.0), (15.0, 22.0)):
            box = with_lightness(mix(c, hex_to_rgb(paper), 0.3) if L > 50 else c, L, cap)
            seed = hex_to_rgb("#3a2d1a") if L > 50 else hex_to_rgb("#f2ede3")
            text = ensure_contrast(seed, box)
            out.append({"box": rgb_to_hex(box), "text": rgb_to_hex(text), "border": _accent([(c, 1.0)], "quiet", L > 50), "contrast": round(contrast(box, text), 2)})
    return out
