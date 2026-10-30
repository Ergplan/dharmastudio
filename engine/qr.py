"""QR codes for printed pages. Every code encodes a short URL (https://cycleofdharma.world/v/{code}); never a raw
destination. One drawing description (in mm) feeds two backends — SVG (vector export, the page element) and Pillow
(the PNG at 600 dpi, the PDF, the live preview and the decode test) — so what is tested is what is printed.

Styles: square | rounded | dots modules; finder patterns stay solid (rounded rings for rounded/dots) so scanners lock
on. EC level H by default; quiet zone >= 4 modules; centre emblem none | chakra | lotus | om (ॐ typeset from Tiro
Devanagari) | an uploaded PNG/SVG, kept to <= 15 % of the symbol area on a knocked-out paper plate; label EN/HI plus
the short URL beneath. Size is the printed width in mm (symbol + quiet zone); 20 mm minimum.

DECODE TEST: the code is rasterised at its printed size at 300 and 150 dpi, on the parchment texture, and read back
with zxing-cpp; it passes only if both read back to exactly the URL.
"""

from __future__ import annotations

import base64
import io
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFilter

from engine.motion import textrender as TR

ENGINE = Path(__file__).resolve().parent
PARCHMENT = ENGINE / "textures" / "page_warm.jpg"
FONT_URL = ENGINE / "comic" / "fonts" / "library" / "Spectral-Regular.ttf"

MIN_MM = 20.0
MAX_EMBLEM_AREA = 0.15
SEPIA = "#2a1d10"
BLACK = "#000000"
MODULES = ("square", "rounded", "dots")
EMBLEMS = ("none", "chakra", "lotus", "om", "upload")
EC_LEVELS = ("L", "M", "Q", "H")
LABELS = {"en": "See this moment", "hi": "यह क्षण देखें"}
TEST_DPIS = (300, 150)


