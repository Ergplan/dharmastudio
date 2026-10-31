"""PAINTED PAGE mode: the image model paints the WHOLE comic page — panels, parchment, narration boxes and the lettering
inside them — in ONE fixed house style, and a vision model proofreads every lettered word afterwards.

Why: the author rejected the composited-shard pages (too dark, too detailed, not parchment). In this mode the image
model letters the page itself, so the text is the risk; it is controlled three ways:
  1. every box text is a verbatim manuscript excerpt (trimmed at word boundaries or elided with "…"), at most
     MAX_BOX_WORDS words — longer lines are rejected with a message telling the author to split them;
  2. the prompt spells every box out in quotes, in reading order, and forbids any other text;
  3. after painting, the critic model transcribes every lettered text in the image; a page passes only if every
     expected text appears exactly (quotes, dashes and case normalised) and no other text exists. Failed pages are
     repainted with a lettering correction (the studio does that, up to 2 times), never auto-approved.

The house style below is the author's sentence and is used VERBATIM on every page (the phrase "burning Lanka" is part
of it; the scene section of each prompt decides the actual content).
"""

from __future__ import annotations

import difflib
import io
import json
import random
import re
import textwrap
import unicodedata
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .brief import fragments, normalise

HOUSE_STYLE = ("Hindu graphic novel. Epic mythic graphic-novel page rendered in a richly textured parchment-and-ink style, with torn panel "
               "edges, cinematic firelight, storm-dark skies, burning Lanka, layered narration boxes, and serif typography.")
TYPOGRAPHY = ("Lettering: LARGE, bold, highly legible dark serif type in parchment narration boxes, at most 14 words per box, generous box "
              "padding, text spelled exactly as given in quotes; no other text anywhere except the given box texts and the chapter header.")
PACING = ("Fast-paced and readable: 3 to 5 panels of clearly different irregular shapes and sizes, bold simple shapes, bright firelight "
          "against storm-dark skies, not muddy or over-detailed.")
SAFE_AREA = ("Format: one full portrait comic page (2:3); keep every narration box, speech balloon and the header well inside the page, "
             "at least 6% from every edge, because the outer edge is trimmed in print.")
MAX_BOX_WORDS = 14
SIZE = (1024, 1536)  # portrait, quality high
TEXT_MODEL_DEFAULT = "gpt-6.1-sol"
TEXT_MODEL_FALLBACK = "gpt-5.5"

SHOT_WORDS = {"EWS": "extreme wide shot", "WS": "wide shot", "MWS": "medium wide shot", "MS": "medium shot", "MCU": "medium close-up",
              "CU": "close-up", "ECU": "extreme close-up"}
BOOK_WORDS = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE"}


