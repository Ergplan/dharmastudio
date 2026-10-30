"""The manuscript layer: Sanskrit verses lettered into the parchment and devotional ink figures, drawn on the paper
under the shards and callouts.

- Verses come from engine/shlokas.yaml and are typeset (never painted) line by line, exactly as written there, in a
  manuscript Devanagari face, sepia ink at ~28-40 % opacity with multiply blending; dandas (and optionally the first
  akshara) in a red-brown rubric; a slight rotation; optional faint ruled lines.
- Figures are the ink sketches in engine/figures, keyed to alpha and inked sepia, at ~35-55 % opacity.
- Placement is automatic and stable per page (a verse that only fits a narrow margin runs up the page, like a
  marginal note): the free parchment is sampled on a 2 mm grid (shards, callouts, the
  title block and marginalia excluded with a 2 mm clearance), candidate rectangles are enumerated and each item takes
  the one where it is largest. A verse is never set below 2.4 mm; if it cannot be, it is not placed.
- Density: off (nothing) | light (1 verse, 1 figure) | rich (2 verses, 2 figures). The author can also place items
  by hand (Page.manuscript with auto=false).
"""

from __future__ import annotations

import base64
import html
import io
import math
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from engine import typography as T

ENGINE = Path(__file__).resolve().parent.parent
VERSES_FILE = ENGINE / "shlokas.yaml"
FIGURE_DIR = ENGINE / "figures"
CELL = 2.0  # mm
CLEAR = 2.0  # mm clearance around shards, callouts, title, marginalia
EDGE = 4.0  # keep off the outer 4 mm of the trim (the burnt edge)
MIN_TYPE, MAX_TYPE = 2.4, 4.2
LEADING = 1.62
INK = "#3a2d1a"
RUBRIC = "#8c2f1c"
DENSITY = {"off": (0, 0), "light": (1, 1), "rich": (2, 2)}
FIGURE_TAGS: dict[str, tuple[str, ...]] = {
    "fig_rama": ("rama", "treta", "opener", "dharma", "prologue"),
    "fig_bow_arrow_hand": ("rama", "war", "lanka", "peak", "action"),
    "fig_hanuman": ("hanuman", "voice", "leap", "quiet"),
    "fig_shiva": ("shiva", "rameshwaram", "prabhas", "death"),
    "fig_shivalinga": ("shiva", "rameshwaram", "dhanushkodi", "revelation"),
    "fig_krishna_charioteer": ("krishna", "arjuna", "dwapara", "phala"),
    "fig_lotus_lamp": ("knowledge", "revelation", "quiet", "calm", "any"),
    "fig_shankha_chakra": ("knowledge", "revelation", "cycle", "kalki", "core"),
}
FIGURE_NAMES = {
    "fig_rama": "Rama", "fig_bow_arrow_hand": "Bow and arrow", "fig_hanuman": "Hanuman", "fig_shiva": "Shiva", "fig_shivalinga": "Shivalinga",
    "fig_krishna_charioteer": "Krishna, charioteer", "fig_lotus_lamp": "Lamp on a lotus", "fig_shankha_chakra": "Shankha and chakra",
}
FIGURE_URL = "/api/figures/{id}.png"

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 (trim mm)


@lru_cache(maxsize=1)
def verses() -> list[dict[str, Any]]:
    return list(yaml.safe_load(VERSES_FILE.read_text(encoding="utf-8"))["shlokas"])


def verse(vid: str) -> dict[str, Any] | None:
    return next((v for v in verses() if v["id"] == vid), None)


def figure_ids() -> list[str]:
    return sorted(p.stem for p in FIGURE_DIR.glob("fig_*.png"))


@lru_cache(maxsize=16)
def figure_png(fid: str, width: int = 720) -> bytes:
    """The sketch keyed to alpha (darkness = ink) and inked sepia, downscaled for embedding."""
    from PIL import Image

    from engine.providers import key_to_alpha

    raw = (FIGURE_DIR / f"{fid}.png").read_bytes()
    with Image.open(io.BytesIO(key_to_alpha(raw))) as im:
        im = im.convert("RGBA")
        if im.width > width:
            im = im.resize((width, int(im.height * width / im.width)), Image.LANCZOS)
        r, g, b = (int(INK[i:i + 2], 16) for i in (1, 3, 5))
        inked = Image.new("RGBA", im.size, (r, g, b, 0))
        inked.putalpha(im.getchannel("A"))
        buf = io.BytesIO()
        inked.save(buf, "PNG", optimize=True)
    return buf.getvalue()


