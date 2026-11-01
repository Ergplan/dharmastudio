"""Stitch — graphic-novel art added to the white space of a finished, typeset book PDF.

The author's paperback interior (6x9, typeset elsewhere: fonts, paper and text are final) is never re-typeset. This
engine only ADDS images on top of its pages with PyMuPDF, in space the text leaves empty:

- **strip**    a wide torn-out piece in the open space above a chapter heading (openers have a deep top margin);
- **collage**  2–4 torn-out pieces on an aged, torn old-paper backing, slightly tilted, with soft shadows, joined by
               red cross-stitches with needle holes — at a chapter end where the text leaves the bottom of the page blank;
- **icon**     a small torn-edged medallion in the top outer corner of a text page (outer = right on odd pages);
- **torn**     one torn-out piece (any slot);
- **plate**    a whole painting as one large torn-out piece on its own page with an italic caption. Plates go in as a
               facing PAIR after an odd page, so every later page keeps its side (the PDF's margins alternate).

The pieces are crops of the paintings (a crop box around a clear subject, or the most detailed window when none is
given), lightly aged (sepia, gentle vignette) and sharpened; art is rasterised at 300 dpi.

`analyse(pdf)` finds the text and the blank areas per page and suggests the slots; `render_placement` draws one
placement; `render(src, project, loader)` applies every placement and plate to a copy of the source PDF.
Ported (and cleaned up) from the author's own script for the Book One paperback sample.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent
TEXTURE = ROOT / "textures" / "page_warm.jpg"
CAPTION_FONT = ROOT / "comic" / "fonts" / "library" / "EBGaramond-Italicwght.ttf"

DPI = 300 / 72                   # art pixels per PDF point (300 dpi)
STYLES = ("strip", "collage", "icon", "torn")
SLOT_KINDS = {"top": "strip", "bottom": "collage", "corner": "icon"}
OLD = (236, 218, 180, 255)       # old paper (medallion rim)
STITCH = (120, 28, 20, 255)      # the red thread
HOLE = (40, 20, 10, 255)         # needle holes
INK = (40, 30, 20)

Loader = Callable[[str], Image.Image]   # photo id -> RGB image


# ---------------------------------------------------------------------------------
# small image helpers
# ---------------------------------------------------------------------------------


def png_bytes(im: Image.Image) -> bytes:
    b = io.BytesIO()
    im.save(b, "PNG", optimize=False, compress_level=6)
    return b.getvalue()


def _texture() -> Image.Image:
    global _TEX
    if _TEX is None:
        _TEX = Image.open(TEXTURE).convert("RGB") if TEXTURE.exists() else Image.new("RGB", (1200, 1800), OLD[:3])
    return _TEX


_TEX: Image.Image | None = None


def old_paper(w: int, h: int, seed: int) -> Image.Image:
    """A w x h piece of the warm aged-paper texture (a random window of it)."""
    r = random.Random(seed)
    tex = _texture()
    t = tex.resize((max(w, tex.width), max(h, tex.height)))
    x, y = r.randint(0, t.width - w), r.randint(0, t.height - h)
    return t.crop((x, y, x + w, y + h))


def torn_mask(w: int, h: int, seed: int, amp: float = 10) -> Image.Image:
    """A naturally torn edge: a slow random walk for the tear plus fine fibre jitter, on all four sides."""
    rnd = random.Random(seed)
    amp = max(2.0, float(amp))

    def edge(n: int) -> list[float]:
        v, out = 0.0, []
        for _ in range(n):
            v = max(0.0, min(amp, v + rnd.uniform(-0.35, 0.35) * amp))
            out.append(v + rnd.uniform(0, amp * 0.18))
        return out

    st = 3
    pts: list[tuple[float, float]] = []
    e = edge(w // st + 1)
    pts += [(x, e[i]) for i, x in enumerate(range(0, w, st))]
    e = edge(h // st + 1)
    pts += [(w - e[i], y) for i, y in enumerate(range(0, h, st))]
    e = edge(w // st + 1)
    pts += [(x, h - e[i]) for i, x in enumerate(range(w, 0, -st))]
    e = edge(h // st + 1)
    pts += [(e[i], y) for i, y in enumerate(range(h, 0, -st))]
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return m.filter(ImageFilter.GaussianBlur(0.9))


def with_shadow(rgba: Image.Image, off: tuple[int, int] = (6, 9), blur: int = 10, alpha: int = 110, pad: int = 30) -> Image.Image:
    """The piece on a transparent canvas `pad` px larger on each side, with a soft warm-brown drop shadow."""
    W, H = rgba.size
    out = Image.new("RGBA", (W + 2 * pad, H + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("L", out.size, 0)
    sh.paste(rgba.split()[3], (pad + off[0], pad + off[1]))
    sh = sh.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: v * alpha // 255)
    out.paste(Image.new("RGBA", out.size, (40, 26, 12, 255)), (0, 0), sh)
    out.alpha_composite(rgba, (pad, pad))
    return out


def age(pic: Image.Image, sepia: float = 0.14, vignette: float = 0.25) -> Image.Image:
    """Lightly aged: blended toward a sepia toning by `sepia` (0..1), edges darkened by a gentle vignette."""
    pic = pic.convert("RGB")
    sep = ImageOps.colorize(ImageOps.grayscale(pic), (60, 38, 18), (240, 222, 186))
    out = Image.blend(pic, sep, max(0.0, min(1.0, sepia)))
    if vignette <= 0:
        return out
    w, h = out.size
    v = Image.new("L", (w, h), 0)
    ImageDraw.Draw(v).ellipse([-w * 0.25, -h * 0.25, w * 1.25, h * 1.25], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(max(1, min(w, h) * 0.12)))
    return Image.composite(out, Image.blend(out, Image.new("RGB", (w, h), (70, 44, 20)), vignette), v)


def sharpen(im: Image.Image) -> Image.Image:
    return im.filter(ImageFilter.UnsharpMask(2, 70, 2))


# ---------------------------------------------------------------------------------
# crops: around a chosen subject box, or the most detailed window
# ---------------------------------------------------------------------------------


def norm_crop(c: Any) -> dict[str, float] | None:
    """A crop box in fractions of the photo {x, y, w, h}, clamped inside it; None for none / invalid."""
    if not isinstance(c, dict):
        return None
    try:
        x, y, w, h = (float(c.get(k, 0)) for k in ("x", "y", "w", "h"))
    except (TypeError, ValueError):
        return None
    w, h = max(0.01, min(1.0, w)), max(0.01, min(1.0, h))
    x, y = max(0.0, min(1.0 - w, x)), max(0.0, min(1.0 - h, y))
    return {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}


def detail_window(im: Image.Image, aspect: float) -> dict[str, float]:
    """The window of aspect w/h with the most detail and skin tone (a fallback subject when none is chosen)."""
    import numpy as np

    small = im.convert("RGB")
    small.thumbnail((320, 320))
    a = np.asarray(small).astype(np.float32)
    H0, W0 = a.shape[:2]
    g = a.mean(axis=2)
    det = np.zeros_like(g)
    det[:, 1:] += np.abs(np.diff(g, axis=1))
    det[1:, :] += np.abs(np.diff(g, axis=0))
    r, gg, b = a[..., 0], a[..., 1], a[..., 2]
    skin = ((r > 95) & (gg > 40) & (b > 20) & (r > gg) & (r > b) & ((r - gg) > 15) & ((r - b) > 40) & (r < 250)).astype(np.float32)
    score = det / (det.mean() + 1e-6) + 3.0 * skin
    ii = np.zeros((H0 + 1, W0 + 1), np.float64)
    ii[1:, 1:] = score.cumsum(0).cumsum(1)
    # the largest window of this aspect, zoomed in a little so the piece reads as a detail
    cw = min(W0, H0 * aspect) / 1.3
    ch = cw / aspect
    cw, ch = int(max(4, cw)), int(max(4, ch))
    best = (-1.0, 0, 0)
    step = max(2, min(W0 - cw, H0 - ch) // 14 + 1)
    for y in range(0, H0 - ch + 1, step):
        for x in range(0, W0 - cw + 1, step):
            v = ii[y + ch, x + cw] - ii[y, x + cw] - ii[y + ch, x] + ii[y, x]
            if v > best[0]:
                best = (v, x, y)
    _, x, y = best
    return {"x": x / W0, "y": y / H0, "w": cw / W0, "h": ch / H0}


def fit_crop(im: Image.Image, crop: dict[str, float] | None, w: int, h: int) -> Image.Image:
    """The photo cut to exactly w x h px around the crop box's centre (the box grown to the piece's aspect)."""
    im = im.convert("RGB")
    W0, H0 = im.size
    c = norm_crop(crop) or detail_window(im, w / h)
    cx, cy = (c["x"] + c["w"] / 2) * W0, (c["y"] + c["h"] / 2) * H0
    bw, bh = c["w"] * W0 * 1.05, c["h"] * H0 * 1.05
    if bw / bh > w / h:
        bh = bw * h / w
    else:
        bw = bh * w / h
    if bw > W0:
        bw, bh = W0, W0 * h / w
    if bh > H0:
        bh, bw = H0, H0 * w / h
    x0 = max(0.0, min(W0 - bw, cx - bw / 2))
    y0 = max(0.0, min(H0 - bh, cy - bh / 2))
    return sharpen(im.crop((int(x0), int(y0), int(x0 + bw), int(y0 + bh))).resize((w, h), Image.LANCZOS))


# ---------------------------------------------------------------------------------
# the pieces
# ---------------------------------------------------------------------------------


def torn_piece(im: Image.Image, crop: dict[str, float] | None, w: int, h: int, seed: int, sepia: float = 0.14, tilt: float = 0.0) -> Image.Image:
    """A torn-out piece of the painting: the picture inside a thin torn rim of old paper, with a drop shadow."""
    w, h = max(40, int(w)), max(40, int(h))
    pic = age(fit_crop(im, crop, w, h), sepia)
    m = torn_mask(w, h, seed, amp=w * 0.012 + 6)
    inner = m.filter(ImageFilter.MinFilter(15))
    rgba = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rgba.paste(old_paper(w, h, seed).convert("RGBA"), (0, 0), m)
    rgba.paste(pic.convert("RGBA"), (0, 0), inner)
    rgba = with_shadow(rgba)
    return rgba.rotate(tilt, resample=Image.BICUBIC, expand=True) if tilt else rgba


def medallion(im: Image.Image, crop: dict[str, float] | None, d: int, seed: int, sepia: float = 0.14) -> Image.Image:
    """A small round icon with a torn rim of old paper and a thin ink ring."""
    d = max(40, int(d))
    pic = age(fit_crop(im, crop, d, d), sepia, vignette=0.15)
    rnd = random.Random(seed)
    pts = []
    for k in range(36):
        a = 2 * math.pi * k / 36
        r = d / 2 - rnd.uniform(0, d * 0.05)
        pts.append((d / 2 + r * math.cos(a), d / 2 + r * math.sin(a)))
    m = Image.new("L", (d, d), 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(0.6))
    inner = m.filter(ImageFilter.MinFilter(9))
    rgba = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    rgba.paste(Image.new("RGBA", (d, d), OLD), (0, 0), m)
    rgba.paste(pic.convert("RGBA"), (0, 0), inner)
    ImageDraw.Draw(rgba).ellipse([d * 0.06, d * 0.06, d * 0.94, d * 0.94], outline=(92, 52, 22, 200), width=max(2, d // 90))
    return with_shadow(rgba, off=(3, 5), blur=6, alpha=90, pad=16)


def stitch_line(d: ImageDraw.ImageDraw, p0: tuple[float, float], p1: tuple[float, float], seed: int, gap: float = 38, arm: float = 15, wid: int = 6) -> None:
    """Red cross-stitches along a seam from p0 to p1, each arm ending in a needle hole."""
    r = random.Random(seed)
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if L < 1:
        return
    n = max(2, int(L / gap))
    ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
    nx, ny = -uy, ux
    for i in range(1, n):
        cx, cy = p0[0] + ux * L * i / n, p0[1] + uy * L * i / n
        a = arm * r.uniform(0.85, 1.15)
        for sgn in (1, -1):
            q0 = (cx - ux * a * 0.7 - sgn * nx * a, cy - uy * a * 0.7 - sgn * ny * a)
            q1 = (cx + ux * a * 0.7 + sgn * nx * a, cy + uy * a * 0.7 + sgn * ny * a)
            d.line([q0, q1], fill=STITCH, width=wid)
            for q in (q0, q1):
                d.ellipse([q[0] - 3.5, q[1] - 3.5, q[0] + 3.5, q[1] + 3.5], fill=HOLE)


def collage(pieces: list[tuple[Image.Image, dict[str, float] | None]], W: int, H: int, seed: int, sepia: float = 0.14) -> Image.Image:
    """2–4 torn-out pieces sewn onto an aged, torn old-paper backing (stains, tilts, shadows, cross-stitched seams)."""
    W, H = max(80, int(W)), max(80, int(H))
    rnd = random.Random(seed)
    sheet = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sm = torn_mask(W, H, seed, amp=W * 0.02 + 8)
    sheet.paste(old_paper(W, H, seed).convert("RGBA"), (0, 0), sm)
    # stains and foxing on the backing sheet
    st = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(st)
    for _ in range(14):
        x, y, rr = rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(W * 0.01, W * 0.06)
        sd.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(120, 80, 30, rnd.randint(12, 34)))
    sheet.alpha_composite(Image.composite(st.filter(ImageFilter.GaussianBlur(8)), Image.new("RGBA", (W, H), (0, 0, 0, 0)), sm))
    n = max(1, min(4, len(pieces)))
    cols = 1 if n == 1 else 2
    rows = math.ceil(n / cols)
    xs = [0.0, rnd.uniform(0.38, 0.62) * W, float(W)] if cols == 2 else [0.0, float(W)]
    ys = [0.0] + [H * (k / rows) * rnd.uniform(0.92, 1.08) for k in range(1, rows)] + [float(H)]
    pad = int(W * 0.045)
    seams = []
    k = 0
    for ri in range(rows):
        for ci in range(cols):
            if k >= n:
                break
            x0, x1 = int(xs[ci]) + pad, int(xs[ci + 1]) - pad // 3
            y0, y1 = int(ys[ri]) + pad, int(ys[ri + 1]) - pad // 3
            if ri == rows - 1 and k == n - 1 and ci < cols - 1:   # an odd last piece spans its row
                x1 = W - pad
            pw, ph = max(40, x1 - x0 + int(W * 0.03)), max(40, y1 - y0 + int(H * 0.03))
            im, crop = pieces[k]
            pic = age(fit_crop(im, crop, pw, ph), sepia)
            m = torn_mask(pw, ph, seed + 7 * k, amp=pw * 0.025 + 7)
            inner = m.filter(ImageFilter.MinFilter(9))
            piece = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
            piece.paste(old_paper(pw, ph, seed + k).convert("RGBA"), (0, 0), m)
            piece.paste(pic.convert("RGBA"), (0, 0), inner)
            piece = with_shadow(piece, off=(4, 6), blur=7, alpha=120, pad=24).rotate(rnd.uniform(-3.5, 3.5), resample=Image.BICUBIC, expand=True)
            px, py = x0 - 24 + rnd.randint(-6, 6), y0 - 24 + rnd.randint(-6, 6)
            sheet.alpha_composite(piece, (max(0, min(W - piece.width, px)), max(0, min(H - piece.height, py))))
            if ci > 0:
                seams.append(((xs[ci], y0 + ph * 0.1), (xs[ci], y0 + ph * 0.9)))
            if ri > 0:
                seams.append(((x0 + pw * 0.1, ys[ri]), (x0 + pw * 0.9, ys[ri])))
            k += 1
    d = ImageDraw.Draw(sheet)
    for j, (a, b) in enumerate(seams):
        stitch_line(d, a, b, seed + j)
    # a running stitch along the top and bottom of the backing sheet
    for a, b in (((pad * 0.5, pad * 0.5), (W - pad * 0.5, pad * 0.5)), ((pad * 0.5, H - pad * 0.5), (W - pad * 0.5, H - pad * 0.5))):
        L = b[0] - a[0]
        m_ = max(2, int(L / 30))
        for i in range(0, m_, 2):
            d.line([(a[0] + L * i / m_, a[1]), (a[0] + L * (i + 1) / m_, a[1])], fill=(110, 30, 22, 230), width=3)
    return with_shadow(sheet, off=(6, 10), blur=12, alpha=110)


# ---------------------------------------------------------------------------------
# analysis: text, blank areas, slots
# ---------------------------------------------------------------------------------

FOLIO_RE = re.compile(r"^\s*([0-9]{1,4}|[ivxlcdm]{1,7})\s*$", re.I)
MIN_STRIP_H = 50        # pt of open space above an opener's heading for a strip
MIN_END_FREE = 150      # pt of blank space under the last line for a collage
GAP = 12                # pt kept clear between art and any text or existing image
EDGE = 14               # pt kept clear of the paper edge


def _r(v: Iterable[float]) -> list[float]:
    return [round(float(x), 2) for x in v]


def _page_blocks(page: fitz.Page) -> tuple[list[list[float]], list[list[float]], str]:
    """(body text blocks, folio blocks, body text) — a folio is a lone page number near the top or bottom edge."""
    H = page.rect.height
    body, folio, text = [], [], []
    for b in page.get_text("blocks"):
        t = (b[4] or "").strip()
        if not t or b[6] != 0:
            continue
        if FOLIO_RE.match(t) and (b[1] > H * 0.85 or b[3] < H * 0.12):
            folio.append(_r(b[:4]))
            continue
        body.append(_r(b[:4]))
        text.append(t)
    return body, folio, "\n\n".join(text)


def _images(page: fitz.Page) -> list[list[float]]:
    out = []
    for info in page.get_image_info():
        r = fitz.Rect(info["bbox"]) & page.rect
        if not r.is_empty and r.width > 2 and r.height > 2:
            out.append(_r(r))
    for dr in page.get_drawings():  # vector ornaments / rules count as content too
        r = fitz.Rect(dr.get("rect") or (0, 0, 0, 0)) & page.rect
        if not r.is_empty and r.width * r.height > 20 and r.width < page.rect.width * 0.98:
            out.append(_r(r))
    return out


def _percentile(vals: list[float], q: float, default: float) -> float:
    if not vals:
        return default
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))]


def _clear(rect: list[float], boxes: list[list[float]]) -> bool:
    R = fitz.Rect(rect)
    return all(not R.intersects(fitz.Rect(b)) for b in boxes)


def analyse(pdf: str | Path | bytes) -> dict[str, Any]:
    """Every page: text blocks, folio, existing images, the blank space above (an opener) and below (a chapter end),
    the outer side, and the suggested slots (top strip / bottom collage / corner icon) as rectangles in PDF points."""
    doc = fitz.open(stream=pdf, filetype="pdf") if isinstance(pdf, (bytes, bytearray)) else fitz.open(str(pdf))
    raw = []
    for i, page in enumerate(doc):
        body, folio, text = _page_blocks(page)
        raw.append((page, body, folio, text, _images(page)))
    tops = [min(b[1] for b in body) for _, body, *_ in raw if body]
    bottoms = [max(b[3] for b in body) for _, body, *_ in raw if body]
    # the text column of each side (recto / verso margins alternate)
    cols = {}
    for parity in (0, 1):
        ls = [min(b[0] for b in r[1]) for i, r in enumerate(raw) if r[1] and (i + 1) % 2 == parity]
        rs = [max(b[2] for b in r[1]) for i, r in enumerate(raw) if r[1] and (i + 1) % 2 == parity]
        cols[parity] = (_percentile(ls, 0.5, 54), _percentile(rs, 0.5, 378))
    H0 = doc[0].rect.height if len(doc) else 648
    body_top = _percentile(tops, 0.1, 54)          # where the text of a full page starts
    body_bottom = _percentile(bottoms, 0.9, H0 - 48)  # and where it ends
    pages = []
    chapter = None
    for i, (page, body, folio, text, imgs) in enumerate(raw):
        W, H = page.rect.width, page.rect.height
        n = i + 1
        recto = n % 2 == 1
        info: dict[str, Any] = {"n": n, "w": round(W, 2), "h": round(H, 2), "side": "recto" if recto else "verso", "outer": "right" if recto else "left",
                                "blocks": body, "folio": folio, "images": imgs, "text": text[:4000], "kind": "blank", "slots": [],
                                "free_top": 0.0, "free_bottom": 0.0, "text_bbox": None, "chapter": None}
        if not body:
            info["chapter"] = chapter
            pages.append(info)
            continue
        x0, y0 = min(b[0] for b in body), min(b[1] for b in body)
        x1, y1 = max(b[2] for b in body), max(b[3] for b in body)
        info["text_bbox"] = _r((x0, y0, x1, y1))
        content = body + imgs
        top = min(b[1] for b in content)
        bottom = max(b[3] for b in body + [im for im in imgs if im[1] >= y0])
        folio_top = min((f[1] for f in folio if f[1] > H / 2), default=H)
        floor = min(folio_top - GAP, max(body_bottom, y1), H - EDGE)
        opener = y0 > body_top + 50
        info["free_top"] = round(max(0.0, top - EDGE), 2)
        info["free_bottom"] = round(max(0.0, floor - bottom), 2)
        if opener:
            first = text.split("\n\n")[0] if text else ""
            chapter = " ".join(first.split())[:80] or chapter
        info["chapter"] = chapter
        others = body + folio + imgs
        tl, tr = cols[n % 2]
        col_l, col_r = max(EDGE, min(x0, tl)), min(W - EDGE, max(x1, tr))
        kind = "text"
        if opener:
            kind = "opener"
            rect = _r((col_l, EDGE + 4, col_r, top - GAP))
            if rect[3] - rect[1] >= MIN_STRIP_H and _clear(rect, others):
                info["slots"].append({"id": "top", "kind": "strip", "rect": rect, "label": "Above the heading"})
        if info["free_bottom"] >= MIN_END_FREE:
            kind = "end" if not opener else kind
            rect = _r((col_l, bottom + GAP, col_r, floor))
            if _clear(rect, others):
                info["slots"].append({"id": "bottom", "kind": "collage", "rect": rect, "label": "Blank space under the text"})
        if not opener and top >= 36:
            d = min(46.0, top - 12)
            cx0 = W - 8 - d if recto else 8.0
            rect = _r((cx0, 6, cx0 + d, 6 + d))
            if _clear(rect, others):
                info["slots"].append({"id": "corner", "kind": "icon", "rect": rect, "label": f"Top outer corner ({info['outer']})"})
        info["kind"] = kind
        pages.append(info)
    return {"pages": pages, "count": len(doc), "size": [round(doc[0].rect.width, 2), round(doc[0].rect.height, 2)] if len(doc) else [432, 648],
            "body": {"top": round(body_top, 2), "bottom": round(body_bottom, 2)}}


# ---------------------------------------------------------------------------------
# placements
# ---------------------------------------------------------------------------------


@dataclass
class Rendered:
    rect: tuple[float, float, float, float]   # where the image goes on the page (PDF points)
    png: bytes


def default_style(slot_kind: str) -> str:
    return {"strip": "strip", "collage": "collage", "icon": "icon"}.get(slot_kind, "torn")


def placement_key(pl: dict[str, Any]) -> str:
    """A stable hash of everything that changes the picture of a placement (the render cache key)."""
    keep = {k: pl.get(k) for k in ("rect", "style", "pieces", "tilt", "size", "sepia", "seed")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _fit(im: Image.Image, box: tuple[float, float, float, float], align_y: str = "center") -> tuple[float, float, float, float]:
    """The rect (pt) of the image scaled down (never up past 300 dpi) to fit inside box, centred."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    iw, ih = im.width / DPI, im.height / DPI
    s = min(1.0, bw / iw, bh / ih)
    iw, ih = iw * s, ih * s
    x = x0 + (bw - iw) / 2
    y = y0 + (bh - ih) / 2 if align_y == "center" else (y1 - ih if align_y == "bottom" else y0)
    return (round(x, 3), round(y, 3), round(x + iw, 3), round(y + ih, 3))


