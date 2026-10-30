// Placeholder imagery for mock mode: coloured SVG data URIs that read as "cinematic plates" at a glance.

const enc = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`

function hash(s: string) {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) }
  return h >>> 0
}
function rng(seed: number) {
  let s = seed || 1
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296 }
}

export const PALETTES: Record<string, [string, string, string]> = {
  lanka: ['#3b1407', '#b4581a', '#f3c069'],
  ocean: ['#061a2e', '#0f5e7a', '#7fd3e6'],
  ember: ['#120404', '#7a1f12', '#e6a24a'],
  night: ['#05070f', '#1c2a4d', '#8fa3d6'],
  gold: ['#2a1a05', '#a67a1c', '#f7d98a'],
  ash: ['#141210', '#4a4036', '#b8a58b'],
  crimson: ['#1a0505', '#8a1414', '#f04b3a'],
  forest: ['#07140b', '#275c2f', '#a3d68c'],
}
const PALETTE_KEYS = Object.keys(PALETTES)

/** A "cinematic plate": layered gradients, horizon, a few silhouettes, light bloom. */
export function plate(seed: string, label = '', w = 1536, h = 1024, paletteKey?: string): string {
  const r = rng(hash(seed))
  const pk = paletteKey ?? PALETTE_KEYS[hash(seed) % PALETTE_KEYS.length]
  const [dark, mid, light] = PALETTES[pk]
  const horizon = h * (0.45 + r() * 0.25)
  const sun = { x: w * (0.2 + r() * 0.6), y: horizon - h * (0.05 + r() * 0.15), R: w * (0.05 + r() * 0.08) }
  const peaks: string[] = []
  let x = 0
  while (x < w) {
    const pw = w * (0.08 + r() * 0.12)
    const ph = h * (0.08 + r() * 0.22)
    peaks.push(`${x},${horizon} ${x + pw / 2},${horizon - ph} ${x + pw},${horizon}`)
    x += pw * 0.7
  }
  const figs = Array.from({ length: 1 + Math.floor(r() * 3) }, () => {
    const fx = w * (0.1 + r() * 0.8), fh = h * (0.18 + r() * 0.25)
    return `<ellipse cx="${fx}" cy="${h - fh * 0.9}" rx="${fh * 0.14}" ry="${fh * 0.14}" fill="${dark}"/><path d="M${fx - fh * 0.22},${h} C${fx - fh * 0.2},${h - fh * 0.6} ${fx + fh * 0.2},${h - fh * 0.6} ${fx + fh * 0.22},${h} Z" fill="${dark}"/>`
  }).join('')
  const sparks = Array.from({ length: 40 }, () => `<circle cx="${r() * w}" cy="${r() * h}" r="${1 + r() * 2.5}" fill="${light}" opacity="${0.3 + r() * 0.6}"/>`).join('')
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
<defs>
 <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${dark}"/><stop offset="0.7" stop-color="${mid}"/><stop offset="1" stop-color="${light}"/></linearGradient>
 <linearGradient id="gnd" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${mid}"/><stop offset="1" stop-color="${dark}"/></linearGradient>
 <radialGradient id="sun"><stop offset="0" stop-color="#fff5d6" stop-opacity="0.95"/><stop offset="0.4" stop-color="${light}" stop-opacity="0.6"/><stop offset="1" stop-color="${light}" stop-opacity="0"/></radialGradient>
 <linearGradient id="vig" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity="0.35"/><stop offset="0.5" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.45"/></linearGradient>
</defs>
<rect width="${w}" height="${h}" fill="url(#sky)"/>
<circle cx="${sun.x}" cy="${sun.y}" r="${sun.R * 3}" fill="url(#sun)"/>
<circle cx="${sun.x}" cy="${sun.y}" r="${sun.R * 0.55}" fill="#fff3cf" opacity="0.9"/>
<g fill="${dark}" opacity="0.85">${peaks.map(p => `<polygon points="${p}"/>`).join('')}</g>
<rect y="${horizon}" width="${w}" height="${h - horizon}" fill="url(#gnd)"/>
<rect y="${horizon}" width="${w}" height="${h * 0.02}" fill="${light}" opacity="0.5"/>
${figs}${sparks}
<rect width="${w}" height="${h}" fill="url(#vig)"/>
${label ? `<text x="${w - 24}" y="${h - 20}" font-family="Georgia,serif" font-size="30" fill="${light}" opacity="0.55" text-anchor="end">${label}</text>` : ''}
</svg>`
  return enc(svg)
}

