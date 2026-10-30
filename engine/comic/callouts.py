"""Callout shapes: captions and balloons as pieces of parchment.

Every shape is drawn around a text box of w x h mm whose origin is the box's top-left (the HTML text sits in that box
with its padding). A shape never cuts into the padding: torn edges are displaced mostly outward (the inward part of
the noise stays well inside the 3 mm padding), and decorations (rules, ornaments, scroll ends, the folded corner) live
in the padding or outside the box. `overhang` reports how far the drawing reaches past the box on each side, so the
layout can keep the whole scrap on the page.

Kinds
- torn_scrap     irregular torn paper with a fibrous deckled edge (seeded multi-octave noise + fibre spikes)
- deckle_rect    a rectangle with soft deckled edges
- scroll         a horizontal ribbon with curled ends (voice / inner voice)
- cartouche      a rounded cartouche with a thin double rule and corner ornaments (knowledge: gold)
- jagged_dark    a sharp torn shard on dark vellum (peak / ego; ego adds a hairline crimson rule)
- oval_vignette  an oval of paper (the caption of an inset vignette)
- folded_corner  a rectangle with its top-right corner turned down
- rounded_shard  the 5-7 vertex shard with rounded corners
- bubble         (balloons) a rounded speech bubble with a tail and a deckled edge

Fills are crops of the painted parchment scraps in engine/textures (light / warm / dark), drawn through an SVG pattern,
with an inner edge burn, a paler fibre rim, and a soft shadow on screen (a faint offset sepia line in print).
"""

from __future__ import annotations

import base64
import io
import math
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

TEXTURES = Path(__file__).resolve().parent.parent / "textures"
SCRAPS = {"light": "scrap_light.jpg", "warm": "scrap_warm.jpg", "dark": "scrap_dark.jpg"}
SCRAP_MM = 90.0  # a scrap texture tile covers 90 x 90 mm (about 7 px/mm at 640 px)
SCRAP_PX = 640

KINDS = ("torn_scrap", "deckle_rect", "scroll", "cartouche", "jagged_dark", "oval_vignette", "folded_corner", "rounded_shard")
BALLOON_KINDS = ("bubble", "deckle_rect", "torn_scrap", "rounded_shard", "scroll", "cartouche")
LABELS = {
    "torn_scrap": "Torn scrap", "deckle_rect": "Deckled sheet", "scroll": "Scroll", "cartouche": "Cartouche", "jagged_dark": "Dark shard",
    "oval_vignette": "Oval", "folded_corner": "Folded corner", "rounded_shard": "Rounded shard", "bubble": "Speech bubble",
}
NOTES = {
    "torn_scrap": "irregular torn paper, fibrous deckled edge — narration", "deckle_rect": "a sheet with soft deckled edges — rising",
    "scroll": "a ribbon with curled ends — voice, inner voice", "cartouche": "rounded cartouche, double gold rule — knowledge",
    "jagged_dark": "sharp torn shard on dark vellum — peak, ego", "oval_vignette": "an oval of paper — under inset vignettes",
    "folded_corner": "a sheet with a turned-down corner", "rounded_shard": "the clean rounded shard", "bubble": "rounded speech bubble with a tail",
}
AUTO_BY_STATE = {"quiet": "torn_scrap", "voice": "scroll", "rising": "deckle_rect", "peak": "jagged_dark", "ego": "jagged_dark", "knowledge": "cartouche"}
PAPER_BY_STATE = {"quiet": "light", "voice": "light", "rising": "warm", "peak": "dark", "ego": "dark", "knowledge": "warm"}
NO_ROTATION = ("scroll", "cartouche")
SEPIA = "#3a2d1a"
GOLD = "#b8901f"
CRIMSON = "#b3261e"

Point = tuple[float, float]


def paper_for(kind: str, state: str) -> str:
    if kind == "jagged_dark":
        return "dark"
    if state in ("peak", "ego") and kind in ("torn_scrap", "rounded_shard", "deckle_rect", "folded_corner"):
        return "dark"
    if kind in ("cartouche", "deckle_rect"):
        return "warm"
    return PAPER_BY_STATE.get(state, "light") if kind not in ("bubble",) else "light"


