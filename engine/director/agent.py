"""The Director agent's thinking: PLAN the page from the manuscript + brief, compose each panel's image PROMPT from the
master prompt, CRITIC each candidate against the 10-point final quality test, decide REVISE / accept / flag.

Pure functions — the studio glue (database rows, painting, the job, the run record) is backend/director.py.

Who enforces what:
- deterministic (code): verbatim callouts, character keys, the lock gate, panel count and hierarchy (3-5 panels:
  1 dominant + 2-3 narrative + 1 detail, or a single full-page plate), the image prompt never asking for text (lint),
  the exact negative list in every prompt, image size / aspect, near-duplicate panels (perceptual hash), in-image text
  (OCR when tesseract is installed), the budget cap, the retry limit, nothing auto-approved;
- model-judged (critic role, vision): the ten points of the FINAL QUALITY TEST, character consistency against the
  attached locked references, anatomy / hands / head count (Ravana's ten heads), era palette and period detail,
  the superhero / anime / plastic look, the proportion rule.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from . import guardrails as G
from .brief import SceneBrief, is_verbatim, normalise

ROLES = ("dominant", "narrative", "detail")
SCALES = ("EWS", "WS", "MWS", "MS", "MCU", "CU", "ECU")
STATES = ("quiet", "rising", "peak", "ego", "knowledge", "voice")
BEATS = ("calm", "tension", "action", "revelation")
ROLE_WEIGHT = {"dominant": 2.2, "narrative": 1.0, "detail": 0.55, "plate": 1.0}
PASS_MIN, PASS_MEAN = 6, 7.0

CAMERA = {
    "EWS": "extreme wide, high vantage, 24mm, deep focus; figures small at true scale",
    "WS": "wide establishing shot, eye level or slightly high, 28mm, deep focus; full figures, the environment dominant",
    "MWS": "medium wide, 35mm, deep focus; figures knee-up, the setting readable behind them",
    "MS": "medium shot, 50mm, moderate depth of field; waist-up",
    "MCU": "medium close-up, 85mm, shallow depth of field; chest-up",
    "CU": "close-up, 100mm, shallow depth of field; one face",
    "ECU": "extreme close-up, macro; one object, one hand or one pair of eyes fills the frame",
}


# ---------------------------------------------------------------------------------------------------------------
# PLAN
# ---------------------------------------------------------------------------------------------------------------

PLAN_SYSTEM = """You are the ART DIRECTOR of the graphic-novel adaptation of THE CYCLE OF DHARMA. You plan ONE comic page.

Rules you must follow exactly:
- Use only events in the supplied manuscript chapter. Never invent events, relationships or dialogue.
- {min_p}-{max_p} panels with a hierarchy: exactly one "dominant" (large establishing or emotionally dominant image),
  two or three "narrative" panels, and one "detail" (close-up or symbolic detail). If the brief asks for a full page
  (a major revelation, divine encounter or dramatic transition) return exactly one panel with role "plate".
- Every "narration" and "dialogue" string must be copied VERBATIM from the manuscript text (exact words; you may cut
  a sentence at a natural boundary or elide with "..."). Empty string if the panel needs none. Include every line
  the author's brief lists, verbatim, in the panel where it happens. Keep callouts concise.
- "scene" describes only what the camera sees (no lettering, no captions, no signs, no quoted words).
- "characters" is a subset of the brief's character keys, exactly as given.
- Panels are in reading order; the reader must never be confused about what happens first.

Return JSON only:
{{"page_beat": "calm|tension|action|revelation", "panels": [{{"role": "dominant|narrative|detail|plate", "scale":
"EWS|WS|MWS|MS|MCU|CU|ECU", "beat": "calm|tension|action|revelation", "state": "quiet|rising|peak|ego|knowledge|voice",
"scene": "...", "characters": ["form/key"], "narration": "...", "dialogue": "...", "speaker": "Name or null"}}]}}

The author's MASTER ART-DIRECTION PROMPT follows verbatim; it is the constant authority for every choice.

