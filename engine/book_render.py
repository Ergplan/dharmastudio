"""Book renderer: one page of a layered book package (paper / art / text) as HTML + CSS.

A package (`dharma-book/1`, see backend/book_api.py) stores every page in page pixels on the book's `page_px`
canvas (2040 x 3060 for a 170 x 255 mm trim, i.e. 12 px per mm). The renderer converts px to mm and positions
every element absolutely, so the same HTML drives the live preview (fonts and images by URL), the single-page PNG
and the PDF (headless Chrome; images by file:// URL, fonts embedded).

Layers, bottom to top:
- paper: the texture (covering the bleed), the sepia line figures (grayscale ink -> #5c3416, alpha = inverted
  luminance x opacity, optionally mirrored), the shloka (line 0 centred in the top margin, the remaining lines joined
  and centred in the bottom margin, shrink-to-fit), the source line and the page number;
- art: the painting in its window with a slightly jagged torn edge (clip-path) and a soft shadow;
- text: parchment cards, frosted glass boxes (backdrop blur) with a short tail, glass narration with a gold accent bar,
  header cards (kicker + title). All text is real, searchable text.

Modes: `screen` = the trim only (170 x 255 mm); `print` = trim + bleed on every side with crop marks in the bleed.
"""

from __future__ import annotations

import base64
import hashlib
import html
import math
import os
import random
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

ENGINE = Path(__file__).resolve().parent
TEXTURES = ENGINE / "textures"
FIGURES = ENGINE / "figures"
FONT_LIB = ENGINE / "comic" / "fonts" / "library"
SHLOKAS_YAML = ENGINE / "shlokas.yaml"

SEPIA = (0x5C, 0x34, 0x16)
SHLOKA_RED = "#8c1e12"
TEXT_KINDS = ("narration", "dialogue", "header")
STYLES = ("parchment", "glass", "glass-narration", "header")
ALIGNS = ("left", "center", "right")

# the faces a book page may use: family -> [(file, css weight, css style)]. The six of the house look come first;
# the rest of the studio's OFL catalogue is offered in the font picker as well.
_HOUSE: dict[str, list[tuple[str, str, str]]] = {
    "EB Garamond": [("EBGaramondwght.ttf", "400 800", "normal"), ("EBGaramond-Italicwght.ttf", "400 800", "italic")],
    "Martel": [("Martel-Regular.ttf", "400", "normal"), ("Martel-Bold.ttf", "700", "normal")],
    "Inter Tight": [("InterTightwght.ttf", "100 900", "normal")],
    "Cinzel": [("Cinzelwght.ttf", "400 900", "normal")],
    "Cinzel Decorative": [("CinzelDecorative-Bold.ttf", "700", "normal")],
    "Tiro Devanagari Hindi": [("TiroDevanagariHindi-Regular.ttf", "400", "normal"), ("TiroDevanagariHindi-Italic.ttf", "400", "italic")],
}


@lru_cache(maxsize=1)
def book_fonts() -> dict[str, list[tuple[str, str, str]]]:
    out = dict(_HOUSE)
    try:
        from engine import typography as T

        for f in T.CATALOG:
            if f.family in out:
                continue
            faces = [(Path(x.file).name, x.weight, x.style) for x in f.faces if x.file.startswith("library/")]
            if faces:
                out[f.family] = faces
    except Exception:  # noqa: BLE001
        pass
    return {fam: faces for fam, faces in out.items() if all((FONT_LIB / f).exists() for f, _w, _s in faces)}


def font_file(name: str) -> Path | None:
    """A book font by bare file name (only files the book font table lists)."""
    for faces in book_fonts().values():
        for f, _w, _s in faces:
            if f == name:
                return FONT_LIB / f
    return None


# per style: font, weight, size px, line height px, colour
STYLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "parchment": {"font": "EB Garamond", "weight": 700, "size": 50, "line": 62, "color": "#24180c", "align": "left"},
    "glass": {"font": "Martel", "weight": 700, "size": 40, "line": 58, "color": "#faf8f2", "align": "center"},
    "glass-modern": {"font": "Inter Tight", "weight": 640, "size": 42, "line": 56, "color": "#faf8f2", "align": "center"},
    "glass-narration": {"font": "Inter Tight", "weight": 560, "size": 44, "line": 58, "color": "#faf8f2", "align": "left"},
    "header": {"font": "Cinzel Decorative", "weight": 700, "size": 64, "line": 74, "color": "#24180c", "align": "left",
               "kicker_font": "Cinzel", "kicker_size": 30, "kicker_color": "#8c1e12"},
}


