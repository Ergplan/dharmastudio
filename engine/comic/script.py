"""The prompt recipe. Every image prompt is built in layers - STYLE, GRADE, LIGHT, CAMERA, SCALE RULE, WORLD, DUEL,
character LOOKS, AVOID, SCENE - so the look is the same on every page and the script only supplies the scene.

Reverse-engineered from the approved Rameshwaram reference (2026-10-30) and merged with the author's art-direction
prompt for the sample spreads (engine/art_direction.md §A): manuscript realism and the amber/copper grade.
Character looks come from the Character table (the lock), not from prose here.
"""

from __future__ import annotations

import re
from pathlib import Path

from .visual_logic import infer_scale

STATES = ("quiet", "rising", "peak", "ego", "knowledge", "voice")
BEATS = ("calm", "tension", "action", "revelation", "hex")
SCALES = ("EWS", "WS", "MWS", "MS", "MCU", "CU", "ECU")
OVERFRAME = 0.30  # shards are cropped at layout, so panels are generated with 30% extra picture

COMIC_STYLE = (
    "An ancient Indian illuminated historical manuscript brought to life through photorealistic cinematic illustration, "
    "in the epic cinematic fantasy register (Advent Children, FF7 Rebirth cutscene still): ultra-detailed digital "
    "painting with smooth airbrushed rendering and crisp edges, physically based light, volumetric smoke and god-rays, "
    "physically plausible skin pores, hair, textiles, bronze, gold, weapons, stone architecture, ocean water, fire and "
    "smoke, atmospheric perspective, idealised proportions with natural anatomy and believable expressions, eyes with "
    "more depth than life, HDR glow on fire and gold. Epic historical cinema quality: not photoreal, never cartoon, not "
    "anime, not glossy video-game art, not flat digital or generic fantasy illustration. Absolutely no text, lettering, "
    "captions, borders or logos. "
)
COMIC_GRADE = (
    "Grade: complementary colour grade pushed to the ceiling with warm amber and copper for Lanka, deep turquoise and "
    "midnight blue for water and night, restrained glowing highlights; low-key exposure with blacks crushed and most of "
    "the frame in shadow so the fire and the one cold light read as the only light; embers and sparks drifting through "
    "the frame; wet surfaces mirroring the fire. "
)
COMIC_LIGHT = (
    "Light: name two sources and give each a job - a warm source (fire, lamps, burning city, sunset) on everything near, "
    "a cold source (moon, astra, divine presence, dawn) on everything far; the two meet as orange and blue rim light on "
    "shoulders, rock and water. "
)
SCALE_RULE = (
    "Proportion rule: everything in the frame is at true physical scale to everything else - a man is the height of a "
    "chariot wheel and a half, a war elephant three men, a city wall ten, a mountain a thousand; monkeys and bears are "
    "animal-sized beside men; Ravana is a tall man, not a mountain; no figure is giant unless the scene text says "
    "'colossal' or 'vast form'. One scale per panel: an aerial shows no large figures, a duel shows chariot-height, a "
    "close-up shows one face. "
)
CAMERA_BY_SCALE = {
    "EWS": "Camera: extreme wide, aerial or high vantage, 24mm, deep focus; figures are a texture, no hero figure larger than true scale.",
    "WS": "Camera: wide shot, eye level or slightly high, 28mm, deep focus; full figures at true scale with the environment dominant.",
    "MWS": "Camera: medium wide, eye level, 35mm, deep focus front to back; figures knee-up with the setting readable behind them.",
    "MS": "Camera: medium shot, eye level, 50mm, moderate depth of field; waist-up figures.",
    "MCU": "Camera: medium close-up, 85mm, shallow depth of field; chest-up, background as bokeh of fire and smoke.",
    "CU": "Camera: close-up, 100mm, shallow depth of field; one face, lit by the weapon or flame in frame.",
    "ECU": "Camera: extreme close-up, macro, razor-thin depth of field; one object or one pair of eyes fills the frame.",
}
OVERFRAME_NOTE = "Compose with 30% extra picture around the subject so the frame can be cut as a shard. "
WORLD_RULES = (
    "World: Lanka is a whole green island (Trikuta mountains, rivers, jungle, the sea and the stone causeway in view) with "
    "several vast cities of tiered golden palaces and temples, the walled capital largest, gem-inlaid golden ramparts, "
    "crocodile moats, siege engines on the gates. The armies are crores: real monkeys and bears with fur and tails, no "
    "armour, no helmets, no blades, fighting with uprooted trees, boulders and hands, vanaras leaping through the air, "
    "flocks of great birds in the smoke; against armoured rakshasas with elephants, chariot squadrons, cavalry and "
    "rakshasa flyers on vimanas - no bat wings, no dragons, no horns. The sky dark with smoke and dust, hundreds of fires, "
    "colossal destruction across the whole country. Wide shots are aerial, armies as a living texture over the land. "
)
DUEL_RULES = (
    "Duel grammar: split palette, Rama's side gold, white and electric blue (white horses, gold chariot, blue-white "
    "lightning and astra beams, the arrow a gold comet), Ravana's side crimson, black and ember (black iron armour, red "
    "skin, crimson cloud, ten crowned heads in a row, fire on the crowns); where they meet one white-gold burst with "
    "radial debris shards and concentric shockwave rings on the ground and mandala rings in the sky. Weapons are light: "
    "arrows as streaks and comets with trails, astras as diagonal meteor rain, chakra rings of light, black crescent "
    "blades and tridents against fire. One dominant hue per panel carried into skin, cloth and smoke, faces lit by the "
    "weapon in frame, nothing grey. Rama and Ravana are the same height on their chariots; the armies are a horizon line. "
)
AVOID = (
    "Avoid: artificial plastic skin, overly saturated neon colours, modern buildings, European medieval castles, extra "
    "limbs, the wrong number of heads, random symbols, any text or lettering. "
)

