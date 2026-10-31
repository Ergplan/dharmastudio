"""Book comments — review and revise a page of the layered book from comments pinned to its elements.

A comment is anchored to one element of the page (a text box, the shloka, a margin figure, the page number, the paper,
the art — a point or a marked rectangle —, an art patch) or to the page as a whole. Applying it fires the engine:

- text box  -> Claude returns a strict JSON patch for that box only (text, style, font, size_px, align, x, y, w, h, tail);
- paper     -> Claude picks ids from the libraries (shloka, figures, textures): it never writes Sanskrit;
- art       -> Sunburst image edit of the painting (a mask from the rectangle; no rectangle: the whole painting), saved as a
               new art file (art/<page>_v<n>.jpg) — the old file stays, so undo / restore bring it back;
- art patch -> the patch's rectangle repainted into the scene, then the patch removed;
- page      -> Claude returns patches across elements, applied as ONE history step.

Every apply is one history step (one undo reverts it), records a summary, the history seq and the cost (also in the ledger).
Comments live in the page JSON (`comments`), the page review state in `status` (draft / review / approved).

POST   /books/{b}/pages/{p}/comments                 {anchor, text}       add a comment (pin)
PATCH  /books/{b}/pages/{p}/comments/{c}             {text?, status?: open|dismissed}
DELETE /books/{b}/pages/{p}/comments/{c}
POST   /books/{b}/pages/{p}/comments/{c}/apply       -> job (book_comment)
POST   /books/{b}/pages/{p}/comments/apply-all       -> job (book_comment), every open comment of the page
POST   /books/{b}/pages/{p}/comments/{c}/revert      undo that apply (when it is the page's last change)
PUT    /books/{b}/pages/{p}/status                   {status: draft|review|approved, force?}
PATCH  /books/{b}/pages/{p}/art/patches/{id}         {hidden?, x?, y?, w?, h?}
DELETE /books/{b}/pages/{p}/art/patches/{id}
GET    /books/{b}/progress                           approved / open comments / unapproved pages
POST   /books/{b}/finish                             {force?, paper?}  print PDF (job) + package, once every page is approved
"""

from __future__ import annotations

import copy
import io
import json
import re
import secrets
import tempfile
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from engine import book_render as R
from engine import providers
from engine.settings import settings

from . import book_api as A
from . import book_store as S
from . import db, jobs

router = APIRouter(prefix="/api/book", tags=["book"])

HOUSE_STYLE = ("Hindu graphic novel. Epic mythic graphic-novel page rendered in a richly textured parchment-and-ink style, with torn panel "
               "edges, cinematic firelight, storm-dark skies, burning Lanka, layered narration boxes, and serif typography.")
NO_TEXT = "no text, no lettering, no empty boxes in the painting"
DEVANAGARI = re.compile(r"[ऀ-ॿ꣠-ꣿ]")
TEXT_PATCH_KEYS = ("text", "style", "font", "size_px", "align", "x", "y", "w", "h", "tail")
SOFT_WORDS, MAX_WORDS = 16, 24
PAPER_ELEMENTS = ("shloka", "texture", "folio")


class CommentError(Exception):
    pass


# ---------------------------------------------------------------------------------
# the engines (tests replace these two)
# ---------------------------------------------------------------------------------


def ask_model(system: str, user: str, images: list[Path]) -> tuple[Any, dict[str, Any]]:
    """Claude (the studio's client, the agent model) — or the OpenAI text model when only that key is present.
    Returns (answer JSON, usage {model, cost_usd, …})."""
    from engine import llm
    from engine.claude_agent import claude_ask_json

    if settings.anthropic_api_key:
        usage: dict[str, Any] = {"provider": "anthropic"}
        return claude_ask_json(system, user, images, max_tokens=2500, usage=usage), usage
    if settings.openai_api_key:
        model = llm.OPENAI_MODELS[0]
        return llm._openai_ask_json(system, user, images, model), {"provider": "openai", "model": model, "cost_usd": 0.0}
    raise CommentError("no ANTHROPIC_API_KEY (or OPENAI_API_KEY) in .env: text and paper comments need the language model")


def image_edit(image_png: bytes, prompt: str, size: str, mask_png: bytes | None) -> providers.ImageResult:
    return providers.sunburst_edit(image_png, prompt, size, mask_png)


# ---------------------------------------------------------------------------------
# anchors
# ---------------------------------------------------------------------------------


def _clamp_rect(r: dict[str, Any], W: float, H: float) -> dict[str, float]:
    x0, y0 = max(0.0, float(r["x"])), max(0.0, float(r["y"]))
    x1, y1 = min(W, float(r["x"]) + float(r["w"])), min(H, float(r["y"]) + float(r["h"]))
    if x1 - x0 < 4 or y1 - y0 < 4:
        raise CommentError("the marked region is empty")
    return {"x": round(x0), "y": round(y0), "w": round(x1 - x0), "h": round(y1 - y0)}