def style_defaults(style: str, font: str | None) -> dict[str, Any]:
    if style == "glass" and font == "Inter Tight":
        return STYLE_DEFAULTS["glass-modern"]
    return STYLE_DEFAULTS.get(style, STYLE_DEFAULTS["parchment"])


# ---------------------------------------------------------------------------------
# shlokas, figures, textures
# ---------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def shlokas() -> list[dict[str, Any]]:
    import yaml

    data = yaml.safe_load(SHLOKAS_YAML.read_text(encoding="utf-8")) or {}
    return [{"id": s["id"], "source": s.get("source", ""), "lines": list(s.get("lines") or []), "iast": s.get("iast", ""),
             "meaning": s.get("meaning", ""), "tags": list(s.get("tags") or [])} for s in data.get("shlokas", [])]


def shloka(sid: str) -> dict[str, Any] | None:
    return next((s for s in shlokas() if s["id"] == sid), None)


def figure_names() -> list[str]:
    return sorted(p.stem[4:] for p in FIGURES.glob("fig_*.png"))


def texture_names() -> list[str]:
    return sorted(p.stem for p in TEXTURES.glob("*.jpg") if not p.stem.startswith("scrap"))


def figure_png(name: str, cache_dir: Path) -> Path | None:
    """The figure as sepia ink with alpha = inverted luminance (opacity is applied by the renderer). Cached."""
    src = FIGURES / f"fig_{name}.png"
    if not src.exists():
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    dst = cache_dir / f"fig_{name}-{int(src.stat().st_mtime)}.png"
    if not dst.exists():
        from PIL import Image, ImageOps

        with Image.open(src) as im:
            lum = im.convert("L")
            alpha = ImageOps.invert(lum)
            out = Image.new("RGBA", lum.size, SEPIA + (0,))
            out.putalpha(alpha)
            tmp = dst.with_name(f"{dst.stem}.{os.getpid()}-{threading.get_ident()}.tmp.png")  # concurrent renders: own temp file
            out.save(tmp, optimize=True)
            tmp.replace(dst)
    return dst


@lru_cache(maxsize=32)
def _aspect(path: str, mtime: float) -> float:  # noqa: ARG001
    from PIL import Image

    with Image.open(path) as im:
        return im.size[0] / max(1, im.size[1])


def image_aspect(p: Path | None) -> float:
    if not (p and p.exists()):
        return 1.0
    return _aspect(str(p), p.stat().st_mtime)


@lru_cache(maxsize=64)
def _pil_font(path: str, size: int):  # noqa: ANN202
    from PIL import ImageFont

    return ImageFont.truetype(path, size)


def text_px(text: str, family: str, size: float) -> float:
    """Approximate advance width of `text` in px at `size` px (for shrink-to-fit)."""
    faces = book_fonts().get(family) or book_fonts()["EB Garamond"]
    f = _pil_font(str(FONT_LIB / faces[0][0]), 100)
    try:
        return f.getlength(text) * size / 100.0
    except Exception:  # noqa: BLE001
        return len(text) * size * 0.55


# ---------------------------------------------------------------------------------
# resources: how the HTML refers to images and fonts
# ---------------------------------------------------------------------------------


@dataclass
class Resources:
    """`url(kind, path)` -> the src for an image (kind: art | texture | figure | card) or a font (kind: font).
    `http`: URLs the backend serves; `file`: file:// URIs (PDF / PNG); `embed`: data URIs (self-contained)."""

    mode: str = "file"
    book_dir: Path | None = None
    cache_dir: Path | None = None
    url_base: Callable[[str, Path], str] | None = None

    def url(self, kind: str, path: Path) -> str:
        if self.mode == "http" and self.url_base:
            return self.url_base(kind, path)
        if self.mode == "embed":
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".ttf": "font/ttf", ".otf": "font/otf", ".webp": "image/webp"}.get(path.suffix.lower(), "application/octet-stream")
            return f"data:{mime};base64," + _b64(str(path), path.stat().st_mtime)
        return path.resolve().as_uri()


@lru_cache(maxsize=96)
def _b64(path: str, mtime: float) -> str:  # noqa: ARG001
    return base64.b64encode(Path(path).read_bytes()).decode()


