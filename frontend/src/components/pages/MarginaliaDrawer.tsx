import { useState } from 'react'
import { Save, Trash2, X, Feather } from 'lucide-react'
import type { Page, Silhouette } from '@/api/types'
import { useEditor } from '@/store/editor'
import { useSavePage, useSilhouettes } from '@/api/hooks'
import { mediaUrl } from '@/api/client'
import { cx, Field, Empty } from '@/components/ui'
import { toast } from '@/store/toasts'

export function MarginaliaDrawer({ page, frozen }: { page: Page; frozen: boolean }) {
  const { data: sils = [] } = useSilhouettes()
  const ed = useEditor()
  const save = useSavePage()
  const draft = ed.margDraft ?? page.marginalia
  const dirty = ed.margDraft !== null && JSON.stringify(ed.margDraft) !== JSON.stringify(page.marginalia)
  const [filter, setFilter] = useState('')
  const sel = ed.selectedMarginalia !== null ? draft[ed.selectedMarginalia] : null
  const update = (patch: Partial<typeof draft[number]>) => { if (ed.selectedMarginalia === null) return; ed.setMargDraft(draft.map((m, i) => i === ed.selectedMarginalia ? { ...m, ...patch } : m)) }
  const remove = () => { if (ed.selectedMarginalia === null) return; ed.setMargDraft(draft.filter((_, i) => i !== ed.selectedMarginalia)); ed.setSelectedMarginalia(null) }
  const tags = [...new Set(sils.flatMap(s => s.tags))].sort()
  const shown = sils.filter(s => !filter || s.tags.includes(filter))
  return (
    <div className="flex flex-col min-h-0">
      <div className="panel-h justify-between">
        <span className="flex items-center gap-2"><Feather size={12} className="text-sky-300" /> Marginalia</span>
        <div className="flex items-center gap-1">
          <button className="btn btn-sm" disabled={!dirty} onClick={() => { ed.setMargDraft(null); ed.setSelectedMarginalia(null) }}><X size={12} /> Discard</button>
          <button className="btn btn-sm btn-primary" disabled={!dirty || frozen || save.isPending} onClick={() => save.mutate({ id: page.id, marginalia: draft }, { onSuccess: () => { ed.setMargDraft(null); toast('ok', 'Marginalia saved') } })}><Save size={12} /> Save</button>
        </div>
      </div>
      {frozen && <div className="mx-3 mt-2 rounded border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-2xs text-amber-200">Approved page — un-approve to change marginalia.</div>}
      <div className="px-3 py-2 text-2xs text-ink-500 leading-4 border-b border-ink-800">Drag a silhouette onto the page margin (the shaded area). Click to select; drag to move; <span className="kbd">Del</span> removes. The layout also auto-places silhouettes from the page’s characters.</div>
      {sel ? (
        <div className="p-3 border-b border-ink-800 grid grid-cols-4 gap-2 items-end">
          <Field label="x mm"><input type="number" step={0.5} className="input font-mono h-6" value={sel.x_mm} onChange={(e) => update({ x_mm: Number(e.target.value) })} /></Field>
          <Field label="y mm"><input type="number" step={0.5} className="input font-mono h-6" value={sel.y_mm} onChange={(e) => update({ y_mm: Number(e.target.value) })} /></Field>
          <Field label="width mm"><input type="number" step={0.5} min={4} max={60} className="input font-mono h-6" value={sel.w_mm} onChange={(e) => update({ w_mm: Number(e.target.value) })} /></Field>
          <Field label="rotation°"><input type="number" step={1} className="input font-mono h-6" value={sel.rotation} onChange={(e) => update({ rotation: Number(e.target.value) })} /></Field>
          <Field label="tint" className="col-span-2"><div className="flex gap-1">{['#3a2d1a', '#b3261e', '#d4a017', '#1d2a33'].map(c => <button key={c} className={cx('w-6 h-6 rounded border', sel.tint === c ? 'border-gold-400' : 'border-ink-600')} style={{ background: c }} onClick={() => update({ tint: c })} />)}</div></Field>
          <button className="btn btn-danger col-span-2" onClick={remove}><Trash2 size={12} /> Remove</button>
        </div>
      ) : <div className="px-3 py-2 text-2xs text-ink-600 border-b border-ink-800">{draft.length} placed on this page.</div>}
      <div className="px-3 py-2 flex flex-wrap gap-1 border-b border-ink-800">
        <button className={cx('chip', !filter && 'chip-on')} onClick={() => setFilter('')}>all</button>
        {tags.map(t => <button key={t} className={cx('chip', filter === t && 'chip-on')} onClick={() => setFilter(t)}>{t}</button>)}
      </div>
      <div className="flex-1 overflow-auto p-3 grid grid-cols-4 gap-2 content-start">
        {shown.length === 0 && <div className="col-span-4"><Empty>No silhouettes{filter ? ` tagged ${filter}` : ''}.</Empty></div>}
        {shown.map(s => <SilCard key={s.id} s={s} />)}
      </div>
    </div>
  )
}

function SilCard({ s }: { s: Silhouette }) {
  return (
    <div draggable onDragStart={(e) => { e.dataTransfer.setData('text/silhouette', String(s.id)); e.dataTransfer.effectAllowed = 'copy' }} className="rounded border border-ink-700 bg-parchment-400 aspect-square p-1 cursor-grab active:cursor-grabbing hover:border-gold-400" title={s.tags.join(', ')}>
      <img src={mediaUrl(s.path)} alt="" className="w-full h-full object-contain" draggable={false} />
    </div>
  )
}
