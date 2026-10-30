import { Undo2, Redo2, Save, X, Lock, Unlock, ArrowUp, ArrowDown, Crosshair } from 'lucide-react'
import type { Panel } from '@/api/types'
import { SHAPE_KINDS, EDGES } from '@/api/types'
import { useEditor } from '@/store/editor'
import { useSavePanel } from '@/api/hooks'
import { cx, Field, Chip } from '@/components/ui'
import { bbox, polygonArea, fmtMm } from '@/lib/mm'
import { toast } from '@/store/toasts'
import { useQueryClient } from '@tanstack/react-query'

export function ShardTools({ panels, selected, frozen }: { panels: Panel[]; selected: Panel | null; frozen: boolean }) {
  const ed = useEditor()
  const save = useSavePanel()
  const qc = useQueryClient()
  const d = selected ? ed.drafts[selected.id] : null
  const changed = panels.filter(p => { const dd = ed.drafts[p.id]; return dd && (JSON.stringify(dd.shape) !== JSON.stringify(p.shape) || dd.locked_shape !== p.locked_shape || dd.image_group !== p.image_group) })
  const onSave = async () => {
    try {
      for (const p of changed) { const dd = ed.drafts[p.id]; await save.mutateAsync({ id: p.id, shape: dd.shape, locked_shape: dd.locked_shape, image_group: dd.image_group }) }
      ed.markSaved(); qc.invalidateQueries({ queryKey: ['render'] })
      toast('ok', `Saved ${changed.length} shard${changed.length === 1 ? '' : 's'}`, 'The page re-renders with the stored polygons.')
    } catch { /* toasted by the mutation */ }
  }
  return (
    <div className="flex flex-col min-h-0">
      <div className="panel-h justify-between">
        <span className="flex items-center gap-2"><Crosshair size={12} className="text-sky-300" /> Shard editor</span>
        <div className="flex items-center gap-1">
          <button className="btn btn-sm btn-icon" title="Undo (Ctrl+Z)" disabled={!ed.past.length} onClick={ed.undo}><Undo2 size={12} /></button>
          <button className="btn btn-sm btn-icon" title="Redo (Ctrl+Y)" disabled={!ed.future.length} onClick={ed.redo}><Redo2 size={12} /></button>
          <button className="btn btn-sm" title="Discard changes" disabled={!changed.length} onClick={() => ed.loadDrafts(panels)}><X size={12} /> Discard</button>
          <button className="btn btn-sm btn-primary" disabled={!changed.length || save.isPending || frozen} title={frozen ? 'Page is approved — un-approve to edit shards' : 'Save shapes (PUT /api/panels)'} onClick={onSave}><Save size={12} /> Save{changed.length ? ` (${changed.length})` : ''}</button>
        </div>
      </div>
      {frozen && <div className="mx-3 mt-2 rounded border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-2xs text-amber-200">Approved pages are frozen. Un-approve to save shard edits.</div>}
      <div className="px-3 py-2 text-2xs text-ink-500 leading-4 border-b border-ink-800">
        Drag vertices (0.5 mm grid, snaps to 6 mm margin and neighbours' gutters; hold <span className="kbd">Alt</span> to skip snapping). Double-click an edge to add a vertex; right-click or <span className="kbd">⌫</span> deletes one (min 3). Drag inside a shard to pan its image, wheel to zoom.
      </div>
      {!d || !selected ? (
        <div className="p-4 text-xs text-ink-500 italic">Select a shard on the page (or press 1–9).</div>
      ) : (
        <div className="flex-1 overflow-auto p-3 flex flex-col gap-3">
          <div className="flex items-center gap-2 text-xs">
            <span className="font-mono text-ink-400">SHARD {selected.n}</span>
            <span className="chip">{d.shape.kind}</span>
            <span className="chip">{d.shape.polygon_mm.length} pts</span>
            <span className="chip">z {d.shape.z}</span>
            <span className="ml-auto font-mono text-2xs text-ink-500">{(() => { const b = bbox(d.shape.polygon_mm); return `${fmtMm(b.w)} × ${fmtMm(b.h)} · ${Math.round(polygonArea(d.shape.polygon_mm) / 100) / 10} cm²` })()}</span>
          </div>
          <div>
            <div className="label mb-1">Shape palette <span className="text-ink-600">— replaces the polygon, sized to the current bbox</span></div>
            <div className="grid grid-cols-4 gap-1.5">
              {SHAPE_KINDS.map(k => (
                <button key={k} disabled={d.locked_shape} onClick={() => ed.applyPreset(selected.id, k)} className={cx('h-14 rounded border text-2xs flex flex-col items-center justify-center gap-1 hover:border-ink-400 disabled:opacity-40', d.shape.kind === k ? 'border-sky-400 bg-sky-500/10 text-sky-200' : 'border-ink-700 bg-ink-900 text-ink-300')}>
                  <ShapeGlyph kind={k} />{k}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Edge treatment"><select className="select" value={d.shape.edge} onChange={(e) => ed.setEdge(selected.id, e.target.value as Panel['shape']['edge'])}>{EDGES.map(e => <option key={e}>{e}</option>)}</select></Field>
            <Field label="Z-order"><div className="flex gap-1"><button className="btn flex-1" onClick={() => ed.bumpZ(selected.id, 1)}><ArrowUp size={12} /> Up</button><button className="btn flex-1" onClick={() => ed.bumpZ(selected.id, -1)} disabled={d.shape.z <= 0}><ArrowDown size={12} /> Down</button></div></Field>
          </div>
          <div>
            <div className="label mb-1">Focal (pan / zoom)</div>
            <div className="grid grid-cols-3 gap-2">
              <NumField label="x" value={d.shape.focal.x} min={0} max={1} step={0.01} onChange={(v) => ed.setFocal(selected.id, { ...d.shape.focal, x: v }, true)} />
              <NumField label="y" value={d.shape.focal.y} min={0} max={1} step={0.01} onChange={(v) => ed.setFocal(selected.id, { ...d.shape.focal, y: v }, true)} />
              <NumField label="scale" value={d.shape.focal.scale} min={1} max={4} step={0.05} onChange={(v) => ed.setFocal(selected.id, { ...d.shape.focal, scale: v }, true)} />
            </div>
            <button className="btn btn-sm mt-1.5" onClick={() => ed.setFocal(selected.id, { x: 0.5, y: 0.5, scale: 1 }, true)}>Reset focal</button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Image group" hint={<span className="normal-case tracking-normal text-ink-600">shards sharing one image</span>}><input className="input font-mono" placeholder="e.g. arrow" value={d.image_group ?? ''} onChange={(e) => ed.setImageGroup(selected.id, e.target.value.trim() || null)} /></Field>
            <Field label="Lock shape"><button className={cx('btn w-full', d.locked_shape && 'border-emerald-500/60 text-emerald-200')} onClick={() => ed.setLocked(selected.id, !d.locked_shape)}>{d.locked_shape ? <Lock size={12} /> : <Unlock size={12} />}{d.locked_shape ? 'Locked — survives Re-cut' : 'Unlocked'}</button></Field>
          </div>
          <div>
            <div className="label mb-1">Vertices (mm)</div>
            <div className="font-mono text-2xs text-ink-400 grid grid-cols-3 gap-x-2 gap-y-0.5">
              {d.shape.polygon_mm.map(([x, y], i) => <button key={i} onClick={() => ed.setSelectedVertex(i)} className={cx('text-left px-1 rounded hover:bg-ink-800', ed.selectedVertex === i && 'bg-gold-500/15 text-gold-300')}>{i + 1}: {x.toFixed(1)}, {y.toFixed(1)}</button>)}
            </div>
          </div>
          <div className="text-2xs text-ink-500">Other shards: <Chip>{panels.length - 1}</Chip> · Snap targets: margin 6 mm, gutter 3 mm.</div>
        </div>
      )}
    </div>
  )
}

function NumField({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void }) {
  return <label className="flex items-center gap-1 text-2xs text-ink-400"><span className="w-8">{label}</span><input type="number" className="input font-mono h-6" value={value} min={min} max={max} step={step} onChange={(e) => onChange(Math.min(max, Math.max(min, Number(e.target.value))))} /></label>
}

function ShapeGlyph({ kind }: { kind: string }) {
  const p: Record<string, string> = {
    torn: '2,3 9,2 14,4 20,2 22,8 21,14 22,19 15,20 8,18 3,20 1,13 2,8',
    crisp: '2,2 21,3 22,20 1,19',
    fracture: '5,1 22,4 19,21 1,17 4,9',
    hex: '12,1 22,6.5 22,15.5 12,21 2,15.5 2,6.5',
    rect: '2,2 22,2 22,20 2,20',
    inset: '',
    bleed: '0,0 24,0 24,22 0,22',
  }
  return <svg width={24} height={22} viewBox="0 0 24 22">{kind === 'inset' ? <ellipse cx={12} cy={11} rx={10} ry={8} fill="none" stroke="currentColor" strokeWidth={1.2} /> : <polygon points={p[kind]} fill="none" stroke="currentColor" strokeWidth={1.2} />}{kind === 'hex' && <polygon points={p.hex} fill="none" stroke="#f2c45a" strokeWidth={0.6} />}</svg>
}
