"""Volume covers and posters (master prompt §7, §8, §9): the poster ART prompt composed from the volume's actual chapters,
and the TYPESET title block — the image model never draws the title; the studio sets the exact strings
(THE CYCLE OF DHARMA, the volume line, RACHIT AGARWAL, the publisher line) in the engraved serif (Cinzel / Cinzel
Decorative from the font library), so the spelling is guaranteed. Vertical 2:3, print resolution (300 ppi).
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import guardrails as G
from .agent import NO_TEXT, _clean_scene, condensed_master
from .chapters import ManuscriptChapter

FONT_DIR = Path(__file__).resolve().parent.parent / "comic" / "fonts" / "library"
TITLE_FONT = FONT_DIR / "CinzelDecorative-Bold.ttf"
TEXT_FONT = FONT_DIR / "Cinzelwght.ttf"
PRINT_W, PRINT_H, PPI = 2000, 3000, 300  # 2:3 at 300 ppi = 169.3 x 254 mm

GOLD_TOP, GOLD_BOTTOM = (246, 222, 160), (176, 128, 52)


@dataclass
class CoverText:
    title: str
    volume_line: str
    author: str
    publisher: str

    def to_json(self) -> dict[str, str]:
        return {"title": self.title, "volume_line": self.volume_line, "author": self.author, "publisher": self.publisher}


def cover_text(volume_line: str, publisher: str) -> CoverText:
    """Series title and author credit come from the master prompt itself (§7), never from user input."""
    g = G.load()
    return CoverText(g.typography.get("series_title", "THE CYCLE OF DHARMA"), volume_line, g.typography.get("author_credit", "RACHIT AGARWAL"), publisher.upper())


# ---------------------------------------------------------------------------------------------------------------
# the poster art prompt
# ---------------------------------------------------------------------------------------------------------------

POSTER_SYSTEM = """You write the image prompt for the theatrical poster of one volume of THE CYCLE OF DHARMA, following
the author's master art-direction prompt (below, verbatim) — especially §8 (Volume Two) and §9 (poster composition).
Use only characters, places and images that appear in the volume's chapters supplied. One unmistakable focal point.
The painter must draw NO text at all (the studio typesets the title and credits): leave the top fifth calm and dark
enough for the series title and the bottom sixth for the credits. No quotation marks in the prompt.
Return JSON only: {"prompt": "..."}

"""


def poster_brief(volume: int, chapters: list[ManuscriptChapter]) -> dict[str, Any]:
    """Facts for the poster from the volume's actual chapters: principal characters by mentions, and key images."""
    mentions: dict[str, int] = {}
    for mc in chapters:
        for c in mc.cast:
            mentions[c["name"]] = mentions.get(c["name"], 0) + int(c.get("mentions") or 1)
    principal = [n for n, _ in sorted(mentions.items(), key=lambda kv: -kv[1])][:6]
    images = []
    for mc in chapters:
        s = _clean_scene(mc.setting)
        if s:
            images.append({"chapter": mc.label, "image": s.split(". ")[0][:220]})
    first = chapters[0].manuscript_number if chapters else None
    last = chapters[-1].manuscript_number if chapters else None
    return {"volume": volume, "chapters": f"{first}-{last}" if first and last else "", "principal": principal, "key_images": images[:20]}


def fallback_poster_prompt(volume: int, facts: dict[str, Any]) -> str:
    principal = [n for n in facts.get("principal", []) if n not in ("Hanuman",)][:4]
    imgs = "; ".join(i["image"] for i in facts.get("key_images", [])[:5])
    if volume == 2:
        centre = (f"Centre: the principal contemporary characters of Volume Two ({', '.join(principal)}) in a believable near-future India, "
                  "with Kalki's awakening as the single emotional focal point, expressed through a subtle change of light and composition, "
                  "not an explosion; behind and around them the digital world as an interconnected structure of intelligence, observation and influence.")
        upper = "Upper third: Treta and Dwapara as fractured memories emerging through torn parchment — Lanka's burning towers, Kurukshetra's chariots."
        lower = "Lower third: a believable near-future Indian city of data centres and screens, with visual echoes of the ancient story."
        motifs = "Hanuman is the visual bridge across time (the same dignified individual in every age), not a giant decorative figure. The golden flame of intelligence and the crimson thread of ego recur as symbols."
    else:
        centre = f"Centre: {', '.join(principal)} and their central conflict, one unmistakable focal point."
        upper = "Upper third: ancient-history fragments appearing through fractured parchment."
        lower = "Lower third: the world of the volume's later chapters, with visual echoes of the ancient story."
        motifs = "Hanuman remains recognisably the same individual across the ages. The golden flame and the crimson thread recur."
    return (f"Vertical 2:3 theatrical graphic-novel poster for Volume {volume} of The Cycle of Dharma. Top fifth: calm, dark, uncluttered sky "
            f"or parchment for the typeset title (paint no letters). {upper} {centre} {lower} {motifs} Key images from the volume: {imgs}. "
            "Bottom sixth: quiet and dark for the typeset credits. Avoid excessive characters and crowded faces; powerful as a small thumbnail.")


