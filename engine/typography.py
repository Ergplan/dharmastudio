"""Typography: the font catalog, the type presets and the size scale.

Every face is an OFL font shipped with the studio (engine/comic/fonts and engine/comic/fonts/library). A volume
stores a *typography setting* (a preset plus optional per-role fonts and sizes); a page may store a partial override
on top. `resolve()` turns a setting into a `TypeSpec` the layout draws from: the family stack, weight and face per
role and language, the caption/balloon/title sizes, and the exact font files a page needs (so a rendered page embeds
only the faces it uses).

Setting shape (all keys optional; missing ones come from the preset, then from DEFAULT_SETTING):
    {preset, title_font, narration_font, dialogue_font, sfx_font, hi_title_font, hi_narration_font,
     hi_dialogue_font, size: "S|M|L|XL", title_size: "S|M|L|XL", line_height}
"""

from __future__ import annotations

import base64
import re
import struct
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

FONT_ROOT = Path(__file__).resolve().parent / "comic" / "fonts"
LIBRARY = FONT_ROOT / "library"

ROLES = ("title", "narration", "dialogue", "sfx")
EN_KEYS = {"title": "title_font", "narration": "narration_font", "dialogue": "dialogue_font", "sfx": "sfx_font"}
HI_KEYS = {"title": "hi_title_font", "narration": "hi_narration_font", "dialogue": "hi_dialogue_font"}
FONT_KEYS = tuple(EN_KEYS.values()) + tuple(HI_KEYS.values())
SIZES = {"S": 0.9, "M": 1.0, "L": 1.2, "XL": 1.4}

# the base sizes at "M" (mm). Callouts are set one step larger than the original layout (2.9 / 3.05 / 2.7 mm at M):
# at the default "L" a caption is 2.9 x 1.4 = 4.06 mm (the author asked for bigger callouts)
CALLOUT_STEP = 1.4 / 1.2
CAPTION_MM = {"en": 2.9 * CALLOUT_STEP, "hi": 3.05 * CALLOUT_STEP}
BALLOON_MM = 2.7 * CALLOUT_STEP
SFX_MM = 8.0
TITLE_MM = {"book": 3.2, "vol": 2.4, "chapnum": 2.3, "chap": 5.2, "epi": 2.5}
LINE_HEIGHT = 1.32


@dataclass(frozen=True)
class Face:
    file: str  # path relative to FONT_ROOT
    weight: str = "400"  # CSS weight, or a range "400 900" for a variable font
    style: str = "normal"

    @property
    def path(self) -> Path:
        return FONT_ROOT / self.file

    @property
    def low(self) -> int:
        return int(self.weight.split()[0])

    @property
    def high(self) -> int:
        return int(self.weight.split()[-1])


@dataclass(frozen=True)
class Font:
    id: str
    family: str
    faces: tuple[Face, ...]
    script: str  # latin | devanagari | both
    roles: tuple[str, ...]
    note: str
    text_weight: int = 400  # weight for narration/dialogue
    title_weight: int = 400  # weight for titles and sfx
    optical: float = 1.0  # small x-height faces are set a touch larger so they read at the same size

    @property
    def files(self) -> dict[str, str]:
        """{regular, italic, bold} file names (as the catalog lists them)."""
        out: dict[str, str] = {}
        for f in self.faces:
            if f.style == "italic":
                out.setdefault("italic", f.file)
            elif f.high >= 600 and f.low >= 600:
                out.setdefault("bold", f.file)
            else:
                out.setdefault("regular", f.file)
        if "regular" not in out and self.faces:
            out["regular"] = self.faces[0].file
        return out

    def face(self, weight: int, italic: bool = False) -> Face:
        """The face the browser will pick for this weight/style (closest weight; italic falls back to roman)."""
        pool = [f for f in self.faces if (f.style == "italic") == italic] or [f for f in self.faces if f.style != "italic"] or list(self.faces)
        for f in pool:
            if f.low <= weight <= f.high:
                return f
        return min(pool, key=lambda f: min(abs(f.low - weight), abs(f.high - weight)))

    def has_italic(self) -> bool:
        return any(f.style == "italic" for f in self.faces)

    def covers(self, lang: str) -> bool:
        return self.script == "both" or (self.script == "devanagari") == (lang == "hi")