def resolve_kind(panel_kind: str | None, volume_kind: str | None, state: str, inset: bool = False, balloon: bool = False) -> str:
    """Panel pick > volume default > by state (inset panels: an oval under the vignette)."""
    allowed = BALLOON_KINDS if balloon else KINDS
    for k in (panel_kind, volume_kind):
        if k and k != "auto" and k in allowed:
            return k
    if balloon:
        return "bubble"
    if inset:
        return "oval_vignette"
    return AUTO_BY_STATE.get(state, "torn_scrap")


# ---------------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------------


@dataclass
class Shape:
    kind: str
    d: str  # outline path (the fill and the clip)
    w: float
    h: float
    overhang: tuple[float, float, float, float]  # left, top, right, bottom (mm beyond the text box)
    rotation: float = 0.0
    torn: bool = False  # fibrous edge: draw the paler fibre rim
    deco: list[str] = field(default_factory=list)  # SVG drawn over the fill (rules, ornaments, flaps)
    under: list[str] = field(default_factory=list)  # SVG drawn under the fill (scroll backs)


def _periodic_noise(rng: random.Random, octaves: tuple[tuple[int, float], ...]):  # noqa: ANN202
    """Smooth noise on a loop t in [0,1): a sum of octaves (cycles, weight) of cosine-interpolated random values."""
    tables = [([rng.uniform(-1, 1) for _ in range(n)], n, wgt) for n, wgt in octaves]
    total = sum(w for _, _, w in tables)

    def f(t: float) -> float:
        v = 0.0
        for vals, n, wgt in tables:
            x = (t % 1.0) * n
            i = int(x)
            a, b = vals[i % n], vals[(i + 1) % n]
            u = (1 - math.cos((x - i) * math.pi)) / 2
            v += (a * (1 - u) + b * u) * wgt
        return v / total

    return f


def _resample(poly: list[Point], step: float) -> list[Point]:
    out: list[Point] = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        L = math.dist(p, q)
        k = max(1, int(L / step))
        for j in range(k):
            t = j / k
            out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return out


def _normals(pts: list[Point]) -> list[Point]:
    """Outward normals for a clockwise (screen coordinates) loop."""
    n = len(pts)
    out = []
    for i in range(n):
        a, b = pts[i - 1], pts[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        out.append((dy / L, -dx / L))
    return out


def displace(poly: list[Point], seed: int, amp: float, step: float = 0.6, bias: float = 0.35, spikes: float = 0.07, fine: bool = False) -> list[Point]:
    """A deckled/torn outline: resample, push each point along its normal by bias*amp + amp*noise, add fibre spikes."""
    rng = random.Random(seed)
    pts = _resample(poly, step)
    per = sum(math.dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))) or 1.0
    octs = ((max(3, int(per / 14)), 1.0), (max(6, int(per / 5)), 0.55), (max(12, int(per / 1.8)), 0.35 if not fine else 0.6))
    noise = _periodic_noise(rng, octs)
    nrm = _normals(pts)
    out: list[Point] = []
    acc = 0.0
    for i, (p, nv) in enumerate(zip(pts, nrm)):
        if i:
            acc += math.dist(pts[i - 1], p)
        dsp = amp * (bias + noise(acc / per))
        out.append((p[0] + nv[0] * dsp, p[1] + nv[1] * dsp))
        if spikes and rng.random() < spikes:  # a fibre standing out of the tear
            q = pts[(i + 1) % len(pts)]
            m = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            s = dsp + rng.uniform(0.25, 0.6)
            out.append((m[0] + nv[0] * s, m[1] + nv[1] * s))
    return out


def _poly_d(pts: list[Point]) -> str:
    return "M" + "L".join(f"{x:.2f},{y:.2f}" for x, y in pts) + "Z"


def _rounded_d(pts: list[Point], radius: float) -> str:
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