def poster_prompt(volume: int, chapters: list[ManuscriptChapter], ask: Callable[..., Any] | None = None) -> dict[str, Any]:
    """{prompt, facts, source}: the prompt_writer composes; the master prompt's image sections and the negatives are appended."""
    g = G.load()
    facts = poster_brief(volume, chapters)
    if ask is None:
        from engine import llm

        ask = llm.ask_json
    fb = {"v": False}

    def _fb() -> dict[str, Any]:
        fb["v"] = True
        return {"prompt": fallback_poster_prompt(volume, facts)}

    raw = ask("prompt_writer", POSTER_SYSTEM + g.raw, json.dumps(facts, ensure_ascii=False), fallback=_fb, max_tokens=2000)
    core = _clean_scene((raw or {}).get("prompt") if isinstance(raw, dict) else "") or fallback_poster_prompt(volume, facts)
    m = condensed_master("kali" if volume >= 2 else "treta", True, ["Hanuman", "Kalki", "Ravana", "Rama"] if volume >= 2 else ["Hanuman", "Rama", "Ravana"])
    parts = [core, m["project"], m["s1_cinematic"], m["s2_parchment"]]
    if volume >= 2:
        parts.append("Three ages integrated: " + " ".join(f"{a.name}: {a.palette_text}" for a in g.ages.values()))
    parts += [m["s5_consistency"], m["s10_lighting"], NO_TEXT + " The series title, volume line and credits are typeset by the studio.", m["s11_negative"]]
    return {"prompt": "\n".join(p for p in parts if p), "facts": facts, "source": "fallback" if fb["v"] else "model"}


# ---------------------------------------------------------------------------------------------------------------
# typesetting
# ---------------------------------------------------------------------------------------------------------------


def _font(path: Path, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(path), size)
    if weight is not None:
        try:
            f.set_variation_by_axes([weight])
        except Exception:  # noqa: BLE001 — static build of the face
            pass
    return f


def _tracked_width(text: str, font: ImageFont.FreeTypeFont, track: float) -> float:
    return sum(font.getlength(ch) for ch in text) + track * font.size * max(0, len(text) - 1)


def _fit(text: str, path: Path, max_w: float, start: int, track: float, weight: int | None = None, min_size: int = 20) -> ImageFont.FreeTypeFont:
    size = start
    while size > min_size:
        f = _font(path, size, weight)
        if _tracked_width(text, f, track) <= max_w:
            return f
        size -= 4
    return _font(path, min_size, weight)


def _text_mask(size: tuple[int, int], text: str, font: ImageFont.FreeTypeFont, cx: float, y: float, track: float) -> Image.Image:
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    x = cx - _tracked_width(text, font, track) / 2
    for ch in text:
        d.text((x, y), ch, font=font, fill=255)
        x += font.getlength(ch) + track * font.size
    return m


def _engrave(img: Image.Image, mask: Image.Image, top: tuple[int, int, int], bottom: tuple[int, int, int], depth: int) -> None:
    """Engraved / letterpress: a soft dark bed below, a gold vertical gradient face, a thin light edge above."""
    w, h = img.size
    box = mask.getbbox()
    if not box:
        return
    shadow = mask.filter(ImageFilter.GaussianBlur(depth * 1.6))
    img.paste((12, 8, 6), (depth, depth), shadow.point(lambda v: int(v * 0.85)))
    grad = Image.new("RGB", (1, h))
    y0, y1 = box[1], max(box[1] + 1, box[3])
    for y in range(h):
        t = min(1.0, max(0.0, (y - y0) / (y1 - y0)))
        grad.putpixel((0, y), tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)))
    grad = grad.resize((w, h))
    hi = Image.new("RGB", (w, h), (255, 244, 214))
    img.paste(hi, (-1, -1), mask.point(lambda v: int(v * 0.55)))
    img.paste(grad, (0, 0), mask)