def render_placement(pl: dict[str, Any], loader: Loader) -> Rendered:
    """Draw one placement: its pieces in its style, sized to `size` of its slot rect, fitted inside the rect."""
    x0, y0, x1, y1 = (float(v) for v in pl["rect"])
    sw, sh = max(10.0, x1 - x0), max(10.0, y1 - y0)
    size = max(0.3, min(1.0, float(pl.get("size") or 1.0)))
    tilt = max(-12.0, min(12.0, float(pl.get("tilt") or 0.0)))
    sepia = max(0.0, min(0.8, float(pl.get("sepia") if pl.get("sepia") is not None else 0.14)))
    seed = int(pl.get("seed") or 1)
    style = pl.get("style") if pl.get("style") in STYLES else "torn"
    pieces = [(loader(p["photo"]), norm_crop(p.get("crop"))) for p in pl.get("pieces") or [] if p.get("photo")]
    if not pieces:
        raise ValueError("a placement needs at least one photo")
    # the drawable box: `size` of the slot, centred (the shadow padding and the tilt eat into it)
    bw, bh = sw * size, sh * size
    pad = 60 / DPI   # shadow padding of torn pieces, both sides (pt)
    if style == "icon":
        dpt = max(12.0, min(bw, bh) - 32 / DPI)
        im = medallion(pieces[0][0], pieces[0][1], int(dpt * DPI), seed, sepia)
        if tilt:
            im = im.rotate(tilt, resample=Image.BICUBIC, expand=True)
    elif style == "collage":
        hpt = max(40.0, min(bh, 300.0) - 24 / DPI)
        wpt = max(40.0, min(bw - 24 / DPI, hpt * 1.15 if bw > hpt * 1.15 else bw - 24 / DPI))
        im = collage(pieces[:4], int(wpt * DPI), int(hpt * DPI), seed, sepia)
        if tilt:
            im = im.rotate(tilt, resample=Image.BICUBIC, expand=True)
    elif style == "strip":
        wpt = max(40.0, bw - pad)
        hpt = max(30.0, min(bh - pad, wpt * 0.5))
        im = torn_piece(pieces[0][0], pieces[0][1], int(wpt * DPI), int(hpt * DPI), seed, sepia, tilt)
    else:  # torn: one piece, landscape-ish, as large as the box allows
        hpt = max(30.0, bh - pad)
        wpt = max(30.0, min(bw - pad, hpt * 1.5))
        im = torn_piece(pieces[0][0], pieces[0][1], int(wpt * DPI), int(hpt * DPI), seed, sepia, tilt)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    box = (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
    return Rendered(_fit(im, box), png_bytes(im))


def plate_art(im: Image.Image, crop: dict[str, float] | None, page_w: float, page_h: float, seed: int, tilt: float, sepia: float = 0.1) -> tuple[Image.Image, tuple[float, float, float, float]]:
    """A full-page plate: the painting as one large torn-out piece (its own aspect) in the upper page, room for a caption."""
    c = norm_crop(crop) or {"x": 0, "y": 0, "w": 1, "h": 1}
    aspect = (c["w"] * im.width) / max(1.0, c["h"] * im.height)
    maxw, maxh = page_w * 0.78, page_h * 0.78
    w = maxw
    h = w / aspect
    if h > maxh:
        h = maxh
        w = h * aspect
    art = torn_piece(im, c, int(w * DPI), int(h * DPI), seed, sepia, tilt)
    iw, ih = art.width / DPI, art.height / DPI
    s = min(1.0, page_w * 0.9 / iw, page_h * 0.84 / ih)
    iw, ih = iw * s, ih * s
    x = (page_w - iw) / 2
    y = max(24.0, (page_h - ih - 40) / 2 - 6)
    return art, (x, y, x + iw, y + ih)


def add_caption(page: fitz.Page, text: str, top: float) -> None:
    """The plate's caption: real italic text, centred under the picture (shrinks to fit two lines)."""
    text = " ".join((text or "").split())
    if not text:
        return
    W, H = page.rect.width, page.rect.height
    font = "F0"
    if CAPTION_FONT.exists():
        page.insert_font(fontname="stitchcap", fontfile=str(CAPTION_FONT))
        font = "stitchcap"
    else:
        font = "tiit"  # Times italic (base-14)
    box = fitz.Rect(W * 0.12, top + 4, W * 0.88, min(H - 18, top + 4 + 40))
    for size in (12.5, 11.5, 10.5, 9.5, 8.5):
        if page.insert_textbox(box, text, fontname=font, fontsize=size, align=fitz.TEXT_ALIGN_CENTER, color=tuple(c / 255 for c in INK)) >= 0:
            return
    page.insert_textbox(box, text[:120], fontname=font, fontsize=8, align=fitz.TEXT_ALIGN_CENTER, color=tuple(c / 255 for c in INK))


def plate_ok(after: int, count: int) -> str | None:
    """Plates go in as a facing pair after an odd page (so the pair is a spread and every later page keeps its side)."""
    if after < 1 or after > count:
        return f"after must be a page of the book (1–{count})"
    if after % 2 == 0:
        return "a plate pair goes after an odd (right-hand) page, so every later page keeps its side"
    return None


def plate_tilt(item: dict[str, Any], j: int) -> float:
    t = item.get("tilt")
    return max(-8.0, min(8.0, float(t))) if t is not None else (-1.3, 1.2)[j % 2]


def draw_plate_page(page: fitz.Page, item: dict[str, Any], loader: Loader, seed: int, tilt: float) -> None:
    W, H = page.rect.width, page.rect.height
    im = loader(item["photo"])
    art, rect = plate_art(im, item.get("crop"), W, H, seed, tilt, float(item.get("sepia") if item.get("sepia") is not None else 0.1))
    page.insert_image(fitz.Rect(*rect), stream=png_bytes(art), overlay=True)
    add_caption(page, str(item.get("caption") or ""), rect[3] - 4)


def apply_placements(page: fitz.Page, placements: list[dict[str, Any]], loader: Loader, cache: Callable[[dict[str, Any]], Rendered] | None = None) -> list[str]:
    """Insert every placement's art on the page (overlay; the page's text and images are untouched). Returns errors."""
    errs = []
    for pl in placements:
        try:
            r = cache(pl) if cache else render_placement(pl, loader)
        except Exception as exc:  # noqa: BLE001 — a missing photo must not stop the book
            errs.append(f"page {pl.get('page')} {pl.get('id')}: {exc}")
            continue
        page.insert_image(fitz.Rect(*r.rect), stream=r.png, overlay=True)
    return errs


def render(src: str | Path, project: dict[str, Any], loader: Loader, progress: Callable[[int, int, str], None] | None = None,
           cache: Callable[[dict[str, Any]], Rendered] | None = None) -> tuple[bytes, list[str]]:
    """The finished PDF: a copy of the source with every placement added and every plate pair inserted.
    Text, fonts and page sizes are untouched. Returns (pdf bytes, errors)."""
    src_doc = fitz.open(str(src))
    out = fitz.open()
    out.insert_pdf(src_doc)
    count = len(out)
    by_page: dict[int, list[dict[str, Any]]] = {}
    for pl in project.get("placements") or []:
        by_page.setdefault(int(pl["page"]), []).append(pl)
    plates = sorted(project.get("plates") or [], key=lambda p: int(p["after"]), reverse=True)
    total = len(by_page) + len(plates) + 1
    errors: list[str] = []
    for k, (n, pls) in enumerate(sorted(by_page.items())):
        if progress:
            progress(k, total, f"page {n}: {len(pls)} piece(s)")
        if 1 <= n <= count:
            errors += apply_placements(out[n - 1], pls, loader, cache)
    for k, pp in enumerate(plates):   # from the back, so earlier insertions do not move later ones
        after = int(pp["after"])
        if progress:
            progress(len(by_page) + k, total, f"plate pair after page {after}")
        bad = plate_ok(after, count)
        if bad:
            errors.append(f"plates {pp.get('id')}: {bad}")
            continue
        ref = src_doc[after - 1].rect
        for j, item in enumerate((pp.get("items") or [])[:2]):
            out.insert_page(after + j, width=ref.width, height=ref.height)
            if item.get("photo"):
                try:
                    draw_plate_page(out[after + j], item, loader, int(pp.get("seed") or 777) + j, plate_tilt(item, j))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"plates {pp.get('id')}[{j}]: {exc}")
        if len((pp.get("items") or [])[:2]) < 2:   # always a pair: a missing second plate is an empty facing page
            for j in range(len((pp.get("items") or [])[:2]), 2):
                out.insert_page(after + j, width=ref.width, height=ref.height)
    if progress:
        progress(total - 1, total, "saving")
    data = out.tobytes(garbage=3, deflate=True)
    return data, errors


def page_png(src: str | Path, n: int, placements: list[dict[str, Any]], loader: Loader, dpi: int = 110,
             cache: Callable[[dict[str, Any]], Rendered] | None = None) -> bytes:
    """One page of the source (1-based) with its placements, as a PNG (the live preview)."""
    src_doc = fitz.open(str(src))
    doc = fitz.open()
    doc.insert_pdf(src_doc, from_page=n - 1, to_page=n - 1)
    if placements:
        apply_placements(doc[0], placements, loader, cache)
    return doc[0].get_pixmap(dpi=dpi, alpha=False).tobytes("png")


def plate_png(src: str | Path, after: int, item: dict[str, Any] | None, loader: Loader, seed: int, tilt: float, dpi: int = 110) -> bytes:
    """One plate page as a PNG (same size as the page it follows)."""
    ref = fitz.open(str(src))[after - 1].rect
    doc = fitz.open()
    doc.new_page(width=ref.width, height=ref.height)
    if item and item.get("photo"):
        draw_plate_page(doc[0], item, loader, seed, tilt)
    return doc[0].get_pixmap(dpi=dpi, alpha=False).tobytes("png")
