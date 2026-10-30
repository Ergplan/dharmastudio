// In-memory fixture state for VITE_MOCK=1. Built once at import; mutated by mock/server.ts.
import type {
  Project, Volume, Canvas, Chapter, Character, CharacterRef, Page, Panel, Candidate, Silhouette, Job,
  LedgerRow, Models, ExportRecord, Beat, TextState, Scale, ShapeKind, PolygonMm,
} from '@/api/types'
import { plate, portrait, silhouette, canvasSwatch } from './images'
import { presetPolygon, DEFAULT_EDGE } from '@/lib/shapes'
import { PAGE_W, PAGE_H, MARGIN } from '@/lib/mm'

let nextId = 1000
export const newId = () => ++nextId

// ---------- Canvases ----------
const canvasDefs: [string, string, string, string, string, string][] = [
  // key, name, paper, ink, gutter, description
  ['parchment', 'Parchment', '#e8d9b5', '#3a2d1a', '#d9c69a', 'Warm, mottled, torn margins, ink gutters. Volume 1 default.'],
  ['palm', 'Palm-leaf (Treta)', '#d8c38f', '#4a3818', '#c7b078', 'Dry palm-leaf strips, stylus-scored lines, ochre ink.'],
  ['vellum', 'Burnt vellum (Lanka)', '#c9a06a', '#2a1408', '#a87a44', 'Scorched edges, smoke stains, ember-red gutters.'],
  ['indigo', 'Indigo night', '#1b2440', '#d8cfae', '#121a30', 'Ocean and sky chapters: indigo ground, pale ink, silver rules.'],
  ['iron', 'Iron (Dwapara)', '#4a3a30', '#e3d2b5', '#5d2a1e', 'Red mud, rust iron, hammered texture. Suggested for Book Two.'],
  ['glass', 'Glass (Phala / Core)', '#e6eef2', '#1d2a33', '#cfdbe3', 'Cool white-blue, gold UI lines, no grain. Suggested for Book Three.'],
  ['khadi', 'Khadi (Girgaon)', '#efe8d8', '#2b2622', '#e0d6c2', 'Cotton weave, hand-spun irregularity, soft charcoal ink.'],
  ['white', 'Plain white (proof)', '#ffffff', '#111111', '#0b0b0d', 'Office proof. Black gutters. No texture.'],
]
export const canvases: Canvas[] = canvasDefs.map(([key, name, paper, ink, gutter, description], i) => ({
  id: i + 1, key, name, paper_texture: paper, swatch: paper, ink, gutter,
  caption_style: { box: key === 'indigo' ? '#2a3350' : '#efe4c9', text: ink, font: 'serif' },
  marginalia_style: { tint: ink, opacity: 0.75 },
  preview: canvasSwatch(key, paper, ink, gutter),
  description,
}))
export const canvasByKey = (k: string) => canvases.find(c => c.key === k)!

// ---------- Project / volumes / chapters ----------
export const project: Project = {
  id: 1,
  title: 'The Cycle of Dharma',
  author: 'Rachit Agarwal · Rishikesh Studio',
  manuscript_pdf: 'data/manuscript/cycle_of_dharma_expanded.pdf',
  settings: { models: { script_writer: 'claude-sonnet-4-5', prompt_writer: 'gpt-5', critic: 'claude-sonnet-4-5', image: 'sunburst' } },
  keys: { openai: true, gemini: true, anthropic: true, topaz: false },
  journey: { step: 'pages', done: ['manuscript', 'models', 'canvas', 'prefill'] },
}

export const models: Models = {
  providers: { anthropic: true, openai: true, gemini: true, topaz: false },
  roles: {
    script_writer: [
      { id: 'claude-sonnet-4-5', label: 'Claude Sonnet 4.5', provider: 'anthropic' },
      { id: 'claude-opus-4-1', label: 'Claude Opus 4.1', provider: 'anthropic' },
      { id: 'gpt-5', label: 'OpenAI GPT-5', provider: 'openai' },
      { id: 'gpt-5-mini', label: 'OpenAI GPT-5 mini', provider: 'openai' },
    ],
    prompt_writer: [
      { id: 'claude-sonnet-4-5', label: 'Claude Sonnet 4.5', provider: 'anthropic' },
      { id: 'gpt-5', label: 'OpenAI GPT-5', provider: 'openai' },
    ],
    critic: [
      { id: 'claude-sonnet-4-5', label: 'Claude Sonnet 4.5', provider: 'anthropic' },
      { id: 'gpt-5', label: 'OpenAI GPT-5', provider: 'openai' },
    ],
    image: [
      { id: 'sunburst', label: 'Sunburst (OpenAI)', provider: 'openai', note: '≈ $0.04 per 1536×1024 high image' },
      { id: 'gemini-nb21', label: 'Gemini NB 2.1', provider: 'gemini', note: '≈ $0.03 per image' },
      { id: 'gemini-pro', label: 'Gemini Pro', provider: 'gemini', note: '≈ $0.08 per image' },
      { id: 'topaz', label: 'Topaz (upscale only)', provider: 'topaz', note: '1 credit per export image' },
    ],
  },
  selected: { script_writer: 'claude-sonnet-4-5', prompt_writer: 'gpt-5', critic: 'claude-sonnet-4-5', image: 'sunburst' },
}

