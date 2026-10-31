import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from 'react'
import { cx } from '@/components/ui'
import { useBoxSize } from '@/components/pages/PageFrame'
import type { Book, BookPage, TextBox } from './api'

export type Selection = { type: 'text'; id: string } | { type: 'art' } | { type: 'paper' } | null

type Rect = { x: number; y: number; w: number; h: number }
type Drag = { mode: 'move' | 'resize' | 'tail'; id: string; sx: number; sy: number; orig: Rect & { tail: [number, number] | null }; cur: Rect & { tail: [number, number] | null }; moved: boolean }

const CSS_PX_PER_MM = 96 / 25.4

/**
 * The page as the renderer draws it (an iframe of /render, the same HTML the PDF is made from), with an editing
 * overlay on top: text boxes can be selected, dragged, resized (corner handle), edited inline (double-click), and a
 * glass balloon's tail moved by its handle. Coordinates are the package's page px.
 */
export function BookCanvas({ book, page, html, sel, onSelect, onCommitBox, onEditText }: {
  book: Book; page: BookPage; html: string | undefined; sel: Selection
  onSelect: (s: Selection) => void
  onCommitBox: (id: string, patch: Partial<TextBox>) => void
  onEditText: (box: TextBox, text: string) => void
}) {
  const { ref, size } = useBoxSize<HTMLDivElement>()
  const [W, H] = book.page_px
  const [tw, th] = book.trim_mm
  const pad = 20
  const dispW = Math.max(50, Math.min(size.w - 2 * pad, (size.h - 2 * pad) * W / H))
  const dispH = dispW * H / W
  const f = dispW / W // display px per page px
  const iframeScale = dispW / (tw * CSS_PX_PER_MM)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const stage = useRef<HTMLDivElement>(null)
  const textOn = page.layers.text

  useEffect(() => { setEditing(null); setDrag(null) }, [page.id])

  // pointer tracking for move / resize / tail
  useEffect(() => {
    if (!drag) return
    const move = (e: PointerEvent) => {
      const dx = (e.clientX - drag.sx) / f, dy = (e.clientY - drag.sy) / f
      const o = drag.orig
      let cur = { ...o }
      if (drag.mode === 'move') cur = { ...o, x: Math.round(o.x + dx), y: Math.round(o.y + dy) }
      else if (drag.mode === 'resize') cur = { ...o, w: Math.max(60, Math.round(o.w + dx)), h: Math.max(40, Math.round(o.h + dy)) }
      else if (o.tail) cur = { ...o, tail: [Math.round(o.tail[0] + dx), Math.round(o.tail[1] + dy)] }
      setDrag({ ...drag, cur, moved: drag.moved || Math.abs(dx) * f > 2 || Math.abs(dy) * f > 2 })
    }
    const up = () => {
      if (drag.moved) {
        const c = drag.cur
        onCommitBox(drag.id, drag.mode === 'move' ? { x: c.x, y: c.y } : drag.mode === 'resize' ? { w: c.w, h: c.h } : { tail: c.tail })
      }
      setDrag(null)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
  }, [drag, f, onCommitBox])

  const start = (e: RPointerEvent, mode: Drag['mode'], t: TextBox) => {
    if (e.button !== 0 || editing === t.id) return
    e.stopPropagation(); e.preventDefault()
    onSelect({ type: 'text', id: t.id })
    const orig = { x: t.x, y: t.y, w: t.w, h: t.h, tail: t.tail ?? null }
    setDrag({ mode, id: t.id, sx: e.clientX, sy: e.clientY, orig, cur: orig, moved: false })
  }

  const clickStage = (e: RPointerEvent) => {
    if (e.button !== 0) return
    const r = stage.current!.getBoundingClientRect()
    const x = (e.clientX - r.left) / f, y = (e.clientY - r.top) / f
    const a = page.art
    if (a && page.layers.art && x >= a.x && x <= a.x + a.w && y >= a.y && y <= a.y + a.h) onSelect({ type: 'art' })
    else onSelect({ type: 'paper' })
    setEditing(null)
  }

  const art = page.art
  return (
    <div ref={ref} className="w-full h-full grid place-items-center overflow-hidden bg-ink-950" data-testid="book-canvas">
      {size.w > 0 && (
        <div ref={stage} className="relative shadow-2xl shadow-black/70 select-none" style={{ width: dispW, height: dispH }} onPointerDown={clickStage}>
          {html ? (
            <iframe title={`page ${page.number}`} srcDoc={html} sandbox="allow-same-origin" scrolling="no"
              className="absolute left-0 top-0 border-0 pointer-events-none bg-transparent"
              style={{ width: `${tw}mm`, height: `${th}mm`, transform: `scale(${iframeScale})`, transformOrigin: '0 0' }} />
          ) : <div className="absolute inset-0 grid place-items-center text-ink-500 text-2xs">rendering…</div>}
          {/* art and paper selection outlines */}
          {sel?.type === 'art' && art && <div className="absolute border-2 border-sky-400/80 pointer-events-none" style={{ left: art.x * f, top: art.y * f, width: art.w * f, height: art.h * f }} />}
          {sel?.type === 'paper' && <div className="absolute inset-0 border-2 border-amber-400/70 pointer-events-none" />}
          {textOn && page.text.map(t => {
            const d = drag?.id === t.id ? drag.cur : null
            const r = d ?? t
            const on = sel?.type === 'text' && sel.id === t.id
            const tail = (d ? d.tail : t.tail) ?? null
            return (
              <div key={t.id}>
                <div data-box={t.id}
                  className={cx('absolute cursor-move rounded-sm', on ? 'outline outline-2 outline-gold-400' : 'hover:outline hover:outline-1 hover:outline-gold-300/60', d && drag?.moved && 'bg-gold-400/10')}
                  style={{ left: r.x * f, top: r.y * f, width: r.w * f, height: r.h * f }}
                  onPointerDown={(e) => start(e, 'move', t)}
                  onDoubleClick={(e) => { e.stopPropagation(); setEditing(t.id) }}
                  title={`${t.style} · double-click to edit`}>
                  {on && editing !== t.id && <div className="absolute -right-1.5 -bottom-1.5 w-3 h-3 bg-gold-400 border border-ink-950 cursor-nwse-resize" onPointerDown={(e) => start(e, 'resize', t)} title="Resize" />}
                  {editing === t.id && <InlineEditor box={t} f={f} onDone={(txt) => { setEditing(null); if (txt !== null) onEditText(t, txt) }} />}
                </div>
                {on && tail && t.style === 'glass' && (
                  <>
                    <svg className="absolute left-0 top-0 pointer-events-none overflow-visible" width={dispW} height={dispH}>
                      <line x1={(r.x + r.w / 2) * f} y1={(r.y + r.h / 2) * f} x2={tail[0] * f} y2={tail[1] * f} stroke="#f2c45a" strokeDasharray="4 3" strokeWidth={1} />
                    </svg>
                    <div className="absolute w-3.5 h-3.5 -ml-[7px] -mt-[7px] rounded-full bg-gold-400 border-2 border-ink-950 cursor-crosshair" style={{ left: tail[0] * f, top: tail[1] * f }}
                      onPointerDown={(e) => start(e, 'tail', t)} title="Tail: drag toward the speaker" />
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function InlineEditor({ box, f, onDone }: { box: TextBox; f: number; onDone: (text: string | null) => void }) {
  const initial = box.style === 'header' ? (box.title ?? box.text) : box.text
  const [v, setV] = useState(initial)
  const ref = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { ref.current?.focus(); ref.current?.select() }, [])
  return (
    <textarea ref={ref} value={v} onChange={(e) => setV(e.target.value)} data-testid="inline-editor"
      className="absolute inset-0 w-full h-full resize-none rounded-sm bg-parchment-300/95 text-ink-950 font-book p-1 leading-snug border-2 border-gold-400 outline-none"
      style={{ fontSize: Math.max(10, (box.size ?? (box.style === 'header' ? 56 : 44)) * f) }}
      onPointerDown={(e) => e.stopPropagation()}
      onBlur={() => onDone(v === initial ? null : v)}
      onKeyDown={(e) => {
        e.stopPropagation()
        if (e.key === 'Escape') onDone(null)
        else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) (e.target as HTMLTextAreaElement).blur()
      }} />
  )
}