# ---------------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------------


@dataclass
class Geo:
    W: int = 2040
    H: int = 3060
    trim_w: float = 170.0
    trim_h: float = 255.0
    bleed: float = 3.0
    frame: dict[str, int] = field(default_factory=lambda: {"l": 104, "r": 104, "t": 170, "b": 200})

    @property
    def k(self) -> float:  # mm per px
        return self.trim_w / self.W

    def mm(self, px: float) -> str:
        return f"{px * self.k:.3f}mm"

    @classmethod
    def of(cls, book: dict[str, Any]) -> "Geo":
        W, H = (book.get("page_px") or [2040, 3060])[:2]
        tw, th = (book.get("trim_mm") or [170, 255])[:2]
        return cls(int(W), int(H), float(tw), float(th), float(book.get("bleed_mm", 3)), dict(book.get("frame") or {"l": 104, "r": 104, "t": 170, "b": 200}))


def _esc(s: Any) -> str:
    return html.escape(str(s or ""), quote=True)


def _text_html(s: str) -> str:
    return "<br>".join(_esc(x) for x in str(s or "").split("\n"))


def torn_clip(w: float, h: float, seed: str, amp: float = 7.0, step: float = 22.0) -> str:
    """A slightly jagged torn edge as a clip-path polygon (percentages of the box), deterministic per seed."""
    rng = random.Random(int(hashlib.sha1(seed.encode()).hexdigest()[:8], 16))
    pts: list[tuple[float, float]] = []

    def edge(x0: float, y0: float, x1: float, y1: float, nx: float, ny: float) -> None:
        n = max(2, int(math.hypot(x1 - x0, y1 - y0) / step))
        for i in range(n):
            t = i / n
            d = rng.random() * amp * (1.6 if rng.random() < 0.12 else 1.0)
            pts.append((x0 + (x1 - x0) * t + nx * d, y0 + (y1 - y0) * t + ny * d))

    edge(0, 0, w, 0, 0, 1)
    edge(w, 0, w, h, -1, 0)
    edge(w, h, 0, h, 0, -1)
    edge(0, h, 0, 0, 1, 0)
    return "polygon(" + ",".join(f"{100 * x / w:.2f}% {100 * y / h:.2f}%" for x, y in pts) + ")"


def tail_polygon(box: dict[str, Any], tail: list[float] | tuple[float, float] | None, radius: float = 26, max_len: float = 84, half: float = 24) -> list[tuple[float, float]] | None:
    """A short tail from the box edge toward `tail` (page px). None when there is no tail or it points inside the box."""
    if not tail:
        return None
    x, y, w, h = (float(box.get(k) or 0) for k in ("x", "y", "w", "h"))
    tx, ty = float(tail[0]), float(tail[1])
    if x <= tx <= x + w and y <= ty <= y + h:
        return None
    cx, cy = x + w / 2, y + h / 2
    dx, dy = tx - cx, ty - cy
    # where the centre->tail ray leaves the box
    ts = []
    if dx:
        ts += [((x + w) - cx) / dx if dx > 0 else (x - cx) / dx]
    if dy:
        ts += [((y + h) - cy) / dy if dy > 0 else (y - cy) / dy]
    t = min(v for v in ts if v > 0)
    ax, ay = cx + dx * t, cy + dy * t
    m = radius + half
    ax = min(max(ax, x + min(m, w / 2)), x + w - min(m, w / 2))
    ay = min(max(ay, y + min(m, h / 2)), y + h - min(m, h / 2))
    vx, vy = tx - ax, ty - ay
    d = math.hypot(vx, vy) or 1.0
    ux, uy = vx / d, vy / d
    L = min(d, max_len)
    px, py = -uy, ux
    bx, by = ax - ux * 6, ay - uy * 6  # the base sits just inside the box
    return [(bx + px * half, by + py * half), (ax + ux * L, ay + uy * L), (bx - px * half, by - py * half)]


# ---------------------------------------------------------------------------------
# page HTML
# ---------------------------------------------------------------------------------


def layers_of(page: dict[str, Any]) -> dict[str, bool]:
    lay = page.get("layers") or {}
    return {k: bool(lay.get(k, True)) for k in ("paper", "art", "text")}