def _irregular_quad(w: float, h: float, rng: random.Random, j: float, extra_out: float) -> list[Point]:
    """A clockwise box with nudged corners and 1-3 outward edge vertices (the rounded/torn shard skeleton)."""
    corners = [(rng.uniform(-j, j * 0.5), rng.uniform(-j, j * 0.5)), (w + rng.uniform(-j * 0.5, j), rng.uniform(-j, j * 0.5)),
               (w + rng.uniform(-j * 0.5, j), h + rng.uniform(-j * 0.5, j)), (rng.uniform(-j, j * 0.5), h + rng.uniform(-j * 0.5, j))]
    edges = rng.sample(range(4), rng.choice((1, 2, 3)))
    out: list[Point] = []
    for i, c in enumerate(corners):
        out.append(c)
        if i in edges:
            q = corners[(i + 1) % 4]
            t = rng.uniform(0.3, 0.7)
            L = math.dist(c, q) or 1.0
            nx, ny = (q[1] - c[1]) / L, -(q[0] - c[0]) / L
            k = rng.uniform(0.3, extra_out)
            out.append((c[0] + (q[0] - c[0]) * t + nx * k, c[1] + (q[1] - c[1]) * t + ny * k))
    return out


def _bounds(pts: list[Point], w: float, h: float) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return max(0.0, -min(xs)), max(0.0, -min(ys)), max(0.0, max(xs) - w), max(0.0, max(ys) - h)