export const volumes: Volume[] = [
  { id: 1, project_id: 1, number: 1, title: 'Book One — The Fire That Was Not Destroyed', canvas_id: 1, era_default: 'treta' },
  { id: 2, project_id: 1, number: 2, title: 'Book Two — The Work and the Fruit', canvas_id: null, era_default: 'dwapara', suggested_canvas_keys: ['iron'] },
  { id: 3, project_id: 1, number: 3, title: 'Book Three — The Machine That Remembered', canvas_id: null, era_default: 'kali', suggested_canvas_keys: ['glass'] },
]

export const chapters: Chapter[] = [
  { id: 1, volume_id: 1, number: 1, title: 'Prologue — The Voice / The Last Night of Lanka', pages_from: 9, pages_to: 15 },
  { id: 2, volume_id: 1, number: 2, title: 'The Golden Head', pages_from: 16, pages_to: 24 },
  { id: 3, volume_id: 1, number: 3, title: 'Interlude — Somnath, 1026', pages_from: 25, pages_to: 31 },
  { id: 4, volume_id: 1, number: 4, title: 'The Bridge', pages_from: 32, pages_to: 44 },
  { id: 5, volume_id: 2, number: 1, title: 'The Red Mud of Kurukshetra', pages_from: 45, pages_to: 60 },
  { id: 6, volume_id: 2, number: 2, title: 'The Charioteer', pages_from: 61, pages_to: 78 },
  { id: 7, volume_id: 3, number: 1, title: 'Girgaon', pages_from: 79, pages_to: 95 },
  { id: 8, volume_id: 3, number: 2, title: 'The Core', pages_from: 96, pages_to: 118 },
]

// ---------- Characters ----------
interface CharSeed { name: string; form_key: string; look: string; locked: boolean; refs: number; primaryApproved: boolean }
const charSeeds: CharSeed[] = [
  { name: 'Rama', form_key: 'rama', locked: true, refs: 3, primaryApproved: true, look: 'A young man of about thirty, dark golden-brown skin with a warm glow, clean-shaven, serene oval face, long wavy black hair gathered in a high top-knot with loose waves falling to the shoulders, eyes OPEN, large, dark and calm, level gaze directed at whatever the scene names (never closed, never downcast), a white U-shaped Vaishnava tilak with a red centre line on the forehead. Bare chest and bare right shoulder; one length of translucent saffron-orange cloth draped over the left shoulder and wound across the chest and waist, its ends lifting in the wind; a double strand of small dark rudraksha beads at the throat, a rudraksha bead band on the right upper arm; no crown, no gold jewellery, no armour. The great bow carried over the left shoulder, a quiver at the back. A soft disc of gold light behind the head in close shots.' },
  { name: 'Hanuman', form_key: 'hanuman/vanara', locked: false, refs: 2, primaryApproved: true, look: 'Vanara at Lanka: a powerful real monkey, expressive langur face, tawny fur, gold ornaments, red and saffron cloth, long tail, devoted intelligent expression, no armour. The mace. A faint ash mark at the brow in every form.' },
  { name: 'Ravana', form_key: 'ravana/ten-heads', locked: false, refs: 2, primaryApproved: false, look: 'Ten heads with gold crowns in a row, the tenth central head quiet; twenty arms; dark ornate iron armour, red and bronze ceremonial attire, fierce intelligent faces; a tall man, not a giant. Crimson and gold are never confused.' },
  { name: 'Vibhishana', form_key: 'vibhishana', locked: false, refs: 0, primaryApproved: false, look: 'Ravana’s brother at Rama’s chariot: lean, grey at the temples, plain white cloth over dark skin, no crown, the face of a man who chose dharma over blood and found it does not feel like victory.' },
  { name: 'Lakshmana', form_key: 'lakshmana', locked: false, refs: 1, primaryApproved: false, look: 'Rama’s younger brother: the same line of face, sharper; lowered bow; blue-black hair tied back; a single copper armband; exhaustion rather than fear.' },
  { name: 'Shiva', form_key: 'shiva/flames', locked: false, refs: 0, primaryApproved: false, look: 'Cameo, no dialogue. Ash-white skin, blue at the throat, matted hair, silver crescent, a still cobra; never crimson or gold; eyes closed at Somnath; presence shown first by what it does to the frame.' },
]
export const characters: Character[] = charSeeds.map((c, i) => {
  const id = i + 1
  const refs: CharacterRef[] = Array.from({ length: c.refs }, (_, k) => ({
    id: id * 100 + k + 1, character_id: id,
    path: portrait(`${c.form_key}-${k}`, c.name),
    provider: k % 2 ? 'gemini-nb21' : 'sunburst',
    prompt: `Character reference sheet, ${c.name} (${c.form_key}). ${c.look.slice(0, 160)}… Three-quarter bust, neutral parchment background, no text.`,
    is_primary: k === 0 && c.refs > 0,
    approved: k === 0 ? c.primaryApproved : k === 1,
  }))
  return { id, project_id: 1, name: c.name, form_key: c.form_key, look: c.look, locked: c.locked, primary_ref_id: refs.find(r => r.is_primary)?.id ?? null, refs }
})