{master}"""


@dataclass
class PanelPlan:
    n: int
    role: str
    scale: str
    beat: str
    state: str
    scene: str
    characters: list[str] = field(default_factory=list)
    narration: str = ""
    dialogue: str = ""
    speaker: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"n": self.n, "role": self.role, "scale": self.scale, "beat": self.beat, "state": self.state, "scene": self.scene,
                "characters": self.characters, "narration": self.narration, "dialogue": self.dialogue, "speaker": self.speaker}


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for para in re.split(r"\n\s*\n|\n", text or ""):
        para = para.strip()
        if not para:
            continue
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[“\"A-Z0-9फ])|(?<=[.!?][”\"])\s+", para) if s.strip()]
    return out


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Zऀ-ॿ]{4,}", (t or "").lower())}


def anchor_index(sents: list[str], brief: SceneBrief) -> int:
    """Where in the chapter the brief's moment is: the first brief line, else the sentence most like the action."""
    for ln in brief.lines:
        target = normalise(ln.text)[:60]
        for i, s in enumerate(sents):
            if target and target[:40] in normalise(s):
                return i
    aw = _words(brief.action)
    if not aw:
        return 0
    scores = [(len(aw & _words(s)), -i) for i, s in enumerate(sents)]
    best = max(range(len(sents)), key=lambda i: scores[i]) if sents else 0
    return best if sents and scores[best][0] > 0 else 0


def _clean_scene(t: str) -> str:
    """Scene text for the painter: no quotation marks (image models letter quoted words)."""
    t = re.sub(r"[\"“”„‟«»]", "", t or "")
    return re.sub(r"\s+", " ", t).strip()


def _speaker_after(sentence: str, cast_names: list[str]) -> str | None:
    m = re.search(r"[”\"]\s*,?\s*([A-Z][\w\-]+)\s+(?:said|asked|whispered|replied|called|answered)", sentence)
    if m and m.group(1) in cast_names:
        return m.group(1)
    m = re.match(r"^([A-Z][\w\-]+)\s+(?:said|asked|whispered|replied)", sentence)
    if m and m.group(1) in cast_names:
        return m.group(1)
    return None


def _quote_in(sentence: str) -> str:
    m = re.search(r"[“\"]([^”\"]{3,220})[”\"]", sentence)
    return m.group(1).strip().rstrip(",") if m else ""


def _beat_for(text: str) -> str:
    low = text.lower()
    if any(k in low for k in ("remember", "awak", "reveal", "open its eyes", "opened her eyes", "divine", "vast form")):
        return "revelation"
    if any(k in low for k in ("arrow", "fight", "struck", "battle", "ran ", "fell", "explod", "fire", "burn", "charg")):
        return "action"
    if any(k in low for k in ("wait", "silence", "watched", "afraid", "dark", "count")):
        return "tension"
    return "calm"


