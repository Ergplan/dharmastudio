# Art direction (from the author's spread prompt, 2026-10-30) — how each part is used in the studio

Source: engine/art_direction_source.md (verbatim). The studio generates ONE PANEL PER IMAGE and typesets all
text, so the source's sections are routed:

## A. Into every panel prompt (engine/comic/script.py: COMIC_STYLE / GRADE)
"An ancient Indian illuminated historical manuscript brought to life through photorealistic cinematic illustration."
Cinematic realism: ultra-detailed, physically plausible skin pores, hair, textiles, bronze, gold, weapons, stone
architecture, ocean water, fire, smoke, atmospheric perspective, volumetric light and shadow. Grade: warm amber
and copper for Lanka; deep turquoise and midnight blue underwater; restrained glowing highlights. Natural anatomy,
believable expressions. Epic historical cinema quality — not cartoon, anime, glossy video-game art, or generic
fantasy illustration. (Since 2026-10-31 COMIC_STYLE opens with the author's house style — engine/director/painted.py
HOUSE_STYLE, verbatim — which replaced the earlier cinematic-fantasy register.)
AVOID list (negative guidance in every prompt): artificial plastic skin, overly saturated neon colours, modern
buildings, European medieval castles, extra limbs, wrong number of heads, random symbols, any text.

## B. Into the layout engine (engine/comic/layout.py + visual_logic.py)
- 3–5 major panels per page; irregular shards of different sizes organically embedded in the parchment; edges
  fractured, torn, feathered, partially dissolved into ink drawings (the `torn` edge + a sketch-fade mask).
- No uniform rectangles, no conventional gutters, no thick black borders, no pasted-photo look: on the parchment
  canvas the gutter is the paper itself, shards get a 0.3 mm sepia ink edge, not black.
- Some scenes bleed across shard boundaries (image_group).
- Large establishing images dominate; small shards for faces and dialogue (scale dial already does this).
- Broad quiet shards for emotion, sharp diagonal fractures for action, one dominant panoramic shard for
  revelation (the beat dial).
- Visual balance target per page: ~70% cinematic image, ~20% clean parchment, ~10% ink marginalia. The layout
  reports the measured split in the page manifest and the Pages screen shows it.
- Reading order left-to-right, top-to-bottom, unmistakable.

## C. Into the silhouette / marginalia library (engine/agents.py silhouette_prompt)
Fine monochrome ink drawings of ancient Indian architecture, bows, chariots, coastal maps, ornamental compass
motifs, battle formations; restrained red and gold ornamental accents (applied as tint at placement, the drawing
itself is ink on white). Marginal drawings support the story; never clutter.

## D. Into caption typesetting (layout.py STATE_STYLE on the parchment canvas)
Elegant dark-brown serif (sepia #3a2d1a) on lightly textured parchment caption areas; narration blocks 15–30
words; balloons minimal; never over busy artwork (the layout places captions on the shard's quietest edge and
may push them into the parchment margin); generous padding; consistent sizes; crop-safe.

## E. Character continuity
Comes from the Character lock (reference images attached to every generation), not from prose. Where the source
differs from a locked reference, the lock wins (Rama: dark golden-brown skin per the locked reference, not
blue-toned). Hanuman: powerful vanara, expressive simian face, tawny fur, gold ornaments, red and saffron cloth,
long tail, devoted intelligent expression, no armour. Ravana: ten heads with gold crowns, dark ornate armour,
red and bronze ceremonial attire, fierce intelligent faces, a tall man (not a giant).

## F. Title block (chapter openers)
"THE CYCLE OF DHARMA / BOOK ONE / THE FIRE THAT WAS NOT DESTROYED" with the chapter name and an epigraph, in the
manuscript register, ink on parchment, a small compass-rose ornament; Devanagari epigraph beside it in the HI
edition (e.g. धर्मो रक्षति रक्षितः — Dharma protects those who protect it).