@lru_cache(maxsize=16)
def figure_aspect(fid: str) -> float:
    from PIL import Image

    with Image.open(FIGURE_DIR / f"{fid}.png") as im:
        return im.width / im.height


def figure_data_uri(fid: str) -> str:
    return "data:image/png;base64," + base64.b64encode(figure_png(fid)).decode()


# ---------------------------------------------------------------------------------
# choosing
# ---------------------------------------------------------------------------------


def choose(tags: set[str], seed: int, n_verses: int = 99, n_figures: int = 99) -> tuple[list[str], list[str]]:
    """Verses and figures for a page, ranked by tag overlap (ties broken by the page seed; `any` items are the
    fallback). `place` walks the ranking until enough items fit."""
    rng = random.Random(seed * 7 + 3)

    def pick(pool: list[tuple[str, tuple[str, ...]]], n: int, fallback: bool) -> list[str]:
        scored = sorted(((len(tags & set(t)), rng.random(), i) for i, t in pool), reverse=True)
        out = [i for s, _, i in scored if s > 0][:n]
        if len(out) < n and fallback:
            out += [i for s, _, i in scored if s == 0 and i not in out and ("any" in dict(pool)[i])][: n - len(out)]
        return out

    vs = pick([(v["id"], tuple(v.get("tags") or ())) for v in verses()], n_verses, True)
    fs = pick([(f, FIGURE_TAGS.get(f, ("any",))) for f in figure_ids()], n_figures, True)
    return vs, fs


# ---------------------------------------------------------------------------------
# free space
# ---------------------------------------------------------------------------------


class Grid:
    """Occupancy of the trim on a CELL mm grid (True = taken)."""

    def __init__(self, page_w: float, page_h: float):
        from PIL import Image

        self.w, self.h = int(page_w / CELL), int(page_h / CELL)
        self.page_w, self.page_h = page_w, page_h
        self.img = Image.new("L", (self.w, self.h), 0)
        e = int(math.ceil(EDGE / CELL))
        from PIL import ImageDraw

        d = ImageDraw.Draw(self.img)
        d.rectangle([0, 0, self.w - 1, e - 1], fill=255)
        d.rectangle([0, self.h - e, self.w - 1, self.h - 1], fill=255)
        d.rectangle([0, 0, e - 1, self.h - 1], fill=255)
        d.rectangle([self.w - e, 0, self.w - 1, self.h - 1], fill=255)

    def polygon(self, pts: list[tuple[float, float]], clear: float = CLEAR) -> None:
        from PIL import Image, ImageDraw, ImageFilter

        if len(pts) < 3:
            return
        layer = Image.new("L", (self.w, self.h), 0)
        ImageDraw.Draw(layer).polygon([(x / CELL, y / CELL) for x, y in pts], fill=255)
        k = 2 * int(math.ceil(clear / CELL)) + 1
        layer = layer.filter(ImageFilter.MaxFilter(k))
        self.img.paste(255, mask=layer)

    def rect(self, r: Rect, clear: float = CLEAR) -> None:
        from PIL import ImageDraw

        x0, y0, x1, y1 = r
        ImageDraw.Draw(self.img).rectangle([math.floor((x0 - clear) / CELL), math.floor((y0 - clear) / CELL), math.ceil((x1 + clear) / CELL), math.ceil((y1 + clear) / CELL)], fill=255)

    def candidates(self) -> list[Rect]:
        """Maximal free rectangles (histogram method over each row), in mm."""
        px = self.img.load()
        heights = [0] * self.w
        seen: set[tuple[int, int, int, int]] = set()
        out: list[Rect] = []
        for r in range(self.h):
            for c in range(self.w):
                heights[c] = heights[c] + 1 if px[c, r] == 0 else 0
            stack: list[int] = []
            for c in range(self.w + 1):
                hc = heights[c] if c < self.w else 0
                while stack and heights[stack[-1]] >= hc:
                    top = stack.pop()
                    hh = heights[top]
                    if hh == 0:
                        continue
                    left = stack[-1] + 1 if stack else 0
                    key = (left, r - hh + 1, c - left, hh)
                    if key not in seen and key[2] >= 3 and hh >= 2:
                        seen.add(key)
                        out.append((left * CELL, (r - hh + 1) * CELL, c * CELL, (r + 1) * CELL))
                stack.append(c)
        return out


# ---------------------------------------------------------------------------------
# placement
# ---------------------------------------------------------------------------------