def _f(file: str, weight: str = "400", style: str = "normal") -> Face:
    return Face(file if "/" in file or file.startswith(("Mukta", "Noto")) else f"library/{file}", weight, style)


CATALOG: tuple[Font, ...] = (
    # --- Latin display ---
    Font("cinzel", "Cinzel", (_f("Cinzelwght.ttf", "400 900"),), "latin", ("title",), "Cinzel — carved Roman capitals, for titles", title_weight=600),
    Font("cinzel-decorative", "Cinzel Decorative", (_f("CinzelDecorative-Bold.ttf", "700"),), "latin", ("title",), "Cinzel Decorative — Roman capitals with flourished swashes, for illuminated titles", text_weight=700, title_weight=700),
    Font("uncial-antiqua", "Uncial Antiqua", (_f("UncialAntiqua-Regular.ttf"),), "latin", ("title", "sfx"), "Uncial Antiqua — insular uncials of the early scriptoria, for chronicle titles"),
    Font("medievalsharp", "MedievalSharp", (_f("MedievalSharp.ttf"),), "latin", ("title", "sfx"), "MedievalSharp — a broad-nib gothic hand, for headings and old-world sound effects"),
    Font("marcellus", "Marcellus", (_f("Marcellus-Regular.ttf"),), "latin", ("title", "dialogue"), "Marcellus — flared Trajan-like letters, clean titles and calm speech"),
    Font("bangers", "Bangers", (_f("Bangers-Regular.ttf"),), "latin", ("sfx", "title"), "Bangers — comic SFX, loud and hand-lettered"),
    Font("teko", "Teko", (_f("Tekowght.ttf", "300 700"),), "both", ("sfx", "title"), "Teko — tall condensed caps (Latin and Devanagari), for impact sound effects", title_weight=600, text_weight=500),
    # --- Latin text ---
    Font("im-fell-english", "IM FELL English", (_f("IMFeENrm28P.ttf"), _f("IMFeENit28P.ttf", style="italic")), "latin", ("narration",), "IM Fell English — 17th-century press, manuscript narration", optical=1.04),
    Font("cormorant-garamond", "Cormorant Garamond", (_f("CormorantGaramondwght.ttf", "300 700"), _f("CormorantGaramond-Italicwght.ttf", "300 700", "italic")), "latin", ("narration", "title"), "Cormorant Garamond — high-contrast display Garamond, cinematic narration", text_weight=500, title_weight=600, optical=1.1),
    Font("eb-garamond", "EB Garamond", (_f("EBGaramondwght.ttf", "400 800"), _f("EBGaramond-Italicwght.ttf", "400 800", "italic")), "latin", ("narration", "dialogue"), "EB Garamond — the classic book Garamond, for long narration", optical=1.04),
    Font("spectral", "Spectral", (_f("Spectral-Regular.ttf"), _f("Spectral-Italic.ttf", style="italic"), _f("Spectral-SemiBold.ttf", "600")), "latin", ("narration", "dialogue"), "Spectral — a screen-sharp book serif, clear dialogue and narration"),
    Font("philosopher", "Philosopher", (_f("Philosopher-Regular.ttf"), _f("Philosopher-Bold.ttf", "700")), "latin", ("dialogue", "title"), "Philosopher — a warm humanist hybrid, for speech"),
    # --- Devanagari (all carry Latin as well) ---
    Font("yatra-one", "Yatra One", (_f("YatraOne-Regular.ttf"),), "both", ("title", "sfx"), "Yatra One — bold Devanagari display, painted-sign energy"),
    Font("rozha-one", "Rozha One", (_f("RozhaOne-Regular.ttf"),), "both", ("title",), "Rozha One — heavy high-contrast Devanagari, cinema-poster titles"),
    Font("amita", "Amita", (_f("Amita-Regular.ttf"), _f("Amita-Bold.ttf", "700")), "both", ("title", "narration"), "Amita — calligraphic Devanagari, a reed-pen hand", title_weight=700),
    Font("eczar", "Eczar", (_f("Eczarwght.ttf", "400 800"),), "both", ("title", "narration"), "Eczar — sculpted Devanagari and Latin, for titles and strong narration", title_weight=600),
    Font("khand", "Khand", (_f("Khand-SemiBold.ttf", "600"),), "both", ("title", "sfx"), "Khand — compact squared Devanagari, modern headings", text_weight=600, title_weight=600),
    Font("tiro-devanagari-hindi", "Tiro Devanagari Hindi", (_f("TiroDevanagariHindi-Regular.ttf"), _f("TiroDevanagariHindi-Italic.ttf", style="italic")), "both", ("narration", "dialogue"), "Tiro Devanagari Hindi — classical book Hindi"),
    Font("martel", "Martel", (_f("Martel-Regular.ttf"), _f("Martel-Bold.ttf", "700")), "both", ("narration", "title"), "Martel — a sturdy Devanagari text serif, cinematic narration", title_weight=700),
    Font("gotu", "Gotu", (_f("Gotu-Regular.ttf"),), "both", ("narration", "dialogue"), "Gotu — soft rounded Devanagari, a quiet chronicle voice"),
    Font("laila", "Laila", (_f("Laila-Regular.ttf"), _f("Laila-SemiBold.ttf", "600")), "both", ("dialogue", "narration"), "Laila — open, friendly Devanagari for speech balloons", title_weight=600),
    Font("kalam", "Kalam", (_f("Kalam-Regular.ttf"), _f("Kalam-Bold.ttf", "700")), "both", ("dialogue", "sfx"), "Kalam — handwritten Hindi notes, a personal voice", title_weight=700),
    Font("pragati-narrow", "Pragati Narrow", (_f("PragatiNarrow-Regular.ttf"), _f("PragatiNarrow-Bold.ttf", "700")), "both", ("dialogue",), "Pragati Narrow — condensed Devanagari sans, fits long balloons", title_weight=700),
    Font("noto-serif-devanagari", "Noto Serif Devanagari", (_f("NotoSerifDevanagari.ttf", "400 700"),), "both", ("narration", "title"), "Noto Serif Devanagari — the studio's original Hindi caption face"),
    Font("mukta", "Mukta", (_f("Mukta-Regular.ttf"), _f("Mukta-SemiBold.ttf", "600")), "both", ("dialogue", "narration"), "Mukta — the studio's original Hindi balloon sans, plain and legible", title_weight=600),
)
FONTS: dict[str, Font] = {f.id: f for f in CATALOG}
FILES: dict[str, Face] = {Path(face.file).name: face for f in CATALOG for face in f.faces}

