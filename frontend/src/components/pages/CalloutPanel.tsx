import { useEffect, useState } from 'react'
import { Zap, Palette } from 'lucide-react'
import type { Panel, CalloutColours } from '@/api/types'
import { usePanelPalette, useSavePanel } from '@/api/hooks'
import { cx, Field } from '@/components/ui'
import { ContrastBadge } from '@/components/typography/FontPicker'
import { contrast } from '@/lib/colour'

/** Inspector section: the panel's SFX lettering and its callout colours (auto, or a pick from the panel's palette). */
export function CalloutPanel({ panel }: { panel: Panel }) {
  const save = useSavePanel()
  const [sfx, setSfx] = useState(panel.sfx ?? '')
  useEffect(() => setSfx(panel.sfx ?? ''), [panel.id, panel.sfx])
  const pinned = panel.text_colours ?? null
  const [pick, setPick] = useState(!!pinned)
  useEffect(() => setPick(!!pinned), [panel.id, !!pinned]) // eslint-disable-line react-hooks/exhaustive-deps
  const { data: pal } = usePanelPalette(panel.id, pick || !!pinned)
  const choose = (c: CalloutColours) => save.mutate({ id: panel.id, text_colours: { box: c.box, text: c.text, ...(c.border?.startsWith('#') ? { border: c.border } : {}) } })
  return (
    <div className="rounded border border-ink-700 bg-ink-850 p-2.5 flex flex-col gap-2.5">
      <Field label="SFX lettering" hint={<span className="normal-case tracking-normal text-ink-600">large, in the SFX font, top-left of the shard</span>}>
        <div className="flex gap-1.5">
          <Zap size={14} className="text-ink-500 mt-1.5 shrink-0" />
          <input className="input" value={sfx} placeholder="e.g. THOOM!  or  धड़ाम!" onChange={(e) => setSfx(e.target.value)} onBlur={() => sfx !== (panel.sfx ?? '') && save.mutate({ id: panel.id, sfx })} onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
        </div>
      </Field>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <span className="label flex items-center gap-1"><Palette size={11} /> Callout colours</span>
          <div className="ml-auto flex rounded border border-ink-600 overflow-hidden">
            <button className={cx('h-6 px-2 text-2xs', !pick ? 'bg-gold-500/20 text-gold-300' : 'text-ink-400 hover:bg-ink-800')} onClick={() => { setPick(false); if (pinned) save.mutate({ id: panel.id, text_colours: null }) }}>auto</button>
            <button className={cx('h-6 px-2 text-2xs', pick ? 'bg-gold-500/20 text-gold-300' : 'text-ink-400 hover:bg-ink-800')} onClick={() => setPick(true)}>pick</button>
          </div>
        </div>
        {pinned && <div className="flex items-center gap-2 text-2xs text-ink-400"><span className="px-2 py-0.5 rounded" style={{ background: pinned.box, color: pinned.text, border: `1px solid ${pinned.border ?? pinned.text}` }}>Aa pinned</span><ContrastBadge ratio={contrast(pinned.box, pinned.text)} /></div>}
        {!pick && !pinned && <p className="text-2xs text-ink-500">Following the volume’s colour mode (Typography screen).</p>}
        {pick && (
          <>
            {pal?.palette.length ? <div className="flex gap-1" title="This panel’s palette">{pal.palette.map(c => <span key={c} className="w-5 h-5 rounded-sm border border-ink-600" style={{ background: c }} />)}</div> : <p className="text-2xs text-ink-500">No image selected yet — these are neutral suggestions.</p>}
            <div className="grid grid-cols-2 gap-1.5">
              {pal && [pal.auto, ...pal.swatches].slice(0, 9).map((s, i) => {
                const on = pinned && pinned.box === s.box && pinned.text === s.text
                return (
                  <button key={i} onClick={() => choose(s)} className={cx('rounded px-2 py-1.5 text-left text-xs flex items-center gap-1.5 border-2', on ? 'border-gold-400' : 'border-transparent hover:border-ink-400')} style={{ background: s.box, color: s.text, outline: `1px solid ${s.border ?? 'transparent'}` }}>
                    <span className="flex-1 truncate">{i === 0 ? 'auto pick' : 'Aa narration'}</span><span className="font-mono text-[0.6rem] opacity-80">{s.contrast.toFixed(1)}</span>
                  </button>
                )
              })}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