def _rounded_rect(x0: float, y0: float, x1: float, y1: float, r: float, steps: int = 5) -> list[Point]:
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    out: list[Point] = []
    for (cx, cy), start in (((x1 - r, y0 + r), -90), ((x1 - r, y1 - r), 0), ((x0 + r, y1 - r), 90), ((x0 + r, y0 + r), 180)):
        for i in range(steps + 1):
            a = math.radians(start + 90 * i / steps)
            out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def build(kind: str, w: float, h: float, seed: int, state: str = "quiet", tail_x: float | None = None) -> Shape:
    """The shape of `kind` around a w x h text box, stable for a given seed."""
    rng = random.Random(seed * 31 + KINDS.index(kind) if kind in KINDS else seed)
    rot = 0.0 if kind in NO_ROTATION else round(rng.uniform(-2.5, 2.5), 2)
    if kind == "torn_scrap":
        amp = rng.uniform(0.6, 1.2)
        pts = displace(_irregular_quad(w, h, rng, 0.8, 1.2), seed, amp, bias=0.45)
        return Shape(kind, _poly_d(pts), w, h, _bounds(pts, w, h), rot, torn=True)
    if kind == "deckle_rect":
        pts = displace([(0, 0), (w, 0), (w, h), (0, h)], seed, 0.35, step=0.45, bias=0.6, spikes=0.03, fine=True)
        return Shape(kind, _poly_d(pts), w, h, _bounds(pts, w, h), rot, torn=True)
    if kind == "jagged_dark":
        base = _irregular_quad(w, h, rng, 1.4, 1.8)
        pts = displace(base, seed, 0.45, step=0.7, bias=0.5, spikes=0.06)
        deco = [f"<path d='{_poly_d(pts)}' fill='none' stroke='{CRIMSON}' stroke-width='0.15' stroke-opacity='0.95'/>"] if state == "ego" else []
        return Shape(kind, _poly_d(pts), w, h, _bounds(pts, w, h), rot, torn=True, deco=deco)
    if kind == "rounded_shard":
        pts = _irregular_quad(w, h, rng, 0.6, 0.8)
        return Shape(kind, _rounded_d(pts, 1.6), w, h, _bounds(pts, w, h), rot)
    if kind == "folded_corner":
        f = 3.0
        pts = displace([(0, 0), (w - f, 0), (w, f), (w, h), (0, h)], seed, 0.3, step=0.5, bias=0.5, spikes=0.02, fine=True)
        flap = (f"<path d='M{w - f:.2f},0L{w - f + 0.35:.2f},{f - 0.35:.2f}L{w:.2f},{f:.2f}Z' fill='#d9c39a' stroke='#8a6a44' stroke-width='0.12' stroke-linejoin='round'/>"
                f"<path d='M{w - f:.2f},0L{w:.2f},{f:.2f}' stroke='#6b4e2c' stroke-opacity='0.45' stroke-width='0.25'/>")
        return Shape(kind, _poly_d(pts), w, h, _bounds(pts, w, h), rot, torn=True, deco=[flap])
    if kind == "oval_vignette":
        rx, ry = w / 2 * 1.42, h / 2 * 1.42
        ell = [(w / 2 + rx * math.cos(2 * math.pi * i / 72), h / 2 + ry * math.sin(2 * math.pi * i / 72)) for i in range(72)]
        pts = displace(ell, seed, 0.35, step=0.6, bias=0.4, spikes=0.03, fine=True)
        return Shape(kind, _poly_d(pts), w, h, _bounds(pts, w, h), rot, torn=True)
    if kind == "cartouche":
        r = min(3.2, h / 2.5)
        outer = _rounded_rect(0, 0, w, h, r)
        rules = []
        for inset, sw in ((0.9, 0.2), (1.45, 0.12)):
            rules.append(f"<path d='{_poly_d(_rounded_rect(inset, inset, w - inset, h - inset, max(0.5, r - inset)))}' fill='none' stroke='{GOLD}' stroke-width='{sw}'/>")
        orn = []
        for cx, cy in ((2.25, 2.25), (w - 2.25, 2.25), (w - 2.25, h - 2.25), (2.25, h - 2.25)):
            orn.append(f"<path d='M{cx:.2f},{cy - 0.55:.2f}L{cx + 0.55:.2f},{cy:.2f}L{cx:.2f},{cy + 0.55:.2f}L{cx - 0.55:.2f},{cy:.2f}Z' fill='{GOLD}'/>")
        return Shape(kind, _poly_d(outer), w, h, (0.0, 0.0, 0.0, 0.0), 0.0, deco=rules + orn)
    if kind == "scroll":
        e = 2.4  # roll width at each end
        wav = 0.45
        top = [(x, -wav * math.sin(x / max(w, 1) * math.pi * 2 + 0.6)) for x in [w * i / 24 for i in range(25)]]
        bot = [(x, h + wav * math.sin(x / max(w, 1) * math.pi * 2 + 1.7)) for x in [w * i / 24 for i in range(24, -1, -1)]]
        body = top + bot
        rolls_under, rolls_over = [], []
        for x0, flip in ((-e, False), (w, True)):
            y0, y1 = -1.0, h + 1.0
            back = f"<rect x='{x0 - (0 if flip else 0.6):.2f}' y='{y0 + 0.6:.2f}' width='{e + 0.6:.2f}' height='{y1 - y0 - 1.2:.2f}' rx='1' fill='#8a6a44' fill-opacity='0.55'/>"
            rolls_under.append(back)
            roll = (f"<rect x='{x0:.2f}' y='{y0:.2f}' width='{e:.2f}' height='{y1 - y0:.2f}' rx='{e / 2:.2f}' fill='url(#FILL)' stroke='#7a5a34' stroke-width='0.18'/>"
                    f"<rect x='{x0:.2f}' y='{y0:.2f}' width='{e:.2f}' height='{y1 - y0:.2f}' rx='{e / 2:.2f}' fill='url(#ROLLSHADE{'R' if flip else 'L'})'/>"
                    f"<path d='M{x0 + e / 2:.2f},{y0 + 0.8:.2f}C{x0 + e * 0.15:.2f},{(y0 + y1) / 2:.2f} {x0 + e * 0.85:.2f},{(y0 + y1) / 2:.2f} {x0 + e / 2:.2f},{y1 - 0.8:.2f}' fill='none' stroke='#6b4e2c' stroke-opacity='0.5' stroke-width='0.15'/>")
            rolls_over.append(roll)
        return Shape(kind, _poly_d(body), w, h, (e + 0.2, 1.1, e + 0.2, 1.1), 0.0, deco=rolls_over, under=rolls_under)
    if kind == "bubble":
        r = min(4.0, h / 2.2, w / 4)
        tx = min(max(tail_x if tail_x is not None else w * 0.22, r + 1), w - r - 5)
        ring = _rounded_rect(0, 0, w, h, r, steps=6)
        # splice the tail into the bottom edge (the bottom edge runs right -> left in the clockwise ring)
        k = next(i for i, p in enumerate(ring) if p[1] >= h - 1e-6 and p[0] <= w - r + 1e-6)
        tail = [(tx + 4.2, h), (tx - 1.8, h + 4.2), (tx + 0.8, h)]
        pts = ring[:k + 1] + tail + ring[k + 1:]
        pts = displace(pts, seed, 0.28, step=0.5, bias=0.5, spikes=0.02, fine=True)
        return Shape(kind, _poly_d(pts), w, h, _bounds(pts, w, h), round(rng.uniform(-1, 1), 2), torn=True)
    return build("torn_scrap", w, h, seed, state)