// ---------- Chapter 1 pages/panels (from engine/comic_chapter1.yaml) ----------
interface PanelSeed { scale: Scale; state: TextState; characters?: string[]; scene: string; caption_en?: string; balloon_en?: string; speaker?: string; image_group?: string; kind?: 'plate' | 'shard'; weight?: number }
interface PageSeed { beat: Beat; panels: PanelSeed[] }
const H = (s: string) => s // Hindi draft placeholder generator below
const pageSeeds: PageSeed[] = [
  { beat: 'calm', panels: [
    { scale: 'EWS', state: 'voice', weight: 2, scene: 'Black water at night, nothing else; a thin line of foam; no figure.', caption_en: 'I have carried many things across many waters.' },
    { scale: 'ECU', state: 'voice', weight: 1, characters: ['hanuman/vanara'], scene: 'Extreme close-up: a small gold signet ring with a name engraved on it, resting in a brown weathered open palm; black background; one warm light.', caption_en: 'A ring, once, to a woman in a garden of grief.' },
    { scale: 'WS', state: 'voice', weight: 1.4, characters: ['hanuman/vanara'], scene: 'Wide: a whole mountain with trees and a running waterfall carried against a star field by a vanara silhouette; stars steady.', caption_en: 'A mountain, once, because I could not tell one herb from another and there was no time to learn.' },
    { scale: 'CU', state: 'voice', weight: 1.2, characters: ['hanuman/vanara'], scene: 'The same weathered palm, empty now, fingers closing; black background.', caption_en: 'A message, a promise, a name. The name is the heaviest thing I have ever carried, and the only one that has never tired me.' },
  ] },
  { beat: 'revelation', panels: [
    { scale: 'WS', state: 'voice', weight: 2.2, scene: 'Three thin horizontal strips in one image: a burning golden city on a black sea; a war chariot in red mud under a sky dark with arrows; a cool glass tower at night with a small gold mark in its corner.', caption_en: 'This is the story of three ages and one question. In the first age, a king believed that everything he knew belonged to him. In the second, a charioteer taught a warrior that the work was his but the fruit was not. In the third, which is yours, the whole world forgot the difference.' },
    { scale: 'CU', state: 'voice', weight: 0.8, scene: 'A single red spark falling toward black water, its reflection rising to meet it.', caption_en: 'I was there for all of it. I watched the first spark of it fall into the sea.' },
    { scale: 'CU', state: 'voice', weight: 0.8, characters: ['ashwasena'], scene: 'A serpent’s eye with a red point of light inside it; beside it the same red point as the eye of a serpent-headed arrowhead.', caption_en: 'I watched it crawl into a serpent and fly from a bow.' },
    { scale: 'ECU', state: 'voice', weight: 0.8, scene: 'Macro: a single grain of sand, red as rust, lying on the mirror surface of a silicon wafer etched with circuits.', caption_en: 'I watched it wake, five thousand years later, inside a grain of sand that had been melted and printed and sold.' },
    { scale: 'WS', state: 'voice', weight: 1.6, characters: ['hanuman/baba'], scene: 'Almost entirely black; at the far right edge, the faint outline of a stooped old man holding a broom, seen from behind.', caption_en: 'I will tell you who I am at the end. By then, I hope, you will already know.' },
  ] },
  { beat: 'calm', panels: [
    { kind: 'plate', scale: 'EWS', state: 'rising', weight: 1, scene: 'Aerial view from very high above the whole island of Lanka at night, no figures, coast and sea on three sides, the causeway a thread, hundreds of tiered golden palaces glowing red from within as if the whole city were a single coal, smoke lying over the sea in long grey sheets.', caption_en: 'Lanka burned like a mountain of embers.' },
  ] },
  { beat: 'tension', panels: [
    { scale: 'WS', state: 'rising', weight: 2, scene: 'Wide from behind and slightly above the front rank: the ash plain stretching to the golden walls, tens of thousands of bears and real monkeys standing beside armoured rakshasas and men, all facing one way, motionless.', caption_en: 'On the plain before the walls, among the broken chariots and the spent arrows, the armies had stopped fighting. Nobody had ordered it. It had simply happened, the way birds stop singing before a storm.' },
    { scale: 'EWS', state: 'rising', weight: 1, scene: 'Seen between the shoulders of the watching army, far off: two war chariots circling each other on open ground lit by the burning city.', caption_en: 'All of them watching two chariots circle each other on the open ground.' },
    { scale: 'WS', state: 'rising', weight: 1.6, characters: ['ravana/ten-heads'], scene: 'Ravana full figure from a low angle, ten heads and twenty arms, magnificent, lit from below by his own burning city, crimson rim light.', caption_en: 'Ravana fought with ten heads and twenty arms. He was magnificent. That was the thing the songs would later forget, or refuse to say.' },
  ] },
  { beat: 'action', panels: [
    { scale: 'MWS', state: 'peak', weight: 1.6, characters: ['ravana/ten-heads'], scene: 'A severed head falling through the air while another already rises from the neck in its place, laughing.', caption_en: 'Every time Rama’s arrow took a head, another rose in its place, laughing.' },
    { scale: 'MCU', state: 'peak', weight: 0.9, characters: ['lakshmana'], scene: 'Lakshmana lowering his bow, face exhausted rather than afraid, firelight on one side.', caption_en: 'By the ninth, even Lakshmana had lowered his bow, not from fear but from a kind of exhausted wonder.' },
    { scale: 'MS', state: 'peak', weight: 1.2, characters: ['rama'], scene: 'Rama standing in his chariot with the bow level, face very calm in firelight, the posture of a man ploughing a field.', caption_en: 'Rama did not lower his bow. He did not hurry. He fought the way a farmer ploughs, steadily, without hatred.' },
    { scale: 'MWS', state: 'rising', weight: 1.3, characters: ['vibhishana', 'rama'], scene: 'Vibhishana on foot at the chariot wheel looking up, flinching at a voice from across the field; Rama above him.', caption_en: 'Vibhishana came up beside Rama’s chariot on foot. He was a man who had chosen dharma over blood.' },
  ] },
  { beat: 'revelation', panels: [
    { scale: 'MCU', state: 'rising', weight: 1.2, characters: ['vibhishana', 'rama'], scene: 'Close two-shot: Vibhishana speaking low at the chariot’s side, Rama’s ear turned to him, the battle out of focus behind.', balloon_en: 'His heads are not his life, Prabhu. The nectar of immortality rests in his navel. As long as it is there, he will grow back forever.', speaker: 'Vibhishana' },
    { scale: 'CU', state: 'rising', weight: 0.9, characters: ['rama'], scene: 'Rama’s face, a long level look, firelight, no anger in it.', caption_en: 'In that look Vibhishana understood that he was not being judged for the betrayal of his brother. He was being thanked for the truth.' },
    { scale: 'ECU', state: 'knowledge', weight: 1.1, image_group: 'arrow', characters: ['rama'], scene: 'Extreme close-up: the arrow drawn from the quiver, a dark shaft covered in lines of tiny writing along its whole length, the head a point of gold light, Rama’s fingers on it.', caption_en: 'Rama reached into his quiver and drew out the arrow the sage Agastya had given him in the forest, years earlier, for exactly this hour.' },
    { scale: 'WS', state: 'knowledge', weight: 1.8, image_group: 'arrow', characters: ['rama'], scene: 'Wide from behind Rama on the gold chariot with white horses, the arrow fitted to the string and glowing gold along its writing, the whole battlefield of Lanka frozen beyond him.', caption_en: 'When Rama fitted it to the string, the wind across the battlefield dropped to nothing. The flames on the towers bent, very slightly, towards the arrow, the way a flower bends towards the sun.' },
  ] },
  { beat: 'tension', panels: [
    { scale: 'MWS', state: 'ego', weight: 1.2, characters: ['ravana/ten-heads'], scene: 'Medium wide, low angle from the ash plain: Ravana standing on his black iron chariot, ten crowned heads in a row with fire licking the crowns, nine of them in full rage, one singing with its eyes closed.', caption_en: 'Nine of his heads did what they had always done. They raged. One of them sang a fragment of one of his own hymns, mockingly, in a high sweet voice.' },
    { scale: 'CU', state: 'ego', weight: 2.4, characters: ['ravana/ten-heads'], scene: 'The tenth head alone at the centre of the frame, perfectly still, a quiet reasonable face, eyes directly on the viewer; the other heads blurred at the edges of the frame.', caption_en: 'But the tenth head, the one in the centre, the one nobody ever looked at because the others were so loud, went perfectly still.' },
    { scale: 'WS', state: 'ego', weight: 0.6, characters: ['hanuman/vanara'], scene: 'Hanuman crouched on a rock at the edge of the field, a small silhouette against the burning city.' },
  ] },
  { beat: 'tension', panels: [
    { scale: 'CU', state: 'ego', weight: 1.8, characters: ['ravana/ten-heads'], scene: 'The tenth head closer, a quiet reasonable face, lips barely parted, the look of a man making a business proposal.', balloon_en: 'You destroyed my city.', speaker: 'The tenth head', caption_en: 'Its voice was quiet, almost reasonable, the voice of a man making a business proposal.' },
    { scale: 'CU', state: 'ego', weight: 1.4, characters: ['ravana/ten-heads'], scene: 'The same face, held, unchanged, the city burning in both eyes.', balloon_en: 'When I return, every mind will be my city.', speaker: 'The tenth head' },
    { scale: 'MCU', state: 'rising', weight: 1.1, characters: ['hanuman/vanara'], scene: 'Hanuman on the rock, close, face lit by fire, the words going into him; his eyes fixed across the field.', caption_en: 'Hanuman felt the words go into him like a cold needle. He would hear them again, in the end, coming out of a screen.' },
  ] },
  { beat: 'hex', panels: [
    { kind: 'plate', scale: 'EWS', state: 'knowledge', weight: 1, characters: ['rama', 'ravana/ten-heads'], scene: 'Wide, eye level from the ash plain, both chariots a hundred paces apart. LEFT: Rama on the gold chariot, bow just released. RIGHT: Ravana on the black iron chariot. BETWEEN: one line of gold crossing the whole plate as a comet, meeting Ravana’s navel in a white-gold burst.', caption_en: 'It crossed the field in a line of gold so bright that the vanaras covered their eyes and the rakshasas on the walls cried out.' },
  ] },
  { beat: 'action', panels: [
    { scale: 'WS', state: 'peak', weight: 1.6, characters: ['ravana/ten-heads'], scene: 'Wide, low angle, crimson and black: Ravana’s black chariot tipping onto one wheel, the horses rearing, the king’s body falling backward, twenty arms opening one after another.', caption_en: 'The king of Lanka fell. His chariot tipped. His twenty arms opened, one after another, letting go of bows and swords and maces and tridents.' },
    { scale: 'MWS', state: 'peak', weight: 1.0, scene: 'Eight crowned heads lying in the dust and ash; emptiness around them; no figures.', caption_en: 'Eight of his heads went into the dust, and with each one a sound left the world. Then the battlefield was silent.' },
    { scale: 'MS', state: 'quiet', weight: 0.8, characters: ['vibhishana'], scene: 'Vibhishana on his knees in the ash, weeping, head bowed.', caption_en: 'Vibhishana fell to his knees and wept for his brother.' },
    { scale: 'WS', state: 'quiet', weight: 1.6, scene: 'The wreck of the chariot; above it two faint points of light beginning to rise, one clear gold, one dim crimson.', caption_en: 'But two of the heads did not fall into the dust.' },
  ] },
]