def fallback_plan(manuscript: str, brief: SceneBrief, cast_names: list[str] | None = None, min_p: int = 3, max_p: int = 5) -> dict[str, Any]:
    """Deterministic plan: sentences selected from the chapter around the brief's moment (no model)."""
    cast_names = cast_names or []
    sents = sentences(manuscript)
    if not sents:
        sents = [brief.action or "(no manuscript)"]
    a = anchor_index(sents, brief)
    window = sents[max(0, a - 1): a + 10]
    narr_pool = [s for s in window if not re.search(r"[“”\"]", s) and 12 <= len(s) <= 240]
    talk_pool = [(s, _quote_in(s), _speaker_after(s, cast_names)) for s in window if _quote_in(s)]
    beat = _beat_for(brief.action + " " + " ".join(window[:4]))
    chars = list(brief.characters)
    setting_short = _clean_scene(brief.setting)[:400]
    brief_narr = [ln for ln in brief.lines if ln.kind == "narration"]
    brief_talk = [ln for ln in brief.lines if ln.kind != "narration"]
    if brief.full_page:
        p = PanelPlan(1, "plate", "WS", "revelation", "knowledge", _clean_scene(f"{brief.action}. {setting_short}"), chars,
                      brief_narr[0].text if brief_narr else (narr_pool[0] if narr_pool else ""), brief_talk[0].text if brief_talk else "",
                      brief_talk[0].speaker if brief_talk else None)
        return {"page_beat": "revelation", "panels": [p.to_json()], "source": "fallback"}
    n = max(min_p, min(max_p, 4 if len(window) >= 4 else 3))
    roles = ["dominant"] + ["narrative"] * (n - 2) + ["detail"]
    scales = {"dominant": "WS" if chars else "EWS", "narrative": "MS", "detail": "CU"}
    panels: list[PanelPlan] = []
    used: set[str] = set()
    moments = [m for m in (re.sub(r"[“\"][^”\"]*[”\"]\s*,?", "", w).strip(" ,") for w in window) if len(m) > 12] or [brief.action]
    for i, role in enumerate(roles):
        moment = moments[min(i, len(moments) - 1)]
        if role == "dominant":
            scene = f"{brief.action}. {moment}"
        elif role == "detail":
            scene = f"A close symbolic detail from the same moment: {moment}"
        else:
            scene = f"{brief.action} — the moment: {moment}"
        state = "ego" if any(k.startswith("ravana") for k in chars) and role != "detail" else ("rising" if beat == "action" else "quiet")
        panels.append(PanelPlan(i + 1, role, scales[role] if not (role == "narrative" and i == n - 2) else "MCU", beat, state, _clean_scene(scene),
                                chars if role != "detail" else chars[:1]))
    # callouts: the author's lines first (in order), then manuscript sentences from the window
    talk_slots = [p for p in panels if p.role == "narrative"] + [p for p in panels if p.role == "dominant"] + [p for p in panels if p.role == "detail"]
    for ln, p in zip(brief_talk, talk_slots):
        p.dialogue, p.speaker = ln.text, ln.speaker
        p.state = "voice"
        used.add(normalise(ln.text))
    narr_slots = [p for p in panels if p.role == "dominant"] + [p for p in panels if p.role != "dominant"]
    for ln, p in zip(brief_narr, narr_slots):
        p.narration = ln.text
        used.add(normalise(ln.text))
    pool = [s for s in narr_pool if normalise(s) not in used]
    for p in panels:
        if not p.narration and pool and p.role != "detail":
            p.narration = pool.pop(0)
    if not brief_talk:
        for (s, q, who), p in zip([t for t in talk_pool if t[2]], [p for p in panels if p.role == "narrative" and not p.dialogue]):
            p.dialogue, p.speaker = q, who
            p.state = "voice"
    return {"page_beat": beat, "panels": [p.to_json() for p in panels], "source": "fallback"}


def check_plan(plan: dict[str, Any], manuscript: str, brief: SceneBrief, min_p: int = 3, max_p: int = 5) -> list[str]:
    """Every failure of a plan against the guardrails (empty list = valid)."""
    fails: list[str] = []
    panels = plan.get("panels") or []
    if brief.full_page:
        if len(panels) != 1:
            fails.append(f"a full-page plate has exactly one panel (got {len(panels)})")
    else:
        if not (min_p <= len(panels) <= max_p):
            fails.append(f"{min_p}-{max_p} panels required (got {len(panels)})")
        roles = [p.get("role") for p in panels]
        if roles.count("dominant") != 1:
            fails.append(f"exactly one dominant panel (got {roles.count('dominant')})")
        if not (2 <= roles.count("narrative") <= 3) and len(panels) >= 4:
            fails.append(f"two or three narrative panels (got {roles.count('narrative')})")
        if roles.count("detail") < 1 and len(panels) >= 3:
            fails.append("one close-up or symbolic detail panel")
    allowed = set(brief.characters)
    for i, p in enumerate(panels, 1):
        for fld in ("narration", "dialogue"):
            t = (p.get(fld) or "").strip()
            if t and not is_verbatim(t, manuscript) and not any(normalise(t) == normalise(ln.text) and ln.adapted_approved for ln in brief.lines):
                fails.append(f"panel {i} {fld} is not verbatim from the manuscript: {t[:90]}")
        extra = [c for c in p.get("characters") or [] if c not in allowed]
        if extra:
            fails.append(f"panel {i} names characters outside the brief: {extra}")
        if re.search(r"[“”\"]", p.get("scene") or ""):
            fails.append(f"panel {i} scene contains quoted words (image models letter them)")
    said = " | ".join(normalise((p.get("narration") or "") + " " + (p.get("dialogue") or "")) for p in panels)
    for ln in brief.lines:
        if normalise(ln.text) not in said:
            fails.append(f"the brief's line is missing from the page: {ln.text[:90]}")
    return fails


