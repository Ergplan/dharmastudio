import { useEffect, useRef, useState } from 'react'
import { Type, RotateCcw } from 'lucide-react'
import { usePresets, useSavePage } from '@/api/hooks'
import { SIZE_STEPS, type Page, type TypographySetting } from '@/api/types'
import { cx } from '@/components/ui'

/** Per-page typography override (preset and sizes) over the volume's setting; "Reset to volume" clears it. */
export function TypePopover({ page }: { page: Page }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const { data: presets } = usePresets()
  const save = useSavePage()
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    window.addEventListener('mousedown', h); return () => window.removeEventListener('mousedown', h)
  }, [open])
  const ov = page.typography_override ?? {}
  const has = Object.keys(ov).length > 0
  const set = (patch: TypographySetting) => {
    const next: TypographySetting = { ...ov, ...patch }
    for (const k of Object.keys(next) as (keyof TypographySetting)[]) if (next[k] == null || next[k] === '') delete next[k]
    save.mutate({ id: page.id, typography_override: Object.keys(next).length ? next : null })
  }
  const r = page.typography
  return (
    <div ref={ref} className="relative">
      <button className={cx('btn btn-sm', has && 'border-gold-500/60 text-gold-300')} title="Typography for this page (override the volume)" onClick={() => setOpen(o => !o)}>
        <Type size={11} /> Type{has ? ' · page' : ''}
      </button>
      {open && presets && (
        <div className="absolute z-40 top-8 left-0 w-[19rem] card shadow-xl shadow-black/60 p-3 flex flex-col gap-3">
          <div className="text-2xs text-ink-400">Now: <span className="text-ink-200">{presets.presets.find(p => p.id === r?.preset)?.name ?? r?.preset}</span> · size {r?.size} · titles {r?.title_size}{has ? ' (page override)' : ' (volume)'}</div>
          <label className="flex flex-col gap-1">
            <span className="label">Preset</span>
            <select className="select" value={ov.preset ?? ''} onChange={(e) => set({ preset: e.target.value || null })}>
              <option value="">volume default</option>
              {presets.presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          {(['size', 'title_size'] as const).map(k => (
            <div key={k} className="flex flex-col gap-1">
              <span className="label">{k === 'size' ? 'Text size' : 'Title size'}</span>
              <div className="flex rounded border border-ink-600 overflow-hidden">
                <button className={cx('h-7 flex-1 text-2xs', !ov[k] ? 'bg-gold-500/20 text-gold-300' : 'text-ink-300 hover:bg-ink-800')} onClick={() => set({ [k]: null })}>volume</button>
                {SIZE_STEPS.map(s => <button key={s} className={cx('h-7 flex-1 text-xs', ov[k] === s ? 'bg-gold-500/20 text-gold-300' : 'text-ink-300 hover:bg-ink-800')} onClick={() => set({ [k]: s })}>{s}</button>)}
              </div>
            </div>
          ))}
          <button className="btn btn-sm self-start" disabled={!has} onClick={() => save.mutate({ id: page.id, typography_override: null })}><RotateCcw size={11} /> Reset to volume</button>
        </div>
      )}
    </div>
  )
}