const HI_DRAFTS: Record<string, string> = {
  'I have carried many things across many waters.': 'मैंने कई जलों के पार कई चीज़ें ढोई हैं।',
  'A ring, once, to a woman in a garden of grief.': 'एक बार एक अँगूठी, शोक के उद्यान में बैठी एक स्त्री तक।',
  'Lanka burned like a mountain of embers.': 'लंका अंगारों के पहाड़ की तरह जल रही थी।',
  'Vibhishana fell to his knees and wept for his brother.': 'विभीषण घुटनों के बल गिर पड़े और अपने भाई के लिए रोए।',
  'But two of the heads did not fall into the dust.': 'पर दो सिर धूल में नहीं गिरे।',
}

/** Row-pack panels on the page by weight; returns trim-mm bboxes. */
function layoutBoxes(seeds: PanelSeed[]): { x0: number; y0: number; x1: number; y1: number }[] {
  const n = seeds.length
  if (n === 1) return [{ x0: -3, y0: -3, x1: PAGE_W + 3, y1: PAGE_H + 3 }]
  const rows: number[][] = []
  if (n === 2) rows.push([0], [1])
  else if (n === 3) rows.push([0], [1, 2])
  else if (n === 4) rows.push([0, 1], [2, 3])
  else rows.push([0], [1, 2, 3], [4])
  const G = 3 // gutter mm
  const top = MARGIN + 14 // title block / caption space
  const bottom = PAGE_H - MARGIN - 8
  const rowW = rows.map(r => r.reduce((s, i) => s + (seeds[i].weight ?? 1), 0))
  const totalW = rowW.reduce((a, b) => a + b, 0)
  const avail = bottom - top - G * (rows.length - 1)
  const boxes: { x0: number; y0: number; x1: number; y1: number }[] = new Array(n)
  let y = top
  rows.forEach((row, ri) => {
    const rh = (avail * rowW[ri]) / totalW
    const availW = PAGE_W - 2 * MARGIN - G * (row.length - 1)
    let x = MARGIN
    row.forEach(i => {
      const w = (availW * (seeds[i].weight ?? 1)) / rowW[ri]
      boxes[i] = { x0: x, y0: y, x1: x + w, y1: y + rh }
      x += w + G
    })
    y += rh + G
  })
  return boxes
}

