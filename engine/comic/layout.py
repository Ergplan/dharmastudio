"""Page layout: shards and plates, bilingual captions on the intensity scale, rendered to HTML (and from there PDF).

Procedure
- A page's panels are split recursively by weight (the auto-cut); each cut is a slightly angled line with jitter, so
  the gutters read as fractures. Panels are polygons in mm on a 170 x 260 mm page (+3 mm bleed). Shapes are stored
  per panel once computed and edited by the author; the renderer only draws what it is given.
- Each polygon becomes an SVG clipPath over the panel's image (object-fit: cover with over-frame and a focal pan/zoom).
- Captions and balloons are typeset in HTML with the state's colours; Hindi uses Noto Serif Devanagari (captions) and
  Mukta (balloons), shaped correctly by Chromium. Playwright renders the PDF.
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
    seed: int = 7


@dataclass
class RenderOptions:
    lang: str = "en"
    paper: str = "screen"  # screen | print
    embed: bool = True  # data URIs (PDF, artifacts) vs served URLs (live UI)

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
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


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


def _caption_html(p: PanelView, lang: str, poly: list[Point], canvas: CanvasView, opts: RenderOptions) -> str:
    st = STATE_STYLE.get(p.text_state, STATE_STYLE["quiet"])
    cap = p.caption_hi if lang == "hi" else p.caption_en
    bal = p.balloon_hi if lang == "hi" else p.balloon_en
    if lang == "hi" and not cap and p.caption_en:
        cap = "[हिंदी अनुवाद लंबित] " + p.caption_en
    if lang == "hi" and not bal and p.balloon_en:
        bal = "[हिंदी] " + p.balloon_en
    x0, y0, x1, y1 = _bbox(poly)
    x0, y0, x1, y1 = max(x0, 0.0), max(y0, 0.0), min(x1, PAGE_W), min(y1, PAGE_H)
    w = x1 - x0
    cs = canvas.caption_style or {}
    parchment_boxes = canvas.paper_is_gutter  # paper canvases: sepia serif on lightly textured parchment boxes
    parts = []
    if cap:
        cw = min(max(w * 0.72, 40), 110)
        edge = st["edge"]
        extra = ""
        if edge == "fracture":
            extra = "clip-path:polygon(0 6%,3% 0,97% 2%,100% 10%,99% 94%,96% 100%,2% 98%,0 90%);"
        elif edge == "shard":
            extra = "clip-path:polygon(0 0,100% 4%,98% 100%,3% 96%);"
        elif edge == "glow":
            extra = "box-shadow:0 0 2.2mm rgba(212,160,23,.55);"
        elif edge == "torn":
            extra = "clip-path:polygon(0 4%,4% 0,30% 2%,55% 0,80% 3%,100% 1%,99% 96%,70% 100%,40% 97%,10% 100%,1% 95%);"
        border = "" if edge in ("none", "fracture", "shard", "glow", "torn") else f"border:{edge};"
        fam = "'DevSerif','Georgia',serif" if lang == "hi" else "'Georgia','Times New Roman',serif"
        size = "2.75mm" if lang == "hi" else "2.6mm"
        box, text = st["box"], st["text"]
        if parchment_boxes and st["box"] == "#efe4c9":
            text = cs.get("text", SEPIA)
            if opts.print:
                box = "transparent"  # the paper is the stock; only the ink frame prints
            else:
                box = cs.get("box", "rgba(239,228,201,0.55)")
            border = f"border:{cs.get('border', '0.2mm solid ' + SEPIA)};"
            if cs.get("textured", True) and not opts.print:
                extra += "background-image:repeating-linear-gradient(0deg,rgba(90,70,40,0.045) 0 0.3mm,transparent 0.3mm 0.9mm);"
        bottom = max(2.0, PAGE_H - y1 + 3)
        parts.append(
            f"<div class='cap' style=\"left:{x0 + 3:.1f}mm;bottom:{bottom:.1f}mm;width:{cw:.1f}mm;background:{box};color:{text};"
            f"font-family:{fam};font-size:{size};{border}{extra}\">{_esc(cap)}</div>"
        )
    if bal:
        bw = min(max(w * 0.55, 34), 80)
        fam = "'Mukta',sans-serif" if lang == "hi" else "'Helvetica Neue',Arial,sans-serif"
        ego = p.text_state == "ego"
        parts.append(
            f"<div class='bal' style=\"right:{max(2.0, PAGE_W - x1 + 3):.1f}mm;top:{y0 + 3:.1f}mm;width:{bw:.1f}mm;font-family:{fam};"
            f"{'background:#0b0b0d;color:#b3261e;border-color:#b3261e;' if ego else ''}\">{_esc(bal)}</div>"
        )
    return "".join(parts)


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


def _title_block_html(t: TitleBlock, lang: str, canvas: CanvasView, opts: RenderOptions) -> str:
    ink = canvas.ink if canvas.paper_is_gutter else ("#e8dcc0" if canvas.gutter != "paper" else canvas.ink)
    if lang == "hi":
        book = t.book_title_hi or t.book_title
        vol = t.volume_title_hi or t.volume_title
        chap = t.chapter_title_hi or t.chapter_title
        epi = t.epigraph_hi or t.epigraph
        fam = "'DevSerif','Georgia',serif"
    else:
        book, vol, chap, epi, fam = t.book_title, t.volume_title, t.chapter_title, t.epigraph, "'Georgia','Times New Roman',serif"
    num = f"{'अध्याय' if lang == 'hi' else 'Chapter'} {t.chapter_number}" if t.chapter_number else ""
    compass = (
        f"<svg class='compass' viewBox='-10 -10 20 20' width='9mm' height='9mm'><g fill='none' stroke='{ink}' stroke-width='0.5'>"
        "<circle r='8.5'/><circle r='5.5'/><path d='M0,-9 L1.6,-1.6 L9,0 L1.6,1.6 L0,9 L-1.6,1.6 L-9,0 L-1.6,-1.6 Z'/>"
        "<path d='M0,-6 L0,6 M-6,0 L6,0' stroke-width='0.3'/></g></svg>"
    )
    rule = f"<div class='rule' style='border-color:{ink}'></div>"
    return (
        f"<div class='title' style=\"color:{ink};font-family:{fam}\">"
        f"<div class='book'>{_esc(book).upper()}</div>"
        + (f"<div class='vol'>{_esc(vol).upper()}</div>" if vol else "")
        + rule
        + (f"<div class='chapnum'>{_esc(num)}</div>" if num else "")
        + (f"<div class='chap'>{_esc(chap)}</div>" if chap else "")
        + (f"<div class='epi'>{_esc(epi)}</div>" if epi else "")
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
    panels = sorted(page.panels, key=lambda p: (p.z, p.n))
    look = page_look_for(page.panels, page.beat)
    single_plate = len(panels) == 1 and panels[0].kind == "plate"
    paper_gutter = canvas.paper_is_gutter
    ink = canvas.ink
    pid = page.number
    clips, imgs, caps, veins = [], [], [], []
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
        if feather:
            clips.append(f"<mask id='m{uid}' maskUnits='userSpaceOnUse'><polygon points='{pts}' fill='white' filter='url(#blur{pid})'/></mask>")
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
            if paper_gutter:
                veins.append(f"<polygon points='{pts}' fill='none' stroke='{ink}' stroke-opacity='0.85' stroke-width='0.3' stroke-linejoin='round'/>")
            if look.crimson_veins:
                veins.append(f"<polygon points='{pts}' fill='none' stroke='#b3261e' stroke-opacity='0.55' stroke-width='0.25'/>")
        if p.shape.get("kind") == "inset":
            veins.append(f"<polygon points='{pts}' fill='none' stroke='{ink}' stroke-width='0.6' stroke-linejoin='round'/>")
        if p.edge == "rim" and p.shape.get("kind") == "hex":
            veins.append(f"<polygon points='{pts}' fill='none' stroke='#f2c45a' stroke-opacity='0.35' stroke-width='1.2' filter='url(#blur{pid})'/>"
                         f"<polygon points='{pts}' fill='none' stroke='#ffd977' stroke-opacity='0.9' stroke-width='0.35'/>")
        caps.append(_caption_html(p, lang, poly, canvas, opts))
    blur = f"<filter id='blur{pid}' x='-5%' y='-5%' width='110%' height='110%'><feGaussianBlur stdDeviation='0.45'/></filter>"
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
        f"{bg}{_marginalia_svg(page.marginalia, canvas, opts)}{''.join(imgs)}{''.join(veins)}{_crop_marks() if pr else ''}</svg>"
    )
    folio_col = ink if paper_gutter else "#8a8580"
    folio = f"<div class='folio' style='color:{folio_col}'>{page.number}</div>"
    title = _title_block_html(page.title, lang, canvas, opts) if (page.is_opener and page.title) else ""
    texture = ""
    if not pr and canvas.paper_texture is not None and canvas.paper_texture.exists():
        tsrc = png_data(canvas.paper_texture) if (opts.embed or not canvas.texture_url) else canvas.texture_url
        texture = f"background-image:url({tsrc});background-size:cover;"
    elif not pr and not paper_gutter:
        texture = f"background:{canvas.gutter};"
    elif not pr:
        texture = "background:#efe4c9;"
    return f"<section class='page' data-page='{page.number}' style=\"{texture}\">{svg}<div class='overlay'>{title}{''.join(caps)}{folio}</div></section>"


def _crop_marks() -> str:
    m, L = 1.0, BLEED - 0.6  # marks sit in the bleed, 1 mm clear of the trim
    lines = []
    for x in (0, PAGE_W):
        for y in (0, PAGE_H):
            sx, sy = (-1 if x == 0 else 1), (-1 if y == 0 else 1)
            lines.append(f"<line x1='{x + sx * m}' y1='{y}' x2='{x + sx * (m + L)}' y2='{y}'/>")
            lines.append(f"<line x1='{x}' y1='{y + sy * m}' x2='{x}' y2='{y + sy * (m + L)}'/>")
    return f"<g stroke='#000' stroke-width='0.15' opacity='0.9'>{''.join(lines)}</g>"


def book_css(opts: RenderOptions) -> str:
    body_bg = "transparent" if opts.print else "#2a2622"
    return f"""{font_css() if opts.embed else ""}