# Rama's locked look (the paragraph seeded into the Character table; the lock wins over any prose elsewhere)
RAMA_LOOK = (
    "Rama, locked look (reference: refs/rama_reference.png): a young man of about thirty, dark golden-brown skin with a "
    "warm glow, clean-shaven, serene oval face, long wavy black hair gathered in a high top-knot with loose waves falling "
    "to the shoulders, eyes OPEN, large, dark and calm, level gaze directed at whatever the scene names (never closed, "
    "never downcast), a white U-shaped Vaishnava tilak with a red centre line on the forehead. Bare chest and bare right "
    "shoulder; one length of translucent saffron-orange cloth draped over the left shoulder and wound across the chest "
    "and waist, its ends lifting in the wind; a double strand of small dark rudraksha beads at the throat, a rudraksha "
    "bead band on the right upper arm; no crown, no gold jewellery, no armour. The great bow carried over the left "
    "shoulder, a quiver at the back. A soft disc of gold light behind the head in close shots. "
)

ERA_PALETTES = {
    "treta": "fire-gold on black ash; embers; smoke in grey sheets; sea black with ash.",
    "dwapara": "red mud under an arrow-dimmed sun; dust; iron; white horses the only clean thing.",
    "prabhas": "white desert glare outside; a thousand lamp flames in dark stone inside; sea-light through doorways.",
    "ashram": "Himalayan morning, green and grey, river light.",
    "phala": "cool glass and steel; gold-on-black UI light; pastel planets in the night sky; desaturated except gold.",
    "girgaon": "warm morning light through a barred window; faded cotton; marigold and jasmine; the same in every era.",
    "resistance": "warm lamp-light; mud, tin and sea; one small flame in the frame where the book places it.",
    "core": "black grid of cold white lines; ten crimson faces; an endless tree of faint gold branches.",
    "dhanushkodi": "white sky, pale flat sea, rust and sand; at the end, pale gold dawn.",
    "montage": "whatever the image's own era is, with black between.",
}


def style_block() -> str:
    p = Path(__file__).resolve().parent.parent / "style_block.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def palette(era: str) -> str:
    for line in style_block().splitlines():
        if line.strip().startswith(f"- {era}:"):
            return line.split(":", 1)[1].strip()
    return ERA_PALETTES.get(era, ERA_PALETTES["treta"])