def _normalise_plan(raw: Any, brief: SceneBrief) -> dict[str, Any]:
    panels = []
    for i, p in enumerate((raw or {}).get("panels") or [], 1):
        if not isinstance(p, dict):
            continue
        role = p.get("role") if p.get("role") in (*ROLES, "plate") else ("dominant" if i == 1 else "narrative")
        panels.append(PanelPlan(i, role, p.get("scale") if p.get("scale") in SCALES else "MS", p.get("beat") if p.get("beat") in BEATS else "calm",
                                p.get("state") if p.get("state") in STATES else "quiet", _clean_scene(p.get("scene") or brief.action),
                                [c for c in p.get("characters") or [] if isinstance(c, str)], (p.get("narration") or "").strip(),
                                (p.get("dialogue") or "").strip(), p.get("speaker") or None).to_json())
    beat = (raw or {}).get("page_beat")
    return {"page_beat": beat if beat in BEATS else "calm", "panels": panels}


def repair_plan(plan: dict[str, Any], manuscript: str, brief: SceneBrief, cast_names: list[str]) -> dict[str, Any]:
    """Keep the model's panels but replace any callout that is not verbatim with deterministic sentence selection."""
    fb = fallback_plan(manuscript, brief, cast_names)
    fbp = fb["panels"]
    allowed = set(brief.characters)
    for i, p in enumerate(plan["panels"]):
        alt = fbp[min(i, len(fbp) - 1)]
        for fld in ("narration", "dialogue"):
            t = p.get(fld) or ""
            if t and not is_verbatim(t, manuscript):
                p[fld] = alt.get(fld) or ""
                if fld == "dialogue":
                    p["speaker"] = alt.get("speaker")
        p["characters"] = [c for c in p.get("characters") or [] if c in allowed]
    said = " ".join(normalise((p.get("narration") or "") + " " + (p.get("dialogue") or "")) for p in plan["panels"])
    for ln in brief.lines:
        if normalise(ln.text) not in said:
            target = next((p for p in plan["panels"] if not p.get("dialogue" if ln.kind != "narration" else "narration")), plan["panels"][-1] if plan["panels"] else None)
            if target is not None:
                if ln.kind == "narration":
                    target["narration"] = ln.text
                else:
                    target["dialogue"], target["speaker"] = ln.text, ln.speaker
    plan["source"] = "model+repair"
    return plan


