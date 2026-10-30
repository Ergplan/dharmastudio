// Mock page renderer: the same kind of standalone HTML the engine's layout.py produces (176 x 266 mm, bleed included).
import type { Page, Panel, Canvas, Silhouette, TextState } from '@/api/types'
import { PAGE_W, PAGE_H, BLEED, bbox } from '@/lib/mm'

const STATE_STYLE: Record<TextState, { box: string; text: string; border: string; glow?: string }> = {
  quiet: { box: 'rgba(239,228,201,0.62)', text: '#161210', border: '0.2mm solid #3a2d1a' },
  rising: { box: '#4a4a4c', text: '#f2ede3', border: '0.25mm solid #0b0b0b' },
  peak: { box: '#0b0b0d', text: '#f2ede3', border: '0.25mm solid #0b0b0b' },
  ego: { box: '#0b0b0d', text: '#b3261e', border: '0.25mm solid #b3261e' },
  knowledge: { box: '#0e1a26', text: '#d4a017', border: '0.2mm solid #d4a017', glow: 'box-shadow:0 0 2.2mm rgba(212,160,23,.55);' },
  voice: { box: 'rgba(239,228,201,0.62)', text: '#5a3a1a', border: '0.2mm dashed #5a3a1a' },
}

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

export function renderPageHtml(page: Page, panels: Panel[], canvas: Canvas, silhouettes: Silhouette[], lang: 'en' | 'hi' = 'en', chapterTitle = ''): string {
  const paper = canvas.paper_texture
  const ink = canvas.ink
  const gutter = canvas.gutter
  const isDark = canvas.key === 'indigo' || canvas.key === 'iron'
  const sorted = [...panels].sort((a, b) => a.shape.z - b.shape.z)
  const defs: string[] = []
  const imgs: string[] = []
  const caps: string[] = []
  sorted.forEach(p => {
    const poly = p.shape.polygon_mm
    const pts = poly.map(([x, y]) => `${(x + BLEED).toFixed(2)},${(y + BLEED).toFixed(2)}`).join(' ')
    const b = bbox(poly)
    const sel = p.candidates.find(c => c.id === p.selected_candidate_id)
    defs.push(`<clipPath id="c${p.id}"><polygon points="${pts}"/></clipPath>`)
    if (sel) {
      const f = p.shape.focal
      // cover-fit the 3:2 image into the bbox then apply focal pan/zoom
      const iw0 = b.w, ih0 = (b.w * 2) / 3
      const cover = Math.max(b.w / iw0, b.h / ih0) * f.scale
      const iw = iw0 * cover, ih = ih0 * cover
      const ix = b.x0 + BLEED + b.w / 2 - iw * f.x
      const iy = b.y0 + BLEED + b.h / 2 - ih * f.y
      imgs.push(`<g clip-path="url(#c${p.id})"><image href="${sel.path}" x="${ix.toFixed(2)}" y="${iy.toFixed(2)}" width="${iw.toFixed(2)}" height="${ih.toFixed(2)}" preserveAspectRatio="none"/></g>`)
    } else {
      const dark = canvas.key === 'white' ? '#1b1b1f' : 'rgba(30,24,16,0.85)'
      imgs.push(`<polygon points="${pts}" fill="${dark}"/><text x="${(b.cx + BLEED).toFixed(1)}" y="${(b.cy + BLEED).toFixed(1)}" fill="#8a8068" font-size="3" text-anchor="middle" font-family="Georgia,serif">panel ${p.n} · no take yet</text>`)
    }
    const edgeStroke = p.shape.edge === 'rim' ? `stroke="#f2c45a" stroke-width="0.6"` : p.shape.edge === 'feathered' ? `stroke="${ink}" stroke-width="0.15" stroke-opacity="0.4"` : `stroke="${canvas.key === 'white' ? '#0b0b0d' : ink}" stroke-width="${p.shape.edge === 'chipped' ? 0.45 : 0.3}" stroke-opacity="0.85"`
    imgs.push(`<polygon points="${pts}" fill="none" ${edgeStroke} ${p.shape.edge === 'torn' ? 'stroke-dasharray="1.2 0.5 0.3 0.4"' : ''}/>`)
    if (p.shape.kind === 'hex') imgs.push(`<polygon points="${pts}" fill="none" stroke="#f2c45a" stroke-opacity="0.35" stroke-width="1.4"/>`)

    const st = STATE_STYLE[p.state]
    const caption = lang === 'hi' ? p.caption_hi || p.caption_en : p.caption_en
    const balloon = lang === 'hi' ? p.balloon_hi || p.balloon_en : p.balloon_en
    const fam = lang === 'hi' ? "'Noto Serif Devanagari','Mukta',serif" : "Georgia,'Times New Roman',serif"
    const size = lang === 'hi' ? '2.75mm' : '2.6mm'
    if (caption) {
      const cw = Math.min(70, Math.max(34, b.w * 0.55))
      caps.push(`<div class="cap" style="left:${(b.x0 + 3).toFixed(1)}mm;bottom:${(PAGE_H - Math.min(b.y1, PAGE_H) + 3).toFixed(1)}mm;width:${cw.toFixed(1)}mm;background:${st.box};color:${st.text};border:${st.border};font-family:${fam};font-size:${size};${st.glow ?? ''}">${esc(caption)}</div>`)
    }
    if (balloon) {
      const bw = Math.min(56, Math.max(30, b.w * 0.45))
      caps.push(`<div class="bal" style="right:${(PAGE_W - Math.min(b.x1, PAGE_W) + 3).toFixed(1)}mm;top:${(Math.max(b.y0, 0) + 3).toFixed(1)}mm;width:${bw.toFixed(1)}mm;font-family:${fam};${p.state === 'ego' ? 'background:#0b0b0d;color:#b3261e;border-color:#b3261e;' : ''}">${p.speaker ? `<span class="spk">${esc(p.speaker)}</span>` : ''}${esc(balloon)}</div>`)
    }
  })

  const marg = page.marginalia.map(m => {
    const s = silhouettes.find(x => x.id === m.silhouette_id)
    if (!s) return ''
    return `<img class="marg" src="${s.path}" style="left:${(m.x_mm + BLEED).toFixed(1)}mm;top:${(m.y_mm + BLEED).toFixed(1)}mm;width:${m.w_mm.toFixed(1)}mm;transform:rotate(${m.rotation}deg);filter:opacity(0.78)"/>`
  }).join('')

  const title = page.number === 1 ? `<div class="title"><div class="t1">THE CYCLE<br>OF DHARMA</div><div class="t2">BOOK ONE<br>THE FIRE THAT WAS<br>NOT DESTROYED</div>${lang === 'hi' ? `<div class="t3">धर्मो रक्षति रक्षितः</div>` : `<div class="t3">Dharma protects<br>those who protect it.</div>`}</div><div class="chap">CHAPTER 1<br><span>${esc(chapterTitle || 'LANKA KAND')}</span></div><div class="rose"><svg viewBox="0 0 40 40" width="9mm" height="9mm"><circle cx="20" cy="20" r="18" fill="none" stroke="#b3261e" stroke-width="1"/><polygon points="20,2 24,16 38,20 24,24 20,38 16,24 2,20 16,16" fill="none" stroke="#b3261e" stroke-width="1.2"/><circle cx="20" cy="20" r="2" fill="#b3261e"/></svg></div>` : ''

  const marks = [
    [BLEED - 0.6, BLEED, 'h'], [BLEED - 0.6, PAGE_H + BLEED, 'h'], [PAGE_W + BLEED + 0.6, BLEED, 'h'], [PAGE_W + BLEED + 0.6, PAGE_H + BLEED, 'h'],
  ].map(([x, y]) => `<line x1="${Number(x) - 2}" y1="${y}" x2="${Number(x)}" y2="${y}" stroke="${isDark ? '#ddd' : '#333'}" stroke-width="0.15"/><line x1="${x}" y1="${Number(y) - 2}" x2="${x}" y2="${y}" stroke="${isDark ? '#ddd' : '#333'}" stroke-width="0.15"/>`).join('')

  return `<!doctype html><html><head><meta charset="utf-8"><title>Page ${page.number}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+Devanagari:wght@400;600&display=swap" rel="stylesheet">
<style>
@page{size:${PAGE_W + 2 * BLEED}mm ${PAGE_H + 2 * BLEED}mm;margin:0}
html,body{margin:0;padding:0;background:transparent}
.page{position:relative;width:${PAGE_W + 2 * BLEED}mm;height:${PAGE_H + 2 * BLEED}mm;overflow:hidden;background:${paper};color:${ink}}
.grain{position:absolute;inset:0;opacity:${canvas.key === 'white' ? 0 : canvas.key === 'glass' ? 0.08 : 0.35};mix-blend-mode:multiply;pointer-events:none}
.stain{position:absolute;inset:0;pointer-events:none;background:
 radial-gradient(ellipse at 12% 8%, rgba(120,80,30,${canvas.key === 'white' || canvas.key === 'glass' ? 0 : 0.22}) 0, transparent 38%),
 radial-gradient(ellipse at 90% 95%, rgba(90,50,20,${canvas.key === 'white' || canvas.key === 'glass' ? 0 : 0.28}) 0, transparent 40%),
 radial-gradient(ellipse at 50% 50%, transparent 55%, rgba(60,40,15,${canvas.key === 'white' || canvas.key === 'glass' ? 0 : 0.18}) 100%)}
svg.art{position:absolute;left:0;top:0;width:${PAGE_W + 2 * BLEED}mm;height:${PAGE_H + 2 * BLEED}mm}
.overlay{position:absolute;left:${BLEED}mm;top:${BLEED}mm;width:${PAGE_W}mm;height:${PAGE_H}mm}
.cap{position:absolute;padding:1.6mm 2.2mm;line-height:1.32;box-sizing:border-box}
.bal{position:absolute;padding:1.8mm 2.4mm;background:#f6f1e6;color:#111;border:0.3mm solid #111;border-radius:3.5mm;font-size:2.7mm;line-height:1.3;box-sizing:border-box}
.spk{display:block;font-size:2mm;letter-spacing:0.3mm;text-transform:uppercase;opacity:.7;margin-bottom:.6mm}
.folio{position:absolute;bottom:2.5mm;right:4mm;color:${ink};font:2.4mm Georgia,serif;opacity:.8}
.marg{position:absolute;pointer-events:none}
.title{position:absolute;left:12mm;top:6mm;color:${ink};font-family:Georgia,serif}
.t1{font-size:7.2mm;line-height:1;letter-spacing:.2mm}.t2{font-size:2.6mm;line-height:1.15;margin-top:1.4mm;letter-spacing:.2mm}.t3{font-size:2.6mm;margin-top:1.4mm;font-style:italic;color:#b3261e}
.chap{position:absolute;left:92mm;top:6mm;font:2.8mm Georgia,serif;letter-spacing:.3mm;color:${ink}}.chap span{font-size:4.2mm}
.rose{position:absolute;left:6mm;top:5mm}
</style></head><body>
<div class="page">
<svg class="grain" xmlns="http://www.w3.org/2000/svg"><filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="3" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 0.35 0 0 0 0 0.25 0 0 0 0 0.1 0 0 0 0.6 0"/></filter><rect width="100%" height="100%" filter="url(#n)"/></svg>
<div class="stain"></div>
<svg class="art" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${PAGE_W + 2 * BLEED} ${PAGE_H + 2 * BLEED}"><defs>${defs.join('')}</defs>
<rect x="${BLEED}" y="${BLEED}" width="${PAGE_W}" height="${PAGE_H}" fill="none" stroke="${gutter}" stroke-opacity="0" />
${imgs.join('\n')}
${marks}
</svg>
${marg}
<div class="overlay">${title}${caps.join('\n')}</div>
<div class="folio">${page.number}</div>
</div></body></html>`
}
