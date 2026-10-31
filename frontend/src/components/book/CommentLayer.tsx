import { useEffect, useRef, useState, type PointerEvent as RPointerEvent } from 'react'
import { cx } from '@/components/ui'
import type { Anchor, Book, BookComment, BookPage, Rect } from './api'
import { anchorLabel, hitTest, pinAt, type Target } from './targets'

/**
 * Comment pins on the page. In comment mode the layer takes the pointer: hovering outlines the element a click would
 * point at (with its layer name), a click drops a pin on it, a drag on the painting marks a rectangle, and a popover
 * takes the comment. Pins stay visible outside comment mode; clicking one selects its comment.
 */
export function CommentLayer({ book, page, f, dispW, dispH, on, comments, active, aspects, onPick, onSubmit, pending, setPending }: {
  book: Book; page: BookPage; f: number; dispW: number; dispH: number; on: boolean; comments: BookComment[]; active: string | null
  aspects: Record<string, number>; onPick: (id: string) => void; onSubmit: (a: Anchor, text: string, apply: boolean) => void
  pending: Anchor | null; setPending: (a: Anchor | null) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<Target | null>(null)
  const [drag, setDrag] = useState<{ x0: number; y0: number; x1: number; y1: number; t: Target } | null>(null)
  useEffect(() => { setHover(null); setDrag(null) }, [page.id, on])
  const pt = (e: { clientX: number; clientY: number }) => {
    const r = ref.current!.getBoundingClientRect()
    return [Math.round((e.clientX - r.left) / f), Math.round((e.clientY - r.top) / f)] as const
  }
  const move = (e: RPointerEvent) => {
    const [x, y] = pt(e)
    if (drag) { setDrag({ ...drag, x1: x, y1: y }); return }
    if (!pending) setHover(hitTest(book, page, x, y, aspects))
  }
  const down = (e: RPointerEvent) => {
    e.stopPropagation()
    if (e.button !== 0 || pending) return
    e.preventDefault()
    const [x, y] = pt(e)
    setDrag({ x0: x, y0: y, x1: x, y1: y, t: hitTest(book, page, x, y, aspects) })
    ref.current?.setPointerCapture(e.pointerId)
  }
  const up = () => {
    if (!drag) return
    const { x0, y0, x1, y1, t } = drag
    setDrag(null)
    const moved = Math.abs(x1 - x0) * f > 6 || Math.abs(y1 - y0) * f > 6
    if (moved && t.layer === 'art' && !t.element) {
      const a = page.art!
      const rx = Math.max(a.x, Math.min(x0, x1)), ry = Math.max(a.y, Math.min(y0, y1))
      const rect: Rect = { x: rx, y: ry, w: Math.min(a.x + a.w, Math.max(x0, x1)) - rx, h: Math.min(a.y + a.h, Math.max(y0, y1)) - ry }
      setPending({ layer: 'art', element: null, x: rect.x + rect.w, y: rect.y, rect })
    } else {
      setPending({ layer: t.layer, element: t.element, x: x0, y: y0, ...(t.element?.startsWith('patch:') ? { rect: t.rect } : {}) })
    }
    setHover(null)
  }
  const shown = comments.filter(c => c.status !== 'dismissed')
  const act = comments.find(c => c.id === active)
  const actRect = act ? rectOf(act.anchor, page) : null
  const nextN = Math.max(0, ...comments.map(c => c.n)) + 1
  const dragRect = drag && drag.t.layer === 'art' && !drag.t.element && (Math.abs(drag.x1 - drag.x0) * f > 6 || Math.abs(drag.y1 - drag.y0) * f > 6)
    ? { x: Math.min(drag.x0, drag.x1), y: Math.min(drag.y0, drag.y1), w: Math.abs(drag.x1 - drag.x0), h: Math.abs(drag.y1 - drag.y0) } : null
  return (
    <>
      {on && (
        <div ref={ref} className="absolute inset-0 z-20 cursor-crosshair" data-testid="comment-layer"
          onPointerMove={move} onPointerDown={down} onPointerUp={up} onPointerLeave={() => !drag && setHover(null)}>
          {hover && !drag && <Outline r={hover.rect} f={f} label={hover.label} tone="hover" />}
          {dragRect && <Outline r={dragRect} f={f} label="Art · region" tone="region" />}
        </div>
      )}
      {actRect && <Outline r={actRect} f={f} tone="active" />}
      {pending?.rect && <Outline r={pending.rect} f={f} tone="region" />}
      <div className="absolute inset-0 z-30 pointer-events-none">
        {shown.map(c => {
          const [x, y] = pinAt(c)
          return (
            <button key={c.id} data-pin={c.n} onClick={(e) => { e.stopPropagation(); onPick(c.id) }} onPointerDown={(e) => e.stopPropagation()}
              title={`${c.n}. ${anchorLabel(c.anchor, page)} — ${c.text}`}
              className={cx('pointer-events-auto absolute -translate-x-1/2 -translate-y-full w-6 h-6 rounded-full rounded-bl-none rotate-[-45deg] grid place-items-center shadow-md shadow-black/60 border',
                c.status === 'applied' ? 'bg-emerald-500 border-emerald-200' : c.result?.error ? 'bg-red-500 border-red-200' : 'bg-gold-400 border-gold-100',
                c.id === active && 'ring-2 ring-white scale-110')}
              style={{ left: x * f, top: y * f }}>
              <span className="rotate-45 text-[11px] font-bold text-ink-950">{c.n}</span>
            </button>
          )
        })}
        {pending && <Popover key={`${pending.layer}${pending.element}${pending.x}${pending.y}`} anchor={pending} page={page} n={nextN} f={f} dispW={dispW} dispH={dispH} onCancel={() => setPending(null)} onSubmit={(t, apply) => { onSubmit(pending, t, apply); setPending(null) }} />}
      </div>
    </>
  )
}

function rectOf(a: Anchor, page: BookPage): Rect | null {
  if (a.rect) return a.rect
  if (a.layer === 'text') { const t = page.text.find(x => x.id === a.element); return t ? { x: t.x, y: t.y, w: t.w, h: t.h } : null }
  if (a.layer === 'art' && page.art) return { x: page.art.x, y: page.art.y, w: page.art.w, h: page.art.h }
  return null
}

function Outline({ r, f, label, tone }: { r: Rect; f: number; label?: string; tone: 'hover' | 'active' | 'region' }) {
  return (
    <div className={cx('absolute pointer-events-none border-2', tone === 'hover' ? 'border-fuchsia-400 bg-fuchsia-400/10' : tone === 'region' ? 'border-sky-400 border-dashed bg-sky-400/15' : 'border-white/90')}
      style={{ left: r.x * f, top: r.y * f, width: r.w * f, height: r.h * f }}>
      {label && <span className="absolute left-0 -top-5 whitespace-nowrap rounded bg-fuchsia-500 px-1.5 py-0.5 text-[10px] font-medium text-white shadow">{label}</span>}
    </div>
  )
}

function Popover({ anchor, page, n, f, dispW, dispH, onCancel, onSubmit }: { anchor: Anchor; page: BookPage; n: number; f: number; dispW: number; dispH: number; onCancel: () => void; onSubmit: (t: string, apply: boolean) => void }) {
  const [v, setV] = useState(anchor.element?.startsWith('patch:') ? 'Repaint this patch area into the scene.' : '')
  const ta = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { ta.current?.focus(); ta.current?.select() }, [])
  const W = 288
  const left = Math.min(Math.max(8, anchor.x * f + 14), dispW - W - 8)
  const top = Math.min(Math.max(8, anchor.y * f + 10), dispH - 190)
  return (
    <div className="pointer-events-auto absolute z-40 card shadow-2xl shadow-black/70 p-2.5 flex flex-col gap-2" style={{ left, top, width: W }} data-testid="comment-popover"
      onPointerDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center gap-2 text-2xs">
        <span className="w-5 h-5 rounded-full bg-gold-400 text-ink-950 font-bold grid place-items-center">{n}</span>
        <span className="text-ink-200 font-medium">{anchorLabel(anchor, page)}</span>
        {anchor.rect && <span className="text-ink-500 font-mono">{Math.round(anchor.rect.w)}×{Math.round(anchor.rect.h)}</span>}
      </div>
      <textarea ref={ta} className="textarea text-xs" rows={3} value={v} onChange={(e) => setV(e.target.value)} placeholder="What should change here?"
        onKeyDown={(e) => { e.stopPropagation(); if (e.key === 'Escape') onCancel(); if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && v.trim()) onSubmit(v.trim(), e.shiftKey) }} />
      <div className="flex items-center gap-1.5">
        <span className="text-2xs text-ink-500 flex-1">⌘↵ add · ⇧⌘↵ add & apply</span>
        <button className="btn btn-sm" onClick={onCancel}>Cancel</button>
        <button className="btn btn-sm" disabled={!v.trim()} onClick={() => onSubmit(v.trim(), false)}>Add</button>
        <button className="btn btn-sm btn-primary" disabled={!v.trim()} onClick={() => onSubmit(v.trim(), true)}>Add & apply</button>
      </div>
    </div>
  )
}