def plan_page(manuscript: str, brief: SceneBrief, chapter_label: str, age: str, ask: Callable[..., Any] | None = None,
              cast_names: list[str] | None = None, character_names: dict[str, str] | None = None) -> dict[str, Any]:
    """The script_writer proposes the page; validated verbatim; re-asked once with the failures; then repaired or
    replaced by the deterministic fallback. Returns the plan with its `source`, `attempts` and `failures`."""
    g = G.load()
    arch = g.page_architecture
    min_p, max_p = arch.get("min_panels", 3), arch.get("max_panels", 5)
    system = PLAN_SYSTEM.format(min_p=min_p, max_p=max_p, master=g.raw)
    user = {"manuscript_chapter": chapter_label, "age": G.AGE_NAMES.get(age, age), "brief": {
        "action": brief.action, "characters": [{"key": k, "name": (character_names or {}).get(k, k)} for k in brief.characters], "setting": brief.setting,
        "lines_to_reproduce": [{"text": ln.text, "kind": ln.kind, "speaker": ln.speaker} for ln in brief.lines], "full_page": brief.full_page},
        "manuscript_text": (manuscript or "")[:60000]}
    log: list[dict[str, Any]] = []
    used_fallback = {"v": False}

    def _fb() -> dict[str, Any]:
        used_fallback["v"] = True
        return fallback_plan(manuscript, brief, cast_names, min_p, max_p)

    if ask is None:
        from engine import llm

        ask = llm.ask_json
    import json

    raw = ask("script_writer", system, json.dumps(user, ensure_ascii=False), fallback=_fb, max_tokens=6000)
    if used_fallback["v"]:
        plan = raw if isinstance(raw, dict) and raw.get("source") == "fallback" else _fb()
        plan.update(attempts=0, failures=[], source="fallback")
        return plan
    plan = _normalise_plan(raw, brief)
    fails = check_plan(plan, manuscript, brief, min_p, max_p)
    log.append({"attempt": 1, "failures": fails})
    if fails:
        user["previous_plan"] = plan
        user["failures"] = fails
        user["instruction"] = "Your previous plan failed these checks. Fix every failure; copy callouts verbatim from manuscript_text."
        used_fallback["v"] = False
        raw2 = ask("script_writer", system, json.dumps(user, ensure_ascii=False), fallback=_fb, max_tokens=6000)
        if not used_fallback["v"]:
            plan = _normalise_plan(raw2, brief)
            fails = check_plan(plan, manuscript, brief, min_p, max_p)
            log.append({"attempt": 2, "failures": fails})
    if fails:
        structural = [f for f in fails if "verbatim" not in f and "missing" not in f and "outside the brief" not in f]
        plan = _fb() if structural or not plan["panels"] else repair_plan(plan, manuscript, brief, cast_names or [])
        plan.setdefault("source", "fallback")
        if structural or not plan.get("panels"):
            plan["source"] = "fallback"
    else:
        plan["source"] = "model"
    plan["attempts"] = len(log)
    plan["failures"] = log
    return plan


# ---------------------------------------------------------------------------------------------------------------
# PROMPT
# ---------------------------------------------------------------------------------------------------------------


def _first(text: str, startswith: str) -> str:
    for s in re.split(r"\n\s*\n", text):
        if s.strip().startswith(startswith):
            return " ".join(s.split())
    return ""


def condensed_master(age: str, plate: bool, names_present: list[str]) -> dict[str, str]:
    """The master prompt condensed to its image-relevant sections, quoting the author's words:
    project essence, §1, §2 (texture, only for a full-page plate), §4 (this panel's age), §5, §10, §11 (all negatives)."""
    g = G.load()
    proj = g.preamble.get("PROJECT", "")
    core = g.preamble.get("CORE CREATIVE PHILOSOPHY", "")
    parts: dict[str, str] = {}
    parts["project"] = " ".join(x for x in (_first(proj, "The artwork must combine"), _first(proj, "This is not a conventional"),
                                            _first(core, "Divine power should feel")) if x)
    s1 = g.section(1)
    parts["s1_cinematic"] = "Cinematic visual quality: " + "; ".join(b.rstrip(".") for b in s1.bullets) + ". " + _first(s1.text, "Target:") + " " + _first(s1.text, "Avoid plastic")
    if plate:
        s2 = g.section(2)
        parts["s2_parchment"] = ("Signature parchment aesthetic (this is a full-page plate): warm ivory parchment base with " + "; ".join(b.rstrip(".").lower() for b in s2.bullets)
                                 + ". " + _first(s2.text, "Illustrations should emerge") + " " + _first(s2.text, "Keep the effect"))
    a = g.ages[age]
    present = [n for n in G.CHARACTERS if n in names_present]
    directives = [s for n in present for s in a.directives.get(n, [])]
    # Hanuman and Ravana carry series-wide rules even outside their age block
    for n in present:
        for d in g.characters.get(n, []):
            if d["age"] in ("all", age) or n in ("Hanuman", "Ravana"):
                if d["text"] not in directives:
                    directives.append(d["text"])
    parts["s4_age"] = (f"{a.name.upper()} — {a.subtitle}. Palette: {a.palette_text} Visual language: {a.visual_language} "
                       + " ".join(a.general) + (" " + " ".join(directives) if directives else "")).strip()
    s5 = g.section(5)
    parts["s5_consistency"] = "Character consistency, non-negotiable: maintain consistent " + "; ".join(b.rstrip(".").lower() for b in s5.bullets) + ". Do not redesign a character between panels."
    s10 = g.section(10)
    parts["s10_lighting"] = "Lighting and rendering: " + "; ".join(b.rstrip(".").lower() for b in s10.bullets) + ". " + _first(s10.text, "Prefer tactile")
    parts["s11_negative"] = "STRICT NEGATIVE DIRECTIONS: " + " ".join(g.negatives)
    return parts


