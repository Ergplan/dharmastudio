"""Exact text for films, QR labels and cards: HarfBuzz shaping (uharfbuzz) + glyph outlines, rasterised with a
non-zero winding fill. Devanagari conjuncts and matras come out right on every Mac, whether or not Pillow was built
with raqm/FriBiDi (it usually is not on macOS), and the same outlines become SVG paths for vector exports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

FONT_LIB = Path(__file__).resolve().parent.parent / "comic" / "fonts" / "library"
FONT_EN = FONT_LIB / "IMFeENrm28P.ttf"  # IM Fell English
FONT_EN_ITALIC = FONT_LIB / "IMFeENit28P.ttf"
FONT_HI = FONT_LIB / "TiroDevanagariHindi-Regular.ttf"  # Tiro Devanagari Hindi
FONT_URL = FONT_LIB / "Spectral-Regular.ttf"  # URLs, numerals (IM Fell has old-style figures)


def is_devanagari(text: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" or "꣠" <= ch <= "ꣿ" for ch in text or "")


def font_for(text: str, italic: bool = False) -> Path:
    if is_devanagari(text):
        return FONT_HI
    return FONT_EN_ITALIC if italic else FONT_EN


@lru_cache(maxsize=16)
def _hb_font(path: str):  # noqa: ANN202
    import uharfbuzz as hb

    blob = hb.Blob.from_file_path(path)
    face = hb.Face(blob)
    font = hb.Font(face)
    return font, face.upem


class _FlatPen:
    """A pen that flattens outlines into closed polylines (font units, y up)."""

    def __init__(self, steps: int = 8) -> None:
        self.contours: list[list[tuple[float, float]]] = []
        self.cur: list[tuple[float, float]] = []
        self.steps = steps

    def moveTo(self, p):  # noqa: N802, ANN001
        if self.cur:
            self.contours.append(self.cur)
        self.cur = [tuple(p)]

    def lineTo(self, p):  # noqa: N802, ANN001
        self.cur.append(tuple(p))

    def qCurveTo(self, *pts):  # noqa: N802, ANN002
        # TrueType implied on-curve points between consecutive off-curve points
        p0 = self.cur[-1]
        offs, end = list(pts[:-1]), pts[-1]
        if not offs:
            self.lineTo(end)
            return
        segs = []
        for i, c in enumerate(offs):
            nxt = end if i == len(offs) - 1 else ((c[0] + offs[i + 1][0]) / 2, (c[1] + offs[i + 1][1]) / 2)
            segs.append((c, nxt))
        for c, e in segs:
            for k in range(1, self.steps + 1):
                t = k / self.steps
                x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * e[0]
                y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * e[1]
                self.cur.append((x, y))
            p0 = e

    def curveTo(self, *pts):  # noqa: N802, ANN002
        if len(pts) == 2:
            self.qCurveTo(*pts)
            return
        p0 = self.cur[-1]
        c1, c2, e = pts[-3], pts[-2], pts[-1]
        for k in range(1, self.steps + 1):
            t = k / self.steps
            mt = 1 - t
            x = mt ** 3 * p0[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * e[0]
            y = mt ** 3 * p0[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * e[1]
            self.cur.append((x, y))

    def closePath(self):  # noqa: N802
        if self.cur:
            self.contours.append(self.cur)
        self.cur = []

    endPath = closePath  # noqa: N815


class _SvgPen:
    """Exact SVG path data (curves kept), transformed to px with y down."""

    def __init__(self, ox: float, oy: float, k: float) -> None:
        self.d: list[str] = []
        self.ox, self.oy, self.k = ox, oy, k

    def _p(self, p) -> str:  # noqa: ANN001
        return f"{self.ox + p[0] * self.k:.3f} {self.oy - p[1] * self.k:.3f}"

    def moveTo(self, p):  # noqa: N802, ANN001
        self.d.append("M" + self._p(p))

    def lineTo(self, p):  # noqa: N802, ANN001
        self.d.append("L" + self._p(p))

    def qCurveTo(self, *pts):  # noqa: N802, ANN002
        offs, end = list(pts[:-1]), pts[-1]
        if not offs:
            self.lineTo(end)
            return
        for i, c in enumerate(offs):
            nxt = end if i == len(offs) - 1 else ((c[0] + offs[i + 1][0]) / 2, (c[1] + offs[i + 1][1]) / 2)
            self.d.append("Q" + self._p(c) + " " + self._p(nxt))

    def curveTo(self, *pts):  # noqa: N802, ANN002
        if len(pts) == 2:
            self.qCurveTo(*pts)
            return
        self.d.append("C" + " ".join(self._p(p) for p in pts[-3:]))

    def closePath(self):  # noqa: N802
        self.d.append("Z")

    endPath = closePath  # noqa: N815


@dataclass
class Shaped:
    glyphs: list[tuple[int, float, float]]  # gid, x, y in font units
    advance: float  # font units
    upem: int
    path: str
    ascender: float
    descender: float


@lru_cache(maxsize=4096)
def shape(text: str, font_path: str) -> Shaped:
    import uharfbuzz as hb

    font, upem = _hb_font(font_path)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True})
    x = 0.0
    out = []
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        out.append((info.codepoint, x + pos.x_offset, pos.y_offset))
        x += pos.x_advance
    ext = font.get_font_extents("ltr")
    return Shaped(out, x, upem, font_path, ext.ascender, ext.descender)


def text_width(text: str, size_px: float, font_path: Path | str | None = None) -> float:
    fp = str(font_path or font_for(text))
    s = shape(text, fp)
    return s.advance * size_px / s.upem


def _contours(s: Shaped, size_px: float, x0: float, baseline: float) -> list[list[tuple[float, float]]]:
    font, _ = _hb_font(s.path)
    k = size_px / s.upem
    out = []
    steps = 6 if size_px < 40 else 10
    for gid, gx, gy in s.glyphs:
        pen = _FlatPen(steps)
        font.draw_glyph_with_pen(gid, pen)
        if pen.cur:
            pen.contours.append(pen.cur)
        for c in pen.contours:
            out.append([(x0 + (gx + px) * k, baseline - (gy + py) * k) for px, py in c])
    return out


def _fill_nonzero(size: tuple[int, int], contours: list[list[tuple[float, float]]], ss: int = 4) -> Image.Image:
    """Coverage mask ('L') with the non-zero winding rule, anti-aliased by `ss`x supersampling."""
    W, H = size
    acc = np.zeros((H * ss, W * ss), dtype=np.int16)
    for c in contours:
        if len(c) < 3:
            continue
        area = sum(c[i][0] * c[(i + 1) % len(c)][1] - c[(i + 1) % len(c)][0] * c[i][1] for i in range(len(c)))
        if abs(area) < 1e-9:
            continue
        xs = [p[0] * ss for p in c]
        ys = [p[1] * ss for p in c]
        x0, x1 = max(0, int(min(xs)) - 1), min(W * ss, int(max(xs)) + 2)
        y0, y1 = max(0, int(min(ys)) - 1), min(H * ss, int(max(ys)) + 2)
        if x1 <= x0 or y1 <= y0:
            continue
        m = Image.new("1", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(m).polygon([(x - x0, y - y0) for x, y in zip(xs, ys)], fill=1)
        acc[y0:y1, x0:x1] += np.asarray(m, dtype=np.int16) * (1 if area > 0 else -1)
    cov = (acc != 0).astype(np.float32)
    if ss > 1:
        cov = cov.reshape(H, ss, W, ss).mean(axis=(1, 3))
    return Image.fromarray((cov * 255).round().astype(np.uint8), "L")


def draw_text(img: Image.Image, text: str, xy: tuple[float, float], size_px: float, fill: tuple[int, ...] | str,
              font_path: Path | str | None = None, anchor: str = "ls") -> tuple[float, float, float, float]:
    """Draw shaped text onto an RGBA/RGB image. anchor: l|m|r + s (baseline) | m (middle of ascent). Returns the box."""
    from PIL import ImageColor

    fp = str(font_path or font_for(text))
    s = shape(text, fp)
    k = size_px / s.upem
    w = s.advance * k
    x, y = xy
    if anchor[0] == "m":
        x -= w / 2
    elif anchor[0] == "r":
        x -= w
    asc, desc = s.ascender * k, -s.descender * k
    baseline = y if anchor[1] == "s" else y + (asc - desc) / 2
    pad = int(size_px)
    bx0, by0 = int(math.floor(x)) - pad, int(math.floor(baseline - asc)) - pad
    bw, bh = int(math.ceil(w)) + 2 * pad, int(math.ceil(asc + desc)) + 2 * pad
    contours = _contours(s, size_px, x - bx0, baseline - by0)
    mask = _fill_nonzero((bw, bh), contours)
    col = ImageColor.getrgb(fill) if isinstance(fill, str) else fill
    if len(col) == 3:
        col = (*col, 255)
    alpha = col[3] / 255.0
    if alpha < 1:
        mask = mask.point(lambda v: int(v * alpha))
    layer = Image.new("RGBA", (bw, bh), (*col[:3], 0))
    layer.putalpha(mask)
    if img.mode == "RGBA":
        img.alpha_composite(layer, (bx0, by0)) if bx0 >= 0 and by0 >= 0 else img.paste(layer, (bx0, by0), layer)
    else:
        img.paste(layer.convert("RGB"), (bx0, by0), layer)
    return (x, baseline - asc, x + w, baseline + desc)


def svg_text_path(text: str, x: float, y: float, size: float, font_path: Path | str | None = None, anchor: str = "ls") -> str:
    """SVG path data for `text` (units = the caller's: px or mm), outlines exact."""
    fp = str(font_path or font_for(text))
    s = shape(text, fp)
    k = size / s.upem
    w = s.advance * k
    if anchor[0] == "m":
        x -= w / 2
    elif anchor[0] == "r":
        x -= w
    if anchor[1] == "m":
        y += (s.ascender + s.descender) * k / 2
    font, _ = _hb_font(fp)
    parts = []
    for gid, gx, gy in s.glyphs:
        pen = _SvgPen(x + gx * k, y - gy * k, k)
        font.draw_glyph_with_pen(gid, pen)
        parts.append("".join(pen.d))
    return "".join(parts)


def wrap(text: str, size_px: float, max_w: float, font_path: Path | str | None = None) -> list[str]:
    fp = str(font_path or font_for(text))
    words = (text or "").split()
    lines: list[str] = []
    cur = ""
    for wd in words:
        trial = f"{cur} {wd}" if cur else wd
        if cur and text_width(trial, size_px, fp) > max_w:
            lines.append(cur)
            cur = wd
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines
