"""Page layout: shards and plates, bilingual captions on the intensity scale, rendered to HTML (and from there PDF).

Procedure
- A page's panels are split recursively by weight (the auto-cut); each cut is a slightly angled line with jitter, so
  the gutters read as fractures. Panels are polygons in mm on a 170 x 260 mm page (+3 mm bleed). Shapes are stored
  per panel once computed and edited by the author; the renderer only draws what it is given.
- Each polygon becomes an SVG clipPath over the panel's image (object-fit: cover with over-frame and a focal pan/zoom).
- Captions, balloons, SFX and the title block are typeset in HTML with the state's colours, in the fonts and sizes of the
  page's typography (engine/typography.py: a volume preset plus an optional page override; Hindi uses the hi_* fonts,
  shaped by Chromium). A page embeds @font-face rules only for the faces it uses. Playwright renders the PDF.
- Canvas: for screen the page background is the canvas's paper texture; for print (paper="print") only ink is output.
"""

from __future__ import annotations

import base64
import html
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine import colour as C
from engine.comic import callouts as CO
from engine.comic import manuscript as MS
from engine import typography as T

from .visual_logic import PageLook, area_weight, beat_of, page_look, panel_colour

PAGE_W, PAGE_H, BLEED = 170.0, 260.0, 3.0  # mm
MARGIN = 6.0  # mm inside trim before any shard edge
OPENER_TOP = 46.0  # mm reserved for the title block on a chapter opener
FONT_DIR = Path(__file__).resolve().parent / "fonts"

STATE_STYLE = {
    "quiet": {"box": "#efe4c9", "text": "#161210", "edge": "none", "font": "serif"},
    "rising": {"box": "#4a4a4c", "text": "#f2ede3", "edge": "0.25mm solid #0b0b0b", "font": "serif"},
    "peak": {"box": "#0b0b0d", "text": "#f2ede3", "edge": "fracture", "font": "serif"},
    "ego": {"box": "#0b0b0d", "text": "#b3261e", "edge": "shard", "font": "serif"},
    "knowledge": {"box": "#0e1a26", "text": "#d4a017", "edge": "glow", "font": "serif"},
    "voice": {"box": "#efe4c9", "text": "#5a3a1a", "edge": "torn", "font": "serif"},
}
SEPIA = "#3a2d1a"
SHAPE_KINDS = ("torn", "crisp", "fracture", "hex", "rect", "inset", "bleed", "custom")
EDGE_KINDS = ("torn", "crisp", "chipped", "feathered", "rim")

Point = tuple[float, float]


# ---------------------------------------------------------------------------------
# views: plain data the renderer draws from (the backend builds them from the ORM)
# ---------------------------------------------------------------------------------


@dataclass
class PanelView:
    number: int  # page*100 + n
    n: int
    kind: str = "shard"  # shard | plate
    shape: dict[str, Any] = field(default_factory=dict)  # {kind, polygon_mm, edge, z, focal{x,y,scale}}
    image_group: str | None = None
    text_state: str = "quiet"
    scale: str = "MS"
    beat: str | None = None
    weight: float = 1.0
    caption_en: str = ""
    caption_hi: str = ""
    balloon_en: str = ""
    balloon_hi: str = ""
    speaker: str | None = None
    image_path: Path | None = None
    image_url: str | None = None  # served URL for the live UI render
    characters: list[str] = field(default_factory=list)
    sfx: str = ""  # lettered sound effect (drawn in the sfx font at the shard's top-left)
    text_colours: dict[str, Any] | None = None  # the panel's pinned callout colours {box, text, border}; None/auto = by mode
    callout_shape: str | None = None  # auto (by state) or a callouts.KINDS kind
    balloon_shape: str | None = None

    @property
    def polygon(self) -> list[Point]:
        return [(float(x), float(y)) for x, y in (self.shape.get("polygon_mm") or [])]

    @property
    def z(self) -> int:
        return int(self.shape.get("z") or 0)

    @property
    def edge(self) -> str:
        return str(self.shape.get("edge") or "crisp")

    @property
    def focal(self) -> dict[str, float]:
        f = self.shape.get("focal") or {}
        return {"x": float(f.get("x", 0.5)), "y": float(f.get("y", 0.5)), "scale": max(1.0, float(f.get("scale", 1.0)))}


@dataclass
class CanvasView:
    key: str = "parchment"
    name: str = "Parchment"
    paper_texture: Path | None = None  # PNG on disk (screen render)
    texture_url: str | None = None  # served URL (screen render without embedding)
    ink: str = SEPIA
    gutter: str = "paper"  # "paper" = the paper itself is the gutter, else a colour
    caption_style: dict[str, Any] = field(default_factory=dict)  # {text, box, border, textured}
    marginalia_style: dict[str, Any] = field(default_factory=dict)  # {tint, opacity}
    finish: str = ""  # "painted": a painted sheet; shards get a torn paper rim instead of an ink edge

    @property
    def paper_is_gutter(self) -> bool:
        return self.gutter == "paper"


@dataclass
class MarginaliaView:
    path: Path | None  # transparent PNG, ink on alpha
    url: str | None = None
    x_mm: float = 0.0
    y_mm: float = 0.0
    w_mm: float = 30.0
    h_mm: float | None = None
    rotation: float = 0.0
    opacity: float = 0.85
    tint: str | None = None  # per-item ink tint (else the canvas marginalia tint)


@dataclass
class TitleBlock:
    book_title: str = "The Cycle of Dharma"
    book_title_hi: str = "धर्म का चक्र"
    volume_title: str = ""
    volume_title_hi: str = ""
    chapter_title: str = ""
    chapter_title_hi: str = ""
    chapter_number: int | None = None
    epigraph: str = ""
    epigraph_hi: str = ""


@dataclass
class PageView:
    number: int
    panels: list[PanelView]
    beat: str | None = None
    is_opener: bool = False
    title: TitleBlock | None = None
    marginalia: list[MarginaliaView] = field(default_factory=list)
    overlays: list[MarginaliaView] = field(default_factory=list)  # drawn above the art, untinted (QR page elements)
    seed: int = 7
    typography: T.TypeSpec | None = None  # resolved fonts and sizes (volume setting + page override); None = default
    ink_dissolve: bool | None = None  # art fading into hatching at the margin edge; None = auto (on for calm, torn pages)
    manuscript: MS.Spec | None = None  # the verses-and-figures layer; None = off
    manuscript_items: list = field(default_factory=list)  # filled by page_html: what the layer placed

    @property
    def type(self) -> T.TypeSpec:
        if self.typography is None:
            self.typography = T.resolve()
        return self.typography


@dataclass
class RenderOptions:
    lang: str = "en"
    paper: str = "screen"  # screen | print
    embed: bool = True  # data URIs (PDF, artifacts) vs served URLs (live UI)
    print_texture: bool = False  # print mode: also print the paper texture (default: the stock is the paper)

    @property
    def print(self) -> bool:
        return self.paper == "print"


# ---------------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------------


def _clip(poly: list[Point], a: Point, n: Point, keep_positive: bool) -> list[Point]:
    """Sutherland-Hodgman clip of poly against the half-plane n.(p-a) >= 0 (or <= 0)."""

    def side(p: Point) -> float:
        return (p[0] - a[0]) * n[0] + (p[1] - a[1]) * n[1]

    out: list[Point] = []
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        sp, sq = side(p), side(q)
        inside_p = sp >= 0 if keep_positive else sp <= 0
        inside_q = sq >= 0 if keep_positive else sq <= 0
        if inside_p:
            out.append(p)
        if inside_p != inside_q:
            t = sp / (sp - sq) if (sp - sq) != 0 else 0.0
            out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return out


def clip_to_rect(poly: list[Point], x0: float, y0: float, x1: float, y1: float) -> list[Point]:
    if not poly:
        return poly
    poly = _clip(poly, (x0, 0), (1, 0), True)
    poly = _clip(poly, (x1, 0), (-1, 0), True)
    poly = _clip(poly, (0, y0), (0, 1), True)
    return _clip(poly, (0, y1), (0, -1), True)


def _bbox(poly: list[Point]) -> tuple[float, float, float, float]:
    if not poly:
        return 0.0, 0.0, 1.0, 1.0
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _area(poly: list[Point]) -> float:
    if len(poly) < 3:
        return 0.0
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))) / 2


def _inset(poly: list[Point], d: float) -> list[Point]:
    """Shrink a convex polygon toward its centroid by about d mm (gutter)."""
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    x0, y0, x1, y1 = _bbox(poly)
    r = max(1.0, min(x1 - x0, y1 - y0) / 2)
    k = max(0.0, 1 - d / r)
    return [(cx + (p[0] - cx) * k, cy + (p[1] - cy) * k) for p in poly]


def _chip(poly: list[Point], rng: random.Random, depth: float = 1.4) -> list[Point]:
    """Add one small notch vertex to each long edge so peak pages read as broken stone."""
    out: list[Point] = []
    n = len(poly)
    for i, p in enumerate(poly):
        q = poly[(i + 1) % n]
        out.append(p)
        L = math.hypot(q[0] - p[0], q[1] - p[1])
        if L > 40:
            t = rng.uniform(0.3, 0.7)
            mx, my = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
            nx, ny = -(q[1] - p[1]) / L, (q[0] - p[0]) / L
            out.append((mx + nx * depth, my + ny * depth))
    return out


def _tear(poly: list[Point], rng: random.Random, amp: float = 0.55, step: float = 6.0) -> list[Point]:
    """Resample each edge with small noise so calm pages read as gently torn paper."""
    out: list[Point] = []
    n = len(poly)
    for i, p in enumerate(poly):
        q = poly[(i + 1) % n]
        L = math.hypot(q[0] - p[0], q[1] - p[1])
        k = max(1, int(L / step))
        nx, ny = (-(q[1] - p[1]) / L, (q[0] - p[0]) / L) if L else (0.0, 0.0)
        for j in range(k):
            t = j / k
            a = rng.uniform(-amp, amp) if j else 0.0
            out.append((p[0] + (q[0] - p[0]) * t + nx * a, p[1] + (q[1] - p[1]) * t + ny * a))
    return out


def ellipse_polygon(cx: float, cy: float, rx: float, ry: float, n: int = 40) -> list[Point]:
    return [(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]


def rounded_rect_polygon(x0: float, y0: float, x1: float, y1: float, r: float = 1.0, steps: int = 4) -> list[Point]:
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    out: list[Point] = []
    corners = [((x1 - r, y0 + r), -90), ((x1 - r, y1 - r), 0), ((x0 + r, y1 - r), 90), ((x0 + r, y0 + r), 180)]
    for (cx, cy), start in corners:
        for i in range(steps + 1):
            a = math.radians(start + 90 * i / steps)
            out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def hexagon_polygon(cx: float, cy: float, R: float) -> list[Point]:
    return [(cx + R * math.cos(math.radians(60 * i - 30)), cy + R * math.sin(math.radians(60 * i - 30))) for i in range(6)]


def page_polygon() -> list[Point]:
    return [(-BLEED, -BLEED), (PAGE_W + BLEED, -BLEED), (PAGE_W + BLEED, PAGE_H + BLEED), (-BLEED, PAGE_H + BLEED)]


# ---------------------------------------------------------------------------------
# the auto-cut
# ---------------------------------------------------------------------------------


def _w(p: PanelView) -> float:
    return area_weight(p.weight, p.scale)


def panel_beat(p: PanelView) -> str:
    return beat_of(p.text_state, p.beat)


def page_look_for(panels: list[PanelView], page_beat: str | None = None) -> PageLook:
    beats = [page_beat] * len(panels) if page_beat else [panel_beat(p) for p in panels]
    return page_look([p.text_state for p in panels], [_w(p) for p in panels], beats)


def _hex_cells(panels: list[PanelView], gutter: float, top: float) -> dict[int, list[Point]]:
    """Opener montage: a honeycomb of regular (pointy-top) hexagons; edge cells run off the trim."""
    n = len(panels)
    cols = 1 if n == 1 else (2 if n <= 4 else 3)
    rows = math.ceil(n / cols)
    H = PAGE_H - top
    R = min(PAGE_W / (cols * math.sqrt(3) + math.sqrt(3) / 2), H / (1.5 * rows + 0.5)) * 1.12
    w, vstep = math.sqrt(3) * R, 1.5 * R
    grid_w, grid_h = cols * w + w / 2, rows * vstep + R / 2
    ox, oy = (PAGE_W - grid_w) / 2 + w / 2, top + (H - grid_h) / 2 + R
    cells = [(ox + c * w + (w / 2 if r % 2 else 0), oy + r * vstep) for r in range(rows) for c in range(cols)]
    return {p.number: clip_to_rect(hexagon_polygon(x, y, R - gutter / 2), -BLEED, max(-BLEED, top - 2), PAGE_W + BLEED, PAGE_H + BLEED) for p, (x, y) in zip(panels, cells)}


def shape_kind_for(look: PageLook, panel: PanelView) -> str:
    if panel.kind == "plate":
        return "bleed"
    return {"calm": "torn", "tension": "crisp", "action": "fracture", "hex": "hex", "revelation": "crisp"}.get(look.beat, "crisp")


def edge_for(look: PageLook, kind: str) -> str:
    if kind == "hex":
        return "rim"
    if kind == "rect":
        return "crisp"
    if kind == "inset":
        return "rim"
    return look.edge if look.edge in EDGE_KINDS else "crisp"


def auto_cut(panels: list[PanelView], seed: int, page_no: int, page_beat: str | None = None, is_opener: bool = False) -> dict[int, dict[str, Any]]:
    """Return {panel.number: shape} for the page's panels (plates get the full bleed page).
    Angle, gutter and edge treatment come from the page's intensity; size from script weight x shot scale."""
    rng = random.Random(seed * 1000 + page_no)
    if not panels:
        return {}
    look = page_look_for(panels, page_beat)
    top = OPENER_TOP if is_opener else MARGIN
    ordered = sorted(panels, key=lambda p: p.n)

    def shape(kind: str, poly: list[Point], z: int = 0) -> dict[str, Any]:
        return {"kind": kind, "polygon_mm": [[round(x, 2), round(y, 2)] for x, y in poly], "edge": edge_for(look, kind), "z": z, "focal": {"x": 0.5, "y": 0.5, "scale": 1.0}}

    if len(ordered) == 1 and ordered[0].kind == "plate":
        return {ordered[0].number: shape("bleed", page_polygon())}
    if look.beat == "hex":
        return {num: shape("hex", poly) for num, poly in _hex_cells(ordered, look.gutter_mm, top).items()}

    inner = [(MARGIN, top), (PAGE_W - MARGIN, top), (PAGE_W - MARGIN, PAGE_H - MARGIN), (MARGIN, PAGE_H - MARGIN)]
    out: dict[int, dict[str, Any]] = {}
    raw = {p.number: _w(p) for p in ordered}
    floor = 0.12 * sum(raw.values())
    W = {k: max(v, floor) for k, v in raw.items()}

    def rec(poly: list[Point], items: list[PanelView]) -> None:
        if len(items) == 1:
            p = items[0]
            if p.kind == "plate":  # a plate among shards: full-bleed under the others
                out[p.number] = shape("bleed", page_polygon(), z=-1)
                return
            shard = _inset(poly, look.gutter_mm / 2)
            kind = shape_kind_for(look, p)
            if look.edge == "chipped" or kind == "fracture":
                shard = _chip(shard, rng)
            elif look.edge == "torn" or kind == "torn":
                shard = _tear(shard, rng)
            out[p.number] = shape(kind, shard)
            return
        total = sum(W[p.number] for p in items)
        acc, k = 0.0, 0
        for k in range(1, len(items)):
            acc += W[items[k - 1].number]
            if acc >= total / 2 or k == len(items) - 1:
                break
        first, second = items[:k], items[k:]
        share = sum(W[p.number] for p in first) / total
        x0, y0, x1, y1 = _bbox(poly)
        w, h = x1 - x0, y1 - y0
        horizontal_cut = h >= w * 0.9
        if look.diagonal_bias and rng.random() < look.diagonal_bias:
            horizontal_cut = not horizontal_cut
        angle = math.radians(rng.uniform(-look.angle_deg, look.angle_deg) * (1.6 if look.beat == "action" and rng.random() < 0.5 else 1.0))
        if horizontal_cut:
            y = y0 + h * (share + rng.uniform(-0.04, 0.04))
            a, n = (x0 + w / 2, y), (-math.sin(angle), math.cos(angle))
            rec(_clip(poly, a, n, keep_positive=False), first)
            rec(_clip(poly, a, n, keep_positive=True), second)
        else:
            x = x0 + w * (share + rng.uniform(-0.04, 0.04))
            a, n = (x, y0 + h / 2), (math.cos(angle), math.sin(angle))
            rec(_clip(poly, a, n, keep_positive=False), first)
            rec(_clip(poly, a, n, keep_positive=True), second)

    rec(inner, ordered)
    return out


def normalise_shape(shape: dict[str, Any] | None) -> dict[str, Any]:
    """Validate/complete a stored shape (from the editor or the API)."""
    s = dict(shape or {})
    kind = s.get("kind") if s.get("kind") in SHAPE_KINDS else "custom"
    poly = [[float(x), float(y)] for x, y in (s.get("polygon_mm") or [])]
    if kind == "bleed" and not poly:
        poly = [[x, y] for x, y in page_polygon()]
    edge = s.get("edge") if s.get("edge") in EDGE_KINDS else ("rim" if kind in ("hex", "inset") else "crisp")
    f = s.get("focal") or {}
    focal = {"x": min(1.0, max(0.0, float(f.get("x", 0.5)))), "y": min(1.0, max(0.0, float(f.get("y", 0.5)))), "scale": max(1.0, float(f.get("scale", 1.0)))}
    return {"kind": kind, "polygon_mm": [[round(x, 2), round(y, 2)] for x, y in poly], "edge": edge, "z": int(s.get("z") or 0), "focal": focal}


def shape_from_kind(kind: str, bbox: tuple[float, float, float, float], seed: int = 1) -> dict[str, Any]:
    """A fresh polygon of the given kind inside a bbox (the editor's palette)."""
    x0, y0, x1, y1 = bbox
    rng = random.Random(seed)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if kind == "inset":
        poly = ellipse_polygon(cx, cy, (x1 - x0) / 2, (y1 - y0) / 2)
        return normalise_shape({"kind": "inset", "polygon_mm": poly, "edge": "rim", "z": 5})
    if kind == "rect":
        return normalise_shape({"kind": "rect", "polygon_mm": rounded_rect_polygon(x0, y0, x1, y1, 1.0), "edge": "crisp"})
    if kind == "hex":
        R = min(x1 - x0, y1 - y0) / 2
        return normalise_shape({"kind": "hex", "polygon_mm": hexagon_polygon(cx, cy, R), "edge": "rim"})
    if kind == "bleed":
        return normalise_shape({"kind": "bleed", "polygon_mm": page_polygon(), "edge": "crisp"})
    base = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if kind == "torn":
        return normalise_shape({"kind": "torn", "polygon_mm": _tear(base, rng), "edge": "torn"})
    if kind == "fracture":
        return normalise_shape({"kind": "fracture", "polygon_mm": _chip(base, rng), "edge": "chipped"})
    return normalise_shape({"kind": kind, "polygon_mm": base, "edge": "crisp"})


# ---------------------------------------------------------------------------------
# html
# ---------------------------------------------------------------------------------


_FONT_CSS: str | None = None


def font_css() -> str:
    global _FONT_CSS
    if _FONT_CSS is None:
        css = []
        for fam, fname, weight in (("DevSerif", "NotoSerifDevanagari.ttf", "400 700"), ("Mukta", "Mukta-Regular.ttf", "400"), ("Mukta", "Mukta-SemiBold.ttf", "600")):
            b = base64.b64encode((FONT_DIR / fname).read_bytes()).decode()
            css.append(f"@font-face{{font-family:'{fam}';src:url(data:font/ttf;base64,{b}) format('truetype');font-weight:{weight};}}")
        _FONT_CSS = "\n".join(css)
    return _FONT_CSS


_IMG_CACHE: dict[tuple[str, float], str] = {}


def img_data(path: Path | None, jpeg_quality: int = 93) -> str:
    """Embed a panel as a data URI. PNGs are re-encoded as JPEG q93 (visually lossless at 300 dpi, ~6x smaller)."""
    if not (path and path.exists()):
        return ""
    key = (str(path), path.stat().st_mtime)
    if key in _IMG_CACHE:
        return _IMG_CACHE[key]
    if path.suffix.lower() == ".png":
        import io

        from PIL import Image

        buf = io.BytesIO()
        with Image.open(path) as im:
            im.convert("RGB").save(buf, "JPEG", quality=jpeg_quality, subsampling=0, optimize=True)
        data = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    else:
        data = "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()
    if len(_IMG_CACHE) > 400:
        _IMG_CACHE.clear()
    _IMG_CACHE[key] = data
    return data


def png_data(path: Path | None) -> str:
    if not (path and path.exists()):
        return ""
    mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def _image_aspect(path: Path | None) -> float | None:
    if not (path and path.exists()):
        return None
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.size[0] / im.size[1]
    except Exception:  # noqa: BLE001
        return None


def _hex_to_rgb01(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    if len(h) != 6:
        return 0.23, 0.18, 0.10
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


def _esc(s: str | None) -> str:
    return html.escape(s or "", quote=False)


# ---------------------------------------------------------------------------------
# callouts: small rounded shards (captions) and rounded balloons with a tail, coloured from the panel's own palette
# ---------------------------------------------------------------------------------

CAP_PAD = (3.2, 3.4)  # vertical, horizontal padding (mm)
BAL_PAD = (2.8, 3.2)
CAP_MIN_W = 46.0


def _rounded_path(pts: list[Point], radius: float) -> str:
    """A closed path through pts with each corner rounded by a quadratic curve of ~radius mm."""
    n = len(pts)
    a_pts, b_pts = [], []
    for i, v in enumerate(pts):
        prv, nxt = pts[i - 1], pts[(i + 1) % n]
        lp, ln = math.dist(prv, v) or 1e-6, math.dist(v, nxt) or 1e-6
        r = min(radius, 0.4 * lp, 0.4 * ln)
        a_pts.append((v[0] + (prv[0] - v[0]) / lp * r, v[1] + (prv[1] - v[1]) / lp * r))
        b_pts.append((v[0] + (nxt[0] - v[0]) / ln * r, v[1] + (nxt[1] - v[1]) / ln * r))
    d = [f"M{b_pts[0][0]:.2f},{b_pts[0][1]:.2f}"]
    for i in list(range(1, n)) + [0]:
        d.append(f"L{a_pts[i][0]:.2f},{a_pts[i][1]:.2f}Q{pts[i][0]:.2f},{pts[i][1]:.2f} {b_pts[i][0]:.2f},{b_pts[i][1]:.2f}")
    return "".join(d) + "Z"


def callout_polygon(w: float, h: float, seed: int, sharp: bool = False) -> list[Point]:
    """An irregular 5-7 vertex shard around a w x h box: corners nudged (slight angle variation), 1-3 extra vertices
    pushed outward on the edges. Stable per seed; never cuts into the padding (inward moves stay < 0.8 mm)."""
    rng = random.Random(seed)
    j = 0.9 if sharp else 0.6
    corners = [(rng.uniform(-j, j * 0.6), rng.uniform(-j, j * 0.6)), (w + rng.uniform(-j * 0.6, j), rng.uniform(-j, j * 0.6)),
               (w + rng.uniform(-j * 0.6, j), h + rng.uniform(-j * 0.6, j)), (rng.uniform(-j, j * 0.6), h + rng.uniform(-j * 0.6, j))]
    extra = rng.choice((1, 2, 3))
    edges = rng.sample(range(4), extra)
    out: list[Point] = []
    for i, c in enumerate(corners):
        out.append(c)
        if i in edges:
            q = corners[(i + 1) % 4]
            t = rng.uniform(0.3, 0.7)
            mx, my = c[0] + (q[0] - c[0]) * t, c[1] + (q[1] - c[1]) * t
            L = math.dist(c, q) or 1.0
            nx, ny = (q[1] - c[1]) / L, -(q[0] - c[0]) / L  # outward normal for a clockwise box
            k = rng.uniform(0.3, 1.1 if sharp else 0.8)
            out.append((mx + nx * k, my + ny * k))
    return out


def balloon_path(w: float, h: float, tail_x: float, r: float = 3.2) -> str:
    """Rounded balloon with a short tail off the bottom edge at tail_x, pointing down and toward the panel."""
    r = min(r, h / 2.2, w / 4)
    tx = min(max(tail_x, r + 1), w - r - 5)
    return (f"M{r:.2f},0L{w - r:.2f},0Q{w:.2f},0 {w:.2f},{r:.2f}L{w:.2f},{h - r:.2f}Q{w:.2f},{h:.2f} {w - r:.2f},{h:.2f}"
            f"L{tx + 4.2:.2f},{h:.2f}L{tx - 1.8:.2f},{h + 4.2:.2f}L{tx + 0.8:.2f},{h:.2f}"
            f"L{r:.2f},{h:.2f}Q0,{h:.2f} 0,{h - r:.2f}L0,{r:.2f}Q0,0 {r:.2f},0Z")


@dataclass
class ImageInfo:
    path: Path | None
    box: tuple[float, float, float, float] | None  # x, y, w, h of the drawn image in page mm


def _paper_hex(canvas: CanvasView) -> str:
    cs = canvas.caption_style or {}
    return cs.get("box_print") or ("#e8d6b2" if canvas.paper_is_gutter else "#efe4c9")


def callout_colours(p: PanelView, kind: str, rect: tuple[float, float, float, float], canvas: CanvasView, ty: T.TypeSpec, img: ImageInfo | None,
                    paper: str | None = None, tile: tuple[float, float, float, float] | None = None) -> dict[str, Any]:
    """{box, text, border, contrast, mode, fill} for one callout, by the panel's pin, then the volume's colour mode.
    Smart mode fills the shape with a parchment scrap (`paper`): the text colour is chosen against the texture's mean
    colour under the text area (`tile`: x, y, w, h in tile mm), tinted toward the panel's palette (multiply <= 12 %)."""
    st = p.text_state if p.text_state in C.STATE_BOX else "quiet"
    st_b = "quiet" if kind == "balloon" and st != "ego" else st
    got = C.pinned(p.text_colours)
    if got:
        return {**got, "mode": "pinned"}
    if ty.colour_mode == "custom":
        got = C.custom(ty.colours, st_b)
        if got:
            return {**got, "mode": "custom"}
    cs = canvas.caption_style or {}
    if ty.colour_mode == "state":
        if kind == "balloon":
            box, text = ("#0b0b0d", "#b3261e") if st == "ego" else ("#f6f1e6", "#111111")
            return {"box": box, "text": text, "border": "#111111" if st != "ego" else "#b3261e", "contrast": round(C.contrast(box, text), 2), "mode": "state"}
        return {**C.fixed(st, canvas.paper_is_gutter, cs.get("box_print"), cs.get("text")), "mode": "state"}
    pal: list = []
    if img and img.path and img.box:
        bx, by, bw, bh = img.box
        x0, y0, x1, y1 = rect
        pal = C.palette(img.path, ((x0 - bx) / bw, (y0 - by) / bh, (x1 - bx) / bw, (y1 - by) / bh))
    ink = cs.get("text", canvas.ink if canvas.paper_is_gutter else "#161210")
    got = C.smart(pal, st_b, paper=_paper_hex(canvas), ink=ink, kind=kind)
    if paper is None or tile is None:
        return {**got, "mode": "smart"}
    # parchment: the texture's mean under the text, multiplied by a light tint of the panel's palette
    mean = CO.mean_under(paper, *tile)
    _, chroma, hue = C.lch(C.hex_to_rgb(got["box"]) if paper != "dark" else (pal[0][0] if pal else (120, 80, 40)))
    tint = C.from_lch(78.0, min(max(chroma, 10.0), 30.0), hue)
    a = 0.10
    eff = tuple(int(round(m * (1 - a + a * t / 255))) for m, t in zip(mean, tint))
    if paper == "dark":
        seed = C.hex_to_rgb({"ego": "#e8b4a8", "knowledge": "#e9c25a"}.get(st_b, "#f2ede3"))
    else:
        seed = C.hex_to_rgb(ink if st_b != "voice" else C.STATE_TEXT["voice"])
    text = C.ensure_contrast(seed, eff)  # type: ignore[arg-type]
    return {"box": C.rgb_to_hex(eff), "text": C.rgb_to_hex(text), "border": got["border"], "contrast": round(C.contrast(text, eff), 2), "mode": "smart",  # type: ignore[arg-type]
            "fill": {"paper": paper, "tint": C.rgb_to_hex(tint), "tint_alpha": a}}


def _callout(cls: str, x: float, y: float, sh: CO.Shape, col: dict[str, Any], font_css: str, size: float, lh: float, text: str, pad: tuple[float, float],
             opts: RenderOptions, uid: str, tile: tuple[float, float]) -> str:
    fill = dict(col.get("fill") or {})
    paper = fill.get("paper")
    if paper:
        fill["use"] = f"sx{paper}"
        fill["offset"] = tile
    else:
        fill = {"flat": col["box"]}
    dark = paper == "dark" or _luma(col["box"]) < 0.35
    fill["edge"] = "#9c7a4e" if dark else "#f4e9cf"
    fill["burn"] = "#0b0603" if dark else "#4a2e14"
    fill["burn_alpha"] = 0.6 if dark else 0.5
    svg = CO.svg(sh, uid, fill, opts.print)
    rot = f"transform:rotate({sh.rotation:.2f}deg);" if sh.rotation else ""
    return (f"<div class='{cls}' data-shape='{sh.kind}' data-paper='{paper or 'flat'}' data-bg='{col['box']}' data-fg='{col['text']}' data-contrast='{col['contrast']}' data-colour='{col['mode']}' "
            f"style=\"left:{x:.2f}mm;top:{y:.2f}mm;width:{sh.w:.2f}mm;height:{sh.h:.2f}mm;padding:{pad[0]}mm {pad[1]}mm;{rot}color:{col['text']};{font_css}font-size:{size:.2f}mm;line-height:{lh:.2f}\">"
            f"{svg}<span>{_esc(text)}</span></div>")


def _place(x: float, y: float, sh: CO.Shape, top_pad: float = 2.0) -> tuple[float, float]:
    """Keep the whole drawn scrap (overhang and rotation included) inside the trim with a small margin."""
    L, T_, R, B = sh.overhang
    grow = abs(math.sin(math.radians(sh.rotation))) * max(sh.w, sh.h) / 2
    x = min(max(x, 1.5 + L + grow), PAGE_W - 1.5 - R - grow - sh.w)
    y = min(max(y, top_pad + T_ + grow), PAGE_H - 1.5 - B - grow - sh.h)
    return x, y


def _sfx_html(p: PanelView, poly: list[Point], canvas: CanvasView, ty: T.TypeSpec) -> str:
    text = (p.sfx or "").strip()
    if not text:
        return ""
    x0, y0, x1, y1 = _bbox(poly)
    x0, y0, x1, y1 = max(x0, 0.0), max(y0, 0.0), min(x1, PAGE_W), min(y1, PAGE_H)
    r = ty.sfx(text)
    ink = SFX_INK.get(p.text_state) or (canvas.ink if canvas.paper_is_gutter else "#f2ede3")
    halo = "#0b0b0d" if _luma(ink) > 0.5 else "#f4ecd9"
    size = ty.sfx_mm()
    room = max(10.0, (x1 - x0) - 8)
    est_w = T.text_width(text, r.face, size)
    if est_w > room:  # keep it inside the shard: shrink a long word to the shard's width
        size = max(4.0, size * room / est_w)
    shadow = ",".join(f"{dx}mm {dy}mm 0 {halo}" for dx, dy in ((0.25, 0.25), (-0.25, 0.25), (0.25, -0.25), (-0.25, -0.25), (0.6, 0.6)))
    return (f"<div class='sfx' style=\"left:{x0 + 4:.1f}mm;top:{y0 + 3:.1f}mm;{_font_css(r)}font-size:{size:.2f}mm;"
            f"color:{ink};text-shadow:{shadow}\">{_esc(text)}</div>")


def _font_css(r: T.RoleFont) -> str:
    return f"font-family:{r.stack};font-weight:{r.weight};" + ("font-style:italic;" if r.italic else "")


def _luma(h: str) -> float:
    r, g, b = _hex_to_rgb01(h)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


SFX_INK = {"rising": "#f2ede3", "peak": "#f2c45a", "ego": "#b3261e", "knowledge": "#d4a017", "voice": "#5a3a1a"}


def _measure(text: str, r: T.RoleFont, size: float, lh: float, w: float, pad: tuple[float, float]) -> float:
    lines = T.wrap_lines(text, r.face, size, w - 2 * pad[1])
    return len(lines) * size * lh + 2 * pad[0] + 0.6


def _caption_html(p: PanelView, lang: str, poly: list[Point], canvas: CanvasView, opts: RenderOptions, ty: T.TypeSpec | None = None, img: ImageInfo | None = None,
                  occupied: list | None = None, papers: set | None = None) -> str:
    ty = ty or T.resolve()
    cap = p.caption_hi if lang == "hi" else p.caption_en
    bal = p.balloon_hi if lang == "hi" else p.balloon_en
    if lang == "hi" and not cap and p.caption_en:
        cap = "[हिंदी अनुवाद लंबित] " + p.caption_en
    if lang == "hi" and not bal and p.balloon_en:
        bal = "[हिंदी] " + p.balloon_en
    x0, y0, x1, y1 = _bbox(poly)
    x0, y0, x1, y1 = max(x0, 0.0), max(y0, 0.0), min(x1, PAGE_W), min(y1, PAGE_H)
    w = x1 - x0
    lh = ty.line_height
    max_w = PAGE_W - 4
    seed = p.number * 7919
    parts = []
    inset = (p.shape or {}).get("kind") == "inset"
    if cap:
        kind = CO.resolve_kind(p.callout_shape, ty.callout_shape, p.text_state, inset=inset)
        pad = (1.8, 2.4) if kind == "oval_vignette" else ((3.2, 3.6) if kind == "cartouche" else CAP_PAD)
        r = ty.role("narration", lang)
        size = ty.caption_mm(lang)
        natural = T.text_width(cap, r.face, size) + 2 * pad[1] + 1
        cw = min(max(CAP_MIN_W, natural), max(CAP_MIN_W, 0.75 * w), max_w)
        # long text: widen (up to the shard, then the page) before letting the box grow tall over the art
        while cw < min(max(w - 4, CAP_MIN_W), max_w) and _measure(cap, r, size, lh, cw, pad) > max(22.0, (y1 - y0) * 0.45):
            cw = min(cw + 6, max(w - 4, CAP_MIN_W), max_w)
        h = _measure(cap, r, size, lh, cw, pad)
        # art guard: a caption may cover at most ~33% of its shard; long narration steps its type down (to 0.7x)
        # rather than burying the picture
        shard_area = max(1.0, (x1 - x0) * (y1 - y0))
        steps = 0
        while cw * h > 0.33 * shard_area and steps < 4 and (p.shape or {}).get("kind") != "inset":
            size *= 0.92
            natural = T.text_width(cap, r.face, size) + 2 * pad[1] + 1
            cw = min(max(CAP_MIN_W, natural), max(CAP_MIN_W, 0.75 * w), max_w)
            h = _measure(cap, r, size, lh, cw, pad)
            steps += 1
        left = max(2.0, min(x0 + 3, PAGE_W - 2 - cw))
        if (p.shape or {}).get("kind") == "inset":  # a vignette's caption sits on the parchment just below the oval
            left = max(2.0, min(PAGE_W - cw - 2, (x0 + x1) / 2 - cw / 2))
            top = max(2.0, min(y1 + 2.5, PAGE_H - 2.5 - h))
        else:
            top = max(2.0, min(y1 - 3 - h, PAGE_H - 2.5 - h))  # bottom-left of the shard, never off the trim
        sh = CO.build(kind, cw, h, seed, p.text_state)
        left, top = _place(left, top, sh)
        paper = CO.paper_for(kind, p.text_state)
        ox, oy = CO.tile_offset(seed)
        col = callout_colours(p, "caption", (left, top, left + cw, top + h), canvas, ty, img, paper, (ox + pad[1], oy + pad[0], cw - 2 * pad[1], h - 2 * pad[0]))
        if col.get("fill") and papers is not None:
            papers.add(paper)
        if occupied is not None:
            L_, T_, R_, B_ = sh.overhang
            occupied.append((left - L_, top - T_, left + cw + R_, top + h + B_ + (4.5 if kind == "bubble" else 0)))
        parts.append(_callout("cap", left, top, sh, col, _font_css(r), size, lh, cap, pad, opts, f"c{p.number}", (ox, oy)))
    if bal:
        r = ty.role("dialogue", lang)
        size = ty.balloon_mm(lang)
        natural = T.text_width(bal, r.face, size) + 2 * BAL_PAD[1] + 1
        bw = min(max(38.0, natural), max(38.0, 0.6 * w), max_w)
        while bw < min(max(w - 4, 38.0), max_w) and _measure(bal, r, size, max(1.2, lh - 0.04), bw, BAL_PAD) > max(20.0, (y1 - y0) * 0.35):
            bw = min(bw + 6, max(w - 4, 38.0), max_w)
        bh = _measure(bal, r, size, max(1.2, lh - 0.04), bw, BAL_PAD)
        steps = 0
        while bw * bh > 0.28 * max(1.0, (x1 - x0) * (y1 - y0)) and steps < 4:
            size *= 0.92
            bw = min(max(38.0, T.text_width(bal, r.face, size) + 2 * BAL_PAD[1] + 1), max(38.0, 0.6 * w), max_w)
            bh = _measure(bal, r, size, max(1.2, lh - 0.04), bw, BAL_PAD)
            steps += 1
        left = min(max(2.0, x1 - 3 - bw), PAGE_W - 2 - bw)
        top = max(2.0, min(y0 + 3, PAGE_H - 7 - bh))
        bkind = CO.resolve_kind(p.balloon_shape, ty.balloon_shape, p.text_state, balloon=True)
        sh = CO.build(bkind, bw, bh, seed + 1, p.text_state, tail_x=bw * 0.22)
        left, top = _place(left, top, sh)
        paper = "dark" if p.text_state == "ego" else "light"
        ox, oy = CO.tile_offset(seed + 1)
        col = callout_colours(p, "balloon", (left, top, left + bw, top + bh), canvas, ty, img, paper, (ox + BAL_PAD[1], oy + BAL_PAD[0], bw - 2 * BAL_PAD[1], bh - 2 * BAL_PAD[0]))
        if col.get("fill") and papers is not None:
            papers.add(paper)
        if occupied is not None:
            L_, T_, R_, B_ = sh.overhang
            occupied.append((left - L_, top - T_, left + bw + R_, top + bh + B_))
        parts.append(_callout("bal", left, top, sh, col, _font_css(r), size, max(1.2, lh - 0.04), bal, BAL_PAD, opts, f"b{p.number}", (ox, oy)))
    parts.append(_sfx_html(p, poly, canvas, ty))
    return "".join(parts)


def used_fonts(page: PageView, lang: str) -> list[T.RoleFont]:
    """The faces this page draws with (narration always: the folio is set in it)."""
    ty = page.type
    out = [ty.role("narration", lang)]
    if page.is_opener and page.title:
        out.append(ty.role("title", lang))
        epi = page.title.epigraph_hi or page.title.epigraph if lang == "hi" else page.title.epigraph
        if epi:
            out.append(ty.role("narration", lang, italic=True))
    if any((p.balloon_hi or p.balloon_en) if lang == "hi" else p.balloon_en for p in page.panels):
        out.append(ty.role("dialogue", lang))
    for p in page.panels:
        if (p.sfx or "").strip():
            out.append(ty.sfx(p.sfx))
    for f in {it.font for it in page.manuscript_items if it.kind == "verse"}:  # call after page_html
        font = T.FONTS.get(f)
        if font:
            out.append(T.RoleFont(font, 400))
    return out


def _image_box(bbox: tuple[float, float, float, float], focal: dict[str, float], img_ar: float | None) -> tuple[float, float, float, float]:
    """The <image> x/y/width/height inside the clip for a focal pan/zoom: the box covers the bbox at `scale`, and the
    focal point (fractions of the image) is brought toward the bbox centre, clamped so the box still covers it."""
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    s = focal["scale"]
    # the box that 'slice' would use: aspect of the image, covering the bbox
    if img_ar:
        if w / h > img_ar:
            bw, bh = w, w / img_ar
        else:
            bw, bh = h * img_ar, h
    else:
        bw, bh = w, h
    bw, bh = bw * s, bh * s
    bx = x0 + w / 2 - focal["x"] * bw
    by = y0 + h / 2 - focal["y"] * bh
    bx = min(x0, max(x1 - bw, bx))
    by = min(y0, max(y1 - bh, by))
    return bx, by, bw, bh


def _title_block_html(t: TitleBlock, lang: str, canvas: CanvasView, opts: RenderOptions, ty: T.TypeSpec | None = None) -> str:
    ty = ty or T.resolve()
    ink = canvas.ink if canvas.paper_is_gutter else ("#e8dcc0" if canvas.gutter != "paper" else canvas.ink)
    if lang == "hi":
        book = t.book_title_hi or t.book_title
        vol = t.volume_title_hi or t.volume_title
        chap = t.chapter_title_hi or t.chapter_title
        epi = t.epigraph_hi or t.epigraph
    else:
        book, vol, chap, epi = t.book_title, t.volume_title, t.chapter_title, t.epigraph
    num = f"{'अध्याय' if lang == 'hi' else 'Chapter'} {t.chapter_number}" if t.chapter_number else ""
    tr, er = ty.role("title", lang), ty.role("narration", lang, italic=True)
    width = PAGE_W - 2 * (MARGIN + 4)
    avail = OPENER_TOP - MARGIN - 4
    sz = {k: ty.title_mm(k) for k in T.TITLE_MM}

    def est(k: float) -> float:  # the block's height at scale k (lines x size x leading, plus rule and ornament)
        h = 0.0
        for part, text, face in (("book", book.upper(), tr.face), ("vol", vol.upper(), tr.face), ("chapnum", num, tr.face), ("chap", chap, tr.face), ("epi", epi, er.face)):
            if text:
                lines = len(T.wrap_lines(text, face, sz[part] * k, width * (0.8 if part in ("book", "vol") else 0.95)))
                h += lines * sz[part] * k * 1.18 + 0.8
        return h + 3.4 + 7.5

    k = 1.0
    while k > 0.6 and est(k) > avail:
        k -= 0.04
    s = {p: v * k for p, v in sz.items()}
    compass = (
        f"<svg class='compass' viewBox='-10 -10 20 20' width='7mm' height='7mm'><g fill='none' stroke='{ink}' stroke-width='0.5'>"
        "<circle r='8.5'/><circle r='5.5'/><path d='M0,-9 L1.6,-1.6 L9,0 L1.6,1.6 L0,9 L-1.6,1.6 L-9,0 L-1.6,-1.6 Z'/>"
        "<path d='M0,-6 L0,6 M-6,0 L6,0' stroke-width='0.3'/></g></svg>"
    )
    rule = f"<div class='rule' style='border-color:{ink}'></div>"
    tf = _font_css(tr)
    return (
        f"<div class='title' style=\"color:{ink};{tf}\">"
        f"<div class='book' style='font-size:{s['book']:.2f}mm'>{_esc(book).upper()}</div>"
        + (f"<div class='vol' style='font-size:{s['vol']:.2f}mm'>{_esc(vol).upper()}</div>" if vol else "")
        + rule
        + (f"<div class='chapnum' style='font-size:{s['chapnum']:.2f}mm'>{_esc(num)}</div>" if num else "")
        + (f"<div class='chap' style='font-size:{s['chap']:.2f}mm'>{_esc(chap)}</div>" if chap else "")
        + (f"<div class='epi' style=\"{_font_css(er)}font-size:{s['epi']:.2f}mm\">{_esc(epi)}</div>" if epi else "")
        + f"<div class='ornament'>{compass}</div></div>"
    )


def _marginalia_svg(items: list[MarginaliaView], canvas: CanvasView, opts: RenderOptions) -> str:
    """Silhouette PNGs under the shards, tinted via feColorMatrix (per item, else the canvas's marginalia ink).
    Each sits in a w x w box (meet), rotated about its centre — the same box the shard editor draws."""
    if not items:
        return ""
    ms = canvas.marginalia_style or {}
    filters: dict[str, str] = {}
    out: list[str] = []
    for m in items:
        src = png_data(m.path) if (opts.embed or not m.url) else m.url
        if not src:
            continue
        if m.tint == "none":  # already in its own colours (a QR on its parchment plate): no ink filter
            h = m.h_mm or m.w_mm
            out.append(f"<image href='{src}' x='{m.x_mm:.2f}' y='{m.y_mm:.2f}' width='{m.w_mm:.2f}' height='{h:.2f}' preserveAspectRatio='none' opacity='{m.opacity if m.opacity is not None else 1:.2f}'/>")
            continue
        tint = m.tint or ms.get("tint") or canvas.ink
        fid = filters.get(tint)
        if fid is None:
            fid = f"ink{len(filters)}"
            r, g, b = _hex_to_rgb01(tint)
            filters[tint] = fid
            out.insert(0, f"<filter id='{fid}'><feColorMatrix type='matrix' values='0 0 0 0 {r:.3f} 0 0 0 0 {g:.3f} 0 0 0 0 {b:.3f} 0 0 0 1 0'/></filter>")
        h = m.h_mm or m.w_mm
        op = m.opacity if m.opacity is not None else float(ms.get("opacity", 0.85))
        rot = f" transform='rotate({m.rotation:.1f} {m.x_mm + m.w_mm / 2:.2f} {m.y_mm + h / 2:.2f})'" if m.rotation else ""
        out.append(f"<image href='{src}' x='{m.x_mm:.2f}' y='{m.y_mm:.2f}' width='{m.w_mm:.2f}' height='{h:.2f}' preserveAspectRatio='xMidYMid meet' filter='url(#{fid})' opacity='{op:.2f}'{rot}/>")
    return f"<g class='marginalia'>{''.join(out)}</g>"


def balance_of(page: PageView) -> dict[str, float]:
    """Measured split of the trim area: image / clean parchment / ink marginalia, as 0-1 fractions (target 70/20/10)."""
    trim = PAGE_W * PAGE_H
    image = 0.0
    for p in page.panels:
        poly = clip_to_rect(p.polygon, 0, 0, PAGE_W, PAGE_H)
        image += _area(poly)
    image = min(image, trim)
    marg = 0.0
    for m in page.marginalia:
        h = m.h_mm or m.w_mm
        marg += m.w_mm * h * 0.35  # line drawings are mostly empty: count about a third of the box as ink
    marg = min(marg, trim - image)
    paper = max(0.0, trim - image - marg)
    return {"image": round(image / trim, 3), "parchment": round(paper / trim, 3), "ink": round(marg / trim, 3)}


def page_html(page: PageView, canvas: CanvasView, opts: RenderOptions) -> str:
    """One page as a <section>. The SVG holds the shards; the overlay holds captions, the title block and the folio."""
    lang, pr = opts.lang, opts.print
    ty = page.type
    panels = sorted(page.panels, key=lambda p: (p.z, p.n))
    look = page_look_for(page.panels, page.beat)
    single_plate = len(panels) == 1 and panels[0].kind == "plate"
    paper_gutter = canvas.paper_is_gutter
    ink = canvas.ink
    pid = page.number
    clips, imgs, caps, veins, fibres, hatch = [], [], [], [], [], []
    occupied: list = []
    papers: set = set()
    painted = canvas.finish == "painted"
    look_beat = look.beat
    dissolve = painted and (page.ink_dissolve if page.ink_dissolve is not None else look_beat == "calm")
    polys = {p.number: p.polygon for p in panels}
    for p in panels:
        poly = polys[p.number]
        if len(poly) < 3:
            continue
        pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in poly)
        col = panel_colour(p.text_state)
        feather = p.edge == "feathered" and p.kind != "plate"
        uid = f"{pid}_{p.number}"
        clips.append(
            f"<filter id='f{uid}' color-interpolation-filters='sRGB'><feColorMatrix type='saturate' values='{col.saturation}'/>"
            f"<feComponentTransfer><feFuncR type='linear' slope='{col.contrast}' intercept='{(1 - col.contrast) / 2:.3f}'/>"
            f"<feFuncG type='linear' slope='{col.contrast}' intercept='{(1 - col.contrast) / 2:.3f}'/>"
            f"<feFuncB type='linear' slope='{col.contrast}' intercept='{(1 - col.contrast) / 2:.3f}'/></feComponentTransfer></filter>"
        )
        # the clipPath is always emitted (the editor and the manifest read it); feathered shards mask with a blurred copy
        clips.append(f"<clipPath id='c{uid}' clipPathUnits='userSpaceOnUse'><polygon points='{pts}'/></clipPath>")
        rim = painted and p.kind != "plate" and p.shape.get("kind") not in ("bleed", "inset", "hex")
        if feather:
            clips.append(f"<mask id='m{uid}' maskUnits='userSpaceOnUse'><polygon points='{pts}' fill='white' filter='url(#blur{pid})'/></mask>")
        elif rim:
            dz = _dissolve_side(poly) if dissolve else None
            grad = ""
            fillm = "white"
            if dz:
                (gx1, gy1), (gx2, gy2) = dz
                grad = (f"<linearGradient id='dg{uid}' gradientUnits='userSpaceOnUse' x1='{gx1:.2f}' y1='{gy1:.2f}' x2='{gx2:.2f}' y2='{gy2:.2f}'>"
                        "<stop offset='0' stop-color='#262626'/><stop offset='0.55' stop-color='#bdbdbd'/><stop offset='1' stop-color='white'/></linearGradient>"
                        f"<linearGradient id='hg{uid}' gradientUnits='userSpaceOnUse' x1='{gx1:.2f}' y1='{gy1:.2f}' x2='{gx2:.2f}' y2='{gy2:.2f}'>"
                        "<stop offset='0' stop-color='white'/><stop offset='0.7' stop-color='#3a3a3a'/><stop offset='1' stop-color='black'/></linearGradient>"
                        f"<mask id='hm{uid}' maskUnits='userSpaceOnUse'><rect x='{-BLEED}' y='{-BLEED}' width='{PAGE_W + 2 * BLEED}' height='{PAGE_H + 2 * BLEED}' fill='url(#hg{uid})'/></mask>")
                fillm = f"url(#dg{uid})"
            clips.append(f"{grad}<mask id='m{uid}' maskUnits='userSpaceOnUse' x='{-BLEED}' y='{-BLEED}' width='{PAGE_W + 2 * BLEED}' height='{PAGE_H + 2 * BLEED}'>"
                         f"<polygon points='{pts}' fill='{fillm}' filter='url(#torn{pid})'/></mask>")
            fibres.append(f"<polygon points='{pts}' fill='none' stroke='#f3e6c6' stroke-opacity='0.9' stroke-width='1.25' stroke-linejoin='round' filter='url(#torn{pid})'/>")
            if dz:
                hatch.append(f"<g mask='url(#hm{uid})' clip-path='url(#c{uid})' opacity='0.8'><rect x='{-BLEED}' y='{-BLEED}' width='{PAGE_W + 2 * BLEED}' height='{PAGE_H + 2 * BLEED}' fill='url(#hatch{pid})'/></g>")
            feather = True  # cut through the mask
        bbox = _bbox(poly)
        img_path = p.image_path
        if p.image_group:  # revelation: one illustration breaking across several shards
            members = [q for q in panels if q.image_group == p.image_group]
            allpts = [pt for q in members for pt in polys[q.number]]
            ubox = _bbox(allpts)
            lead = max(members, key=lambda q: _area(polys[q.number]))
            lead_img = lead.image_path
            union_ar = (ubox[2] - ubox[0]) / max(1e-6, (ubox[3] - ubox[1]))
            img_ar = _image_aspect(lead_img)
            if img_ar is not None and 0.6 < union_ar / img_ar < 1.7:
                bbox, img_path = ubox, lead_img
        lead_url = p.image_url if img_path is p.image_path else next((q.image_url for q in panels if q.image_path == img_path), None)
        src = img_data(img_path) if (opts.embed or not lead_url) else lead_url
        cut = f"mask='url(#m{uid})'" if feather else f"clip-path='url(#c{uid})'"
        info = ImageInfo(img_path if src else None, _image_box(bbox, p.focal, _image_aspect(img_path)) if src else None)
        if src:
            bx, by, bw, bh = _image_box(bbox, p.focal, _image_aspect(img_path))
            imgs.append(
                f"<g {cut}><image href='{src}' x='{bx:.2f}' y='{by:.2f}' width='{bw:.2f}' height='{bh:.2f}' "
                f"preserveAspectRatio='xMidYMid slice' filter='url(#f{uid})'/>"
                + (f"<polygon points='{pts}' fill='{col.tint}' fill-opacity='{col.tint_opacity}'/>" if col.tint else "") + "</g>"
            )
        else:
            fill = "#1b1b1f" if not paper_gutter else "rgba(58,45,26,0.12)"
            txt = "#666" if not paper_gutter else ink
            imgs.append(f"<g {cut}><polygon points='{pts}' fill='{fill}'/><text x='{(bbox[0] + bbox[2]) / 2:.1f}' y='{(bbox[1] + bbox[3]) / 2:.1f}' fill='{txt}' font-size='3' text-anchor='middle'>panel {p.n} · no take yet</text></g>")
        # edges: sepia ink edge on paper canvases (never black), gold rim on hex, ink rim on insets, crimson veins on ego pages
        if p.kind != "plate" and p.shape.get("kind") != "bleed":
            if paper_gutter and not rim:
                veins.append(f"<polygon points='{pts}' fill='none' stroke='{ink}' stroke-opacity='0.85' stroke-width='0.3' stroke-linejoin='round'/>")
            if look.crimson_veins:
                veins.append(f"<polygon points='{pts}' fill='none' stroke='#b3261e' stroke-opacity='0.55' stroke-width='0.25'/>")
        if p.shape.get("kind") == "inset":
            veins.append(f"<polygon points='{pts}' fill='none' stroke='{ink}' stroke-width='0.6' stroke-linejoin='round'/>")
        if p.edge == "rim" and p.shape.get("kind") == "hex":
            veins.append(f"<polygon points='{pts}' fill='none' stroke='#f2c45a' stroke-opacity='0.35' stroke-width='1.2' filter='url(#blur{pid})'/>"
                         f"<polygon points='{pts}' fill='none' stroke='#ffd977' stroke-opacity='0.9' stroke-width='0.35'/>")
        caps.append(_caption_html(p, lang, poly, canvas, opts, ty, info, occupied, papers))
    blur = f"<filter id='blur{pid}' x='-5%' y='-5%' width='110%' height='110%'><feGaussianBlur stdDeviation='0.45'/></filter>"
    if painted:  # torn paper: the shard edge displaced by fibrous noise, then softened (a 0.8-1.5 mm dissolve)
        blur += (f"<filter id='torn{pid}' filterUnits='userSpaceOnUse' x='{-BLEED}' y='{-BLEED}' width='{PAGE_W + 2 * BLEED}' height='{PAGE_H + 2 * BLEED}'>"
                 f"<feTurbulence type='fractalNoise' baseFrequency='0.62' numOctaves='3' seed='{page.seed % 97}' result='n'/>"
                 "<feDisplacementMap in='SourceGraphic' in2='n' scale='2.2' xChannelSelector='R' yChannelSelector='G' result='d'/>"
                 "<feGaussianBlur in='d' stdDeviation='0.38'/></filter>"
                 f"<pattern id='hatch{pid}' patternUnits='userSpaceOnUse' width='0.95' height='0.95' patternTransform='rotate(38)'>"
                 f"<line x1='0' y1='0' x2='0' y2='0.95' stroke='{ink}' stroke-width='0.17' stroke-opacity='0.85'/></pattern>")
    ms_svg = _manuscript(page, panels, polys, occupied, opts, single_plate)
    # background: paper canvases show the paper (texture for screen, nothing for print); others fill the gutter colour
    if single_plate:
        bg = ""
    elif paper_gutter:
        bg = ""
    else:
        gut = canvas.gutter if canvas.gutter and canvas.gutter != "paper" else look.gutter_colour
        bg = f"<rect x='{-BLEED}' y='{-BLEED}' width='{PAGE_W + 2 * BLEED}' height='{PAGE_H + 2 * BLEED}' fill='{gut}'/>"
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{PAGE_W + 2 * BLEED}mm' height='{PAGE_H + 2 * BLEED}mm' "
        f"viewBox='{-BLEED} {-BLEED} {PAGE_W + 2 * BLEED} {PAGE_H + 2 * BLEED}'><defs>{blur}{''.join(clips)}</defs>"
        f"{bg}{ms_svg}{_marginalia_svg(page.marginalia, canvas, opts)}{''.join(fibres)}{''.join(imgs)}{''.join(hatch)}{''.join(veins)}{_marginalia_svg(page.overlays, canvas, opts)}{_crop_marks() if pr else ''}</svg>"
    )
    folio_col = ink if paper_gutter else "#8a8580"
    folio = f"<div class='folio' style=\"color:{folio_col};{_font_css(ty.role('narration', lang))}font-size:{2.4 * ty.size:.2f}mm\">{page.number}</div>"
    title = _title_block_html(page.title, lang, canvas, opts, ty) if (page.is_opener and page.title) else ""
    texture = ""
    show_paper = not pr or opts.print_texture
    if show_paper and canvas.paper_texture is not None and canvas.paper_texture.exists():
        tsrc = png_data(canvas.paper_texture) if (opts.embed or not canvas.texture_url) else canvas.texture_url
        texture = f"background-image:url({tsrc});background-size:100% 100%;"
    elif not pr and not paper_gutter:
        texture = f"background:{canvas.gutter};"
    elif not pr:
        texture = "background:#efe4c9;"
    defs = CO.scrap_defs(papers, opts.embed)
    return f"<section class='page' data-page='{page.number}' style=\"{texture}\">{svg}<div class='overlay'>{defs}{title}{''.join(caps)}{folio}</div></section>"


def painted_page_html(number: int, image_path: Path | None, image_url: str | None, opts: RenderOptions) -> str:
    """A painted page (painted-page mode): the image model's whole page is the artifact. Placed full-bleed — it covers
    the trim plus the 3 mm bleed on every side (slice-fit, centred), crop marks in print. No folio or typeset text:
    the lettering is in the painting and has been proofread."""
    src = img_data(image_path, 95) if (opts.embed or not image_url) else image_url
    W, H = PAGE_W + 2 * BLEED, PAGE_H + 2 * BLEED
    img = (f"<image class='painted' x='{-BLEED}' y='{-BLEED}' width='{W}' height='{H}' preserveAspectRatio='xMidYMid slice' href='{src}'/>" if src else
           f"<rect x='{-BLEED}' y='{-BLEED}' width='{W}' height='{H}' fill='#efe4c9'/>")
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}mm' height='{H}mm' viewBox='{-BLEED} {-BLEED} {W} {H}'>"
           f"{img}{_crop_marks() if opts.print else ''}</svg>")
    return f"<section class='page painted-page' data-page='{number}' data-mode='painted'>{svg}</section>"


def _dissolve_side(poly: list[Point]) -> tuple[Point, Point] | None:
    """The gradient (outer point -> 16 mm inward) on the shard side nearest the page edge, for the ink dissolve."""
    x0, y0, x1, y1 = _bbox(poly)
    x0, y0, x1, y1 = max(x0, 0.0), max(y0, 0.0), min(x1, PAGE_W), min(y1, PAGE_H)
    sides = {"l": x0, "r": PAGE_W - x1, "t": y0, "b": PAGE_H - y1}
    side = min(sides, key=sides.get)
    if sides[side] > 30:
        return None
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    depth = min(16.0, 0.35 * ((x1 - x0) if side in "lr" else (y1 - y0)))
    return {"l": ((x0, cy), (x0 + depth, cy)), "r": ((x1, cy), (x1 - depth, cy)), "t": ((cx, y0), (cx, y0 + depth)), "b": ((cx, y1), (cx, y1 - depth))}[side]


