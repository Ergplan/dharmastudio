import { useEffect, useState } from 'react'
import { Check, Type, Palette } from 'lucide-react'
import { useVolumes, useCanvases, useChapters, usePages, useRender, useFonts, usePresets, useVolumeTypography, useSaveVolumeTypography } from '@/api/hooks'
import { FONT_KEYS, SIZE_STEPS, type FontInfo, type TypePreset, type Canvas, type SizeStep, type ColourMode, type TextState, type TypographySetting, type CalloutColours } from '@/api/types'
import { cx, Spinner, Empty } from '@/components/ui'
import { FittedPage } from '@/components/pages/PageFrame'
import { FontFaces } from '@/components/typography/FontFaces'
import { FontPicker, ContrastBadge } from '@/components/typography/FontPicker'
import { contrast } from '@/lib/colour'

const LINE_HEIGHTS = [null, 1.2, 1.32, 1.45, 1.6] as const
const MODE_NOTES: Record<ColourMode, string> = {
  smart: 'Box, text and border are drawn from each panel’s own palette under the callout, with text at 7:1 contrast or better.',
  state: 'The fixed table: parchment boxes for narration, dark boxes for peak, ego and knowledge.',
  custom: 'Your colours per state. The badge shows the text-on-box contrast (aim for 7:1).',
}

export default function TypographyScreen() {
  const { data: volumes } = useVolumes()
  const { data: canvases = [] } = useCanvases()
  const { data: chapters = [] } = useChapters()
  const { data: fonts = [] } = useFonts()
  const { data: presets } = usePresets()
  const [volId, setVolId] = useState<number | null>(null)
  const [lang, setLang] = useState<'en' | 'hi'>('en')
  useEffect(() => { if (volumes?.length && volId === null) setVolId(volumes[0].id) }, [volumes, volId])
  const { data: vt } = useVolumeTypography(volId)
  const save = useSaveVolumeTypography()
  if (!volumes || !presets) return <Spinner />
  const vol = volumes.find(v => v.id === volId) ?? volumes[0]
  const canvas = canvases.find(c => c.id === vol?.canvas_id) ?? canvases.find(c => c.key === 'parchment')
  const first = chapters.filter(c => c.volume_id === vol?.id).sort((a, b) => a.number - b.number)[0]
  const t = vt?.typography ?? presets.default
  const stored = vt?.stored ?? {}
  const preset = presets.presets.find(p => p.id === t.preset) ?? presets.presets[0]
  const put = (body: TypographySetting) => vol && save.mutate({ id: vol.id, ...body })
  const byId = (id?: string | null) => fonts.find(f => f.id === id)

  return (
    <div className="h-full flex min-h-0">
      <FontFaces />
      <div className="flex-1 min-w-0 overflow-auto">
        <div className="max-w-[72rem] mx-auto p-5 flex flex-col gap-6">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex rounded-md border border-ink-600 overflow-hidden">
              {volumes.map(v => <button key={v.id} className={cx('h-9 px-3 text-sm', v.id === vol?.id ? 'bg-gold-500/20 text-gold-300' : 'text-ink-300 hover:bg-ink-800')} onClick={() => setVolId(v.id)}>Vol {v.number}</button>)}
            </div>
            <span className="text-sm text-ink-300 truncate">{vol?.title}</span>
            <span className="ml-auto text-xs text-ink-500">Volume default · pages can override size and preset on the Pages screen</span>
          </div>

          <section>
            <h2 className="label mb-2 flex items-center gap-2"><Type size={12} /> Preset</h2>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(19rem,1fr))] gap-3">
              {presets.presets.map(p => <PresetCard key={p.id} p={p} fonts={fonts} canvas={canvas} active={p.id === t.preset} onPick={() => put({ preset: p.id })} />)}
            </div>
          </section>

          <section className="card p-4 flex flex-col gap-4">
            <div className="flex items-center gap-2"><h2 className="label">Fonts per role</h2><span className="text-2xs text-ink-500">from “{preset.name}” unless you pick another · each list shows only fonts with the right script</span></div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-6 gap-y-3">
              {FONT_KEYS.map(k => (
                <label key={k.key} className="flex flex-col gap-1">
                  <span className="label">{k.label}</span>
                  <FontPicker fonts={fonts} role={k.role} lang={k.lang} value={stored[k.key] ?? null} inherited={preset.fonts[k.key]} onChange={(id) => put({ [k.key]: id })} />
                </label>
              ))}
            </div>
            <div className="flex flex-wrap gap-6 pt-1">
              <SizePick label="Text size" value={(t.size ?? 'L') as SizeStep} onPick={(s) => put({ size: s })} sizes={presets.sizes} />
              <SizePick label="Title size" value={(t.title_size ?? t.size ?? 'L') as SizeStep} onPick={(s) => put({ title_size: s })} sizes={presets.sizes} />
              <div className="flex flex-col gap-1">
                <span className="label">Line height</span>
                <div className="flex rounded border border-ink-600 overflow-hidden">
                  {LINE_HEIGHTS.map(lh => <button key={String(lh)} className={cx('h-8 px-2.5 text-xs', (t.line_height ?? null) === lh ? 'bg-gold-500/20 text-gold-300' : 'text-ink-300 hover:bg-ink-800')} onClick={() => put({ line_height: lh })}>{lh ?? 'auto'}</button>)}
                </div>
              </div>
            </div>
          </section>

          <ColourSection t={t} states={presets.states} defaults={presets.state_colours} onSave={put} modes={presets.colour_modes} />
          <p className="text-2xs text-ink-500">All fonts are SIL Open Font License faces shipped with the studio; a page embeds only the faces it uses (PDF and artifacts carry them inline).</p>
        </div>
      </div>

      <div className="w-[30rem] shrink-0 border-l border-ink-800 flex flex-col min-h-0">
        <div className="panel-h justify-between">
          <span>Preview — page 1{first ? ` of ch ${first.number}` : ''}</span>
          <div className="flex rounded border border-ink-600 overflow-hidden">{(['en', 'hi'] as const).map(l => <button key={l} className={cx('h-6 px-2 text-2xs uppercase', lang === l ? 'bg-gold-500/20 text-gold-300' : 'text-ink-400 hover:bg-ink-800')} onClick={() => setLang(l)}>{l}</button>)}</div>
        </div>
        <div className="flex-1 min-h-0 bg-ink-950 p-3">
          {first ? <Preview chapterId={first.id} lang={lang} /> : <div className="h-full grid place-items-center text-xs text-ink-500">No chapter in this volume yet.</div>}
        </div>
        <div className="px-3 py-2 text-2xs text-ink-500 border-t border-ink-800">Rendered by the engine (the same HTML the PDF is made from); it re-renders after every change. {byId(vt?.resolved.fonts.narration_font.id)?.note}</div>
      </div>
    </div>
  )
}