def is_duel(characters: list[str] | None, scene: str) -> bool:
    chars = " ".join(characters or [])
    txt = (scene or "").lower()
    return ("ravana" in chars and ("rama" in chars or "arrow" in txt)) or any(k in txt for k in ("astra", "arrow", "chariot tipping", "ten heads", "tenth head"))


def look_paragraph(name: str, form_key: str, look: str) -> str:
    """A per-character look paragraph for the prompt, in the RAMA_LOOK pattern."""
    look = (look or "").strip()
    if not look:
        return ""
    head = f"{name}, locked look"
    if look.lower().startswith(name.lower()):
        return look.rstrip() + " "
    return f"{head} ({form_key}): {look.rstrip('. ')}. "


def panel_prompt(era: str, scene: str, kind: str, duel: bool = False, scale: str = "MS", looks: list[str] | None = None) -> str:
    """The full prompt for one panel. `looks` are the look paragraphs of the locked characters on the panel."""
    plate = "A full-page plate: one image, the whole page, bleed on all sides, monumental composition. " if kind == "plate" else OVERFRAME_NOTE
    world = WORLD_RULES if era == "treta" else ""
    rules = DUEL_RULES if duel else ""
    camera = CAMERA_BY_SCALE.get(scale, CAMERA_BY_SCALE["MS"]) + " "
    looks_txt = "".join(l for l in (looks or []) if l)
    return (f"{COMIC_STYLE}{COMIC_GRADE}{COMIC_LIGHT}{camera}{SCALE_RULE}{plate}{world}{rules}{looks_txt}{AVOID}"
            f"Palette: {palette(era)} SCENE: {scene}")


def reference_prefix(names: list[str]) -> str:
    """Prefix for edits-with-reference calls: the attached images are the exact identity of the named characters."""
    if not names:
        return ""
    who = ", ".join(names)
    return (f"Use the attached image(s) as the exact reference for {who}'s face, hair, skin tone and attire; keep that "
            f"identity precisely while painting this new scene. ")


def silhouette_prompt_text(tags: list[str]) -> str:
    """Marginalia: ink line drawing on pure white, in the manuscript-detailing register (art_direction §C)."""
    subject = ", ".join(t.strip() for t in tags if t.strip()) or "an ornamental compass rose"
    return (f"Fine monochrome ink line drawing of {subject}, in the manner of marginal drawings in an ancient Indian "
            "illuminated manuscript: ancient Indian architecture, bows, chariots, coastal maps, ornamental compass motifs, "
            "battle formations. Ink line drawing on pure white, no colour, no shading except hatching, no background, no "
            "frame, no text. Restrained, supports the story, never clutters.")


def scale_of(scene: str, explicit: str | None = None) -> str:
    return explicit if explicit in SCALES else infer_scale(scene or "")


def fallback_pages(chapter_text: str, first_page: int, pages: int | None = None) -> dict:
    """No key: split the chapter into pages of 2-5 panels with the book's sentences as captions."""
    sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", (chapter_text or "").strip()) if len(x.strip()) > 20]
    if not sents:
        sents = ["(no chapter text yet)"]
    pages = pages or max(1, min(12, int(round(len(sents) / 10))))
    per_page = max(2, -(-len(sents) // pages))
    out = []
    for i in range(pages):
        chunk = sents[i * per_page:(i + 1) * per_page] or sents[-1:]
        panels = [{"n": j + 1, "kind": "shard", "weight": 1.0, "state": "quiet", "scale": infer_scale(s), "image": s[:220], "caption_en": s, "characters": []} for j, s in enumerate(chunk[:5])]
        if i == pages - 1:
            panels = [{"n": 1, "kind": "plate", "weight": 1, "state": "knowledge", "scale": "EWS", "image": chunk[-1][:220], "caption_en": chunk[-1], "characters": []}]
        out.append({"page": first_page + i, "panels": panels})
    return {"pages": out}