@dataclass
class QRStyle:
    colour: str = SEPIA
    module: str = "square"
    ec: str = "H"
    quiet: int = 4
    emblem: str = "none"
    emblem_png: bytes | None = None  # uploaded emblem (PNG bytes; SVGs are rasterised on upload)
    emblem_scale: float = 0.22  # emblem plate side as a fraction of the symbol side (area <= 15 %)
    label: str = "en"  # en | hi | none
    show_url: bool = True
    size_mm: float = 24.0  # printed width of the symbol incl. quiet zone

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None, emblem_png: bytes | None = None) -> "QRStyle":
        d = dict(d or {})
        s = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "emblem_png"})
        s.emblem_png = emblem_png
        return s.normalised()

    def normalised(self) -> "QRStyle":
        self.module = self.module if self.module in MODULES else "square"
        self.ec = (self.ec or "H").upper() if (self.ec or "H").upper() in EC_LEVELS else "H"
        self.quiet = max(4, int(self.quiet or 4))
        self.emblem = self.emblem if self.emblem in EMBLEMS else "none"
        self.label = self.label if self.label in ("en", "hi", "none") else "en"
        self.size_mm = max(MIN_MM, float(self.size_mm or MIN_MM))
        self.emblem_scale = min(max(0.08, float(self.emblem_scale or 0.22)), math.sqrt(MAX_EMBLEM_AREA))
        try:
            ImageColor.getrgb(self.colour)
        except ValueError:
            self.colour = SEPIA
        return self

    def json(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("emblem_png", None)
        return d


def validate_size(size_mm: float) -> None:
    if float(size_mm) < MIN_MM:
        raise ValueError(f"a printed QR must be at least {MIN_MM:.0f} mm wide")


# ---------------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------------


@dataclass
class Symbol:
    url: str
    n: int  # modules per side (without the quiet zone)
    version: int
    dark: list[list[bool]]
    finder: list[tuple[int, int]] = field(default_factory=list)  # top-left module of each 7x7 finder


def encode(url: str, ec: str = "H") -> Symbol:
    import segno

    q = segno.make_qr(url, error=ec.lower(), boost_error=False)
    rows = [[bool(v) for v in row] for row in q.matrix]
    n = len(rows)
    return Symbol(url=url, n=n, version=int(q.version), dark=rows, finder=[(0, 0), (n - 7, 0), (0, n - 7)])


def _in_finder(sym: Symbol, x: int, y: int) -> bool:
    return any(fx <= x < fx + 7 and fy <= y < fy + 7 for fx, fy in sym.finder)


# ---------------------------------------------------------------------------------
# drawing backends (units: mm)
# ---------------------------------------------------------------------------------


class SvgCanvas:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def rect(self, x: float, y: float, w: float, h: float, fill: str, r: float = 0.0) -> None:
        rr = f' rx="{r:.4f}"' if r else ""
        self.parts.append(f'<rect x="{x:.4f}" y="{y:.4f}" width="{w:.4f}" height="{h:.4f}"{rr} fill="{fill}"/>')

    def ring(self, x: float, y: float, outer: float, width: float, fill: str, r: float = 0.0) -> None:
        """A square ring (finder) — outer square minus inner, even-odd."""
        i = width
        ro, ri = r, max(0.0, r - width * 0.6)
        self.parts.append(f'<path fill="{fill}" fill-rule="evenodd" d="{_rrect_d(x, y, outer, outer, ro)}{_rrect_d(x + i, y + i, outer - 2 * i, outer - 2 * i, ri)}"/>')

    def circle(self, cx: float, cy: float, r: float, fill: str) -> None:
        self.parts.append(f'<circle cx="{cx:.4f}" cy="{cy:.4f}" r="{r:.4f}" fill="{fill}"/>')

    def stroke_circle(self, cx: float, cy: float, r: float, w: float, colour: str) -> None:
        self.parts.append(f'<circle cx="{cx:.4f}" cy="{cy:.4f}" r="{r:.4f}" fill="none" stroke="{colour}" stroke-width="{w:.4f}"/>')

    def line(self, x0: float, y0: float, x1: float, y1: float, w: float, colour: str) -> None:
        self.parts.append(f'<line x1="{x0:.4f}" y1="{y0:.4f}" x2="{x1:.4f}" y2="{y1:.4f}" stroke="{colour}" stroke-width="{w:.4f}" stroke-linecap="round"/>')

    def polygon(self, pts: list[tuple[float, float]], fill: str) -> None:
        self.parts.append(f'<polygon fill="{fill}" points="{" ".join(f"{x:.4f},{y:.4f}" for x, y in pts)}"/>')

    def text(self, text: str, x: float, y: float, size: float, fill: str, font: Path | None = None) -> None:
        self.parts.append(f'<path fill="{fill}" d="{TR.svg_text_path(text, x, y, size, font, anchor="ms")}"/>')

    def image(self, png: bytes, x: float, y: float, w: float, h: float) -> None:
        b64 = base64.b64encode(png).decode()
        self.parts.append(f'<image x="{x:.4f}" y="{y:.4f}" width="{w:.4f}" height="{h:.4f}" preserveAspectRatio="xMidYMid meet" href="data:image/png;base64,{b64}"/>')


def _rrect_d(x: float, y: float, w: float, h: float, r: float) -> str:
    if r <= 0:
        return f"M{x:.4f} {y:.4f}h{w:.4f}v{h:.4f}h{-w:.4f}Z"
    r = min(r, w / 2, h / 2)
    return (f"M{x + r:.4f} {y:.4f}h{w - 2 * r:.4f}a{r:.4f} {r:.4f} 0 0 1 {r:.4f} {r:.4f}v{h - 2 * r:.4f}a{r:.4f} {r:.4f} 0 0 1 {-r:.4f} {r:.4f}"
            f"h{-(w - 2 * r):.4f}a{r:.4f} {r:.4f} 0 0 1 {-r:.4f} {-r:.4f}v{-(h - 2 * r):.4f}a{r:.4f} {r:.4f} 0 0 1 {r:.4f} {-r:.4f}Z")


class PilCanvas:
    """Draws in mm onto an RGBA image at `dpi`, supersampled `ss`x for clean edges."""

    def __init__(self, w_mm: float, h_mm: float, dpi: int, ss: int = 3) -> None:
        self.dpi, self.ss = dpi, ss
        self.k = dpi / 25.4 * ss
        self.size = (max(1, round(w_mm * dpi / 25.4)), max(1, round(h_mm * dpi / 25.4)))
        self.img = Image.new("RGBA", (self.size[0] * ss, self.size[1] * ss), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def _c(self, colour: str) -> tuple[int, int, int, int]:
        rgb = ImageColor.getrgb(colour)
        return (*rgb[:3], rgb[3] if len(rgb) > 3 else 255)

    def rect(self, x: float, y: float, w: float, h: float, fill: str, r: float = 0.0) -> None:
        k = self.k
        box = [x * k, y * k, (x + w) * k - 1, (y + h) * k - 1]
        if r:
            self.d.rounded_rectangle(box, radius=r * k, fill=self._c(fill))
        else:
            self.d.rectangle(box, fill=self._c(fill))

    def ring(self, x: float, y: float, outer: float, width: float, fill: str, r: float = 0.0) -> None:
        k = self.k
        m = Image.new("L", self.img.size, 0)
        md = ImageDraw.Draw(m)
        md.rounded_rectangle([x * k, y * k, (x + outer) * k - 1, (y + outer) * k - 1], radius=r * k, fill=255)
        ri = max(0.0, r - width * 0.6)
        md.rounded_rectangle([(x + width) * k, (y + width) * k, (x + outer - width) * k - 1, (y + outer - width) * k - 1], radius=ri * k, fill=0)
        self.img.paste(Image.new("RGBA", self.img.size, self._c(fill)), mask=m)

    def circle(self, cx: float, cy: float, r: float, fill: str) -> None:
        k = self.k
        self.d.ellipse([(cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k], fill=self._c(fill))

    def stroke_circle(self, cx: float, cy: float, r: float, w: float, colour: str) -> None:
        k = self.k
        self.d.ellipse([(cx - r - w / 2) * k, (cy - r - w / 2) * k, (cx + r + w / 2) * k, (cy + r + w / 2) * k], outline=self._c(colour), width=max(1, round(w * k)))

    def line(self, x0: float, y0: float, x1: float, y1: float, w: float, colour: str) -> None:
        k = self.k
        self.d.line([x0 * k, y0 * k, x1 * k, y1 * k], fill=self._c(colour), width=max(1, round(w * k)))

    def polygon(self, pts: list[tuple[float, float]], fill: str) -> None:
        self.d.polygon([(x * self.k, y * self.k) for x, y in pts], fill=self._c(fill))

    def text(self, text: str, x: float, y: float, size: float, fill: str, font: Path | None = None) -> None:
        TR.draw_text(self.img, text, (x * self.k, y * self.k), size * self.k, self._c(fill), font, anchor="ms")

    def image(self, png: bytes, x: float, y: float, w: float, h: float) -> None:
        im = Image.open(io.BytesIO(png)).convert("RGBA")
        k = self.k
        bw, bh = max(1, round(w * k)), max(1, round(h * k))
        im.thumbnail((bw, bh), Image.LANCZOS)
        self.img.alpha_composite(im, (round(x * k + (bw - im.width) / 2), round(y * k + (bh - im.height) / 2)))

    def result(self) -> Image.Image:
        return self.img.resize(self.size, Image.LANCZOS) if self.ss > 1 else self.img


# ---------------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------------


def label_lines(url: str, style: QRStyle) -> list[tuple[str, float, Path | None]]:
    """(text, size_mm, font) per line beneath the symbol."""
    out: list[tuple[str, float, Path | None]] = []
    base = max(1.9, style.size_mm * 0.085)
    if style.label in LABELS:
        out.append((LABELS[style.label], base * (1.12 if style.label == "hi" else 1.0), None))
    if style.show_url:
        out.append((short_display(url), base * 0.78, FONT_URL))
    return out


def short_display(url: str) -> str:
    return url.replace("https://", "").replace("http://", "")


def dimensions(url: str, style: QRStyle) -> tuple[float, float]:
    """(width, height) in mm, label included."""
    lines = label_lines(url, style)
    h = style.size_mm + sum(s * 1.45 for _, s, _ in lines) + (0.6 if lines else 0)
    w = style.size_mm
    for t, s, f in lines:  # a long URL can be wider than a small symbol
        w = max(w, TR.text_width(t, s, f) + 1.0)
    return w, h


def emblem_box(sym: Symbol, style: QRStyle) -> tuple[int, int, int] | None:
    """(x, y, side) in modules of the knocked-out plate, aligned to the grid, area <= 15 %."""
    if style.emblem == "none" or (style.emblem == "upload" and not style.emblem_png):
        return None
    side = int(round(sym.n * style.emblem_scale))
    while side * side > MAX_EMBLEM_AREA * sym.n * sym.n:
        side -= 1
    if side % 2 != sym.n % 2:
        side -= 1
    side = max(3, side)
    o = (sym.n - side) // 2
    return (o, o, side)


def draw(url: str, style: QRStyle, cv: Any, paper: str = "#ffffff00") -> None:
    sym = encode(url, style.ec)
    W, _H = dimensions(url, style)
    mod = style.size_mm / (sym.n + 2 * style.quiet)
    ox = (W - style.size_mm) / 2 + style.quiet * mod
    oy = style.quiet * mod
    ink = style.colour
    box = emblem_box(sym, style)

    def covered(x: int, y: int) -> bool:
        return bool(box) and box[0] <= x < box[0] + box[2] and box[1] <= y < box[1] + box[2]

    # data modules
    for y, row in enumerate(sym.dark):
        for x, v in enumerate(row):
            if not v or _in_finder(sym, x, y) or covered(x, y):
                continue
            px, py = ox + x * mod, oy + y * mod
            if style.module == "dots":
                cv.circle(px + mod / 2, py + mod / 2, mod * 0.46, ink)
            elif style.module == "rounded":
                cv.rect(px, py, mod, mod, ink, r=mod * 0.32)
                # bridge to the right / below so runs read as connected strokes
                if x + 1 < sym.n and row[x + 1] and not _in_finder(sym, x + 1, y) and not covered(x + 1, y):
                    cv.rect(px + mod / 2, py, mod, mod, ink)
                if y + 1 < sym.n and sym.dark[y + 1][x] and not _in_finder(sym, x, y + 1) and not covered(x, y + 1):
                    cv.rect(px, py + mod / 2, mod, mod, ink)
            else:
                cv.rect(px, py, mod + 0.002, mod + 0.002, ink)
    # finders
    r_out = {"square": 0.0, "rounded": mod * 1.6, "dots": mod * 2.2}[style.module]
    for fx, fy in sym.finder:
        x, y = ox + fx * mod, oy + fy * mod
        cv.ring(x, y, 7 * mod, mod, ink, r=r_out)
        cv.rect(x + 2 * mod, y + 2 * mod, 3 * mod, 3 * mod, ink, r=r_out * 0.45)
    # emblem
    if box:
        bx, by, side = ox + box[0] * mod, oy + box[1] * mod, box[2] * mod
        cx, cy = bx + side / 2, by + side / 2
        inner = side * 0.82
        _emblem(cv, style, cx, cy, inner, ink)
    # label
    ty = style.size_mm + 0.2
    for text, size, font in label_lines(url, style):
        ty += size * 1.32
        cv.text(text, W / 2, ty, size, ink, font)


def _emblem(cv: Any, style: QRStyle, cx: float, cy: float, s: float, ink: str) -> None:
    r = s / 2
    if style.emblem == "chakra":
        cv.stroke_circle(cx, cy, r * 0.86, r * 0.16, ink)
        cv.circle(cx, cy, r * 0.2, ink)
        for i in range(24):
            a = 2 * math.pi * i / 24
            cv.line(cx + math.cos(a) * r * 0.2, cy + math.sin(a) * r * 0.2, cx + math.cos(a) * r * 0.8, cy + math.sin(a) * r * 0.8, r * 0.055, ink)
    elif style.emblem == "lotus":
        for i, ang in enumerate((-60, -30, 0, 30, 60)):
            L = r * (0.95 if ang == 0 else 0.82 if abs(ang) == 30 else 0.66)
            cv.polygon(_petal(cx, cy + r * 0.45, L, r * 0.26, ang), ink)
        cv.polygon([(cx - r * 0.85, cy + r * 0.5), (cx + r * 0.85, cy + r * 0.5), (cx + r * 0.55, cy + r * 0.72), (cx - r * 0.55, cy + r * 0.72)], ink)
    elif style.emblem == "om":
        sz = s * 0.95
        cv.text("ॐ", cx, cy + sz * 0.36, sz, ink, TR.FONT_HI)
    elif style.emblem == "upload" and style.emblem_png:
        cv.image(style.emblem_png, cx - r, cy - r, s, s)


def _petal(bx: float, by: float, length: float, width: float, angle_deg: float) -> list[tuple[float, float]]:
    a = math.radians(angle_deg)
    pts = []
    for i in range(25):
        t = i / 24
        px = math.sin(math.pi * t) * width * (1 - 0.35 * t)
        py = -length * t
        pts.append((px, py))
    pts += [(-x, y) for x, y in reversed(pts)]
    return [(bx + x * math.cos(a) - y * math.sin(a), by + x * math.sin(a) + y * math.cos(a)) for x, y in pts]


# ---------------------------------------------------------------------------------
# outputs
# ---------------------------------------------------------------------------------


def svg(url: str, style: QRStyle) -> str:
    style = style.normalised()
    w, h = dimensions(url, style)
    cv = SvgCanvas()
    draw(url, style, cv)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.3f}mm" height="{h:.3f}mm" viewBox="0 0 {w:.4f} {h:.4f}">'
            f'<title>{short_display(url)}</title>{"".join(cv.parts)}</svg>')


def raster(url: str, style: QRStyle, dpi: int = 600, background: str | Image.Image | None = None) -> Image.Image:
    """RGBA (transparent paper) or composited on `background` (a colour or a texture image)."""
    style = style.normalised()
    w, h = dimensions(url, style)
    cv = PilCanvas(w, h, dpi, ss=3 if dpi <= 300 else 2)
    draw(url, style, cv)
    img = cv.result()
    if background is None:
        return img
    if isinstance(background, Image.Image):
        bg = background.convert("RGB").resize(img.size, Image.LANCZOS) if background.size != img.size else background.convert("RGB")
    else:
        bg = Image.new("RGB", img.size, background)
    bg = bg.convert("RGBA")
    bg.alpha_composite(img)
    return bg.convert("RGB")


def parchment(size: tuple[int, int]) -> Image.Image:
    if PARCHMENT.exists():
        tex = Image.open(PARCHMENT).convert("RGB")
        # take a patch at the texture's own scale (about 600 dpi over the page) so the grain is realistic
        k = min(1.0, tex.width / (size[0] * 2), tex.height / (size[1] * 2))  # keep the aspect when the patch is large
        cw, ch = max(1, int(size[0] * 2 * k)), max(1, int(size[1] * 2 * k))
        x0, y0 = min(tex.width // 3, tex.width - cw), min(tex.height // 3, tex.height - ch)
        patch = tex.crop((x0, y0, x0 + cw, y0 + ch))
        return patch.resize(size, Image.LANCZOS)
    return Image.new("RGB", size, "#efe4c9")


PLATE_MM = 2.5  # parchment backing around a placed QR (feathered), so it scans even where it overlaps the art


def element_png(url: str, style: QRStyle, dpi: int = 600) -> bytes:
    """The page element: the QR on a soft-edged patch of the parchment (the margin is PLATE_MM on every side)."""
    base = raster(url, style, dpi)
    pad = round(PLATE_MM / 25.4 * dpi)
    W, H = base.width + 2 * pad, base.height + 2 * pad
    plate = parchment((W, H)).convert("RGBA")
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([pad // 2, pad // 2, W - pad // 2, H - pad // 2], radius=pad, fill=255)
    plate.putalpha(mask.filter(ImageFilter.GaussianBlur(pad / 3)))
    plate.alpha_composite(base, (pad, pad))
    buf = io.BytesIO()
    plate.save(buf, "PNG", dpi=(dpi, dpi))
    return buf.getvalue()


def png(url: str, style: QRStyle, dpi: int = 600) -> bytes:
    buf = io.BytesIO()
    raster(url, style, dpi).save(buf, "PNG", dpi=(dpi, dpi))
    return buf.getvalue()


def pdf(url: str, style: QRStyle, dpi: int = 600) -> bytes:
    """The symbol at its printed size (raster at 600 dpi on white; vector SVG is the other export)."""
    img = raster(url, style, dpi, background="#ffffff")
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=float(dpi))
    return buf.getvalue()


def preview_png(url: str, style: QRStyle, dpi: int = 200) -> bytes:
    """On the parchment, as it will look printed."""
    base = raster(url, style, dpi)
    out = parchment(base.size).convert("RGBA")
    out.alpha_composite(base)
    buf = io.BytesIO()
    out.convert("RGB").save(buf, "PNG", dpi=(dpi, dpi))
    return buf.getvalue()


# ---------------------------------------------------------------------------------
# decode test
# ---------------------------------------------------------------------------------


def decoder_available() -> bool:
    try:
        import zxingcpp  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def decode(img: Image.Image) -> list[str]:
    import zxingcpp

    res = zxingcpp.read_barcodes(img.convert("L"))
    return [r.text for r in res if r.valid]


def decode_test(url: str, style: QRStyle, dpis: tuple[int, ...] = TEST_DPIS) -> dict[str, Any]:
    """Rasterise at the printed size on the parchment at each dpi and read it back. ok only if every read is exact."""
    style = style.normalised()
    out: dict[str, Any] = {"url": url, "size_mm": style.size_mm, "dpis": {}, "decoder": "zxing-cpp"}
    if not decoder_available():
        out.update(ok=False, error="zxing-cpp is not installed; the QR cannot be verified")
        return out
    ok = True
    for dpi in dpis:
        base = raster(url, style, dpi)
        bg = parchment(base.size).convert("RGBA")
        bg.alpha_composite(base)
        img = bg.convert("RGB").filter(ImageFilter.GaussianBlur(0.35 * dpi / 300))  # a little ink spread
        texts = decode(img)
        good = url in texts
        out["dpis"][str(dpi)] = {"ok": good, "read": texts[0] if texts else None, "px": list(img.size)}
        ok = ok and good
    out["ok"] = ok
    return out


def rasterise_svg_upload(raw: bytes, px: int = 512) -> bytes:
    """An uploaded SVG emblem -> PNG via the studio's Chromium (Playwright or the downloaded headless shell)."""
    import tempfile

    svg_txt = raw.decode("utf-8", "replace")
    html = f"<html><body style='margin:0;background:transparent'><div style='width:{px}px;height:{px}px'>{svg_txt}</div><style>svg{{width:100%;height:100%}}</style></body></html>"
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": px, "height": px})
            pg.set_content(html)
            data = pg.screenshot(omit_background=True)
            b.close()
            return data
    except Exception:  # noqa: BLE001
        pass
    from engine import pdf_engine
    import subprocess

    binary = pdf_engine.installed()
    if not binary:
        raise ValueError("SVG emblems need the studio's PDF engine (export a PDF once) — or upload a PNG")
    with tempfile.TemporaryDirectory() as d:
        hp = Path(d) / "e.html"
        hp.write_text(html)
        shot = Path(d) / "e.png"
        subprocess.run([str(binary), "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--default-background-color=00000000",
                        f"--window-size={px},{px}", f"--screenshot={shot}", hp.as_uri()], check=True, timeout=60, capture_output=True)
        return shot.read_bytes()