class BoxTextError(ValueError):
    """A box text that cannot be lettered: too long, or not in the manuscript. `errors` lists every problem."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# ---------------------------------------------------------------------------------------------------------------
# box texts
# ---------------------------------------------------------------------------------------------------------------

_WORD = re.compile(r"[\wऀ-ॿ]+(?:['’][\wऀ-ॿ]+)*")
_DQ = "\"“”„‟«»″"


def word_count(text: str) -> int:
    return len(_WORD.findall(text or ""))


def clean_box_text(text: str) -> str:
    """The text as it is lettered: no surrounding quotation marks (a balloon is already speech), single spaces."""
    t = unicodedata.normalize("NFKC", text or "").strip()
    t = t.strip(_DQ + " ")
    t = re.sub(r"[“”\"]", "", t)
    t = re.sub(r"\.\s*\.\s*\.", "…", t)
    return re.sub(r"\s+", " ", t).strip()


def _at_word_boundaries(hay: str, frag: str, start: int) -> int:
    """Index of `frag` in `hay` at or after `start` that begins and ends on word boundaries (-1 if none)."""
    i = hay.find(frag, start)
    while i >= 0:
        before = hay[i - 1] if i > 0 else " "
        after = hay[i + len(frag)] if i + len(frag) < len(hay) else " "
        if not (before.isalnum() and frag[:1].isalnum()) and not (after.isalnum() and frag[-1:].isalnum()):
            return i
        i = hay.find(frag, i + 1)
    return -1


def is_verbatim_excerpt(text: str, manuscript: str) -> bool:
    """Verbatim from the manuscript, allowing trimming at word/clause boundaries and elisions marked "…" / "...".
    Quotes, dashes and whitespace are normalised (brief.normalise); the trailing full stop of a trimmed clause may go."""
    frags = fragments(text)
    if not frags:
        return False
    hay = normalise(manuscript)
    pos = 0
    for f in frags:
        f = f.rstrip(" ,;:")
        i = _at_word_boundaries(hay, f, pos)
        if i < 0 and f.endswith((".", "!", "?")):
            i = _at_word_boundaries(hay, f[:-1].rstrip(), pos)
            f = f[:-1].rstrip() if i >= 0 else f
        if i < 0:
            return False
        pos = i + len(f)
    return True


def fit_box(text: str, max_words: int = MAX_BOX_WORDS) -> str:
    """A planner-chosen manuscript sentence fitted to one box: whole clauses while they fit, else the opening words
    elided with "…". (Lines the author supplies are never trimmed silently: longer ones are rejected.)"""
    t = clean_box_text(text)
    if word_count(t) <= max_words:
        return t
    clauses = re.split(r"(?<=[,;:.!?—])\s+", t)
    out = ""
    for c in clauses:
        cand = f"{out} {c}".strip()
        if word_count(cand) > max_words:
            break
        out = cand
    if out and word_count(out) >= 4:
        return out.rstrip(",;:—- ") + ("" if out.endswith((".", "!", "?")) else "…")
    words = t.split(" ")
    acc: list[str] = []
    for w in words:
        if word_count(" ".join(acc + [w])) > max_words:
            break
        acc.append(w)
    return " ".join(acc).rstrip(",;:—- ") + "…"


def check_box(text: str, manuscript: str | None, where: str = "", adapted_approved: bool = False) -> list[str]:
    errs: list[str] = []
    t = clean_box_text(text)
    label = f"{where}: " if where else ""
    if not t:
        return [f"{label}empty box text"]
    n = word_count(t)
    if n > MAX_BOX_WORDS:
        errs.append(f"{label}“{t[:70]}{'…' if len(t) > 70 else ''}” has {n} words; a painted narration box holds at most {MAX_BOX_WORDS} — "
                    "split it into two lines (two boxes), or trim it at a clause boundary with “…”.")
    if manuscript is not None and not adapted_approved and not is_verbatim_excerpt(t, manuscript):
        errs.append(f"{label}“{t[:70]}” is not a verbatim manuscript excerpt — use the book's exact words (trim only at clause boundaries or with “…”).")
    return errs


# ---------------------------------------------------------------------------------------------------------------
# the page spec and its prompt
# ---------------------------------------------------------------------------------------------------------------


def header_text(volume: int, chapter_number: int | None, title: str) -> str:
    n = f" · {chapter_number}" if chapter_number is not None else ""
    return f"BOOK {BOOK_WORDS.get(volume, str(volume))}{n} — {title}".strip()


def spec_from_plan(plan: dict[str, Any], looks: list[str], header: str | None = None, references: list[str] | None = None,
                   names: dict[str, str] | None = None) -> dict[str, Any]:
    """The painted page from an Art Director plan: one entry per panel in reading order; narration -> a narration box,
    dialogue -> a speech balloon. Planner sentences are fitted to MAX_BOX_WORDS at clause boundaries."""
    panels = []
    for i, p in enumerate(plan.get("panels") or [], 1):
        boxes = []
        if (p.get("narration") or "").strip():
            boxes.append({"kind": "narration", "text": fit_box(p["narration"]), "speaker": None})
        if (p.get("dialogue") or "").strip():
            boxes.append({"kind": "speech", "text": fit_box(p["dialogue"]), "speaker": p.get("speaker") or None})
        shot = "full-page splash" if p.get("role") == "plate" else SHOT_WORDS.get(p.get("scale") or "MS", "medium shot")
        panels.append({"n": i, "shot": shot, "scene": (p.get("scene") or "").strip(), "role": p.get("role"), "characters": list(p.get("characters") or []),
                       "boxes": boxes})
    return {"header": header, "looks": [x.strip() for x in looks if x and x.strip()], "references": list(references or []), "panels": panels}


def boxes_of(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Every box in reading order with its panel number and index (the order the critic is asked about)."""
    out = []
    for p in spec.get("panels") or []:
        for j, b in enumerate(p.get("boxes") or []):
            out.append({"index": len(out), "panel": p.get("n"), "box": j, "kind": b.get("kind", "narration"), "speaker": b.get("speaker"), "text": clean_box_text(b.get("text", ""))})
    return out