PRESETS: dict[str, dict[str, Any]] = {
    "illuminated-manuscript": {
        "name": "Illuminated manuscript", "note": "Flourished capitals over a 17th-century press, a sharp book serif for speech.",
        "title_font": "cinzel-decorative", "narration_font": "im-fell-english", "dialogue_font": "spectral", "sfx_font": "medievalsharp",
        "hi_title_font": "yatra-one", "hi_narration_font": "tiro-devanagari-hindi", "hi_dialogue_font": "laila",
    },
    "epic-cinema": {
        "name": "Epic cinema", "note": "Carved Roman capitals and a high-contrast Garamond — the trailer voice.",
        "title_font": "cinzel", "narration_font": "cormorant-garamond", "dialogue_font": "marcellus", "sfx_font": "bangers",
        "hi_title_font": "rozha-one", "hi_narration_font": "martel", "hi_dialogue_font": "mukta",
    },
    "ancient-chronicle": {
        "name": "Ancient chronicle", "note": "Insular uncials, the book Garamond, a calligraphic Devanagari hand.",
        "title_font": "uncial-antiqua", "narration_font": "eb-garamond", "dialogue_font": "philosopher", "sfx_font": "medievalsharp",
        "hi_title_font": "amita", "hi_narration_font": "gotu", "hi_dialogue_font": "kalam",
    },
    "modern-clean": {
        "name": "Modern clean", "note": "Quiet flared capitals and a crisp serif; squared Devanagari headings.",
        "title_font": "marcellus", "narration_font": "spectral", "dialogue_font": "philosopher", "sfx_font": "teko",
        "hi_title_font": "khand", "hi_narration_font": "laila", "hi_dialogue_font": "mukta",
    },
    "comic-house": {
        "name": "Comic house", "note": "Loud comic lettering for titles and SFX over a readable book serif.",
        "title_font": "bangers", "narration_font": "spectral", "dialogue_font": "philosopher", "sfx_font": "bangers",
        "hi_title_font": "yatra-one", "hi_narration_font": "eczar", "hi_dialogue_font": "pragati-narrow",
    },
}
DEFAULT_PRESET = "illuminated-manuscript"
DEFAULT_SETTING: dict[str, Any] = {"preset": DEFAULT_PRESET, "size": "L", "title_size": "L", "line_height": None, "colour_mode": "smart"}
SETTING_KEYS = ("preset", *FONT_KEYS, "size", "title_size", "line_height", "colour_mode", "colours")
COLOUR_MODES = ("smart", "state", "custom")
STATES = ("quiet", "rising", "peak", "ego", "knowledge", "voice")