# ---------------------------------------------------------------------------------
# textures
# ---------------------------------------------------------------------------------


@lru_cache(maxsize=8)
def scrap_bytes(paper: str) -> bytes:
    """The scrap texture prepared for embedding: SCRAP_PX square JPEG (~60 kB)."""
    from PIL import Image

    with Image.open(TEXTURES / SCRAPS[paper]) as im:
        im = im.convert("RGB").resize((SCRAP_PX, SCRAP_PX), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=84, optimize=True)
    return buf.getvalue()


@lru_cache(maxsize=8)
def scrap_data_uri(paper: str) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(scrap_bytes(paper)).decode()


SCRAP_URL = "/api/textures/scrap_{paper}.jpg"


@lru_cache(maxsize=4096)
def mean_under(paper: str, x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int]:
    """Mean colour of the scrap texture over a region in tile mm (wrapped into the tile)."""
    from PIL import Image

    with Image.open(TEXTURES / SCRAPS[paper]) as im:
        im = im.convert("RGB")
        k = im.width / SCRAP_MM
        x0, y0 = x0 % SCRAP_MM, y0 % SCRAP_MM
        x1, y1 = min(SCRAP_MM, x0 + max(1.0, x1)), min(SCRAP_MM, y0 + max(1.0, y1))
        box = (int(x0 * k), int(y0 * k), max(int(x0 * k) + 1, int(x1 * k)), max(int(y0 * k) + 1, int(y1 * k)))
        return im.crop(box).resize((1, 1), Image.BOX).getpixel((0, 0))  # type: ignore[return-value]


def tile_offset(seed: int) -> tuple[float, float]:
    rng = random.Random(seed * 977)
    return round(rng.uniform(0, SCRAP_MM), 2), round(rng.uniform(0, SCRAP_MM), 2)


# ---------------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------------


def svg(shape: Shape, uid: str, fill: dict[str, Any], print_mode: bool) -> str:
    """The callout's SVG (positioned by the caller over the text box). fill = {paper, href, offset, tint, tint_alpha}
    for parchment, or {flat: '#hex'}; plus edge (fibre rim colour) and burn (edge-burn colour)."""
    L, T, R, B = shape.overhang
    m = 1.6  # room for shadow and fibre rim
    vx, vy, vw, vh = -L - m, -T - m, shape.w + L + R + 2 * m, shape.h + T + B + 2 * m
    defs = [f"<clipPath id='k{uid}'><path d='{shape.d}'/></clipPath>",
            f"<filter id='b{uid}' x='-20%' y='-40%' width='140%' height='180%'><feGaussianBlur stdDeviation='0.75'/></filter>"]
    if "href" in fill or "use" in fill:
        ox, oy = fill["offset"]
        tile = f"<use href='#{fill['use']}'/>" if "use" in fill else f"<image href='{fill['href']}' width='{SCRAP_MM}' height='{SCRAP_MM}' preserveAspectRatio='none'/>"
        defs.append(f"<pattern id='p{uid}' patternUnits='userSpaceOnUse' width='{SCRAP_MM}' height='{SCRAP_MM}' x='{-ox:.2f}' y='{-oy:.2f}'>{tile}</pattern>")
        paint = f"url(#p{uid})"
    else:
        paint = fill["flat"]
    if shape.kind == "scroll":
        for side, x1 in (("L", "0"), ("R", "1")):
            defs.append(f"<linearGradient id='g{side}{uid}' x1='{x1}' x2='{1 - int(x1)}' y1='0' y2='0'><stop offset='0' stop-color='#2a1a0a' stop-opacity='0.35'/>"
                        f"<stop offset='0.55' stop-color='#2a1a0a' stop-opacity='0'/><stop offset='1' stop-color='#fff4dc' stop-opacity='0.25'/></linearGradient>")
    parts = []
    if print_mode:
        parts.append(f"<path d='{shape.d}' transform='translate(0.25 0.35)' fill='none' stroke='{SEPIA}' stroke-opacity='0.35' stroke-width='0.15'/>")
    else:
        parts.append(f"<path d='{shape.d}' transform='translate(0.35 0.6)' fill='#1e1206' fill-opacity='0.42' filter='url(#b{uid})'/>")
    parts += [u.replace("url(#FILL)", paint) for u in shape.under]
    body = [f"<rect x='{vx:.2f}' y='{vy:.2f}' width='{vw:.2f}' height='{vh:.2f}' fill='{paint}'/>"]
    if fill.get("tint") and fill.get("tint_alpha"):
        body.append(f"<rect x='{vx:.2f}' y='{vy:.2f}' width='{vw:.2f}' height='{vh:.2f}' fill='{fill['tint']}' fill-opacity='{fill['tint_alpha']:.3f}' style='mix-blend-mode:multiply'/>")
    burn = fill.get("burn", "#4a2e14")
    body.append(f"<path d='{shape.d}' fill='none' stroke='{burn}' stroke-opacity='{fill.get('burn_alpha', 0.55):.2f}' stroke-width='2.6' filter='url(#b{uid})'/>")
    parts.append(f"<g clip-path='url(#k{uid})'>{''.join(body)}</g>")
    if shape.torn:
        parts.append(f"<path d='{shape.d}' fill='none' stroke='{fill.get('edge', '#f4e9cf')}' stroke-opacity='0.85' stroke-width='0.42' stroke-linejoin='round'/>")
    deco = [d.replace("url(#FILL)", paint).replace("url(#ROLLSHADEL)", f"url(#gL{uid})").replace("url(#ROLLSHADER)", f"url(#gR{uid})") for d in shape.deco]
    parts += deco
    return (f"<svg class='co' xmlns='http://www.w3.org/2000/svg' viewBox='{vx:.2f} {vy:.2f} {vw:.2f} {vh:.2f}' "
            f"style='left:{vx:.2f}mm;top:{vy:.2f}mm;width:{vw:.2f}mm;height:{vh:.2f}mm'><defs>{''.join(defs)}</defs>{''.join(parts)}</svg>")