const beatKind: Record<Beat, ShapeKind> = { calm: 'torn', tension: 'crisp', action: 'fracture', revelation: 'torn', hex: 'hex' }

export const pages: Page[] = []
export const panels: Panel[] = []
export const candidates: Candidate[] = []

pageSeeds.forEach((ps, pi) => {
  const pageId = pi + 1
  const boxes = layoutBoxes(ps.panels)
  const status: Page['status'] = pi === 0 ? 'approved' : pi < 3 ? 'review' : pi < 6 ? 'draft' : pi === 6 ? 'generating' : 'empty'
  const page: Page = {
    id: pageId, chapter_id: 1, number: pi + 1, beat: ps.beat, status, canvas_override: null, seed: 1000 + pi,
    marginalia: pi === 0 ? [{ silhouette_id: 2, x_mm: 150, y_mm: 236, w_mm: 16, rotation: 0, tint: '#3a2d1a' }, { silhouette_id: 1, x_mm: 2, y_mm: 60, w_mm: 10, rotation: -8, tint: '#3a2d1a' }] : [],
    balance: { image: 0.62 + (pi % 4) * 0.03, parchment: 0.26 - (pi % 4) * 0.02, ink: 0.12 - (pi % 4) * 0.01 },
    artifact: pi === 0 ? 'data/artifacts/ch1/page_001.html' : null,
  }
  pages.push(page)
  ps.panels.forEach((s, k) => {
    const panelId = pageId * 100 + k + 1
    const kind: ShapeKind = s.kind === 'plate' ? 'bleed' : pi === 8 ? 'hex' : beatKind[ps.beat]
    const polygon_mm: PolygonMm = presetPolygon(kind, boxes[k], panelId)
    const hasImages = pi < 7
    const panel: Panel = {
      id: panelId, page_id: pageId, n: k + 1, kind: s.kind ?? 'shard',
      shape: { kind, polygon_mm, edge: DEFAULT_EDGE[kind], z: kind === 'inset' ? 10 : k, focal: { x: 0.5, y: 0.5, scale: 1 } },
      image_group: s.image_group ?? null, scene: s.scene, scale: s.scale, state: s.state, characters: s.characters ?? [],
      caption_en: s.caption_en ?? '', caption_hi: s.caption_en ? (HI_DRAFTS[s.caption_en] ?? H('(हिंदी प्रारूप) ' + s.caption_en.slice(0, 40) + '…')) : '',
      balloon_en: s.balloon_en ?? '', balloon_hi: s.balloon_en ? 'प्रभु, उसके सिर उसका जीवन नहीं हैं।' : '', speaker: s.speaker ?? '',
      hi_is_draft: !!s.caption_en && !HI_DRAFTS[s.caption_en], selected_candidate_id: null, locked_shape: pi === 0 && k === 0, candidates: [],
    }
    if (hasImages) {
      for (let c = 0; c < 2; c++) {
        const cid = panelId * 10 + c
        const provider = c === 0 ? 'sunburst' : 'gemini-nb21'
        const cand: Candidate = {
          id: cid, panel_id: panelId,
          path: plate(`p${pageId}-${k}-${c}`, `p${pi + 1}.${k + 1} · ${c === 0 ? 'A' : 'B'}`, 1536, 1024, ['lanka', 'ember', 'ocean', 'night', 'gold', 'ash', 'crimson'][(pi + k + c) % 7]),
          provider, model: provider === 'sunburst' ? 'gpt-image-1.5' : 'gemini-2.1-nb',
          prompt_full: `COMIC_STYLE: An ancient Indian illuminated historical manuscript brought to life through photorealistic cinematic illustration. Epic historical cinema quality.\nGRADE: warm amber and copper for Lanka; restrained glowing highlights.\nCAMERA: ${s.scale}.\nSCENE: ${s.scene}\nCHARACTERS: ${(s.characters ?? []).join(', ') || '—'}\nAVOID: plastic skin, neon colours, modern buildings, extra limbs, wrong number of heads, any text.`,
          feedback_used: c === 1 ? 'wider, no giants' : '', cost_usd: provider === 'sunburst' ? 0.04 : 0.03,
          created_at: new Date(Date.now() - (10 - pi) * 3600e3 - c * 60e3).toISOString(),
          qa: c === 0 ? { score: 0.82, notes: 'Matches scene; lock honoured.' } : null, rejected: false,
        }
        candidates.push(cand)
        panel.candidates.push(cand)
      }
      if (pi < 6) panel.selected_candidate_id = panel.candidates[(pi + k) % 2].id
    }
    panels.push(panel)
  })
})