NO_TEXT = ("No text in the image: no lettering, captions, speech balloons, signs, labels, logos, watermarks or written symbols "
           "of any kind; all typography is typeset by the studio afterwards.")
PROPORTION = ("Proportion rule: one scale per panel; everything at true physical scale to everything else; no giant figures "
              "unless the manuscript says so.")
OVERFRAME = "Compose with about 30% extra picture around the subject: the frame is cut into an irregular shard on the page."


def compose_prompt(age: str, panel: dict[str, Any], brief: SceneBrief, chapter_label: str, looks: list[str], ref_names: list[str],
                   names_present: list[str], plate: bool = False, fix: str = "") -> dict[str, Any]:
    """One panel's image prompt = condensed master prompt + locked looks + the scene brief + the panel's shot.
    Returns {prompt, parts, chars}. Never asks for text; quoted words are stripped from the scene."""
    m = condensed_master(age, plate, names_present)
    parts: dict[str, str] = {}
    if ref_names:
        parts["references"] = (f"The attached image(s) are the locked canonical reference sheets for {', '.join(ref_names)}: keep each face, "
                               "hair, skin tone, proportions, costume and ornaments exactly; paint them into this new scene.")
    parts.update(m)
    if looks:
        parts["looks"] = "Locked character looks: " + " ".join(l.strip() for l in looks if l)
    parts["proportion"] = PROPORTION
    scale = panel.get("scale") or "MS"
    parts["camera"] = f"Camera: {CAMERA.get(scale, CAMERA['MS'])}. " + ("A full-page plate: one monumental image, the whole page." if plate else OVERFRAME)
    setting = _clean_scene(brief.setting)[:700]
    role = panel.get("role") or "narrative"
    allow_glyph = "agastya" in (brief.action + " " + panel.get("scene", "")).lower()
    parts["no_text"] = NO_TEXT + (" The only permitted glyphs are the word राम engraved on Agastya's arrow." if allow_glyph else "")
    parts["scene"] = _clean_scene(f"SCENE — manuscript {chapter_label}. Setting: {setting} Action: {brief.action}. "
                                  f"This panel ({role}, {scale}, {panel.get('beat') or 'calm'}): {panel.get('scene') or ''}")
    if fix:
        parts["correction"] = "Correction from the art director's review: " + _clean_scene(fix)
    order = ["references", "project", "s1_cinematic", "s2_parchment", "s4_age", "s5_consistency", "looks", "proportion", "camera", "s10_lighting", "no_text", "scene", "correction", "s11_negative"]
    prompt = "\n".join(parts[k] for k in order if parts.get(k))
    return {"prompt": prompt, "parts": parts, "chars": len(prompt)}


def lint_prompt(prompt: str, panel: dict[str, Any]) -> list[str]:
    """Deterministic: the image prompt must not carry the panel's dialogue nor quoted words, and must carry the negatives."""
    issues = []
    d = normalise(panel.get("dialogue") or "")
    if d and len(d) > 12 and d in normalise(prompt):
        issues.append("the dialogue text is in the image prompt")
    if re.search(r"[“”\"]", prompt):
        issues.append("quoted words in the image prompt")
    g = G.load()
    if not all(n in prompt for n in g.negatives):
        issues.append("the negative list is incomplete")
    return issues


# ---------------------------------------------------------------------------------------------------------------
# CRITIC
# ---------------------------------------------------------------------------------------------------------------