def _paper_html(page: dict[str, Any], g: Geo, res: Resources, number: int | None) -> str:
    paper = page.get("paper") or {}
    out: list[str] = []
    cache = res.cache_dir or Path("/tmp")
    for f in paper.get("figures") or []:
        p = figure_png(str(f.get("name")), cache)
        if not p:
            continue
        h = float(f.get("h") or 400)
        w = h * image_aspect(FIGURES / f"fig_{f.get('name')}.png")
        tr = "transform:scaleX(-1);" if f.get("mirror") else ""
        out.append(f"<img class='fig' alt='' src='{res.url('figure', p)}' style='left:{g.mm(float(f.get('x') or 0))};top:{g.mm(float(f.get('y') or 0))};"
                   f"width:{g.mm(w)};height:{g.mm(h)};opacity:{float(f.get('opacity', 0.4)):.3f};{tr}'>")
    sh = paper.get("shloka") or None
    if sh and sh.get("lines"):
        lines = [str(x) for x in sh["lines"]]
        avail = g.W - 260
        top = lines[0]
        bottom = " ".join(lines[1:])
        for txt, cy in ((top, 66), (bottom, g.H - g.frame.get("b", 200) + 40)):
            if not txt:
                continue
            size = min(46.0, 46.0 * avail / max(1.0, text_px(txt, "Tiro Devanagari Hindi", 46.0)))
            out.append(f"<div class='shloka' lang='sa' style='left:{g.mm(130)};width:{g.mm(avail)};top:{g.mm(cy - 40)};height:{g.mm(80)};font-size:{g.mm(size)}'>{_esc(txt)}</div>")
        if sh.get("source"):
            out.append(f"<div class='shloka-src' style='left:{g.mm(130)};width:{g.mm(avail)};top:{g.mm(g.H - 78 - 22)};height:{g.mm(44)};font-size:{g.mm(28)}'>— {_esc(sh['source'])}</div>")
    if page.get("page_number", True) and number is not None:
        out.append(f"<div class='folio' style='right:{g.mm(120)};top:{g.mm(g.H - 78 - 22)};height:{g.mm(44)};font-size:{g.mm(30)}'>{number}</div>")
    return f"<div class='layer layer-paper'>{''.join(out)}</div>"


def _art_html(page: dict[str, Any], g: Geo, res: Resources) -> str:
    art = page.get("art") or {}
    if not art.get("file") or not res.book_dir:
        return "<div class='layer layer-art'></div>"
    path = res.book_dir / str(art["file"])
    if not path.exists():
        return "<div class='layer layer-art'></div>"
    x, y, w, h = (float(art.get(k) or 0) for k in ("x", "y", "w", "h"))
    fit = art.get("fit") if art.get("fit") in ("cover", "contain", "fill") else "cover"
    fx, fy = (art.get("focus") or [0.5, 0.5])[:2]
    clip = f"clip-path:{torn_clip(w, h, str(page.get('id')) + str(art['file']))};" if art.get("torn", True) else ""
    return (f"<div class='layer layer-art'><div class='art' style='left:{g.mm(x)};top:{g.mm(y)};width:{g.mm(w)};height:{g.mm(h)}'>"
            f"<div class='art-clip' style='{clip}'><img class='art-img' alt='' src='{res.url('art', path)}' "
            f"style='object-fit:{fit};object-position:{100 * float(fx):.1f}% {100 * float(fy):.1f}%'></div></div></div>")


def box_font(t: dict[str, Any]) -> tuple[str, int, float, float, str, str]:
    """(family, weight, size px, line px, colour, align) of a text box, from its style and its own overrides."""
    d = style_defaults(str(t.get("style") or "parchment"), t.get("font"))
    fam = t.get("font") or d["font"]
    if fam not in book_fonts():
        fam = d["font"]
    size = float(t.get("size") or d["size"])
    line = float(t.get("line") or d["line"] * size / d["size"])
    weight = int(t.get("weight") or d["weight"])
    align = t.get("align") if t.get("align") in ALIGNS else d["align"]
    return fam, weight, size, line, str(t.get("color") or d["color"]), align


