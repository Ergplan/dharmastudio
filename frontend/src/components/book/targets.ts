import type { Anchor, Book, BookPage, Rect } from './api'

/** What a click on the page in comment mode would point at: the element, its outline (page px) and a label. */
export interface Target { layer: Anchor['layer']; element: string | null; rect: Rect; label: string }

const inside = (x: number, y: number, r: Rect) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h

/** Paper elements as the renderer places them (engine/book_render.py): shloka bands, source line, folio, figures. */
export function paperRects(book: Book, page: BookPage, aspects: Record<string, number>): { element: string; rect: Rect; label: string }[] {
  const [W, H] = book.page_px
  const fb = book.frame?.b ?? 200
  const out: { element: string; rect: Rect; label: string }[] = []
  page.paper.figures.forEach((f, i) => out.push({ element: `figure:${i}`, rect: { x: f.x, y: f.y, w: f.h * (aspects[f.name] ?? 0.6), h: f.h }, label: `Paper · figure ${i + 1} (${f.name})` }))
  if (page.paper.shloka) {
    out.push({ element: 'shloka', rect: { x: 130, y: 26, w: W - 260, h: 80 }, label: 'Paper · shloka' })
    out.push({ element: 'shloka', rect: { x: 130, y: H - fb, w: W - 260, h: 80 }, label: 'Paper · shloka' })
    out.push({ element: 'shloka', rect: { x: 130, y: H - 100, w: W - 400, h: 44 }, label: 'Paper · shloka source' })
  }
  if (page.page_number) out.push({ element: 'folio', rect: { x: W - 250, y: H - 100, w: 130, h: 44 }, label: 'Paper · page number' })
  return out
}

export function hitTest(book: Book, page: BookPage, x: number, y: number, aspects: Record<string, number>): Target {
  const [W, H] = book.page_px
  if (page.layers.text) {
    for (let i = page.text.length - 1; i >= 0; i--) {
      const t = page.text[i]
      if (inside(x, y, t)) return { layer: 'text', element: t.id, rect: { x: t.x, y: t.y, w: t.w, h: t.h }, label: `Text · box ${i + 1} (${t.style})` }
    }
  }
  const a = page.art
  if (a && page.layers.art) {
    for (const p of [...(a.patches ?? [])].reverse()) if (!p.hidden && inside(x, y, p)) return { layer: 'art', element: `patch:${p.id}`, rect: p, label: `Art · patch ${p.id}` }
  }
  if (page.layers.paper) {
    // margin elements sit outside the art window; figures may overlap it slightly, so test them before the art
    for (const r of paperRects(book, page, aspects)) if (inside(x, y, r.rect) && !(a && page.layers.art && inside(x, y, a))) return { layer: 'paper', element: r.element, rect: r.rect, label: r.label }
  }
  if (a && page.layers.art && inside(x, y, a)) return { layer: 'art', element: null, rect: { x: a.x, y: a.y, w: a.w, h: a.h }, label: 'Art · painting (drag to mark a region)' }
  return { layer: 'paper', element: 'texture', rect: { x: 0, y: 0, w: W, h: H }, label: 'Paper · texture' }
}

/** Where a comment's pin sits (page px). */
export function pinAt(c: { anchor: Anchor }): [number, number] {
  const r = c.anchor.rect
  return r && c.anchor.layer === 'art' && !c.anchor.element ? [r.x + r.w, r.y] : [c.anchor.x, c.anchor.y]
}

export function anchorLabel(a: Anchor, page: BookPage): string {
  if (a.layer === 'text') { const i = page.text.findIndex(t => t.id === a.element); return i >= 0 ? `Text box ${i + 1}` : `Text ${a.element}` }
  if (a.layer === 'paper') return a.element === 'shloka' ? 'Shloka' : a.element === 'folio' ? 'Page number' : a.element?.startsWith('figure:') ? `Figure ${Number(a.element.slice(7)) + 1}` : 'Paper'
  if (a.layer === 'art') return a.element ? `Art patch ${a.element.slice(6)}` : a.rect ? 'Art region' : 'Art'
  return 'Whole page'
}