SAMPLES = {
    "latin": {"title": "The Last Night of Lanka", "narration": "I have carried many things across many waters.", "dialogue": "Dharma protects those who protect it.", "sfx": "THOOM!"},
    "devanagari": {"title": "लंका की अंतिम रात", "narration": "मैंने अनेक जल पार करके अनेक चीज़ें ढोई हैं।", "dialogue": "धर्मो रक्षति रक्षितः।", "sfx": "धड़ाम!"},
}
DEVANAGARI = re.compile(r"[ऀ-ॿ꣠-ꣿ]")


class TypographyError(ValueError):
    pass


def validate(setting: dict[str, Any] | None, partial: bool = False) -> dict[str, Any]:
    """Clean a setting from the API: known keys only, valid ids/sizes. `partial` keeps None (= inherit) values."""
    out: dict[str, Any] = {}
    for k, v in (setting or {}).items():
        if k not in SETTING_KEYS:
            continue
        if v in (None, ""):
            if partial:
                out[k] = None
            continue
        if k == "preset":
            if v not in PRESETS:
                raise TypographyError(f"unknown preset {v!r}")
        elif k in FONT_KEYS:
            if v not in FONTS:
                raise TypographyError(f"unknown font {v!r}")
            lang = "hi" if k.startswith("hi_") else "en"
            if not FONTS[v].covers(lang):
                raise TypographyError(f"{FONTS[v].family} has no {'Devanagari' if lang == 'hi' else 'Latin'} glyphs")
        elif k in ("size", "title_size"):
            if v not in SIZES:
                raise TypographyError(f"{k} must be one of {', '.join(SIZES)}")
        elif k == "colour_mode":
            if v not in COLOUR_MODES:
                raise TypographyError(f"colour_mode must be one of {', '.join(COLOUR_MODES)}")
        elif k == "colours":
            if not isinstance(v, dict):
                raise TypographyError("colours must be {state: {box, text, border}}")
            clean: dict[str, Any] = {}
            for st, c in v.items():
                if st not in STATES or not isinstance(c, dict):
                    raise TypographyError(f"unknown state {st!r} in colours")
                cc = {}
                for part in ("box", "text", "border"):
                    if c.get(part) in (None, ""):
                        continue
                    if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(c[part])):
                        raise TypographyError(f"colours.{st}.{part} must be a #rrggbb hex")
                    cc[part] = str(c[part]).lower()
                clean[st] = cc
            v = clean
        elif k == "line_height":
            try:
                v = float(v)
            except (TypeError, ValueError) as exc:
                raise TypographyError("line_height must be a number") from exc
            if not 1.0 <= v <= 2.0:
                raise TypographyError("line_height must be between 1.0 and 2.0")
        out[k] = v
    return out


def merge(volume: dict[str, Any] | None, override: dict[str, Any] | None = None) -> dict[str, Any]:
    """The effective setting: DEFAULT_SETTING < volume < page override. A preset chosen on a level drops the explicit
    role fonts of the levels below it (picking a preset means 'these fonts')."""
    eff = dict(DEFAULT_SETTING)
    for layer in (volume or {}, override or {}):
        layer = {k: v for k, v in layer.items() if v not in (None, "") and k in SETTING_KEYS}
        if "preset" in layer:
            for k in FONT_KEYS:
                eff.pop(k, None)
        eff.update(layer)
    return eff