def _text_box_html(t: dict[str, Any], g: Geo, res: Resources, card_url: str) -> tuple[str, str]:
    style = str(t.get("style") or "parchment")
    if style not in STYLES:
        style = "parchment"
    x, y, w, h = (float(t.get(k) or 0) for k in ("x", "y", "w", "h"))
    fam, weight, size, line, color, align = box_font(t)
    font = f"font-family:'{fam}';font-weight:{weight};font-size:{g.mm(size)};line-height:{g.mm(line)};color:{color};text-align:{align};"
    pos = f"left:{g.mm(x)};top:{g.mm(y)};width:{g.mm(w)};height:{g.mm(h)};"
    tid = _esc(t.get("id"))
    kind = _esc(t.get("kind") or "narration")
    tail_svg = ""
    if style == "header":
        d = STYLE_DEFAULTS["header"]
        kicker = t.get("kicker")
        title = t.get("title") if t.get("title") is not None else t.get("text")
        kick = (f"<div class='kicker' style=\"font-family:'{d['kicker_font']}';font-weight:600;font-size:{g.mm(float(t.get('kicker_size') or d['kicker_size']))};"
                f"color:{d['kicker_color']}\">{_text_html(kicker)}</div>") if kicker else ""
        # a header title sits on one line: shrink it to the card's width (the author can still set a size)
        widest = max((text_px(x, fam, size) * 1.04 for x in str(title or "").split("\n")), default=0.0)
        avail = max(40.0, w - 68)
        if widest > avail:
            k = avail / widest
            font = f"font-family:'{fam}';font-weight:{weight};font-size:{g.mm(size * k)};line-height:{g.mm(line * k)};color:{color};text-align:{align};white-space:nowrap;"
        body = f"{kick}<div class='title' style=\"{font}\">{_text_html(title)}</div>"
        inner = f"<div class='tb-in' style='padding:{g.mm(18)} {g.mm(34)};text-align:{align}'>{body}</div>"
        cls = "tb tb-card tb-header"
        bg = f"background-image:url('{card_url}');" if card_url else ""
        return f"<div class='{cls}' data-id='{tid}' data-kind='{kind}' style=\"{pos}{bg}\"><div class='rule' style='inset:{g.mm(9)}'></div>{inner}</div>", ""
    if style == "parchment":
        bg = f"background-image:url('{card_url}');" if card_url else ""
        inner = f"<div class='tb-in' style=\"padding:{g.mm(20)} {g.mm(32)};{font}\">{_text_html(t.get('text'))}</div>"
        return f"<div class='tb tb-card' data-id='{tid}' data-kind='{kind}' style=\"{pos}{bg}\"><div class='rule' style='inset:{g.mm(9)}'></div>{inner}</div>", ""
    # glass and glass-narration
    rad = g.mm(26)
    glass = f"border-radius:{rad};border:{g.mm(2.4)} solid rgba(255,255,255,0.47);-webkit-backdrop-filter:blur({g.mm(14)});backdrop-filter:blur({g.mm(14)});"
    accent = ""
    pad = f"padding:{g.mm(12)} {g.mm(18)};"
    if style == "glass-narration":
        accent = f"<div class='accent' style='left:{g.mm(16)};top:{g.mm(18)};bottom:{g.mm(18)};width:{g.mm(7)}'></div>"
        pad = f"padding:{g.mm(14)} {g.mm(24)} {g.mm(14)} {g.mm(40)};"
    else:
        poly = tail_polygon(t, t.get("tail"))
        if poly:
            pts = " ".join(f"{px * g.k:.3f},{py * g.k:.3f}" for px, py in poly)
            tail_svg = (f"<polygon class='tail' data-for='{tid}' points='{pts}' fill='rgba(14,18,26,0.62)' stroke='rgba(255,255,255,0.47)' "
                        f"stroke-width='{2.4 * g.k:.3f}' stroke-linejoin='round'/>")
    inner = f"<div class='tb-in' style=\"{pad}{font}\">{_text_html(t.get('text'))}</div>"
    return f"<div class='tb tb-glass {'tb-gn' if accent else ''}' data-id='{tid}' data-kind='{kind}' style=\"{pos}{glass}\">{accent}{inner}</div>", tail_svg


def _text_html_layer(page: dict[str, Any], g: Geo, res: Resources) -> str:
    card = TEXTURES / "page_light.jpg"
    card_url = res.url("card", card) if card.exists() else ""
    boxes, tails = [], []
    for t in page.get("text") or []:
        b, tl = _text_box_html(t, g, res, card_url)
        boxes.append(b)
        if tl:
            tails.append(tl)
    svg = (f"<svg class='tails' xmlns='http://www.w3.org/2000/svg' width='{g.trim_w}mm' height='{g.trim_h}mm' viewBox='0 0 {g.trim_w} {g.trim_h}'>{''.join(tails)}</svg>"
           if tails else "")
    return f"<div class='layer layer-text'>{svg}{''.join(boxes)}</div>"