def _manuscript(page: PageView, panels: list[PanelView], polys: dict[int, list[Point]], occupied: list, opts: RenderOptions, single_plate: bool) -> str:
    """Place (or take the author's placement of) the verses and figures in the free parchment; store them on the page."""
    spec = page.manuscript
    page.manuscript_items = []
    if spec is None or single_plate:
        return ""
    if spec.auto:
        nv, nf = MS.DENSITY.get(spec.density, (0, 0))
        if not (nv or nf):
            return ""
        grid = MS.Grid(PAGE_W, PAGE_H)
        for p in panels:
            if p.kind == "plate" or (p.shape or {}).get("kind") == "bleed":
                return ""
            grid.polygon(clip_to_rect(polys[p.number], 0, 0, PAGE_W, PAGE_H))
        for r in occupied:
            grid.rect(r)
        if page.is_opener and page.title:  # only the centred title text, so the parchment either side stays free
            tr = page.type.role("title", "en")
            t = page.title
            spacing = {"book": 0.3, "vol": 0.22, "chap": 0.04}  # the title block's letter-spacing (em)
            widest = max(T.text_width(x, tr.face, page.type.title_mm(k)) + len(x) * spacing[k] * page.type.title_mm(k)
                         for k, x in (("book", t.book_title.upper()), ("vol", t.volume_title.upper()), ("chap", t.chapter_title)) if x)
            half = min(PAGE_W / 2 - MARGIN - 4, widest / 2 + 3)
            grid.rect((PAGE_W / 2 - half, MARGIN, PAGE_W / 2 + half, OPENER_TOP - 3))
        for m in page.marginalia + page.overlays:
            grid.rect((m.x_mm, m.y_mm, m.x_mm + m.w_mm, m.y_mm + (m.h_mm or m.w_mm)))
        grid.rect((PAGE_W - 12, PAGE_H - 8, PAGE_W, PAGE_H), 0)  # the folio
        vs, fs = MS.choose(spec.tags | {"any"}, page.seed * 1000 + page.number)
        items = MS.place(grid, vs, fs, page.seed * 1000 + page.number, spec.font, spec.opacity, nv, nf)
    else:
        items = MS.from_stored(spec.stored, spec.font, spec.opacity)
    page.manuscript_items = items
    return MS.layer_svg(items, opts.embed, spec.rubric)