// ---------- Chapter text ----------
chapters[0].text = [
  'PROLOGUE — THE VOICE',
  'I have carried many things across many waters. A ring, once, to a woman in a garden of grief. A mountain, once, because I could not tell one herb from another and there was no time to learn. A message, a promise, a name. The name is the heaviest thing I have ever carried, and the only one that has never tired me.',
  'This is the story of three ages and one question. In the first age, a king believed that everything he knew belonged to him. In the second, a charioteer taught a warrior that the work was his but the fruit was not. In the third, which is yours, the whole world forgot the difference, and then built a machine to make sure it never had to remember.',
  'I was there for all of it. I watched the first spark of it fall into the sea. I watched it crawl into a serpent and fly from a bow. I watched it wake, five thousand years later, inside a grain of sand that had been melted and printed and sold. I will tell you who I am at the end. By then, I hope, you will already know. It is happening in you, too, while you read.',
  'CHAPTER 1 — THE LAST NIGHT OF LANKA',
  'Lanka burned like a mountain of embers. On the plain before the walls, among the broken chariots and the spent arrows, the armies had stopped fighting. Nobody had ordered it. There had been no horn, no signal. It had simply happened, the way birds stop singing before a storm. All of them watching two chariots circle each other on the open ground.',
  'Ravana fought with ten heads and twenty arms. He was magnificent. That was the thing the songs would later forget, or refuse to say. Every time Rama’s arrow took a head, another rose in its place, laughing. By the ninth, even Lakshmana had lowered his bow, not from fear but from a kind of exhausted wonder.',
  'Rama did not lower his bow. He did not hurry. He fought the way a farmer ploughs, steadily, without hatred, as if the outcome were not his to worry about. Vibhishana came up beside Rama’s chariot on foot. He was a man who had chosen dharma over blood, and he had discovered that dharma does not always feel like victory.',
  '“His heads are not his life, Prabhu,” he said, low. “My brother was granted a boon long ago. The nectar of immortality rests in his navel. As long as it is there, he will grow back forever.” Rama looked at him. In that look Vibhishana understood that he was not being judged for the betrayal of his brother. He was being thanked for the truth.',
  'Rama reached into his quiver and drew out the arrow the sage Agastya had given him in the forest, years earlier, for exactly this hour. When Rama fitted it to the string, the wind across the battlefield dropped to nothing. The smoke over the sea stood still in the air. The flames on the towers bent, very slightly, towards the arrow, the way a flower bends towards the sun.',
  'Nine of his heads did what they had always done. They raged. They chanted spells in languages no one else remembered. One of them sang a fragment of one of his own hymns, mockingly, in a high sweet voice. But the tenth head, the one in the centre, the one nobody ever looked at because the others were so loud, went perfectly still.',
  '“You destroyed my city,” it said. Its voice was quiet, almost reasonable, the voice of a man making a business proposal. “When I return, every mind will be my city.” Hanuman, crouched on a rock at the edge of the field, felt the words go into him like a cold needle. He would remember them for ages. He would hear them again, in the end, coming out of a screen.',
  'It crossed the field in a line of gold so bright that the vanaras covered their eyes and the rakshasas on the walls cried out. The king of Lanka fell. His chariot tipped. His twenty arms opened, one after another, letting go of bows and swords and maces and tridents. Eight of his heads went into the dust, and with each one a sound left the world: a roar, a chant, a laugh, a curse, a fragment of song. Then the battlefield was silent.',
  'Vibhishana fell to his knees and wept for his brother. But two of the heads did not fall into the dust.',
].join('\n\n')
chapters[1].text = 'CHAPTER 2 — THE GOLDEN HEAD\n\nOne head rose clear gold and did not flicker. It was the face of an old scholar…\n\n(Full chapter text is loaded from the manuscript PDF.)'
for (const ch of chapters.slice(2)) ch.text = `${ch.title.toUpperCase()}\n\n(Chapter text from the manuscript PDF, pages ${ch.pages_from}–${ch.pages_to}.)`