CRITIC_SYSTEM = """You are the CRITIC for the graphic-novel adaptation of THE CYCLE OF DHARMA. Image 1 is a candidate panel.
Any further images are the LOCKED canonical reference sheets of the characters named (in that order).

Score the candidate 0-10 on each point of the FINAL QUALITY TEST below (for a single panel: point 6 = the action
reads at a glance; point 7 = the image contains no lettering, so the studio can typeset cleanly). Then list every
guardrail violation you can see, checking especially:
- character consistency against the attached references (face, hair, skin tone, costume, ornaments; not redesigned);
- anatomy: hands, limbs, faces; the number of heads (Ravana has ten heads when the brief requires it: the golden head
  is intelligence, the crimson head is ego);
- era-appropriate palette and historical / technological detail for the age named;
- any text, letters, numbers, signs or meaningless glowing symbols in the image;
- superhero, anime, cartoon, plastic or video-game look; neon overload; lens-flare excess;
- the proportion rule (one scale per panel, no giants unless the manuscript says so).

Return JSON only: {"scores": {"1": n, ..., "10": n}, "violations": [{"rule": "...", "detail": "..."}],
"fix_prompt": "one or two sentences telling the painter exactly what to change (empty if nothing)"}

FINAL QUALITY TEST:
{quality}

STRICT NEGATIVE DIRECTIONS:
{negatives}

The author's MASTER ART-DIRECTION PROMPT follows verbatim; it is the authority.

{master}"""


def critic_system() -> str:
    g = G.load()
    return CRITIC_SYSTEM.replace("{quality}", "\n".join(f"{i}. {q}" for i, q in enumerate(g.quality_test, 1))).replace(
        "{negatives}", "\n".join(g.negatives)).replace("{master}", g.raw)


def critique(image: Path, references: list[tuple[str, Path]], panel: dict[str, Any], brief: SceneBrief, age: str, chapter_label: str,
             looks: list[str], ask: Callable[..., Any] | None = None) -> dict[str, Any]:
    """The critic role (vision). Without a critic key: {judged: False} — the candidate is flagged for the author."""
    import json

    if ask is None:
        from engine import llm

        ask = llm.ask_json
    g = G.load()
    a = g.ages[age]
    user = {"manuscript_chapter": chapter_label, "age": a.name, "palette": a.palette, "panel": {k: panel.get(k) for k in ("role", "scale", "beat", "scene", "characters")},
            "brief_action": brief.action, "setting": brief.setting[:800], "looks": looks,
            "reference_images": [n for n, _ in references], "ten_heads_required": any(k.startswith("ravana/ten") for k in panel.get("characters") or [])}
    unjudged = {"v": False}

    def _fb() -> dict[str, Any]:
        unjudged["v"] = True
        return {}

    raw = ask("critic", critic_system(), json.dumps(user, ensure_ascii=False), images=[image] + [p for _, p in references], fallback=_fb, max_tokens=1500)
    if unjudged["v"] or not isinstance(raw, dict):
        return {"judged": False, "scores": {}, "violations": [], "fix_prompt": "", "note": "no critic model available: flagged for the author's eye"}
    scores: dict[str, int] = {}
    for k, v in (raw.get("scores") or {}).items():
        try:
            if 1 <= int(k) <= 10:
                scores[str(int(k))] = max(0, min(10, int(round(float(v)))))
        except (TypeError, ValueError):
            continue
    viol = [v if isinstance(v, dict) else {"rule": str(v), "detail": ""} for v in raw.get("violations") or []]
    return {"judged": True, "scores": scores, "violations": viol, "fix_prompt": (raw.get("fix_prompt") or "").strip()}


def dhash(path: Path, size: int = 8) -> int:
    with Image.open(path) as im:
        g = im.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
        px = list(g.tobytes())
    bits = 0
    for y in range(size):
        for x in range(size):
            bits = (bits << 1) | (1 if px[y * (size + 1) + x] > px[y * (size + 1) + x + 1] else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def ocr_words(path: Path) -> list[str] | None:
    """Words tesseract reads in the image, or None when no OCR is installed on this Mac."""
    exe = shutil.which("tesseract")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, str(path), "stdout", "--psm", "11"], capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return None
    return [w for w in re.findall(r"[A-Za-z0-9]{3,}", out)]


