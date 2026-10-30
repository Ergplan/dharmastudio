"""The visual logic of the page: one table, three dials.

Intensity (from the panel's text_state) drives sharpness and colour; scale (how wide the shot is) drives size.

    intensity I in [0, 1]:  quiet 0.10 · voice 0.15 · knowledge 0.35 · rising 0.50 · peak 0.90 · ego 1.00
    page intensity        = 0.5 * max(I of panels) + 0.5 * area-weighted mean(I)

Sharpness (page level, so a page reads as one surface):
    cut angle range  = 2° + 12° * I_page          quiet pages are near-rectilinear, peak pages are violently skewed
    gutter width     = 3.4 mm - 2.2 mm * I_page   calm wide gutters -> thin fractures
    edge             = feathered 0.9 mm when I_page < 0.3; crisp when 0.3-0.7; crisp + chips (extra notch vertices on
                       long edges) when > 0.7
Size (panel level):
    area weight      = script weight * scale factor    EWS 1.8 · WS 1.45 · MWS 1.2 · MS 1.0 · MCU 0.9 · CU 0.8 · ECU 0.7
    (a wide shot earns room; a close-up stays small unless the script makes it a plate)
Colour (panel level, applied as an SVG filter over the image; the grade in Pixelmator is the same curve):
    saturation       = 0.82 + 0.38 * I
    contrast         = 0.98 + 0.30 * I
    tint             = ego: crimson 7% · knowledge: gold 6% · quiet/voice: parchment 4% · else none
    gutter colour    = warm black (#17130f) at I_page 0 -> pure black (#050505) at 1; ego pages get a hairline
                       crimson vein along every cut
Beat (page level, the shape of the cuts):
    calm        -> broad shards, few cuts, edges gently torn (paper noise), angles under 4°
    tension     -> crisp straight cuts (the default)
    action      -> sharp diagonal fractures: cuts prefer the diagonal, angles up to 18°, chipped edges
    hex         -> title / chapter-opener montage: regular hexagonal cells with a luminous rim, no fractures
    revelation  -> one large illustration breaks across several shards: panels that share an image_group are cut
                   as fragments of a single picture, so the image reads through the fractures
    The beat comes from the script (`beat`), else from the state: quiet/voice -> calm, rising/ego -> tension,
    peak -> action, knowledge -> revelation.
Captions keep the six-state colour table in layout.STATE_STYLE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INTENSITY = {"quiet": 0.10, "voice": 0.15, "knowledge": 0.35, "rising": 0.50, "peak": 0.90, "ego": 1.00}
SCALE_FACTOR = {"EWS": 1.8, "WS": 1.45, "MWS": 1.2, "MS": 1.0, "MCU": 0.9, "CU": 0.8, "ECU": 0.7}

_SCALE_HINTS = [
    (r"\b(extreme wide|from the plain|whole frame|horizon|the armies|the city from|sky)\b", "EWS"),
    (r"\b(wide|full figure|the hall|the plain|the field)\b", "WS"),
    (r"\b(medium wide|from behind|two[- ]shot)\b", "MWS"),
    (r"\b(extreme close|macro|a single grain|signet ring|fingertip)\b", "ECU"),
    (r"\b(close[- ]up|close:|closer|the face|his face|her face|eyes)\b", "CU"),
    (r"\b(medium)\b", "MS"),
]


def infer_scale(image_text: str) -> str:
    t = image_text.lower()
    for pat, sc in _SCALE_HINTS:
        if re.search(pat, t):
            return sc
    return "MS"


def intensity(state: str) -> float:
    return INTENSITY.get(state, 0.3)


def area_weight(script_weight: float, scale: str) -> float:
    return max(0.2, script_weight) * SCALE_FACTOR.get(scale, 1.0)


BEATS = ("calm", "tension", "action", "revelation", "hex")
BEAT_FROM_STATE = {"quiet": "calm", "voice": "calm", "rising": "tension", "ego": "tension", "peak": "action", "knowledge": "revelation"}


def beat_of(state: str, explicit: str | None = None) -> str:
    return explicit if explicit in BEATS else BEAT_FROM_STATE.get(state, "tension")


def page_beat(beats: list[str]) -> str:
    """The page's beat is its strongest: action > revelation > tension > calm."""
    for b in ("hex", "action", "revelation", "tension", "calm"):
        if b in beats:
            return b
    return "tension"


@dataclass(frozen=True)
class PageLook:
    intensity: float
    angle_deg: float
    gutter_mm: float
    edge: str  # torn | feathered | crisp | chipped
    gutter_colour: str
    crimson_veins: bool
    beat: str = "tension"
    diagonal_bias: float = 0.0  # 0..1 chance a cut ignores the aspect ratio and goes diagonal


def page_look(states: list[str], weights: list[float], beats: list[str] | None = None) -> PageLook:
    if not states:
        return PageLook(0.1, 2.0, 3.4, "torn", "#17130f", False, "calm", 0.0)
    ints = [intensity(s) for s in states]
    tot = sum(weights) or 1.0
    mean = sum(i * w for i, w in zip(ints, weights)) / tot
    ip = 0.5 * max(ints) + 0.5 * mean
    beat = page_beat(beats or [beat_of(s) for s in states])
    angle = 2.0 + 12.0 * ip
    gutter = 3.4 - 2.2 * ip
    edge = "feathered" if ip < 0.3 else ("crisp" if ip <= 0.7 else "chipped")
    diag = 0.0
    if beat == "calm":
        angle, gutter, edge = min(angle, 4.0), max(gutter, 3.0), "torn"
    elif beat == "action":
        angle, gutter, edge, diag = max(angle, 14.0) if ip > 0.5 else max(angle, 10.0), min(gutter, 1.6), "chipped", 0.6
    elif beat == "revelation":
        angle, edge = min(angle, 8.0), "crisp"
    elif beat == "hex":
        angle, gutter, edge = 0.0, 2.4, "rim"
    r, g, b = (int(0x17 + (0x05 - 0x17) * ip), int(0x13 + (0x05 - 0x13) * ip), int(0x0f + (0x05 - 0x0f) * ip))
    return PageLook(round(ip, 3), round(angle, 2), round(gutter, 2), edge, f"#{r:02x}{g:02x}{b:02x}", any(s == "ego" for s in states), beat, diag)


@dataclass(frozen=True)
class PanelColour:
    saturation: float
    contrast: float
    tint: str | None  # hex
    tint_opacity: float


def panel_colour(state: str) -> PanelColour:
    i = intensity(state)
    tint, op = None, 0.0
    if state == "ego":
        tint, op = "#b3261e", 0.07
    elif state == "knowledge":
        tint, op = "#d4a017", 0.06
    elif state in ("quiet", "voice"):
        tint, op = "#efe4c9", 0.04
    return PanelColour(round(0.82 + 0.38 * i, 3), round(0.98 + 0.30 * i, 3), tint, op)