@dataclass
class RoleFont:
    font: Font
    weight: int
    italic: bool = False

    @property
    def face(self) -> Face:
        return self.font.face(self.weight, self.italic)

    @property
    def stack(self) -> str:
        generic = "sans-serif" if self.font.id in ("bangers", "teko", "khand", "mukta", "pragati-narrow", "philosopher") else "serif"
        return f"'{self.font.family}',{generic}"


@dataclass
class TypeSpec:
    setting: dict[str, Any]
    fonts: dict[str, Font] = field(default_factory=dict)  # setting key -> Font
    size: float = SIZES["L"]
    title_size: float = SIZES["L"]
    line_height: float = LINE_HEIGHT
    colour_mode: str = "smart"
    colours: dict[str, Any] = field(default_factory=dict)

    def font(self, role: str, lang: str) -> Font:
        key = (HI_KEYS.get(role) if lang == "hi" else None) or EN_KEYS[role]
        return self.fonts[key]

    def role(self, role: str, lang: str, italic: bool = False) -> RoleFont:
        f = self.font(role, lang)
        weight = f.title_weight if role in ("title", "sfx") else f.text_weight
        return RoleFont(f, weight, italic and f.has_italic())

    def sfx(self, text: str) -> RoleFont:
        """SFX in Latin uses the sfx font; Devanagari SFX (which a Latin display face cannot draw) the Hindi title font."""
        if DEVANAGARI.search(text or "") and not self.fonts["sfx_font"].covers("hi"):
            f = self.fonts["hi_title_font"]
            return RoleFont(f, f.title_weight)
        return self.role("sfx", "en")

    def caption_mm(self, lang: str) -> float:
        return CAPTION_MM["hi" if lang == "hi" else "en"] * self.size * self.role("narration", lang).font.optical

    def balloon_mm(self, lang: str) -> float:
        return BALLOON_MM * self.size * self.role("dialogue", lang).font.optical

    def sfx_mm(self) -> float:
        return SFX_MM * self.size

    def title_mm(self, part: str) -> float:
        return TITLE_MM[part] * self.title_size

    def summary(self) -> dict[str, Any]:
        return {"preset": self.setting.get("preset"), "size": self.setting.get("size"), "title_size": self.setting.get("title_size"), "line_height": self.line_height,
                "colour_mode": self.colour_mode, "colours": self.colours,
                "fonts": {k: {"id": f.id, "family": f.family} for k, f in self.fonts.items()}, "scale": {"size": self.size, "title_size": self.title_size}}


def resolve(volume: dict[str, Any] | None = None, override: dict[str, Any] | None = None) -> TypeSpec:
    eff = merge(volume, override)
    preset = PRESETS.get(eff.get("preset") or DEFAULT_PRESET) or PRESETS[DEFAULT_PRESET]
    fonts: dict[str, Font] = {}
    for k in FONT_KEYS:
        fid = eff.get(k) or preset[k]
        f = FONTS.get(fid) or FONTS[PRESETS[DEFAULT_PRESET][k]]
        if not f.covers("hi" if k.startswith("hi_") else "en"):
            f = FONTS[preset[k]]
        fonts[k] = f
    lh = eff.get("line_height")
    return TypeSpec(setting=eff, fonts=fonts, size=SIZES.get(eff.get("size") or "L", 1.2), title_size=SIZES.get(eff.get("title_size") or eff.get("size") or "L", 1.2),
                    line_height=float(lh) if lh else LINE_HEIGHT, colour_mode=eff.get("colour_mode") or "smart", colours=eff.get("colours") or {})


# ---------------------------------------------------------------------------------
# measuring (so callout shapes are sized to the text they hold)
# ---------------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _pil_font(path: str):  # noqa: ANN202
    from PIL import ImageFont

    return ImageFont.truetype(path, 100)


@lru_cache(maxsize=8192)
def _advance(path: str, text: str) -> float:
    """Advance width of `text` at 100 units (shaped with raqm when available)."""
    return float(_pil_font(path).getlength(text))


SAFETY = 1.08  # variable fonts are measured at their default instance; browsers round differently