function Preview({ chapterId, lang }: { chapterId: number; lang: 'en' | 'hi' }) {
  const { data: pages } = usePages(chapterId)
  const first = pages?.[0]
  const { data: html } = useRender(first?.id ?? null, null, lang)
  if (!pages) return <Spinner />
  if (!first) return <Empty>No pages in this chapter yet — prefill it from Script.</Empty>
  return <FittedPage html={html} pad={4} />
}

function SizePick({ label, value, onPick, sizes }: { label: string; value: SizeStep; onPick: (s: SizeStep) => void; sizes: Record<SizeStep, number> }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="label">{label}</span>
      <div className="flex rounded border border-ink-600 overflow-hidden">
        {SIZE_STEPS.map(s => <button key={s} title={`× ${sizes[s]}`} className={cx('h-8 w-11 text-xs font-medium', value === s ? 'bg-gold-500/20 text-gold-300' : 'text-ink-300 hover:bg-ink-800')} onClick={() => onPick(s)}>{s}</button>)}
      </div>
    </div>
  )
}

function PresetCard({ p, fonts, canvas, active, onPick }: { p: TypePreset; fonts: FontInfo[]; canvas?: Canvas; active: boolean; onPick: () => void }) {
  const f = (k: keyof TypePreset['fonts']) => fonts.find(x => x.id === p.fonts[k])
  const fam = (k: keyof TypePreset['fonts'], fb = 'serif') => { const x = f(k); return x ? `'${x.family}',${fb}` : fb }
  const w = (k: keyof TypePreset['fonts'], title = false) => { const x = f(k); return x ? (title ? x.title_weight : x.text_weight) : 400 }
  const paper = canvas?.swatch ?? '#e8d6b2'
  const ink = canvas?.ink ?? '#3a2d1a'
  const bg = canvas?.texture_url ? `url(${canvas.texture_url}) center/cover, ${paper}` : paper
  return (
    <button onClick={onPick} className={cx('text-left rounded-lg border overflow-hidden transition-colors', active ? 'border-gold-500 ring-2 ring-gold-500/30' : 'border-ink-700 hover:border-ink-400')}>
      <div className="relative px-4 py-3.5 flex flex-col gap-2.5" style={{ background: bg, color: ink }}>
        {active && <span className="absolute top-2 right-2 w-6 h-6 rounded-full bg-gold-500 text-ink-950 grid place-items-center"><Check size={14} /></span>}
        {(['en', 'hi'] as const).map(l => {
          const k = l === 'hi' ? { t: 'hi_title_font', n: 'hi_narration_font', d: 'hi_dialogue_font' } as const : { t: 'title_font', n: 'narration_font', d: 'dialogue_font' } as const
          const s = l === 'hi' ? { t: 'लंका की अंतिम रात', n: 'मैंने अनेक जल पार करके अनेक चीज़ें ढोई हैं।', d: 'धर्मो रक्षति रक्षितः।' } : { t: 'The Last Night of Lanka', n: 'I have carried many things across many waters.', d: 'Dharma protects those who protect it.' }
          return (
            <div key={l} className="flex flex-col gap-1.5">
              <div className="text-[1.45rem] leading-tight" style={{ fontFamily: fam(k.t), fontWeight: w(k.t, true) }}>{s.t}</div>
              <div className="text-[0.98rem] leading-snug px-2.5 py-1.5 rounded-md border shadow-sm" style={{ fontFamily: fam(k.n), fontWeight: w(k.n), background: 'rgba(241,231,206,0.94)', borderColor: ink }}>{s.n}</div>
              <div className="self-end text-[0.92rem] leading-snug px-3 py-1 rounded-2xl border bg-[#f6f1e6] text-[#111]" style={{ fontFamily: fam(k.d, 'sans-serif'), fontWeight: w(k.d), borderColor: '#111' }}>{s.d}</div>
            </div>
          )
        })}
      </div>
      <div className="px-3 py-2 bg-ink-850">
        <div className="text-sm text-ink-100 font-medium">{p.name}</div>
        <div className="text-2xs text-ink-400 leading-4 mt-0.5">{p.note}</div>
        <div className="text-2xs text-ink-500 mt-1 truncate">{p.families.title_font} · {p.families.narration_font} · {p.families.dialogue_font} · {p.families.hi_title_font} · {p.families.hi_narration_font}</div>
      </div>
    </button>
  )
}