@dataclass
class Placed:
    kind: str  # verse | figure
    id: str
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float
    rotation: float = 0.0
    size_mm: float = 0.0  # verses: the type size
    opacity: float = 0.34
    font: str = "tiro-devanagari-hindi"
    ruled: bool = False

    def rect(self) -> Rect:
        return (self.x_mm, self.y_mm, self.x_mm + self.w_mm, self.y_mm + self.h_mm)

    def json(self) -> dict[str, Any]:
        d = {"id": self.id, "x_mm": round(self.x_mm, 2), "y_mm": round(self.y_mm, 2), "w_mm": round(self.w_mm, 2), "h_mm": round(self.h_mm, 2), "rotation": round(self.rotation, 2), "opacity": round(self.opacity, 3)}
        if self.kind == "verse":
            d.update({"font": self.font, "size_mm": round(self.size_mm, 2), "ruled": self.ruled})
        return d


def _face(font_id: str) -> T.Face:
    f = T.FONTS.get(font_id) or T.FONTS["tiro-devanagari-hindi"]
    return f.face(400)


def verse_block(vid: str, size: float, font_id: str) -> tuple[float, float]:
    v = verse(vid) or {"lines": [""]}
    face = _face(font_id)
    tw = max(T.text_width(line, face, size) for line in v["lines"])
    return tw + 1.0, len(v["lines"]) * size * LEADING + 0.6


def _rotated(w: float, h: float, deg: float) -> tuple[float, float]:
    a = math.radians(abs(deg))
    return w * math.cos(a) + h * math.sin(a), w * math.sin(a) + h * math.cos(a)


def _fit_verse(vid: str, rect: Rect, rot: float, font_id: str) -> tuple[float, float, float] | None:
    """The largest type size (<= MAX_TYPE, >= MIN_TYPE) at which the rotated block fits the rect: (size, w, h)."""
    W, H = rect[2] - rect[0], rect[3] - rect[1]
    s = MAX_TYPE
    while s >= MIN_TYPE - 1e-6:
        w, h = verse_block(vid, s, font_id)
        rw, rh = _rotated(w, h, rot)
        if rw <= W and rh <= H:
            return s, w, h
        s = round(s - 0.1, 2)
    return None


def place(grid: Grid, verse_ids: list[str], figure_ids_: list[str], seed: int, font_id: str, opacity: float, n_verses: int = 1, n_figures: int = 1) -> list[Placed]:
    rng = random.Random(seed * 13 + 1)
    out: list[Placed] = []
    for vid in verse_ids:
        if sum(1 for p in out if p.kind == "verse") >= n_verses:
            break
        tilt = round(rng.uniform(-4, 4), 2)
        # horizontal (a slight tilt) first; a narrow margin takes the verse running up the page like a marginal note
        vertical = round((-90 if rng.random() < 0.5 else 90) + rng.uniform(-3, 3), 2)
        best = None
        for r in grid.candidates():
            for rot in (tilt, vertical):
                got = _fit_verse(vid, r, rot, font_id)
                if got and (best is None or (got[0], -abs(rot)) > (best[0][0], -abs(best[2]))):
                    best = (got, r, rot)
        if best is None:
            continue
        (s, w, h), r, rot = best
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        p = Placed("verse", vid, cx - w / 2, cy - h / 2, w, h, rot, s, opacity, font_id, ruled=rng.random() < 0.5)
        out.append(p)
        rw, rh = _rotated(w, h, rot)
        grid.rect((cx - rw / 2, cy - rh / 2, cx + rw / 2, cy + rh / 2))
    for fid in figure_ids_:
        if sum(1 for p in out if p.kind == "figure") >= n_figures:
            break
        a = figure_aspect(fid)
        rot = round(rng.uniform(-5, 5), 2)
        best = None
        for r in grid.candidates():
            W, H = r[2] - r[0] - 1, r[3] - r[1] - 1
            w = min(60.0, W, H * a)
            if w >= 28 and (best is None or w > best[0]):
                best = (w, r)
        if best is None:
            continue
        w, r = best
        h = w / a
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        out.append(Placed("figure", fid, cx - w / 2, cy - h / 2, w, h, rot, 0.0, min(0.55, max(0.35, opacity + 0.12))))
        grid.rect((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
    return out


def from_stored(stored: dict[str, Any], default_font: str, opacity: float) -> list[Placed]:
    """The author's own placements (Page.manuscript with auto=false)."""
    out: list[Placed] = []
    for v in stored.get("verses") or []:
        if not verse(str(v.get("id"))):
            continue
        font = v.get("font") if v.get("font") in T.MANUSCRIPT_FONTS else default_font
        w = float(v.get("w_mm") or 50)
        tw, _ = verse_block(v["id"], 1.0, font)
        s = max(2.4, (w - 1.0) / max(tw - 1.0, 1e-6))
        bw, bh = verse_block(v["id"], s, font)
        out.append(Placed("verse", v["id"], float(v.get("x_mm", 0)), float(v.get("y_mm", 0)), bw, bh, float(v.get("rotation", 0)), s,
                          float(v.get("opacity") or opacity), font, bool(v.get("ruled", False))))
    for f in stored.get("figures") or []:
        if f.get("id") not in figure_ids():
            continue
        w = float(f.get("w_mm") or 40)
        out.append(Placed("figure", f["id"], float(f.get("x_mm", 0)), float(f.get("y_mm", 0)), w, w / figure_aspect(f["id"]), float(f.get("rotation", 0)), 0.0,
                          float(f.get("opacity") or min(0.55, opacity + 0.12))))
    return out


# ---------------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------------

_MARKS = set("ऀँंःऺऻ़ािीुूृॄॅॆेैॉॊोौ्ॎॏ॒॑॓॔ॕॖॗॢॣ‌‍")


def first_akshara(line: str) -> int:
    """Length of the first akshara (consonant cluster with its vowel signs), so a rubric never splits a conjunct."""
    i = 1 if line else 0
    while i < len(line) and (line[i] in _MARKS or line[i - 1] == "्"):
        i += 1
    return i


def _line_svg(line: str, rubric: bool, first: bool, rubric_colour: str = RUBRIC) -> str:
    """tspans: dandas (and the first akshara of the verse) in the rubric colour, split only at cluster boundaries."""
    esc = lambda s: html.escape(s, quote=False)  # noqa: E731
    segs: list[tuple[str, bool]] = []
    start = 0
    if rubric and first:
        k = first_akshara(line)
        segs.append((line[:k], True))
        start = k
    buf = ""
    for ch in line[start:]:
        if rubric and ch in "।॥":
            if buf:
                segs.append((buf, False))
                buf = ""
            segs.append((ch, True))
        else:
            buf += ch
    if buf:
        segs.append((buf, False))
    return "".join(f"<tspan fill='{rubric_colour}'>{esc(t)}</tspan>" if red else esc(t) for t, red in segs)


def layer_svg(items: list[Placed], embed: bool, rubric: bool) -> str:
    if not items:
        return ""
    out = []
    for p in items:
        cx, cy = p.x_mm + p.w_mm / 2, p.y_mm + p.h_mm / 2
        tr = f"rotate({p.rotation:.2f} {cx:.2f} {cy:.2f})"
        if p.kind == "figure":
            src = figure_data_uri(p.id) if embed else FIGURE_URL.format(id=p.id)
            out.append(f"<g class='ms-fig' data-id='{p.id}' transform='{tr}' opacity='{p.opacity:.2f}' style='mix-blend-mode:multiply'>"
                       f"<image href='{src}' x='{p.x_mm:.2f}' y='{p.y_mm:.2f}' width='{p.w_mm:.2f}' height='{p.h_mm:.2f}' preserveAspectRatio='xMidYMid meet'/></g>")
            continue
        v = verse(p.id) or {"lines": []}
        fam = (T.FONTS.get(p.font) or T.FONTS["tiro-devanagari-hindi"]).family
        lines = []
        for i, line in enumerate(v["lines"]):
            y = p.y_mm + 0.3 + (i + 0.78) * p.size_mm * LEADING
            if p.ruled:
                lines.append(f"<line x1='{p.x_mm:.2f}' x2='{p.x_mm + p.w_mm:.2f}' y1='{y + p.size_mm * 0.28:.2f}' y2='{y + p.size_mm * 0.28:.2f}' stroke='{INK}' stroke-opacity='0.35' stroke-width='0.12'/>")
            lines.append(f"<text class='ms-line' x='{p.x_mm + 0.5:.2f}' y='{y:.2f}'>{_line_svg(line, rubric, i == 0)}</text>")
        out.append(f"<g class='ms-verse' data-id='{p.id}' transform='{tr}' opacity='{p.opacity:.2f}' fill='{INK}' font-family=\"'{fam}',serif\" "
                   f"font-size='{p.size_mm:.2f}' style='mix-blend-mode:multiply'>{''.join(lines)}</g>")
    return f"<g class='manuscript'>{''.join(out)}</g>"


@dataclass
class Spec:
    """What a page asks of the layer: settings, the stored placements, the tags that choose verses and figures."""
    density: str = "light"
    font: str = "tiro-devanagari-hindi"
    opacity: float = 0.34
    rubric: bool = True
    stored: dict[str, Any] = field(default_factory=dict)  # Page.manuscript
    tags: set[str] = field(default_factory=set)

    @property
    def auto(self) -> bool:
        return self.stored.get("auto", True) is not False