def crop_marks(g: Geo) -> str:
    W, H, B = g.trim_w + 2 * g.bleed, g.trim_h + 2 * g.bleed, g.bleed
    m, L = 1.0, max(0.5, B - 0.6)
    lines = []
    for x in (B, B + g.trim_w):
        for y in (B, B + g.trim_h):
            sx, sy = (-1 if x == B else 1), (-1 if y == B else 1)
            lines.append(f"<line x1='{x + sx * m:.3f}' y1='{y:.3f}' x2='{x + sx * (m + L):.3f}' y2='{y:.3f}'/>")
            lines.append(f"<line x1='{x:.3f}' y1='{y + sy * m:.3f}' x2='{x:.3f}' y2='{y + sy * (m + L):.3f}'/>")
    return (f"<svg class='marks' xmlns='http://www.w3.org/2000/svg' width='{W}mm' height='{H}mm' viewBox='0 0 {W} {H}'>"
            f"<g stroke='#000' stroke-width='0.15'>{''.join(lines)}</g></svg>")


def page_html(book: dict[str, Any], page: dict[str, Any], res: Resources, paper: str = "screen", number: int | None = None) -> str:
    """One page as a <section>. `paper`: screen (trim) | print (bleed + crop marks)."""
    g = Geo.of(book)
    lay = layers_of(page)
    pr = paper == "print"
    off = g.bleed if pr else 0.0
    tex_name = str((page.get("paper") or {}).get("texture") or "page_warm")
    tex = TEXTURES / f"{tex_name}.jpg"
    if not tex.exists():
        tex = TEXTURES / "page_warm.jpg"
    bg = f"background-image:url('{res.url('texture', tex)}');" if lay["paper"] else "background:#ffffff;"
    num = number if number is not None else page.get("number")
    parts = []
    if lay["paper"]:
        parts.append(_paper_html(page, g, res, num))
    if lay["art"]:
        parts.append(_art_html(page, g, res))
    if lay["text"]:
        parts.append(_text_html_layer(page, g, res))
    W = g.trim_w + (2 * g.bleed if pr else 0)
    H = g.trim_h + (2 * g.bleed if pr else 0)
    marks = crop_marks(g) if pr else ""
    return (f"<section class='bpage' data-page='{_esc(page.get('id'))}' data-number='{_esc(num)}' style=\"width:{W}mm;height:{H}mm;{bg}\">"
            f"<div class='trim' style='left:{off}mm;top:{off}mm;width:{g.trim_w}mm;height:{g.trim_h}mm'>{''.join(parts)}</div>{marks}</section>")


def cover_html(book: dict[str, Any], res: Resources, paper: str = "screen") -> str:
    g = Geo.of(book)
    pr = paper == "print"
    W = g.trim_w + (2 * g.bleed if pr else 0)
    H = g.trim_h + (2 * g.bleed if pr else 0)
    f = (book.get("cover") or {}).get("file")
    p = (res.book_dir / f) if (f and res.book_dir) else None
    img = f"<img class='cover-img' alt='{_esc(book.get('title'))}' src='{res.url('art', p)}'>" if p and p.exists() else f"<div class='cover-title'>{_esc(book.get('title'))}</div>"
    return f"<section class='bpage cover' data-page='cover' style='width:{W}mm;height:{H}mm;background:#1a120b'>{img}{crop_marks(g) if pr else ''}</section>"


def families_used(pages: list[dict[str, Any]]) -> set[str]:
    fams: set[str] = set()
    for p in pages:
        lay = layers_of(p)
        if lay["paper"]:
            fams |= {"EB Garamond"}
            if (p.get("paper") or {}).get("shloka"):
                fams.add("Tiro Devanagari Hindi")
        if lay["text"]:
            for t in p.get("text") or []:
                fams.add(box_font(t)[0])
                if t.get("style") == "header":
                    fams.add("Cinzel")
    return fams


def font_css(fams: set[str], res: Resources) -> str:
    rules = []
    for fam in sorted(fams):
        for f, w, s in book_fonts().get(fam, []):
            rules.append(f"@font-face{{font-family:'{fam}';src:url('{res.url('font', FONT_LIB / f)}') format('truetype');font-weight:{w};font-style:{s};font-display:block;}}")
    return "\n".join(rules)