def _scrim(img: Image.Image, top_frac: float, bottom_frac: float) -> None:
    w, h = img.size
    a = Image.new("L", (1, h), 0)
    for y in range(h):
        t = y / h
        v = 0.0
        if t < top_frac:
            v = (1 - t / top_frac) ** 1.6 * 0.72
        elif t > 1 - bottom_frac:
            v = ((t - (1 - bottom_frac)) / bottom_frac) ** 1.4 * 0.82
        a.putpixel((0, y), int(255 * v))
    img.paste((8, 6, 10), (0, 0), a.resize((w, h)))


def _fit_art(art: Image.Image | None, w: int, h: int) -> Image.Image:
    if art is None:
        bg = Image.new("RGB", (w, h), (52, 38, 26))
        d = ImageDraw.Draw(bg)
        for y in range(h):
            k = y / h
            d.line([(0, y), (w, y)], fill=(int(70 - 40 * k), int(50 - 32 * k), int(34 - 18 * k)))
        return bg
    art = art.convert("RGB")
    s = max(w / art.width, h / art.height)
    art = art.resize((int(art.width * s + 0.5), int(art.height * s + 0.5)), Image.Resampling.LANCZOS)
    x, y = (art.width - w) // 2, (art.height - h) // 2
    return art.crop((x, y, x + w, y + h))


def layout(text: CoverText, w: int = PRINT_W, h: int = PRINT_H) -> list[dict[str, Any]]:
    """Where each line goes (shared by the PNG/PDF raster and the SVG preview)."""
    t1, t2 = _split_title(text.title)
    margin = w * 0.07
    tw = w - 2 * margin
    title_track = 0.06
    f1 = _fit(t1, TITLE_FONT, tw, int(h * 0.075), title_track)
    f2 = _fit(t2, TITLE_FONT, tw, int(h * 0.075), title_track)
    size = min(f1.size, f2.size)
    lines = [
        {"role": "title", "text": t1, "font": "Cinzel Decorative", "file": TITLE_FONT.name, "size": size, "weight": 700, "y": h * 0.045, "track": title_track},
        {"role": "title", "text": t2, "font": "Cinzel Decorative", "file": TITLE_FONT.name, "size": size, "weight": 700, "y": h * 0.045 + size * 1.08, "track": title_track},
    ]
    fv = _fit(text.volume_line, TEXT_FONT, tw, int(h * 0.026), 0.12, 600)
    fa = _fit(text.author, TEXT_FONT, tw * 0.8, int(h * 0.034), 0.18, 700)
    fp = _fit(text.publisher, TEXT_FONT, tw, int(h * 0.0125), 0.16, 500)
    yb = h * 0.955
    lines.append({"role": "publisher", "text": text.publisher, "font": "Cinzel", "file": TEXT_FONT.name, "size": fp.size, "weight": 500, "y": yb - fp.size, "track": 0.16})
    lines.append({"role": "author", "text": text.author, "font": "Cinzel", "file": TEXT_FONT.name, "size": fa.size, "weight": 700, "y": yb - fp.size * 2.6 - fa.size, "track": 0.18})
    lines.append({"role": "volume", "text": text.volume_line, "font": "Cinzel", "file": TEXT_FONT.name, "size": fv.size, "weight": 600, "y": yb - fp.size * 2.6 - fa.size * 2.0 - fv.size, "track": 0.12})
    return lines


def _split_title(title: str) -> tuple[str, str]:
    """Two balanced lines that join back to the exact title ('THE CYCLE' / 'OF DHARMA')."""
    words = title.split(" ")
    best = (title, "")
    diff = 1e9
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        d = abs(len(a) - len(b))
        if d < diff:
            best, diff = (a, b), d
    return best