def scrap_defs(papers: set[str] | list[str], embed: bool) -> str:
    """A hidden SVG holding one <image> per scrap tone a page uses; callout patterns <use> it (one copy per page)."""
    if not papers:
        return ""
    imgs = "".join(f"<image id='sx{p}' href='{scrap_data_uri(p) if embed else SCRAP_URL.format(paper=p)}' width='{SCRAP_MM}' height='{SCRAP_MM}' preserveAspectRatio='none'/>"
                   for p in sorted(papers))
    return f"<svg width='0' height='0' style='position:absolute' aria-hidden='true'><defs>{imgs}</defs></svg>"


def thumbnail(kind: str, paper: str | None = None, state: str = "quiet", w: float = 34, h: float = 14) -> str:
    """A standalone SVG of one shape (the Typography and inspector pickers), texture embedded, grey lines for text."""
    sh = build(kind, w, h, seed=7, state=state)
    paper = paper if paper in SCRAPS else paper_for(kind, state)
    dark = paper == "dark"
    inner = svg(sh, f"t{kind}{paper}", {"href": scrap_data_uri(paper), "offset": tile_offset(7), "edge": "#9c7a4e" if dark else "#f4e9cf",
                                        "burn": "#0b0603" if dark else "#4a2e14", "burn_alpha": 0.6 if dark else 0.5}, False)
    pad = 7.0
    W, H = w + 2 * pad, h + 2 * pad + (4 if kind == "bubble" else 0)
    lines = "".join(f"<rect x='{3.4:.1f}' y='{3.2 + i * 2.8:.1f}' width='{(w - 6.8) * (0.92 if i < 2 else 0.5):.1f}' height='0.8' rx='0.4' fill='{'#efe4c9' if dark else SEPIA}' fill-opacity='0.6'/>"
                    for i in range(3) if 3.2 + i * 2.8 + 0.8 < h - 2.6)
    body = inner[inner.index(">") + 1: inner.rindex("</svg>")]
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W:.1f} {H:.1f}' width='{W * 5:.0f}' height='{H * 5:.0f}'>"
            f"<g transform='translate({pad} {pad}) rotate({sh.rotation} {w / 2} {h / 2})'>{body}{lines}</g></svg>")