def css(book: dict[str, Any], paper: str = "screen") -> str:
    g = Geo.of(book)
    pr = paper == "print"
    W = g.trim_w + (2 * g.bleed if pr else 0)
    H = g.trim_h + (2 * g.bleed if pr else 0)
    return f"""
@page {{ size: {W}mm {H}mm; margin: 0; }}
html,body{{margin:0;padding:0;background:#2a2622}}
*{{-webkit-print-color-adjust:exact;print-color-adjust:exact;box-sizing:border-box}}
.bpage{{position:relative;overflow:hidden;background-size:cover;background-position:center;page-break-after:always;break-after:page}}
.bpage:last-child{{page-break-after:auto;break-after:auto}}
.trim{{position:absolute;overflow:visible}}
.layer{{position:absolute;inset:0}}
.fig{{position:absolute;pointer-events:none}}
.shloka{{position:absolute;display:flex;align-items:center;justify-content:center;white-space:nowrap;font-family:'Tiro Devanagari Hindi';color:{SHLOKA_RED};line-height:1}}
.shloka-src{{position:absolute;display:flex;align-items:center;justify-content:center;font-family:'EB Garamond';font-style:italic;color:#5c3416;opacity:.85}}
.folio{{position:absolute;display:flex;align-items:center;font-family:'EB Garamond';color:#5c3416}}
.art{{position:absolute;filter:drop-shadow(0 0.5mm 1.1mm rgba(30,16,4,.55))}}
.art-clip{{position:absolute;inset:0;overflow:hidden;background:#1a120b}}
.art-img{{display:block;width:100%;height:100%}}
.tails{{position:absolute;left:0;top:0;overflow:visible}}
.tb{{position:absolute;display:flex;align-items:center}}
.tb-in{{position:relative;width:100%;overflow-wrap:break-word}}
.tb-card{{background-size:cover;background-position:center;background-color:#efe4c9;box-shadow:0 0.4mm 1.2mm rgba(40,22,6,.45)}}
.tb-card .rule{{position:absolute;border:0.13mm solid #5c3416;opacity:.7;pointer-events:none}}
.tb-glass{{background:rgba(14,18,26,0.52);box-shadow:0 0.4mm 1.4mm rgba(0,0,0,.35)}}
.tb-glass .accent{{position:absolute;background:#d6a848;border-radius:0.4mm}}
.tb-header .kicker{{letter-spacing:0.06em;line-height:1.25}}
.tb-header .title{{letter-spacing:0.01em}}
.marks{{position:absolute;left:0;top:0}}
.cover-img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
.cover-title{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#efe4c9;font-family:'Cinzel Decorative';font-size:9mm;text-align:center}}
"""


def document(book: dict[str, Any], sections: list[str], pages: list[dict[str, Any]], res: Resources, paper: str = "screen", title: str = "", extra_css: str = "") -> str:
    fams = families_used(pages) | ({"Cinzel Decorative"} if any("cover" in s[:60] for s in sections) else set())
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{_esc(title or book.get('title'))}</title>"
            f"<style>{font_css(fams, res)}\n{css(book, paper)}{extra_css}</style></head><body>{''.join(sections)}</body></html>")


def page_document(book: dict[str, Any], page: dict[str, Any], res: Resources, paper: str = "screen", number: int | None = None, extra_css: str = "") -> str:
    return document(book, [page_html(book, page, res, paper, number)], [page], res, paper, f"{book.get('title', '')} · {page.get('id')}", extra_css)


def book_document(book: dict[str, Any], pages: list[dict[str, Any]], res: Resources, paper: str = "print", cover: bool = True, first_number: int = 1) -> str:
    """The cover (optional) and `pages`, numbered from `first_number` (a long book is rendered in chunks)."""
    secs = ([cover_html(book, res, paper)] if cover else []) + [page_html(book, p, res, paper, first_number + i) for i, p in enumerate(pages)]
    return document(book, secs, pages, res, paper, str(book.get("title") or "Book"))


def page_size_mm(book: dict[str, Any], paper: str) -> tuple[float, float]:
    g = Geo.of(book)
    e = 2 * g.bleed if paper == "print" else 0.0
    return g.trim_w + e, g.trim_h + e
