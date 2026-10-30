import { useEffect, useState } from 'react'
import { Check, Lightbulb } from 'lucide-react'
import { useVolumes, useCanvases, useChapters, usePages, useRender, useSaveVolume } from '@/api/hooks'
import { cx, Spinner, Empty } from '@/components/ui'
import { FittedPage } from '@/components/pages/PageFrame'
import type { Volume, Canvas } from '@/api/types'
import { mediaUrl } from '@/api/client'

export default function CanvasScreen() {
  const { data: volumes } = useVolumes()
  const { data: canvases } = useCanvases()
  const { data: chapters = [] } = useChapters()
  const save = useSaveVolume()
  const [volId, setVolId] = useState<number | null>(null)
  const [previewKey, setPreviewKey] = useState<string | null>(null)
  useEffect(() => { if (volumes?.length && volId === null) setVolId(volumes[0].id) }, [volumes, volId])
  if (!volumes || !canvases) return <Spinner />
  const vol = volumes.find(v => v.id === volId) ?? volumes[0]
  const chosen = canvases.find(c => c.id === vol?.canvas_id)
  const firstChapter = chapters.filter(c => c.volume_id === vol?.id).sort((a, b) => a.number - b.number)[0]
  const previewCanvas = previewKey ?? chosen?.key ?? 'parchment'
  return (
    <div className="h-full flex">
      <div className="flex-1 min-w-0 overflow-auto p-5 flex flex-col gap-6">
        {volumes.length === 0 && <Empty>No volumes yet.</Empty>}
        {volumes.map(v => (
          <VolumeRow key={v.id} v={v} canvases={canvases} active={v.id === vol?.id} onFocus={() => { setVolId(v.id); setPreviewKey(null) }} onPreview={(k) => { setVolId(v.id); setPreviewKey(k) }} onPick={(c) => { setVolId(v.id); setPreviewKey(null); save.mutate({ id: v.id, canvas_id: c.id }) }} />
        ))}
      </div>
      <div className="w-[440px] shrink-0 border-l border-ink-800 flex flex-col min-h-0">
        <div className="panel-h justify-between"><span>Preview — {vol?.title.split('—')[0].trim()}</span><span className="text-ink-500 font-normal">{canvases.find(c => c.key === previewCanvas)?.name}{previewKey && previewKey !== chosen?.key ? ' (hover)' : ''}</span></div>
        <div className="flex-1 min-h-0 bg-ink-950 p-3">
          {firstChapter ? <Preview chapterId={firstChapter.id} canvasKey={previewCanvas} /> : <div className="h-full grid place-items-center text-xs text-ink-500">No chapter in this volume yet.</div>}
        </div>
        <div className="px-3 py-2 text-2xs text-ink-500 border-t border-ink-800">Page 1 of the volume’s first chapter, rendered by the engine on the selected canvas. Hover a card to preview it; click to set it for the volume.</div>
      </div>
    </div>
  )
}

function Preview({ chapterId, canvasKey }: { chapterId: number; canvasKey: string }) {
  const { data: pages } = usePages(chapterId)
  const first = pages?.[0]
  const { data: html } = useRender(first?.id ?? null, canvasKey, 'en')
  if (!pages) return <Spinner />
  if (!first) return <div className="h-full grid place-items-center text-xs text-ink-500">No pages in this chapter yet — prefill it from Script.</div>
  return <FittedPage html={html} pad={6} />
}

function VolumeRow({ v, canvases, active, onFocus, onPreview, onPick }: { v: Volume; canvases: Canvas[]; active: boolean; onFocus: () => void; onPreview: (k: string | null) => void; onPick: (c: Canvas) => void }) {
  const suggested = new Set(v.suggested_canvas_keys ?? [])
  return (
    <section className={cx('card', active && 'border-ink-500')} onMouseEnter={onFocus}>
      <div className="panel-h justify-between">
        <span><span className="font-mono text-ink-500 mr-2">VOL {v.number}</span>{v.title}</span>
        <span className="text-ink-500 font-normal">{v.canvas_id ? `canvas: ${canvases.find(c => c.id === v.canvas_id)?.name}` : 'no canvas chosen'}{suggested.size ? ` · suggested: ${[...suggested].map(k => canvases.find(c => c.key === k)?.name).join(', ')}` : ''}</span>
      </div>
      <div className="p-3 grid grid-cols-[repeat(auto-fill,minmax(128px,1fr))] gap-3">
        {canvases.map(c => {
          const sel = c.id === v.canvas_id
          return (
            <button key={c.id} onClick={() => onPick(c)} onMouseEnter={() => onPreview(c.key)} onMouseLeave={() => onPreview(null)}
              className={cx('text-left rounded-md border overflow-hidden transition-colors', sel ? 'border-gold-500 ring-2 ring-gold-500/30' : 'border-ink-700 hover:border-ink-400')}>
              <div className="relative aspect-[3/2] bg-ink-900">
                <img src={mediaUrl(c.preview)} alt="" className="w-full h-full object-cover" />
                {sel && <span className="absolute top-1 right-1 w-5 h-5 rounded-full bg-gold-500 text-ink-950 grid place-items-center"><Check size={12} /></span>}
                {suggested.has(c.key) && <span className="absolute top-1 left-1 chip border-sky-400/60 bg-sky-500/20 text-sky-200"><Lightbulb size={9} /> Suggested</span>}
              </div>
              <div className="px-2 py-1.5">
                <div className="text-xs text-ink-100 flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm border border-ink-500" style={{ background: c.swatch ?? c.paper_texture }} /><span className="w-2.5 h-2.5 rounded-sm" style={{ background: c.ink }} />{c.name}</div>
                <div className="text-2xs text-ink-500 leading-4 mt-0.5 line-clamp-2">{c.description}</div>
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}
