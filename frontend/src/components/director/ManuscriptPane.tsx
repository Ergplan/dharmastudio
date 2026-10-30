import { useEffect, useRef, useState, type ReactNode } from 'react'
import { MessageSquareQuote, ScrollText, Crosshair } from 'lucide-react'
import type { DChapterDetail } from './api'

/** The chapter's manuscript text. Select words to add them to the brief as dialogue, narration or the action. */
export function ManuscriptPane({ ch, onAdd, highlight }: { ch: DChapterDetail; onAdd: (text: string, kind: 'dialogue' | 'narration' | 'action') => void; highlight: string[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const [sel, setSel] = useState<{ text: string; x: number; y: number } | null>(null)
  useEffect(() => {
    const h = () => {
      const s = window.getSelection()
      const t = s?.toString().trim() ?? ''
      if (!t || !ref.current || !s?.rangeCount || !ref.current.contains(s.anchorNode)) { setSel(null); return }
      const r = s.getRangeAt(0).getBoundingClientRect()
      const box = ref.current.getBoundingClientRect()
      setSel({ text: t.replace(/\s+/g, ' '), x: Math.min(r.left - box.left, box.width - 300), y: r.bottom - box.top + ref.current.scrollTop + 6 })
    }
    document.addEventListener('selectionchange', h)
    return () => document.removeEventListener('selectionchange', h)
  }, [])
  const add = (kind: 'dialogue' | 'narration' | 'action') => { if (sel) { onAdd(sel.text.replace(/^[“"]|[”"]$/g, ''), kind); window.getSelection()?.removeAllRanges(); setSel(null) } }
  if (ch.no_manuscript) {
    return <div className="m-6 p-4 rounded border border-amber-500/30 bg-amber-500/10 text-xs text-amber-100 leading-5">No manuscript text for this chapter yet. Drop the book PDF in <a className="underline" href="#/project">Project → Manuscript</a>; the Director only works from the author's words.</div>
  }
  const marks = highlight.filter(h => h.length > 6)
  return (
    <div ref={ref} className="relative h-full overflow-auto px-8 py-6 bg-[#f3ead6] text-[#2b2116]">
      <div className="max-w-[38rem] mx-auto">
        <div className="text-[0.65rem] uppercase tracking-[0.2em] text-[#7a5a32] mb-1">{ch.manuscript.book_title ? `Book ${ch.volume} · ${ch.manuscript.book_title}` : `Volume ${ch.volume}`}</div>
        <h2 className="font-book text-xl mb-4">{ch.label}</h2>
        {ch.paragraphs.map((p, i) => <p key={i} className="font-book text-[0.95rem] leading-7 mb-3 selection:bg-amber-300/60">{mark(p, marks)}</p>)}
      </div>
      {sel && (
        <div className="absolute z-10 flex gap-1 p-1 rounded-md border border-ink-600 bg-ink-900 shadow-xl" style={{ left: Math.max(8, sel.x), top: sel.y }}>
          <button className="btn btn-sm" onMouseDown={(e) => { e.preventDefault(); add('dialogue') }}><MessageSquareQuote size={11} /> Dialogue</button>
          <button className="btn btn-sm" onMouseDown={(e) => { e.preventDefault(); add('narration') }}><ScrollText size={11} /> Narration</button>
          <button className="btn btn-sm" onMouseDown={(e) => { e.preventDefault(); add('action') }}><Crosshair size={11} /> Action</button>
        </div>
      )}
    </div>
  )
}

function mark(p: string, marks: string[]): ReactNode {
  const hit = marks.find(m => p.includes(m))
  if (!hit) return p
  const i = p.indexOf(hit)
  return <>{p.slice(0, i)}<mark className="bg-amber-300/70 text-inherit rounded-sm px-0.5">{hit}</mark>{mark(p.slice(i + hit.length), marks.filter(m => m !== hit))}</>
}