def wrap_lines(text: str, face: Face, size_mm: float, width_mm: float) -> list[str]:
    """Greedy word wrap with the real glyph advances of `face` (what Chromium will do, give or take)."""
    path = str(face.path)
    k = size_mm / 100 * SAFETY
    space = _advance(path, " ") * k
    lines: list[str] = []
    for para in (text or "").split("\n"):
        cur, cur_w = "", 0.0
        for word in para.split():
            w = _advance(path, word) * k
            if cur and cur_w + space + w > width_mm:
                lines.append(cur)
                cur, cur_w = word, w
            else:
                cur, cur_w = (f"{cur} {word}" if cur else word), (cur_w + space + w if cur else w)
        lines.append(cur)
    return lines


def text_width(text: str, face: Face, size_mm: float) -> float:
    return _advance(str(face.path), text) * size_mm / 100 * SAFETY


# ---------------------------------------------------------------------------------
# @font-face
# ---------------------------------------------------------------------------------

FONT_URL = "/api/fonts/"


@lru_cache(maxsize=64)
def _b64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def face_css(face: Face, family: str, embed: bool, url_prefix: str = FONT_URL) -> str:
    src = f"url(data:font/ttf;base64,{_b64(str(face.path))})" if embed else f"url('{url_prefix}{Path(face.file).name}')"
    return f"@font-face{{font-family:'{family}';src:{src} format('truetype');font-weight:{face.weight};font-style:{face.style};font-display:block;}}"


def font_face_css(used: list[RoleFont] | set[tuple[str, Face]], embed: bool) -> str:
    """@font-face rules for exactly the faces in `used` (RoleFonts or (family, Face) pairs), deduplicated."""
    seen: dict[str, tuple[str, Face]] = {}
    for u in used:
        fam, face = (u.font.family, u.face) if isinstance(u, RoleFont) else u
        seen.setdefault(face.file, (fam, face))
    return "\n".join(face_css(face, fam, embed) for fam, face in sorted(seen.values(), key=lambda t: t[1].file))


def faces_of(used: list[RoleFont]) -> set[tuple[str, Face]]:
    return {(u.font.family, u.face) for u in used}


# ---------------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------------


def catalog_json() -> list[dict[str, Any]]:
    out = []
    for f in CATALOG:
        scripts = ["latin", "devanagari"] if f.script == "both" else [f.script]
        out.append({
            "id": f.id, "family": f.family, "script": f.script, "roles": list(f.roles), "note": f.note, "files": f.files,
            "faces": [{"file": Path(x.file).name, "url": FONT_URL + Path(x.file).name, "weight": x.weight, "style": x.style} for x in f.faces],
            "text_weight": f.text_weight, "title_weight": f.title_weight,
            "preview": {s: SAMPLES[s] for s in scripts},
            "licence": _licence(f),
        })
    return out


def _licence(f: Font) -> str | None:
    base = f.faces[0].path.parent
    fam = f.family.lower().replace(" ", "")
    hits = [c for c in base.glob("OFL*.txt") if c.stem.lower().replace("ofl-", "") in fam]
    return max(hits, key=lambda c: len(c.stem)).name if hits else None


def presets_json() -> list[dict[str, Any]]:
    out = []
    for pid, p in PRESETS.items():
        out.append({"id": pid, "name": p["name"], "note": p["note"], "fonts": {k: p[k] for k in FONT_KEYS},
                    "families": {k: FONTS[p[k]].family for k in FONT_KEYS}})
    return out


def font_file(name: str) -> Path | None:
    """A catalog file by its bare name (the /api/fonts/{file} route); None for anything not in the catalog."""
    face = FILES.get(name)
    return face.path if face and face.path.exists() else None


def postscript_name(path: Path) -> str:
    """The font's PostScript name (name table id 6) — the name a PDF embeds (tests read it back with pdffonts)."""
    data = Path(path).read_bytes()
    num = struct.unpack(">H", data[4:6])[0]
    for i in range(num):
        tag, _cs, off, _ln = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
        if tag != b"name":
            continue
        _fmt, count, str_off = struct.unpack(">HHH", data[off: off + 6])
        for j in range(count):
            pid, eid, _lid, nid, ln, so = struct.unpack(">HHHHHH", data[off + 6 + 12 * j: off + 18 + 12 * j])
            if nid != 6:
                continue
            raw = data[off + str_off + so: off + str_off + so + ln]
            return raw.decode("utf-16-be") if pid in (0, 3) else raw.decode("latin-1")
    return Path(path).stem