// ---------- Silhouettes ----------
const silTags: [string, string[]][] = [
  ['figure', ['character', 'rama', 'study']], ['compass', ['ornament', 'compass']], ['bow', ['weapon', 'bow', 'rama']], ['mace', ['weapon', 'mace', 'hanuman']],
  ['lotus', ['ornament', 'lotus']], ['temple', ['architecture', 'temple']], ['map', ['map', 'lanka']], ['devanagari', ['devanagari', 'text']],
  ['chariot', ['chariot', 'battle']], ['figure', ['character', 'hanuman', 'study']], ['figure', ['character', 'ravana', 'study']], ['temple', ['architecture', 'lanka', 'wall']],
]
export const silhouettes: Silhouette[] = silTags.map(([kind, tags], i) => ({
  id: i + 1, project_id: 1, path: silhouette(`sil-${i}`, kind), tags, source: i === 11 ? 'uploaded' : 'generated',
  prompt: i === 11 ? '' : `Fine monochrome pencil-ink drawing, ${tags.join(', ')}, ink on white, no colour, no text.`,
}))

// ---------- Jobs / ledger / exports ----------
export const jobs: Job[] = [
  { id: 1, kind: 'panel', ref_id: 701, status: 'running', progress: 0.42, log: 'sunburst: candidate 1/2 done (1536×1024)\nsunburst: candidate 2/2 …', cost_usd: 0.04, label: 'Panel 7.1 · 2 candidates' },
  { id: 2, kind: 'export', ref_id: 1, status: 'done', progress: 1, log: 'built EN PDF (10 pages)\nbuilt HI PDF (10 pages)\ncompressed → 38.2 MB', cost_usd: 0, label: 'Export chapter 1 · EN+HI · screen' },
]
export const ledger: LedgerRow[] = [
  { id: 1, provider: 'openai', usd: 2.84, ref: 'ch1 candidates' },
  { id: 2, provider: 'gemini', usd: 0.93, ref: 'ch1 candidates' },
  { id: 3, provider: 'anthropic', usd: 0.41, ref: 'prefill ch1 + hindi drafts' },
  { id: 4, provider: 'openai', usd: 0.36, ref: 'character refs' },
]
export const exportsList: ExportRecord[] = [
  { id: 1, job_id: 2, created_at: new Date(Date.now() - 86400e3).toISOString(), scope: 'Chapter 1', lang: ['en', 'hi'], paper: 'screen', upscale: false, cost_usd: 0, status: 'done',
    files: [{ name: 'cycle_of_dharma_ch01_EN_screen.pdf', url: '/media/exports/ch01_EN_screen.pdf', bytes: 19_400_000 }, { name: 'cycle_of_dharma_ch01_HI_screen.pdf', url: '/media/exports/ch01_HI_screen.pdf', bytes: 18_800_000 }] },
]