@page {{ size: {PAGE_W + 2 * BLEED}mm {PAGE_H + 2 * BLEED}mm; margin: 0; }}
html,body{{margin:0;padding:0;background:{body_bg}}}
.page{{position:relative;width:{PAGE_W + 2 * BLEED}mm;height:{PAGE_H + 2 * BLEED}mm;page-break-after:always;overflow:hidden;background-color:{'transparent' if opts.print else '#efe4c9'}}}
.page > svg{{position:absolute;left:0;top:0}}
.overlay{{position:absolute;left:{BLEED}mm;top:{BLEED}mm;width:{PAGE_W}mm;height:{PAGE_H}mm}}
.cap{{position:absolute;padding:1.6mm 2.2mm;line-height:1.32;box-sizing:border-box}}
.bal{{position:absolute;padding:1.8mm 2.4mm;background:#f6f1e6;color:#111;border:0.3mm solid #111;border-radius:3.5mm;font-size:2.7mm;line-height:1.3;box-sizing:border-box}}
.folio{{position:absolute;bottom:2.5mm;right:4mm;font:2.4mm 'Georgia',serif}}
.title{{position:absolute;left:{MARGIN + 4}mm;right:{MARGIN + 4}mm;top:{MARGIN + 2}mm;height:{OPENER_TOP - MARGIN - 6}mm;text-align:center;letter-spacing:0.08em}}
.title .book{{font-size:3.2mm;letter-spacing:0.3em}}
.title .vol{{font-size:2.4mm;letter-spacing:0.22em;margin-top:0.8mm;opacity:.85}}
.title .rule{{border-top:0.25mm solid;width:40mm;margin:1.6mm auto}}
.title .chapnum{{font-size:2.3mm;letter-spacing:0.25em;opacity:.8}}
.title .chap{{font-size:5.2mm;letter-spacing:0.04em;margin-top:0.6mm}}
.title .epi{{font-size:2.5mm;font-style:italic;letter-spacing:0;margin-top:1.4mm;opacity:.9}}
.title .ornament{{margin-top:1mm}}
"""


FONT_CSS_URL = "/api/fonts.css"


def book_html(pages: list[str], title: str, opts: RenderOptions) -> str:
    link = "" if opts.embed else f"<link rel='stylesheet' href='{FONT_CSS_URL}'>"
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{_esc(title)}</title>{link}<style>\n{book_css(opts)}</style></head><body>{''.join(pages)}</body></html>"


def render_pdf(html_text: str, out_pdf: Path) -> Path:
    """Playwright/Chromium (executable fallback glob), else a system Chrome in headless print mode."""
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    html_path = out_pdf.with_suffix(".html")
    html_path.write_text(html_text, encoding="utf-8")
    import glob
    import os
    import shutil
    import subprocess

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
    except Exception as exc:  # noqa: BLE001
        for cand in (exe, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("chrome")):
            if cand and Path(cand).exists():
                subprocess.run([cand, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer", f"--print-to-pdf={out_pdf}", html_path.resolve().as_uri()], check=True, timeout=300)
                return out_pdf
        raise RuntimeError(f"no PDF renderer available ({exc}); the HTML proof is at {html_path}")


def layout_manifest(page: PageView) -> dict[str, Any]:
    """Polygons in mm for the layout file (Affinity/InDesign) plus the measured image/paper/marginalia balance."""
    look = page_look_for(page.panels, page.beat)
    return {"page": page.number, "trim_mm": [PAGE_W, PAGE_H], "bleed_mm": BLEED, "look": look.__dict__, "balance": balance_of(page), "panels": [
        {"panel": p.n, "number": p.number, "kind": p.kind, "state": p.text_state, "beat": panel_beat(p), "scale": p.scale, "image_group": p.image_group,
         "shape": p.shape, "caption_en": p.caption_en, "caption_hi": p.caption_hi, "balloon_en": p.balloon_en, "balloon_hi": p.balloon_hi, "speaker": p.speaker}
        for p in page.panels
    ]}