def _crop_marks() -> str:
    m, L = 1.0, BLEED - 0.6  # marks sit in the bleed, 1 mm clear of the trim
    lines = []
    for x in (0, PAGE_W):
        for y in (0, PAGE_H):
            sx, sy = (-1 if x == 0 else 1), (-1 if y == 0 else 1)
            lines.append(f"<line x1='{x + sx * m}' y1='{y}' x2='{x + sx * (m + L)}' y2='{y}'/>")
            lines.append(f"<line x1='{x}' y1='{y + sy * m}' x2='{x}' y2='{y + sy * (m + L)}'/>")
    return f"<g stroke='#000' stroke-width='0.15' opacity='0.9'>{''.join(lines)}</g>"


def book_css(opts: RenderOptions, faces: set | None = None) -> str:
    """The book's CSS. @font-face rules only for `faces` ((family, Face) pairs, from used_fonts): embedded as data
    URIs for PDFs and artifacts, else /api/fonts/{file} URLs (long-cached) for the live render."""
    body_bg = "transparent" if opts.print else "#2a2622"
    shadow = "" if opts.print else ".cap>svg.co,.bal>svg.co{filter:drop-shadow(0 0.25mm 0.5mm rgba(0,0,0,.35)) drop-shadow(0 0 1mm rgba(0,0,0,.18))}"
    return f"""{T.font_face_css(faces or set(), opts.embed)}
@page {{ size: {PAGE_W + 2 * BLEED}mm {PAGE_H + 2 * BLEED}mm; margin: 0; }}
html,body{{margin:0;padding:0;background:{body_bg}}}
.page{{position:relative;width:{PAGE_W + 2 * BLEED}mm;height:{PAGE_H + 2 * BLEED}mm;page-break-after:always;overflow:hidden;background-color:{'transparent' if opts.print else '#efe4c9'}}}
.page > svg{{position:absolute;left:0;top:0}}
.overlay{{position:absolute;left:{BLEED}mm;top:{BLEED}mm;width:{PAGE_W}mm;height:{PAGE_H}mm}}
.cap,.bal{{position:absolute;box-sizing:border-box;display:flex;align-items:center;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.bal{{justify-content:center;text-align:center}}
.cap>svg.co,.bal>svg.co{{position:absolute;overflow:visible;pointer-events:none}}
.cap>span,.bal>span{{position:relative}}
{shadow}
.sfx{{position:absolute;line-height:1;white-space:nowrap;letter-spacing:0.02em;transform:rotate(-7deg);transform-origin:0 0}}
.folio{{position:absolute;bottom:2.5mm;right:4mm}}
.title{{position:absolute;left:{MARGIN + 4}mm;right:{MARGIN + 4}mm;top:{MARGIN + 1}mm;height:{OPENER_TOP - MARGIN - 4}mm;text-align:center;letter-spacing:0.08em;line-height:1.18;display:flex;flex-direction:column;align-items:center;justify-content:center}}
.title .book{{letter-spacing:0.3em}}
.title .vol{{letter-spacing:0.22em;margin-top:0.8mm;opacity:.85}}
.title .rule{{border-top:0.25mm solid;width:40mm;margin:1.4mm auto}}
.title .chapnum{{letter-spacing:0.25em;opacity:.8}}
.title .chap{{letter-spacing:0.04em;margin-top:0.4mm}}
.title .epi{{letter-spacing:0;margin-top:1.2mm;opacity:.9}}
.title .ornament{{margin-top:0.8mm;line-height:0}}
"""