def typeset(art: Path | bytes | None, text: CoverText, out_dir: Path, stem: str = "cover") -> dict[str, Any]:
    """Compose the cover at print resolution: PNG + PDF (300 ppi) + an SVG whose text is live (exact strings)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    src = None
    if isinstance(art, (bytes, bytearray)):
        src = Image.open(io.BytesIO(art))
    elif isinstance(art, Path) and art.exists():
        src = Image.open(art)
    w, h = PRINT_W, PRINT_H
    img = _fit_art(src, w, h)
    _scrim(img, 0.24, 0.22)
    lines = layout(text, w, h)
    for ln in lines:
        path = FONT_DIR / ln["file"]
        f = _font(path, ln["size"], ln["weight"] if path == TEXT_FONT else None)
        mask = _text_mask((w, h), ln["text"], f, w / 2, ln["y"], ln["track"])
        if ln["role"] == "title":
            _engrave(img, mask, GOLD_TOP, GOLD_BOTTOM, depth=6)
        elif ln["role"] == "author":
            _engrave(img, mask, (240, 228, 200), (196, 170, 120), depth=3)
        else:
            _engrave(img, mask, (232, 214, 170), (200, 170, 112), depth=2)
    png = out_dir / f"{stem}.png"
    pdf = out_dir / f"{stem}.pdf"
    svg = out_dir / f"{stem}.svg"
    thumb = out_dir / f"{stem}_thumb.png"
    img.save(png, "PNG", dpi=(PPI, PPI), optimize=True)
    img.save(pdf, "PDF", resolution=PPI)
    t = img.copy()
    t.thumbnail((240, 360))
    t.save(thumb, "PNG")
    svg.write_text(svg_markup(text, lines, art_href="", w=w, h=h), encoding="utf-8")
    return {"png": png, "pdf": pdf, "svg": svg, "thumb": thumb, "size_px": [w, h], "ppi": PPI, "mm": [round(w / PPI * 25.4, 1), round(h / PPI * 25.4, 1)],
            "lines": [{k: v for k, v in ln.items() if k != "file"} for ln in lines], "text": text.to_json()}


def svg_markup(text: CoverText, lines: list[dict[str, Any]] | None = None, art_href: str = "", w: int = PRINT_W, h: int = PRINT_H) -> str:
    """The typeset layer as SVG with live text (preview in the UI; the strings are exactly the CoverText)."""
    lines = lines or layout(text, w, h)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
           f"<title>{escape(text.title)} — {escape(text.volume_line)}</title>",
           '<defs><linearGradient id="gold" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f6dea0"/><stop offset="1" stop-color="#b08034"/></linearGradient></defs>']
    if art_href:
        out.append(f'<image href="{escape(art_href)}" x="0" y="0" width="{w}" height="{h}" preserveAspectRatio="xMidYMid slice"/>')
    out.append(f'<g data-role="title" aria-label="{escape(text.title)}">')
    for ln in lines:
        if ln["role"] != "title":
            continue
        out.append(f'<text x="{w / 2}" y="{ln["y"] + ln["size"] * 0.8:.1f}" text-anchor="middle" font-family="{ln["font"]}, serif" font-weight="{ln["weight"]}" '
                   f'font-size="{ln["size"]}" letter-spacing="{ln["track"] * ln["size"]:.1f}" fill="url(#gold)">{escape(ln["text"])}</text>')
    out.append("</g>")
    for ln in lines:
        if ln["role"] == "title":
            continue
        out.append(f'<text data-role="{ln["role"]}" x="{w / 2}" y="{ln["y"] + ln["size"] * 0.8:.1f}" text-anchor="middle" font-family="{ln["font"]}, serif" '
                   f'font-weight="{ln["weight"]}" font-size="{ln["size"]}" letter-spacing="{ln["track"] * ln["size"]:.1f}" fill="#ead6a8">{escape(ln["text"])}</text>')
    out.append("</svg>")
    return "\n".join(out)


def svg_strings(svg: str) -> dict[str, str]:
    """Read the typeset strings back out of the SVG (tests and the UI's exact-spelling badge)."""
    from html import unescape

    title = " ".join(unescape(t) for t in re.findall(r"<text[^>]*fill=\"url\(#gold\)\"[^>]*>([^<]*)</text>", svg))
    roles = {k: unescape(v) for k, v in re.findall(r'<text data-role="(\w+)"[^>]*>([^<]*)</text>', svg)}
    return {"title": title, **roles}