def validate_spec(spec: dict[str, Any], manuscript: str | None = None) -> list[str]:
    errs: list[str] = []
    for p in spec.get("panels") or []:
        for b in p.get("boxes") or []:
            where = f"panel {p.get('n')} {'speech balloon' if b.get('kind') == 'speech' else 'narration box'}"
            errs += check_box(b.get("text", ""), manuscript, where, bool(b.get("adapted_approved")))
    if not spec.get("panels"):
        errs.append("the page has no panels")
    return errs


def _scene(t: str) -> str:
    t = re.sub(r"[“”\"]", "", t or "")
    return re.sub(r"\s+", " ", t).strip().rstrip(".")


def build_page_prompt(page: dict[str, Any], manuscript: str | None = None, correction: str = "") -> str:
    """HOUSE_STYLE (verbatim) + typography + pacing + safe area + optional opener header + the locked looks + every
    panel in reading order with its exact box texts. Raises BoxTextError if a box is over MAX_BOX_WORDS words or (with
    `manuscript`) not a verbatim excerpt."""
    errs = validate_spec(page, manuscript)
    if errs:
        raise BoxTextError(errs)
    lines = [HOUSE_STYLE, TYPOGRAPHY, PACING, SAFE_AREA]
    if page.get("references"):
        lines.append(f"The attached image(s) are the locked canonical reference sheets for {', '.join(page['references'])}: keep each face, hair, skin tone, "
                     "costume and ornaments exactly.")
    if page.get("header"):
        lines.append(f"It opens with the header “{page['header']}”.")
    if page.get("looks"):
        lines.append("Locked character looks (paint exactly, in every panel): " + " ".join(l.strip() for l in page["looks"]))
    lines.append("Panels in reading order:")
    for p in page.get("panels") or []:
        parts = [f"Panel {p['n']} ({p.get('shot') or 'medium shot'}): {_scene(p.get('scene', ''))}."]
        for b in p.get("boxes") or []:
            t = clean_box_text(b.get("text", ""))
            if b.get("kind") == "speech":
                parts.append(f"Speech balloon ({b.get('speaker') or 'speaker'}): “{t}”")
            else:
                parts.append(f"Narration box: “{t}”")
        lines.append(" ".join(parts))
    if correction:
        lines.append(correction)
    return "\n".join(lines)


def correction_for(verification: dict[str, Any]) -> str:
    """A lettering correction for the repaint, from a failed verification."""
    bits = []
    for b in verification.get("boxes") or []:
        if not b.get("match"):
            where = f"panel {b.get('panel')} {'speech balloon' if b.get('kind') == 'speech' else 'narration box'}"
            got = (b.get("found") or "").strip()
            bits.append(f"the {where} must read exactly “{b['text']}”" + (f" (it was painted “{got}”)" if got else " (it was missing)"))
    h = verification.get("header")
    if h and not h.get("match"):
        bits.append(f"the header must read exactly “{h['text']}”")
    for x in verification.get("extra") or []:
        bits.append(f"remove the stray text “{x}”")
    if not bits:
        return ""
    return "Lettering correction from the proofreader: " + "; ".join(bits) + ". Letter every box exactly as quoted; no other text."


# ---------------------------------------------------------------------------------------------------------------
# text verification (the critic model, vision)
# ---------------------------------------------------------------------------------------------------------------

VERIFY_SYSTEM = """You are a meticulous comic-lettering proofreader. Image 1 is one painted comic page.

1. Transcribe EVERY piece of lettered text visible anywhere in the image - narration boxes, speech balloons, the
   header, signs, banners, stray letters or numbers - exactly as painted, character for character. Keep the painted
   spelling, punctuation and capitalisation; never correct anything. Transcribe each box or balloon as ONE string,
   joining its lines with single spaces.
2. For each EXPECTED text (by index), give the transcription of the box that was meant to carry it ("" if none) and
   whether it matches the expected text exactly.

Return JSON only:
{"texts": [{"text": "...", "kind": "narration|speech|header|other"}],
 "boxes": [{"index": 0, "found": "...", "match": true}]}"""