/** A character reference sheet placeholder: portrait bust on a warm gradient. */
export function portrait(seed: string, name: string, w = 1024, h = 1024): string {
  const r = rng(hash(seed))
  const pk = PALETTE_KEYS[hash(seed + name) % PALETTE_KEYS.length]
  const [dark, mid, light] = PALETTES[pk]
  const skin = ['#8a5a32', '#6f4423', '#a06a3a', '#5a3a20'][Math.floor(r() * 4)]
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
<defs><radialGradient id="bg" cx="0.5" cy="0.35"><stop offset="0" stop-color="${light}" stop-opacity="0.8"/><stop offset="0.6" stop-color="${mid}"/><stop offset="1" stop-color="${dark}"/></radialGradient>
<radialGradient id="halo"><stop offset="0" stop-color="#f7d98a" stop-opacity="0.9"/><stop offset="1" stop-color="#f7d98a" stop-opacity="0"/></radialGradient></defs>
<rect width="${w}" height="${h}" fill="url(#bg)"/>
<circle cx="${w / 2}" cy="${h * 0.38}" r="${w * 0.32}" fill="url(#halo)"/>
<path d="M${w * 0.2},${h} C${w * 0.22},${h * 0.7} ${w * 0.78},${h * 0.7} ${w * 0.8},${h} Z" fill="${dark}"/>
<rect x="${w * 0.44}" y="${h * 0.52}" width="${w * 0.12}" height="${h * 0.14}" fill="${skin}"/>
<ellipse cx="${w / 2}" cy="${h * 0.4}" rx="${w * 0.16}" ry="${h * 0.2}" fill="${skin}"/>
<path d="M${w * 0.32},${h * 0.36} C${w * 0.34},${h * 0.1} ${w * 0.66},${h * 0.1} ${w * 0.68},${h * 0.36} L${w * 0.62},${h * 0.3} C${w * 0.56},${h * 0.2} ${w * 0.44},${h * 0.2} ${w * 0.38},${h * 0.3} Z" fill="#1a110a"/>
<path d="M${w * 0.47},${h * 0.3} L${w / 2},${h * 0.24} L${w * 0.53},${h * 0.3}" fill="none" stroke="#fff" stroke-width="${w * 0.012}"/>
<text x="${w / 2}" y="${h * 0.95}" font-family="Georgia,serif" font-size="${w * 0.045}" fill="${light}" text-anchor="middle" opacity="0.85">${name}</text>
</svg>`
  return enc(svg)
}

/** Pencil-sketch silhouette: ink strokes on transparent background. */
export function silhouette(seed: string, kind: string, w = 512, h = 512): string {
  const r = rng(hash(seed + kind))
  const ink = '#3a2d1a'
  let body = ''
  switch (kind) {
    case 'bow':
      body = `<path d="M${w * 0.3},${h * 0.1} Q${w * 0.85},${h * 0.5} ${w * 0.3},${h * 0.9}" fill="none" stroke="${ink}" stroke-width="7"/><line x1="${w * 0.3}" y1="${h * 0.1}" x2="${w * 0.3}" y2="${h * 0.9}" stroke="${ink}" stroke-width="2"/><line x1="${w * 0.12}" y1="${h * 0.5}" x2="${w * 0.72}" y2="${h * 0.5}" stroke="${ink}" stroke-width="3"/><path d="M${w * 0.72},${h * 0.5} l-30,-12 v24 z" fill="${ink}"/>`
      break
    case 'compass': {
      const cx = w / 2, cy = h / 2
      const pts = Array.from({ length: 8 }, (_, i) => { const a = (Math.PI / 4) * i; const R = i % 2 ? w * 0.2 : w * 0.42; return `${cx + R * Math.cos(a)},${cy + R * Math.sin(a)}` }).join(' ')
      body = `<circle cx="${cx}" cy="${cy}" r="${w * 0.45}" fill="none" stroke="${ink}" stroke-width="3"/><polygon points="${pts}" fill="none" stroke="${ink}" stroke-width="4"/><circle cx="${cx}" cy="${cy}" r="${w * 0.06}" fill="#b3261e"/>`
      break
    }
    case 'mace':
      body = `<line x1="${w * 0.25}" y1="${h * 0.85}" x2="${w * 0.6}" y2="${h * 0.35}" stroke="${ink}" stroke-width="10"/><circle cx="${w * 0.66}" cy="${h * 0.28}" r="${w * 0.16}" fill="none" stroke="${ink}" stroke-width="8"/><circle cx="${w * 0.66}" cy="${h * 0.28}" r="${w * 0.08}" fill="none" stroke="${ink}" stroke-width="3"/>`
      break
    case 'lotus':
      body = Array.from({ length: 7 }, (_, i) => { const a = -Math.PI / 2 + (i - 3) * 0.35; const L = h * 0.38; return `<path d="M${w / 2},${h * 0.8} Q${w / 2 + L * Math.cos(a) * 0.8 - 40},${h * 0.8 + L * Math.sin(a)} ${w / 2 + L * Math.cos(a)},${h * 0.8 + L * Math.sin(a)} Q${w / 2 + L * Math.cos(a) * 0.8 + 40},${h * 0.8 + L * Math.sin(a)} ${w / 2},${h * 0.8}" fill="none" stroke="${ink}" stroke-width="3"/>` }).join('')
      break
    case 'temple':
      body = `<path d="M${w * 0.15},${h * 0.85} v-${h * 0.3} l${w * 0.35},-${h * 0.45} l${w * 0.35},${h * 0.45} v${h * 0.3} z" fill="none" stroke="${ink}" stroke-width="4"/><path d="M${w * 0.3},${h * 0.85} v-${h * 0.22} h${w * 0.4} v${h * 0.22}" fill="none" stroke="${ink}" stroke-width="3"/><line x1="${w * 0.5}" y1="${h * 0.1}" x2="${w * 0.5}" y2="${h * 0.02}" stroke="${ink}" stroke-width="3"/>`
      break
    case 'map':
      body = `<path d="M${w * 0.1},${h * 0.3} C${w * 0.3},${h * 0.1} ${w * 0.5},${h * 0.5} ${w * 0.7},${h * 0.25} S${w * 0.95},${h * 0.6} ${w * 0.8},${h * 0.8} S${w * 0.3},${h * 0.9} ${w * 0.15},${h * 0.7} Z" fill="none" stroke="${ink}" stroke-width="3" stroke-dasharray="6 4"/>${Array.from({ length: 14 }, () => `<line x1="${r() * w}" y1="${r() * h}" x2="${r() * w}" y2="${r() * h}" stroke="${ink}" stroke-width="1" opacity="0.5"/>`).join('')}<text x="${w * 0.5}" y="${h * 0.55}" font-family="Georgia,serif" font-size="34" fill="${ink}" text-anchor="middle" letter-spacing="6">LANKA</text>`
      break
    case 'devanagari':
      body = `<text x="${w / 2}" y="${h * 0.45}" font-family="'Noto Serif Devanagari',serif" font-size="${w * 0.16}" fill="${ink}" text-anchor="middle">धर्मो रक्षति</text><text x="${w / 2}" y="${h * 0.7}" font-family="'Noto Serif Devanagari',serif" font-size="${w * 0.16}" fill="${ink}" text-anchor="middle">रक्षितः</text>`
      break
    case 'chariot':
      body = `<circle cx="${w * 0.3}" cy="${h * 0.7}" r="${w * 0.14}" fill="none" stroke="${ink}" stroke-width="4"/><circle cx="${w * 0.7}" cy="${h * 0.7}" r="${w * 0.14}" fill="none" stroke="${ink}" stroke-width="4"/>${Array.from({ length: 8 }, (_, i) => `<line x1="${w * 0.3}" y1="${h * 0.7}" x2="${w * 0.3 + w * 0.14 * Math.cos(i * Math.PI / 4)}" y2="${h * 0.7 + w * 0.14 * Math.sin(i * Math.PI / 4)}" stroke="${ink}" stroke-width="2"/>`).join('')}<path d="M${w * 0.2},${h * 0.55} h${w * 0.6} l-${w * 0.08},-${h * 0.25} h-${w * 0.44} z" fill="none" stroke="${ink}" stroke-width="4"/>`
      break
    default: // figure study
      body = `<path d="M${w * 0.5},${h * 0.12} m-40,0 a40,40 0 1,0 80,0 a40,40 0 1,0 -80,0" fill="none" stroke="${ink}" stroke-width="3"/><path d="M${w * 0.5},${h * 0.2} v${h * 0.3} M${w * 0.5},${h * 0.28} l-${w * 0.2},${h * 0.18} M${w * 0.5},${h * 0.28} l${w * 0.22},${h * 0.1} M${w * 0.5},${h * 0.5} l-${w * 0.12},${h * 0.35} M${w * 0.5},${h * 0.5} l${w * 0.14},${h * 0.35}" fill="none" stroke="${ink}" stroke-width="3" stroke-linecap="round"/>${Array.from({ length: 30 }, () => `<line x1="${w * 0.3 + r() * w * 0.4}" y1="${h * 0.2 + r() * h * 0.6}" x2="${w * 0.3 + r() * w * 0.4}" y2="${h * 0.2 + r() * h * 0.6}" stroke="${ink}" stroke-width="1" opacity="0.35"/>`).join('')}`
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${body}</svg>`
  return enc(svg)
}