function ColourSection({ t, states, defaults, onSave, modes }: { t: TypographySetting; states: TextState[]; defaults: Record<TextState, CalloutColours>; onSave: (b: TypographySetting) => void; modes: ColourMode[] }) {
  const mode = (t.colour_mode ?? 'smart') as ColourMode
  const colours = t.colours ?? {}
  const setColour = (st: TextState, part: keyof CalloutColours, v: string) => {
    const cur = { ...defaults[st], ...(colours[st] ?? {}) }
    onSave({ colours: { ...colours, [st]: { ...cur, [part]: v } } })
  }
  return (
    <section className="card p-4 flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <h2 className="label flex items-center gap-2"><Palette size={12} /> Callout colours</h2>
        <div className="flex rounded border border-ink-600 overflow-hidden">
          {modes.map(m => <button key={m} className={cx('h-8 px-3 text-xs capitalize', mode === m ? 'bg-gold-500/20 text-gold-300' : 'text-ink-300 hover:bg-ink-800')} onClick={() => onSave({ colour_mode: m })}>{m}</button>)}
        </div>
        <span className="text-2xs text-ink-400">{MODE_NOTES[mode]}</span>
      </div>
      {mode === 'custom' && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {states.map(st => {
            const c = { ...defaults[st], ...(colours[st] ?? {}) } as CalloutColours
            return (
              <div key={st} className="rounded-md border border-ink-700 p-2.5 flex flex-col gap-2">
                <div className="flex items-center gap-2"><span className="text-xs text-ink-200 capitalize">{st}</span><span className="ml-auto"><ContrastBadge ratio={contrast(c.box, c.text)} /></span></div>
                <div className="px-3 py-2 rounded-md text-sm" style={{ background: c.box, color: c.text, border: `0.35mm solid ${c.border ?? c.text}` }}>The armies had stopped fighting.</div>
                <div className="flex gap-2 text-2xs text-ink-400">
                  {(['box', 'text', 'border'] as const).map(part => (
                    <label key={part} className="flex items-center gap-1">
                      <input type="color" className="w-7 h-6 bg-transparent border border-ink-600 rounded" value={c[part] ?? '#000000'} onChange={(e) => setColour(st, part, e.target.value)} />{part}
                    </label>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