FONT_CSS_URL = "/api/fonts.css"  # legacy (the studio's original two Devanagari faces); pages now carry their own @font-face


def book_html(pages: list[str], title: str, opts: RenderOptions, faces: set | None = None) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{_esc(title)}</title><style>\n{book_css(opts, faces)}</style></head><body>{''.join(pages)}</body></html>"


def render_pdf(html_text: str, out_pdf: Path, progress=None) -> Path:
    """HTML -> PDF. Order: the studio's own PDF engine if already installed (the Mac app's normal path) ->
    Playwright Chromium (source/dev) -> an installed Chrome/Chromium -> download the studio's PDF engine once.
    DHARMA_PDF_ENGINE=shell forces the studio engine."""
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    html_path = out_pdf.with_suffix(".html")
    html_path.write_text(html_text, encoding="utf-8")
    import glob
    import os
    import shutil

    from engine import pdf_engine

    force_shell = os.environ.get("DHARMA_PDF_ENGINE") == "shell"
    shell = pdf_engine.installed()
    if shell or force_shell:
        pdf_engine.print_to_pdf(shell or pdf_engine.ensure(progress), html_path, out_pdf)
        return out_pdf
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM") or next(iter(sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome") + glob.glob("/opt/pw-browsers/chromium*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium"))), None)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                if not exe:
                    raise
                browser = p.chromium.launch(executable_path=exe)
            pg = browser.new_page()
            pg.goto(html_path.resolve().as_uri())
            pg.wait_for_timeout(300)
            pg.pdf(path=str(out_pdf), width=f"{PAGE_W + 2 * BLEED}mm", height=f"{PAGE_H + 2 * BLEED}mm", print_background=True, prefer_css_page_size=True)
            browser.close()
        return out_pdf
    except Exception:  # noqa: BLE001
        for cand in (exe, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
                     shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("chrome")):
            if cand and Path(cand).exists():
                pdf_engine.print_to_pdf(Path(cand), html_path, out_pdf)
                return out_pdf
    # nothing installed: fetch the studio's own engine once, then use it from now on
    pdf_engine.print_to_pdf(pdf_engine.ensure(progress), html_path, out_pdf)
    return out_pdf


def layout_manifest(page: PageView) -> dict[str, Any]:
    """Polygons in mm for the layout file (Affinity/InDesign) plus the measured image/paper/marginalia balance."""
    look = page_look_for(page.panels, page.beat)
    return {"page": page.number, "trim_mm": [PAGE_W, PAGE_H], "bleed_mm": BLEED, "look": look.__dict__, "balance": balance_of(page), "panels": [
        {"panel": p.n, "number": p.number, "kind": p.kind, "state": p.text_state, "beat": panel_beat(p), "scale": p.scale, "image_group": p.image_group,
         "shape": p.shape, "caption_en": p.caption_en, "caption_hi": p.caption_hi, "balloon_en": p.balloon_en, "balloon_hi": p.balloon_hi, "speaker": p.speaker}
        for p in page.panels
    ]}