_SQ = {ord(c): "'" for c in "‘’‚‛′`"}
_DASH = {ord(c): "-" for c in "—–‒―‐‑−"}


def norm_text(t: str) -> str:
    """Compare-form: NFKC, quotes dropped/straightened, dashes unified, '...' == '…', whitespace collapsed, lower case."""
    s = unicodedata.normalize("NFKC", t or "")
    s = s.translate({ord(c): None for c in _DQ}).translate(_SQ).translate(_DASH)
    s = re.sub(r"\.\s*\.\s*\.", "…", s)
    s = re.sub(r"\s*-\s*", " - ", s)
    s = re.sub(r"\s*…\s*", "… ", s)
    s = re.sub(r"\s+", " ", s).strip(" '")
    return s.lower()


def _alnum(t: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", t or "")).lower()


def compare(expected: list[dict[str, Any]], header: str | None, texts: list[str], model_boxes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Deterministic decision from a transcription. A box matches when one transcribed text (or up to three adjacent
    ones, if the proofreader split a box) equals it after normalisation. Every transcribed text that is not a box or
    the header is EXTRA. pass = every box matched, the header (when the page has one) present, and no extra text."""
    norm = [norm_text(t) for t in texts]
    used = [False] * len(texts)
    hdr = norm_text(header or "")
    by_idx = {int(b.get("index", -1)): b for b in (model_boxes or []) if isinstance(b, dict) and str(b.get("index", "")).lstrip("-").isdigit()}
    hits: dict[int, tuple[int, int]] = {}
    for k, e in enumerate(expected):  # pass 1: exact matches (a box may span up to three adjacent transcribed texts)
        want = norm_text(e["text"])
        for i in range(len(texts)):
            w = next((w for w in (1, 2, 3) if i + w <= len(texts) and not any(used[i:i + w]) and " ".join(norm[i:i + w]) == want), None)
            if w:
                hits[k] = (i, w)
                for j in range(i, i + w):
                    used[j] = True
                break
    out_boxes = []
    for k, e in enumerate(expected):  # pass 2: a missed box is paired with what was painted in its place (not "extra")
        mb = by_idx.get(int(e["index"])) or {}
        if k in hits:
            i, w = hits[k]
            found = " ".join(texts[i:i + w])
        else:
            free = [i for i in range(len(texts)) if not used[i]]
            mf = norm_text(mb.get("found") or "")
            pick = next((i for i in free if mf and norm[i] == mf), None)
            if pick is None:
                best = difflib.get_close_matches(norm_text(e["text"]), [norm[i] for i in free], n=1, cutoff=0.4)
                pick = next((i for i in free if best and norm[i] == best[0]), None)
            if pick is not None:
                used[pick] = True
            found = texts[pick] if pick is not None else (mb.get("found") or "").strip()
        out_boxes.append({**e, "found": found, "match": k in hits, "model_match": mb.get("match")})
    head = None
    if hdr:  # the chapter header: one text or up to four adjacent pieces, compared on its letters and digits (the
        # "·" and "—" separators are where a proofreader splits it)
        for i in range(len(texts)):
            w = next((w for w in (1, 2, 3, 4) if i + w <= len(texts) and not any(used[i:i + w]) and _alnum(" ".join(texts[i:i + w])) == _alnum(header or "")), None)
            if w:
                for j in range(i, i + w):
                    used[j] = True
                head = {"text": header, "found": " ".join(texts[i:i + w]), "match": True}
                break
        if head is None:
            head = {"text": header, "found": "", "match": False}
    extra = [t for i, t in enumerate(texts) if not used[i] and norm[i]]
    ok = all(b["match"] for b in out_boxes) and not extra and (head is None or head["match"])
    return {"boxes": out_boxes, "extra": extra, "header": head, "pass": ok}


def verify_text(image: Path, spec: dict[str, Any], ask: Callable[..., Any] | None = None, model: str | None = None) -> dict[str, Any]:
    """Send the painted page + the expected box texts to the critic model; decide pass/fail deterministically.
    Without a model (no key): {judged: False, pass: False} — flagged for the author, never silently accepted."""
    expected = boxes_of(spec)
    header = spec.get("header")
    user = json.dumps({"expected": [{"index": b["index"], "text": b["text"], "kind": b["kind"], "speaker": b["speaker"]} for b in expected],
                       "header": header or None}, ensure_ascii=False)
    used_model: dict[str, Any] = {"m": None}
    if ask is None:
        from engine import llm

        models = [m for m in dict.fromkeys([model or TEXT_MODEL_DEFAULT, TEXT_MODEL_FALLBACK]) if m]

        def ask(system: str, u: str, images: list[Path], fallback: Callable[[], Any]) -> Any:  # noqa: E306
            raw, m = llm.ask_json_models(models, system, u, images=images, fallback=fallback, max_tokens=3000)
            used_model["m"] = m
            return raw
    else:
        used_model["m"] = model or "stand-in"
    unjudged = {"v": False}

    def _fb() -> dict[str, Any]:
        unjudged["v"] = True
        return {}

    raw = ask(VERIFY_SYSTEM, user, [image], _fb)
    if unjudged["v"] or not isinstance(raw, dict):
        return {"judged": False, "pass": False, "model": None, "transcription": [], "boxes": [{**b, "found": "", "match": None} for b in expected], "extra": [],
                "note": "no text-check model available (no OpenAI key): the lettering is unproven — flagged for the author"}
    texts = []
    for t in raw.get("texts") or []:
        s = (t.get("text") if isinstance(t, dict) else str(t)) or ""
        if s.strip():
            texts.append(s.strip())
    res = compare(expected, header, texts, raw.get("boxes") if isinstance(raw.get("boxes"), list) else None)
    return {"judged": True, "model": used_model["m"], "transcription": texts, **res}


def verdict(verification: dict[str, Any]) -> dict[str, Any]:
    if not verification.get("judged"):
        return {"pass": False, "judged": False, "reasons": [verification.get("note") or "unjudged"], "retry": False}
    reasons = [f"panel {b['panel']}: expected “{b['text']}”, found “{b.get('found') or '—'}”" for b in verification.get("boxes") or [] if not b.get("match")]
    reasons += [f"extra text: “{x}”" for x in verification.get("extra") or []]
    h = verification.get("header")
    if h and not h.get("match"):
        reasons.append(f"header missing or misspelled: expected “{h['text']}”")
    return {"pass": bool(verification.get("pass")), "judged": True, "reasons": reasons, "retry": not verification.get("pass")}


def rank_key(c: dict[str, Any]) -> tuple:
    v = c.get("verification") or {}
    matched = sum(1 for b in v.get("boxes") or [] if b.get("match"))
    return (1 if v.get("pass") else 0, matched, -len(v.get("extra") or []), c.get("attempt", 0))


# ---------------------------------------------------------------------------------------------------------------
# dry run: a parchment placeholder page with the box texts lettered by PIL
# ---------------------------------------------------------------------------------------------------------------

_FONT_DIR = Path(__file__).resolve().parent.parent / "comic" / "fonts" / "library"


def _serif(size: int, bold: bool = True) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for name in ("EBGaramondwght.ttf", "CormorantGaramondwght.ttf", "Marcellus-Regular.ttf"):
        p = _FONT_DIR / name
        if p.exists():
            try:
                f = ImageFont.truetype(str(p), size)
                if bold:
                    try:
                        f.set_variation_by_axes([700])
                    except Exception:  # noqa: BLE001
                        pass
                return f
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def _panel_rects(n: int, rng: random.Random, top: int, w: int, h: int, m: int) -> list[list[tuple[float, float]]]:
    """n irregular (slanted) panel polygons of clearly different sizes, in reading order."""
    rows = {1: [1], 2: [1, 1], 3: [1, 2], 4: [1, 2, 1], 5: [2, 1, 2]}.get(n, [1] * n)
    weights = {1: [1.0], 2: [1.3, 1.0], 3: [1.35, 1.0], 4: [1.3, 1.0, 0.8], 5: [1.0, 1.3, 0.9]}.get(n, [1.0] * len(rows))
    H = h - top - m
    tot = sum(weights)
    y = float(top)
    polys = []
    for r, wt in zip(rows, weights):
        rh = H * wt / tot
        if r == 1:
            xs = [m, w - m]
        else:
            split = w * rng.uniform(0.38, 0.62)
            xs = [m, split, w - m]
        for k in range(r):
            x0, x1 = xs[k] + (6 if k else 0), xs[k + 1] - (6 if k < r - 1 else 0)
            j = lambda: rng.uniform(-10, 10)  # noqa: E731
            polys.append([(x0 + j(), y + 6 + j()), (x1 + j(), y + 6 + j()), (x1 + j(), y + rh - 6 + j()), (x0 + j(), y + rh - 6 + j())])
        y += rh
    return polys


def placeholder_page(spec: dict[str, Any], seed: int = 7, label: str = "DRY RUN") -> bytes:
    """A 1024x1536 parchment page: storm-dark panels with a firelight glow and the exact box texts lettered in large
    dark serif type inside parchment boxes (what the painted page should look like, with no image model)."""
    w, h = SIZE
    rng = random.Random(seed)
    im = Image.new("RGB", (w, h), (233, 214, 172))
    noise = Image.effect_noise((w // 4, h // 4), 22).resize((w, h), Image.Resampling.BICUBIC).convert("L")
    tint = Image.merge("RGB", [noise.point(lambda v: 150 + v // 3), noise.point(lambda v: 128 + v // 3), noise.point(lambda v: 88 + v // 3)])
    im = Image.blend(im, tint, 0.35)
    d = ImageDraw.Draw(im)
    m = 64
    top = m
    if spec.get("header"):
        f = _serif(40)
        d.text((w / 2, m + 18), spec["header"], fill=(58, 34, 18), font=f, anchor="mm")
        d.line([(w * 0.3, m + 52), (w * 0.7, m + 52)], fill=(110, 70, 40), width=2)
        top = m + 70
    panels = spec.get("panels") or []
    polys = _panel_rects(max(1, len(panels)), rng, top, w, h, m)
    font = _serif(34)
    for p, poly in zip(panels, polys):
        xs, ys = [x for x, _ in poly], [y for _, y in poly]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        art = Image.new("RGB", (int(x1 - x0) + 1, int(y1 - y0) + 1), (34, 38, 58))
        ad = ImageDraw.Draw(art)
        aw, ah = art.size
        for yy in range(ah):  # storm sky to ember ground
            k = yy / max(1, ah)
            ad.line([(0, yy), (aw, yy)], fill=(int(34 + 150 * k ** 2), int(38 + 60 * k ** 2), int(58 - 30 * k)))
        ad.ellipse([aw * 0.2, ah * 0.55, aw * 0.8, ah * 1.25], fill=(232, 132, 44))
        art = art.filter(ImageFilter.GaussianBlur(6))
        mask = Image.new("L", art.size, 0)
        ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in poly], fill=255)
        im.paste(art, (int(x0), int(y0)), mask)
        d.line(poly + [poly[0]], fill=(52, 30, 16), width=4)
        by = y0 + 16
        for b in p.get("boxes") or []:
            text = clean_box_text(b.get("text", ""))
            lines = textwrap.wrap(text, 30)
            lh = 42
            bw = min(x1 - x0 - 28, max(d.textlength(ln, font=font) for ln in lines) + 40) if lines else 100
            bh = lh * len(lines) + 28
            bx = x0 + 14 if b.get("kind") != "speech" else x1 - 14 - bw
            box = [bx, by, bx + bw, by + bh]
            if b.get("kind") == "speech":
                d.rounded_rectangle(box, radius=28, fill=(250, 244, 228), outline=(52, 30, 16), width=3)
            else:
                d.rectangle(box, fill=(240, 222, 182), outline=(92, 58, 30), width=3)
            for k, ln in enumerate(lines):
                d.text((bx + 20, by + 14 + k * lh), ln, fill=(36, 22, 12), font=font)
            by += bh + 12
    d.text((w - m, h - 22), label, fill=(150, 120, 90), font=_serif(16, bold=False), anchor="rm")
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()