def deterministic_checks(path: Path, orientation: str, other_hashes: list[int], dry_run: bool) -> dict[str, Any]:
    """Code-enforced checks on a painted candidate."""
    checks: list[dict[str, Any]] = []
    with Image.open(path) as im:
        w, h = im.size
    r = w / max(1, h)
    got = "landscape" if r > 1.15 else ("portrait" if r < 0.87 else "square")
    checks.append({"check": "size", "ok": max(w, h) >= 1024, "detail": f"{w}×{h}"})
    checks.append({"check": "aspect", "ok": got == orientation, "detail": f"{got} (wanted {orientation})"})
    hsh = dhash(path)
    if dry_run:
        checks.append({"check": "near-duplicate", "ok": True, "skipped": True, "detail": "placeholder image (dry run)"})
        checks.append({"check": "no text in image", "ok": True, "skipped": True, "detail": "placeholder image (dry run)"})
    else:
        close = [hamming(hsh, o) for o in other_hashes]
        dup = any(d <= 6 for d in close)
        checks.append({"check": "near-duplicate", "ok": not dup, "detail": f"min distance {min(close)}" if close else "first panel"})
        words = ocr_words(path)
        if words is None:
            checks.append({"check": "no text in image", "ok": True, "skipped": True, "detail": "no OCR installed (tesseract); the critic checks text"})
        else:
            checks.append({"check": "no text in image", "ok": len(words) <= 1, "detail": ("read: " + " ".join(words[:8])) if words else "none read"})
    return {"checks": checks, "dhash": hsh, "ok": all(c["ok"] for c in checks)}


def verdict(critic: dict[str, Any], det: dict[str, Any]) -> dict[str, Any]:
    """pass = every quality point >= 6, mean >= 7, no violations, every deterministic check ok.
    Unjudged (no critic model) never passes silently: it is flagged for the author."""
    reasons = [f"{c['check']}: {c['detail']}" for c in det.get("checks", []) if not c["ok"]]
    if not critic.get("judged"):
        return {"pass": False, "judged": False, "mean": None, "min": None, "failed_points": [], "reasons": reasons + ["unjudged: no critic model — author review required"],
                "retry": bool(reasons)}
    sc = critic.get("scores") or {}
    vals = [sc.get(str(i)) for i in range(1, 11)]
    missing = [i for i, v in enumerate(vals, 1) if v is None]
    nums = [v for v in vals if v is not None]
    mean = round(sum(nums) / len(nums), 2) if nums else 0.0
    failed = [i for i, v in enumerate(vals, 1) if v is not None and v < PASS_MIN]
    reasons += [f"point {i} scored {vals[i - 1]}" for i in failed]
    reasons += [f"{v.get('rule')}: {v.get('detail')}" for v in critic.get("violations") or []]
    if missing:
        reasons.append(f"points not scored: {missing}")
    ok = not reasons and mean >= PASS_MEAN
    if not ok and mean < PASS_MEAN and f"mean {mean}" not in reasons:
        reasons.append(f"mean {mean} < {PASS_MEAN}")
    return {"pass": ok, "judged": True, "mean": mean, "min": min(nums) if nums else None, "failed_points": failed, "reasons": reasons, "retry": not ok}


def rank_key(c: dict[str, Any]) -> tuple:
    v = c.get("verdict") or {}
    return (1 if v.get("pass") else 0, 1 if (c.get("checks") or {}).get("ok") else 0, v.get("mean") or 0, -len(v.get("reasons") or []), -c.get("attempt", 0))


# ---------------------------------------------------------------------------------------------------------------
# ESTIMATE
# ---------------------------------------------------------------------------------------------------------------

PLAN_USD, CRITIC_USD = 0.03, 0.01


def estimate(panels: int, candidates: int, retries: int, image_usd: float, critic_on: bool, text_live: bool, critic_live: bool) -> dict[str, Any]:
    images = panels * candidates
    worst = panels * candidates * (1 + retries)
    crit = (CRITIC_USD if (critic_on and critic_live) else 0.0)
    plan = PLAN_USD if text_live else 0.0
    usd = images * (image_usd + crit) + plan
    usd_worst = worst * (image_usd + crit) + plan * 2
    return {"panels": panels, "images": images, "images_worst": worst, "usd": round(usd, 3), "usd_worst": round(usd_worst, 3), "per_image": image_usd}


def png_bytes_size(png: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png)) as im:
        return im.size