/** Canvas preview swatch: paper texture + ink colour + a mock shard. */
export function canvasSwatch(key: string, paper: string, ink: string, gutter: string, w = 480, h = 320): string {
  const r = rng(hash(key))
  const grain = Array.from({ length: 160 }, () => `<circle cx="${r() * w}" cy="${r() * h}" r="${0.5 + r() * 2}" fill="${ink}" opacity="${0.03 + r() * 0.08}"/>`).join('')
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
<rect width="${w}" height="${h}" fill="${paper}"/>${grain}
<polygon points="${w * 0.08},${h * 0.12} ${w * 0.6},${h * 0.08} ${w * 0.58},${h * 0.55} ${w * 0.1},${h * 0.6}" fill="${gutter}" stroke="${ink}" stroke-width="1.5" opacity="0.9"/>
<polygon points="${w * 0.64},${h * 0.1} ${w * 0.92},${h * 0.14} ${w * 0.9},${h * 0.5} ${w * 0.62},${h * 0.52}" fill="${gutter}" stroke="${ink}" stroke-width="1.5" opacity="0.7"/>
<rect x="${w * 0.1}" y="${h * 0.68}" width="${w * 0.5}" height="${h * 0.18}" fill="${paper}" stroke="${ink}" stroke-width="1" opacity="0.9"/>
<line x1="${w * 0.14}" y1="${h * 0.74}" x2="${w * 0.52}" y2="${h * 0.74}" stroke="${ink}" stroke-width="2" opacity="0.5"/>
<line x1="${w * 0.14}" y1="${h * 0.8}" x2="${w * 0.44}" y2="${h * 0.8}" stroke="${ink}" stroke-width="2" opacity="0.5"/>
</svg>`
  return enc(svg)
}