def clean_anchor(a: Any, page: dict[str, Any], book: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(a, dict):
        raise CommentError("anchor is {layer, element, x, y, rect?}")
    W, H = (book.get("page_px") or [2040, 3060])[:2]
    layer, el = a.get("layer"), a.get("element") or None
    out: dict[str, Any] = {"layer": layer, "element": el, "x": round(min(W, max(0, float(a.get("x") or 0)))), "y": round(min(H, max(0, float(a.get("y") or 0))))}
    if layer == "text":
        if not any(t.get("id") == el for t in page.get("text") or []):
            raise CommentError(f"no text box {el!r} on this page")
    elif layer == "paper":
        el = el or "texture"
        out["element"] = el
        m = re.fullmatch(r"figure:(\d+)", str(el))
        if not (el in PAPER_ELEMENTS or (m and int(m.group(1)) < len((page.get("paper") or {}).get("figures") or []))):
            raise CommentError(f"unknown paper element {el!r}")
    elif layer == "art":
        art = page.get("art")
        if not art:
            raise CommentError("this page has no art")
        if el and str(el).startswith("patch:"):
            pa = next((x for x in art.get("patches") or [] if x["id"] == str(el)[6:]), None)
            if pa is None:
                raise CommentError(f"no patch {el!r}")
            out["rect"] = {k: pa[k] for k in ("x", "y", "w", "h")}
        elif el:
            raise CommentError(f"unknown art element {el!r}")
        if a.get("rect") and "rect" not in out:
            out["rect"] = _clamp_rect(a["rect"], W, H)
    elif layer == "page":
        out["element"] = None
    else:
        raise CommentError("anchor layer is text, paper, art or page")
    return out


def anchor_label(a: dict[str, Any], page: dict[str, Any]) -> str:
    el = a.get("element")
    if a["layer"] == "text":
        i = next((k for k, t in enumerate(page.get("text") or []) if t.get("id") == el), None)
        return f"text box {(i or 0) + 1} ({el})"
    if a["layer"] == "paper":
        named = {"shloka": "the shloka", "texture": "the paper", "folio": "the page number"}
        if el in named or not str(el or "").startswith("figure:"):
            return named.get(el, "the paper")
        return f"margin figure {int(str(el)[7:]) + 1}"
    if a["layer"] == "art":
        if el:
            return f"art patch {str(el)[6:]}"
        return "a region of the art" if a.get("rect") else "the art"
    return "the whole page"


def _find(page: dict[str, Any], cid: str) -> dict[str, Any]:
    c = next((c for c in page.get("comments") or [] if c.get("id") == cid), None)
    if c is None:
        raise S.BookError(404, "comment not found")
    return c


# ---------------------------------------------------------------------------------
# validation of the model's answers
# ---------------------------------------------------------------------------------


def _strict(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except HTTPException as e:
        raise CommentError(str(e.detail)) from None


def validate_text_patch(box: dict[str, Any], patch: Any, page_px: tuple[float, float]) -> tuple[dict[str, Any], list[str]]:
    """The model's patch for one box -> (the new box, warnings). Raises CommentError on anything outside the schema,
    Devanagari, too many words, or a box / tail outside the page."""
    if not isinstance(patch, dict) or not patch:
        raise CommentError("the answer has no patch for the box")
    bad = sorted(set(patch) - set(TEXT_PATCH_KEYS))
    if bad:
        raise CommentError(f"the patch has fields outside the schema: {', '.join(bad)}")
    warn: list[str] = []
    p = dict(patch)
    if "size_px" in p:
        p["size"] = p.pop("size_px")
    if "text" in p:
        if not isinstance(p["text"], str) or not p["text"].strip():
            raise CommentError("text must be a non-empty string")
        if DEVANAGARI.search(p["text"]):
            raise CommentError("Devanagari is not allowed inside a text box")
        n = len(p["text"].split())
        if n > MAX_WORDS:
            raise CommentError(f"the new text has {n} words (the house limit is about {SOFT_WORDS})")
        if n > SOFT_WORDS:
            warn.append(f"{n} words (over the ~{SOFT_WORDS} house limit)")
        if box.get("style") == "header" and "title" not in p:
            p["title"] = p["text"]
            p["text"] = " · ".join(x for x in (box.get("kicker"), p["text"]) if x)
    new = {**_strict(lambda: A.clean_text_box(p, box)), "id": box["id"]}
    W, H = page_px
    if new["x"] < 0 or new["y"] < 0 or new["x"] + new["w"] > W or new["y"] + new["h"] > H:
        raise CommentError(f"the box would leave the page ({new['x']:.0f}, {new['y']:.0f}, {new['w']:.0f} x {new['h']:.0f} on {W} x {H})")
    tail = new.get("tail")
    if tail and not (0 <= tail[0] <= W and 0 <= tail[1] <= H):
        raise CommentError("the tail points outside the page")
    return new, warn


def _figure(f: Any, base: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(f, dict):
        raise CommentError("a figure is {name, x, y, h, opacity, mirror}")
    bad = sorted(set(f) - {"name", "x", "y", "h", "opacity", "mirror"})
    if bad:
        raise CommentError(f"figure fields outside the schema: {', '.join(bad)}")
    merged = {**(base or {"x": 8, "y": 1200, "h": 420, "opacity": 0.35, "mirror": False}), **f}
    return _strict(lambda: A.clean_paper({"figures": [merged]}, {"figures": []}))["figures"][0]


def validate_paper_patch(paper: dict[str, Any], element: str, patch: Any, page_level: bool = False) -> tuple[dict[str, Any], bool | None]:
    """Paper changes by id only -> (new paper, page_number or None). An element anchor may change only that element."""
    if not isinstance(patch, dict) or not patch:
        raise CommentError("the answer has no paper patch")
    allowed = {"shloka": {"shloka_id"}, "texture": {"texture"}, "folio": {"page_number"}}.get(element, {"figure"})
    if page_level:
        allowed = {"shloka_id", "texture", "page_number", "figures"}
    if "shloka" in patch or "lines" in patch:
        raise CommentError("a shloka is chosen by id from the library (shloka_id), never written")
    bad = sorted(set(patch) - allowed)
    if bad:
        raise CommentError(f"the patch changes elements outside the comment's anchor: {', '.join(bad)}")
    out = copy.deepcopy(paper)
    if "shloka_id" in patch:
        out = _strict(lambda: A.clean_paper({"shloka_id": patch["shloka_id"]}, out))
    if "texture" in patch:
        out = _strict(lambda: A.clean_paper({"texture": patch["texture"]}, out))
    if "figures" in patch:
        if not isinstance(patch["figures"], list):
            raise CommentError("figures is a list")
        out["figures"] = [_figure(f, None) for f in patch["figures"]]
    if "figure" in patch:
        i = int(element.split(":")[1])
        figs = list(out.get("figures") or [])
        if patch["figure"] is None:
            figs.pop(i)
        else:
            figs[i] = _figure(patch["figure"], figs[i])
        out["figures"] = figs
    num = patch.get("page_number")
    return out, (bool(num) if num is not None else None)


# ---------------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------------


def _box_brief(t: dict[str, Any], i: int) -> dict[str, Any]:
    keep = ("id", "kind", "style", "font", "size", "align", "x", "y", "w", "h", "tail", "kicker", "title", "text")
    return {"n": i + 1, **{k: t[k] for k in keep if k in t}}


def page_context(book: dict[str, Any], page: dict[str, Any], number: int | None) -> dict[str, Any]:
    ps = S.pages(book["id"])
    i = next((k for k, p in enumerate(ps) if p["id"] == page["id"]), None)
    neigh = {}
    for label, k in (("previous_page", (i or 0) - 1), ("next_page", (i or 0) + 1)):
        if i is not None and 0 <= k < len(ps):
            neigh[label] = [t.get("title") or t.get("text") for t in ps[k].get("text") or []]
    paper = page.get("paper") or {}
    art = page.get("art") or None
    return {
        "page": {"id": page["id"], "number": number, "era": page.get("era"), "template": page.get("template"), "scene_type": page.get("scene_type"),
                 "page_px": book.get("page_px") or [2040, 3060], "frame": book.get("frame"),
                 "art_window": {k: art.get(k) for k in ("x", "y", "w", "h")} if art else None,
                 "art_patches": [{k: x[k] for k in ("id", "x", "y", "w", "h", "linked")} for x in (art or {}).get("patches") or []],
                 "text_boxes": [_box_brief(t, k) for k, t in enumerate(page.get("text") or [])],
                 "paper": {"texture": paper.get("texture"), "shloka": (paper.get("shloka") or {}).get("id"), "shloka_source": (paper.get("shloka") or {}).get("source"),
                           "figures": [{"index": k, **f} for k, f in enumerate(paper.get("figures") or [])], "page_number": page.get("page_number", True)}},
        **neigh,
        "styles": {"text_styles": list(R.STYLES), "manifest_styles": book.get("styles") or {}},
        "fonts": list(R.book_fonts()),
    }


def page_sketch(book: dict[str, Any], page: dict[str, Any], anchor: dict[str, Any] | None, out: Path) -> Path:
    """The page as the model sees it: the painting, each text box drawn and labelled with its id, the comment's pin."""
    from PIL import Image, ImageDraw

    A.make_thumb(book, page, S.book_dir(book["id"]), out, width=760)
    with Image.open(out) as im:
        im = im.convert("RGB")
    k = im.width / (book.get("page_px") or [2040])[0]
    d = ImageDraw.Draw(im)
    if page.get("layers", {}).get("text", True):
        for t in page.get("text") or []:
            d.rectangle([t["x"] * k, t["y"] * k, (t["x"] + t["w"]) * k, (t["y"] + t["h"]) * k], outline=(200, 30, 30), width=2)
            d.text((t["x"] * k + 4, t["y"] * k + 3), str(t["id"]), fill=(200, 30, 30))
    if anchor:
        r = anchor.get("rect")
        if r:
            d.rectangle([r["x"] * k, r["y"] * k, (r["x"] + r["w"]) * k, (r["y"] + r["h"]) * k], outline=(30, 120, 230), width=3)
        x, y = anchor["x"] * k, anchor["y"] * k
        d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(240, 180, 40), outline=(0, 0, 0))
    im.save(out, "JPEG", quality=85)
    return out


ANSWER_TEXT = {"summary": "one short sentence", "patch": {"text?": "…", "style?": "|".join(R.STYLES), "font?": "a family from fonts", "size_px?": 44,
                                                          "align?": "left|center|right", "x?": 0, "y?": 0, "w?": 0, "h?": 0, "tail?": "[x, y] or null"}}
ANSWER_PAGE = {"summary": "one short sentence", "patches": [{"target": "text:<box id>", "set": "a text patch as above"},
                                                            {"target": "paper", "set": {"shloka_id?": "id from shloka_library", "texture?": "a texture name", "page_number?": True}},
                                                            {"target": "figure:<index>", "set": "{name?, x?, y?, h?, opacity?, mirror?} or null to remove"}]}


def _catalogue() -> dict[str, Any]:
    return {"shloka_library": [{"id": s["id"], "source": s["source"], "meaning": s["meaning"], "tags": s["tags"]} for s in R.shlokas()],
            "figure_names": R.figure_names(), "textures": R.texture_names()}


# ---------------------------------------------------------------------------------
# art edits
# ---------------------------------------------------------------------------------


def page_rect_to_image(art: dict[str, Any], iw: int, ih: int, r: dict[str, float]) -> tuple[int, int, int, int] | None:
    """A page-px rectangle -> the painting's pixels (object-fit cover / contain / fill with the crop focus)."""
    x, y, w, h = (float(art[k]) for k in ("x", "y", "w", "h"))
    fit = art.get("fit") if art.get("fit") in ("cover", "contain", "fill") else "cover"
    fx, fy = (art.get("focus") or [0.5, 0.5])[:2]
    if fit == "fill":
        sx, sy, ox, oy = w / iw, h / ih, 0.0, 0.0
    else:
        s = max(w / iw, h / ih) if fit == "cover" else min(w / iw, h / ih)
        sx = sy = s
        ox, oy = (w - iw * s) * float(fx), (h - ih * s) * float(fy)
    x0 = (r["x"] - x - ox) / sx
    y0 = (r["y"] - y - oy) / sy
    x1 = (r["x"] + r["w"] - x - ox) / sx
    y1 = (r["y"] + r["h"] - y - oy) / sy
    x0, y0, x1, y1 = max(0, round(x0)), max(0, round(y0)), min(iw, round(x1)), min(ih, round(y1))
    return (x0, y0, x1, y1) if x1 - x0 >= 4 and y1 - y0 >= 4 else None


def next_art_name(bid: str, pid: str) -> str:
    d = S.book_dir(bid) / "art"
    n = 1
    while (d / f"{pid}_v{n}.jpg").exists():
        n += 1
    return f"art/{pid}_v{n}.jpg"


def edit_art(bid: str, page: dict[str, Any], rect: dict[str, float] | None, comment: str) -> dict[str, Any]:
    """Repaint the region (or the whole painting) with Sunburst. Returns {file, cost_usd, dry_run, notes}."""
    from PIL import Image, ImageDraw, ImageFilter

    art = page.get("art")
    if not art:
        raise CommentError("this page has no art")
    src = S.book_dir(bid) / art["file"]
    with Image.open(src) as im:
        orig = im.convert("RGB")
    iw, ih = orig.size
    box = page_rect_to_image(art, iw, ih, rect) if rect else None
    if rect and box is None:
        raise CommentError("the marked region is outside the visible painting")
    size = providers.SUNBURST_SIZES[providers.orientation_of(iw / ih)]
    sw, sh = (int(v) for v in size.split("x"))
    buf = io.BytesIO()
    orig.resize((sw, sh), Image.LANCZOS).save(buf, "PNG")
    image_png = buf.getvalue()
    notes: list[str] = []
    used_mask = False
    prompt = f"{comment.strip()}\n\n{HOUSE_STYLE}\n{NO_TEXT}."
    mask_png = None
    if box:
        kx, ky = sw / iw, sh / ih
        sb = (round(box[0] * kx), round(box[1] * ky), round(box[2] * kx), round(box[3] * ky))
        pct = f"{100 * box[0] / iw:.0f}-{100 * box[2] / iw:.0f}% across, {100 * box[1] / ih:.0f}-{100 * box[3] / ih:.0f}% down"
        region_only = f"\nChange ONLY the marked region ({pct}); keep everything outside it exactly as it is."
        if settings.sunburst_mask:
            m = Image.new("RGBA", (sw, sh), (255, 255, 255, 255))
            ImageDraw.Draw(m).rectangle(sb, fill=(0, 0, 0, 0))
            mb = io.BytesIO()
            m.save(mb, "PNG")
            mask_png = mb.getvalue()
        try:
            res = image_edit(image_png, prompt + region_only, size, mask_png)
            used_mask = mask_png is not None
        except Exception as exc:  # noqa: BLE001 — a model without mask support: whole-art edit, keep only the region
            if mask_png is None:
                raise
            notes.append(f"the image model refused the mask ({str(exc)[:80]}): edited the whole painting with a 'change only the marked region' instruction and kept only that region")
            res = image_edit(image_png, prompt + region_only, size, None)
        if mask_png is None and not notes:
            notes.append("no mask support configured: edited the whole painting with a 'change only the marked region' instruction and kept only that region")
    else:
        res = image_edit(image_png, prompt, size, None)
    with Image.open(io.BytesIO(res.png)) as im:
        edited = im.convert("RGB").resize((iw, ih), Image.LANCZOS)
    if box:
        feather = max(4, round(min(iw, ih) * 0.006))
        alpha = Image.new("L", (iw, ih), 0)
        ImageDraw.Draw(alpha).rectangle([box[0] - feather, box[1] - feather, box[2] + feather, box[3] + feather], fill=255)
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
        out = Image.composite(edited, orig, alpha)
    else:
        out = edited
    rel = next_art_name(bid, page["id"])
    out.save(S.book_dir(bid) / rel, "JPEG", quality=92)
    if res.dry_run:
        notes.append("dry run: no OPENAI_API_KEY, the region is a labelled placeholder")
    return {"file": rel, "cost_usd": float(res.cost_usd or 0.0), "dry_run": res.dry_run, "notes": notes, "model": res.model, "mask": used_mask}


# ---------------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------------


def _ask(book: dict[str, Any], page: dict[str, Any], c: dict[str, Any], number: int | None, answer: dict[str, Any], extra: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
    from engine.claude_agent import load_prompt

    payload = {"comment": c["text"], "anchor": {**c["anchor"], "label": anchor_label(c["anchor"], page)}, **page_context(book, page, number), **(extra or {}), "answer_format": answer}
    with tempfile.TemporaryDirectory() as td:
        sk = page_sketch(book, page, c["anchor"], Path(td) / "sketch.jpg")
        ans, usage = ask_model(load_prompt("book_comment"), json.dumps(payload, ensure_ascii=False), [sk])
    if not isinstance(ans, dict):
        raise CommentError("the model's answer is not a JSON object")
    return ans, usage


def _summary(ans: dict[str, Any], default: str) -> str:
    s = ans.get("summary")
    return str(s).strip()[:300] if isinstance(s, str) and s.strip() else default


def apply_comment(bid: str, pid: str, cid: str) -> dict[str, Any]:
    """Apply one open comment (one history step). Returns the comment's result. Raises CommentError / BookError."""
    book = S.load_book(bid)
    page = S.load_page(bid, pid)
    number = S.number_of(book, pid)
    c = _find(page, cid)
    if c["status"] == "applied":
        raise CommentError("this comment is already applied (revert it first)")
    a = c["anchor"]
    W, H = (book.get("page_px") or [2040, 3060])[:2]
    cost, usage, notes, model = 0.0, {}, [], None
    change: Callable[[dict[str, Any]], None]
    if a["layer"] == "text":
        box = next((t for t in page["text"] if t["id"] == a["element"]), None)
        if box is None:
            raise CommentError("the text box of this comment is gone")
        ans, usage = _ask(book, page, c, number, ANSWER_TEXT)
        if ans.get("patches") or (ans.get("id") and ans["id"] != box["id"]) or set(ans) - {"summary", "patch", "id"}:
            raise CommentError("the answer changes elements other than the anchored text box")
        new, notes = validate_text_patch(box, ans.get("patch"), (W, H))
        summary = _summary(ans, f"Edited {anchor_label(a, page)}")

        def change(p: dict[str, Any]) -> None:
            for i, t in enumerate(p["text"]):
                if t["id"] == new["id"]:
                    p["text"][i] = new
                    return
            raise CommentError("the text box of this comment is gone")
    elif a["layer"] == "paper":
        ans, usage = _ask(book, page, c, number, {"summary": "one short sentence", "paper": {"shloka": {"shloka_id": "an id from shloka_library or null"},
                          "texture": {"texture": "a name from textures"}, "folio": {"page_number": True}}.get(a["element"], {"figure": "{name?, x?, y?, h?, opacity?, mirror?} or null to remove"})},
                          _catalogue())
        if set(ans) - {"summary", "paper"}:
            raise CommentError("the answer changes elements other than the anchored paper element")
        new_paper, num = validate_paper_patch(page["paper"], a["element"], ans.get("paper"))
        summary = _summary(ans, f"Changed {anchor_label(a, page)}")

        def change(p: dict[str, Any]) -> None:
            p["paper"] = new_paper
            if num is not None:
                p["page_number"] = num
    elif a["layer"] == "art":
        r = edit_art(bid, page, a.get("rect"), c["text"])
        cost, notes, model = r["cost_usd"], r["notes"], r["model"]
        patch_id = str(a["element"])[6:] if a.get("element") else None
        what = f"patch {patch_id} area" if patch_id else ("the marked region" if a.get("rect") else "the painting")
        summary = f"Repainted {what}" + (" and removed the patch" if patch_id else "") + f" ({r['file'].split('/')[-1]})"

        def change(p: dict[str, Any]) -> None:
            p["art"] = {**p["art"], "file": r["file"]}
            if patch_id:
                p["art"]["patches"] = [x for x in p["art"].get("patches") or [] if x["id"] != patch_id]
    else:  # the page as a whole: several patches, one history step
        ans, usage = _ask(book, page, c, number, ANSWER_PAGE, _catalogue())
        pl = ans.get("patches")
        if not isinstance(pl, list) or not pl:
            raise CommentError("the answer has no patches")
        boxes = {t["id"]: t for t in page["text"]}
        new_boxes: dict[str, dict[str, Any]] = {}
        paper, num = copy.deepcopy(page["paper"]), None
        for x in pl:
            tgt, st = str((x or {}).get("target") or ""), (x or {}).get("set")
            if tgt.startswith("text:"):
                tid = tgt[5:]
                if tid not in boxes:
                    raise CommentError(f"no text box {tid!r}")
                nb, w = validate_text_patch(new_boxes.get(tid, boxes[tid]), st, (W, H))
                new_boxes[tid] = nb
                notes += [f"{tid}: {m}" for m in w]
            elif tgt == "paper":
                paper, n2 = validate_paper_patch(paper, "", st, page_level=True)
                num = n2 if n2 is not None else num
            elif re.fullmatch(r"figure:\d+", tgt):
                if int(tgt[7:]) >= len(paper.get("figures") or []):
                    raise CommentError(f"no {tgt}")
                paper, _ = validate_paper_patch(paper, tgt, {"figure": st})
            else:
                raise CommentError(f"unknown patch target {tgt!r}")
        summary = _summary(ans, f"Revised the page ({len(pl)} changes)")

        def change(p: dict[str, Any]) -> None:
            p["text"] = [new_boxes.get(t["id"], t) for t in p["text"]]
            p["paper"] = paper
            if num is not None:
                p["page_number"] = num
    cost += float(usage.get("cost_usd") or 0.0)
    model = model or usage.get("model")
    result: dict[str, Any] = {}

    def fn(p: dict[str, Any], seq: int) -> None:
        change(p)
        cc = _find(p, cid)
        result.update(summary=summary, history_seq=seq, cost=round(cost, 5), model=model, notes=notes, applied=S.now())
        cc["status"], cc["result"] = "applied", dict(result)

    S.mutate_page_seq(bid, pid, fn, f"comment {c['n']}: {summary}"[:160])
    return result


def h_book_comment(ctx: jobs.Ctx, params: dict[str, Any]) -> dict[str, Any]:
    from .models import Ledger

    bid, pid = str(params["book_id"]), str(params["page_id"])
    ids = [str(x) for x in params.get("comment_ids") or []]
    done, failed = [], []
    for k, cid in enumerate(ids):
        ctx.check_stop()
        ctx.progress(done=k, total=len(ids))
        try:
            r = apply_comment(bid, pid, cid)
        except (CommentError, S.BookError) as exc:
            msg = getattr(exc, "detail", None) or str(exc)
            ctx.log(f"comment {cid}: not applied — {msg}")
            try:
                S.set_comment_result(bid, pid, cid, {"error": msg, "at": S.now()})
            except S.BookError:
                pass
            failed.append({"id": cid, "error": msg})
            continue
        except Exception as exc:  # noqa: BLE001 — provider error: record it on the comment, go on with the next
            msg = f"{type(exc).__name__}: {str(exc)[:300]}"
            ctx.log(f"comment {cid}: provider error — {msg}")
            S.set_comment_result(bid, pid, cid, {"error": msg, "at": S.now()})
            failed.append({"id": cid, "error": msg})
            continue
        ctx.add_cost(r["cost"])
        if r["cost"]:
            prov = "sunburst" if str(r.get("model") or "").startswith("gpt-image") else ("anthropic" if str(r.get("model") or "").startswith("claude") else "openai")
            ctx.session.add(Ledger(provider=prov, usd=round(r["cost"], 4), ref=f"book {bid} page {pid} comment {cid}"[:200]))
            ctx.session.commit()
        ctx.log(f"comment {cid}: {r['summary']} (v{r['history_seq']}, ${r['cost']:.4f})")
        done.append({"id": cid, **r})
    ctx.progress(done=len(ids), total=len(ids))
    if failed and not done:
        raise RuntimeError("; ".join(f"{f['id']}: {f['error']}" for f in failed))
    return {"applied": done, "failed": failed, "book_id": bid, "page_id": pid}


jobs.HANDLERS.setdefault("book_comment", h_book_comment)


# ---------------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------------


def _c(fn, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN202
    try:
        return fn(*a, **k)
    except S.BookError as e:
        raise HTTPException(e.status, e.detail) from None
    except CommentError as e:
        raise HTTPException(400, str(e)) from None


def _view(bid: str, p: dict[str, Any]) -> dict[str, Any]:
    return A.page_view(bid, p)


@router.post("/books/{bid}/pages/{pid}/comments")
def add_comment(bid: str, pid: str, body: dict[str, Any]) -> dict[str, Any]:
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "the comment is empty")
    book = _c(S.load_book, bid)
    anchor = _c(clean_anchor, body.get("anchor"), _c(S.load_page, bid, pid), book)
    out: dict[str, Any] = {}

    def fn(p: dict[str, Any]) -> None:
        n = max([c.get("n", 0) for c in p.get("comments") or []] + [0]) + 1
        cid = "c" + secrets.token_hex(3)
        p.setdefault("comments", []).append({"id": cid, "n": n, "anchor": anchor, "text": text[:4000], "status": "open", "created": S.now(), "result": None})
        out["id"] = cid

    page = _c(S.mutate_page, bid, pid, fn, f"add comment ({anchor_label(anchor, _c(S.load_page, bid, pid))})")
    return {**_view(bid, page), "created": out["id"]}


@router.patch("/books/{bid}/pages/{pid}/comments/{cid}")
def patch_comment(bid: str, pid: str, cid: str, body: dict[str, Any]) -> dict[str, Any]:
    def fn(p: dict[str, Any]) -> None:
        c = _find(p, cid)
        if "text" in body:
            if not str(body["text"]).strip():
                raise S.BookError(400, "the comment is empty")
            c["text"] = str(body["text"]).strip()[:4000]
        if "status" in body:
            if body["status"] not in ("open", "dismissed"):
                raise S.BookError(400, "status is open or dismissed (applied comes from Apply)")
            if c["status"] == "applied":
                raise S.BookError(409, "revert the applied comment first")
            c["status"] = body["status"]

    label = "dismiss comment" if body.get("status") == "dismissed" else "reopen comment" if body.get("status") == "open" else "edit comment"
    return _view(bid, _c(S.mutate_page, bid, pid, fn, label))


@router.delete("/books/{bid}/pages/{pid}/comments/{cid}")
def delete_comment(bid: str, pid: str, cid: str) -> dict[str, Any]:
    def fn(p: dict[str, Any]) -> None:
        _find(p, cid)
        p["comments"] = [c for c in p["comments"] if c["id"] != cid]

    return _view(bid, _c(S.mutate_page, bid, pid, fn, "delete comment"))


def _submit(session: Session, bid: str, pid: str, ids: list[str], label: str) -> dict[str, Any]:
    from .api import job_resp

    j = jobs.submit(session, "book_comment", None, {"book_id": bid, "page_id": pid, "comment_ids": ids, "label": label})
    return job_resp(j)


@router.post("/books/{bid}/pages/{pid}/comments/{cid}/apply", status_code=202)
def apply_one(bid: str, pid: str, cid: str, session: Session = A.Sess()) -> dict[str, Any]:
    book = _c(S.load_book, bid)
    c = _c(_find, _c(S.load_page, bid, pid), cid)
    if c["status"] != "open":
        raise HTTPException(409, f"comment is {c['status']}")
    return _submit(session, bid, pid, [cid], f"Comment {c['n']} · page {S.number_of(book, pid)}")


@router.post("/books/{bid}/pages/{pid}/comments/apply-all", status_code=202)
def apply_all(bid: str, pid: str, session: Session = A.Sess()) -> dict[str, Any]:
    book = _c(S.load_book, bid)
    ids = [c["id"] for c in _c(S.load_page, bid, pid).get("comments") or [] if c["status"] == "open"]
    if not ids:
        raise HTTPException(409, "no open comments on this page")
    return _submit(session, bid, pid, ids, f"{len(ids)} comments · page {S.number_of(book, pid)}")


@router.post("/books/{bid}/pages/{pid}/comments/{cid}/revert")
def revert(bid: str, pid: str, cid: str) -> dict[str, Any]:
    c = _c(_find, _c(S.load_page, bid, pid), cid)
    seq = (c.get("result") or {}).get("history_seq")
    if c["status"] != "applied" or not seq:
        raise HTTPException(409, "this comment is not applied")
    if S.last_page_seq(bid, pid) != seq:
        raise HTTPException(409, "the page changed after this comment was applied: use Page versions to go back further")
    _c(S.undo, bid, pid)
    return A.get_page(bid, pid)


@router.put("/books/{bid}/pages/{pid}/status")
def put_status(bid: str, pid: str, body: dict[str, Any]) -> dict[str, Any]:
    st = body.get("status")
    if st not in S.PAGE_STATUSES:
        raise HTTPException(400, "status is draft, review or approved")
    page = _c(S.load_page, bid, pid)
    n_open = sum(1 for c in page.get("comments") or [] if c["status"] == "open")
    if st == "approved" and n_open and not body.get("force"):
        raise HTTPException(409, {"message": f"{n_open} open comment{'s' if n_open != 1 else ''} on this page", "open_comments": n_open})
    return _view(bid, _c(S.mutate_page, bid, pid, lambda p: p.update(status=st), f"status: {st}"))


def _patch_op(bid: str, pid: str, xid: str, op: Callable[[list[dict[str, Any]], int], None], label: str) -> dict[str, Any]:
    def fn(p: dict[str, Any]) -> None:
        pl = (p.get("art") or {}).get("patches") or []
        i = next((k for k, x in enumerate(pl) if x["id"] == xid), None)
        if i is None:
            raise S.BookError(404, "patch not found")
        op(pl, i)
        p["art"]["patches"] = pl

    return _view(bid, _c(S.mutate_page, bid, pid, fn, label))


@router.patch("/books/{bid}/pages/{pid}/art/patches/{xid}")
def patch_patch(bid: str, pid: str, xid: str, body: dict[str, Any]) -> dict[str, Any]:
    def op(pl: list[dict[str, Any]], i: int) -> None:
        if "hidden" in body:
            pl[i]["hidden"] = bool(body["hidden"])
        for k in ("x", "y", "w", "h"):
            if k in body:
                pl[i][k] = A._num(body[k], 1 if k in ("w", "h") else -10000)

    label = ("hide" if body.get("hidden") else "show") + f" patch {xid}" if set(body) == {"hidden"} else f"edit patch {xid}"
    return _patch_op(bid, pid, xid, op, label)


@router.delete("/books/{bid}/pages/{pid}/art/patches/{xid}")
def delete_patch(bid: str, pid: str, xid: str) -> dict[str, Any]:
    return _patch_op(bid, pid, xid, lambda pl, i: pl.pop(i), f"remove patch {xid}")


@router.get("/books/{bid}/progress")
def progress(bid: str) -> dict[str, Any]:
    _c(S.load_book, bid)
    return A.progress_of(S.pages(bid))


@router.post("/books/{bid}/finish", status_code=202)
def finish(bid: str, body: dict[str, Any], session: Session = A.Sess()) -> dict[str, Any]:
    """The finished comic: the print PDF (job) + the package. Refused while pages are unapproved, unless `force`."""
    _c(S.load_book, bid)
    pr = A.progress_of(S.pages(bid))
    if pr["unapproved"] and not body.get("force"):
        raise HTTPException(409, {"message": f"{len(pr['unapproved'])} of {pr['pages']} pages are not approved", "unapproved": pr["unapproved"],
                                  "open_comments": pr["open_comments"]})
    pdf = A.export_pdf(bid, {"paper": "screen" if body.get("paper") == "screen" else "print", "cover": True}, session)
    pkg = A.export_package(bid)
    return {**pdf, "package": pkg, "unapproved": pr["unapproved"], "open_comments": pr["open_comments"]}
