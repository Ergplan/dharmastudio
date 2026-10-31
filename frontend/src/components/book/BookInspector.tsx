import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Eye, EyeOff, Trash2, Plus, Image as ImageIcon, Type, ScrollText, History, ArrowUpToLine, ArrowDownToLine, AlignLeft, AlignCenter, AlignRight } from 'lucide-react'
import { cx } from '@/components/ui'
import type { Selection } from './BookCanvas'
import {
  useBookFonts, useFigures, useShlokas, useTextures, usePageHistory, STYLE_LABEL,
  type Book, type BookPage, type TextBox, type TextStyle, type TextKind, type Figure, type Layers, type LayerKey, type Art, type Align,
} from './api'

/** A labelled group (a div, not a <label>: several groups hold more than one control). */
function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="label flex items-baseline gap-2 min-w-0">{label}{hint && <span className="normal-case tracking-normal font-normal text-ink-500 truncate">{hint}</span>}</span>
      {children}
    </div>
  )
}

const LAYER_LABEL: Record<LayerKey, string> = { paper: 'Paper', art: 'Art', text: 'Text' }

/** Paper · Art · Text visibility toggles (the canvas toolbar). */
export function LayerToggles({ layers, onToggle }: { layers: Layers; onToggle: (k: LayerKey, v: boolean) => void }) {
  return (
    <div className="flex items-center rounded border border-ink-600 overflow-hidden" role="group" aria-label="Layers">
      {(['paper', 'art', 'text'] as LayerKey[]).map((k, i) => (
        <button key={k} className={cx('h-7 px-2.5 text-xs flex items-center gap-1.5', i > 0 && 'border-l border-ink-600', layers[k] ? 'text-gold-300 bg-gold-500/10' : 'text-ink-500 hover:bg-ink-800')}
          onClick={() => onToggle(k, !layers[k])} aria-pressed={layers[k]} title={`${layers[k] ? 'Hide' : 'Show'} the ${LAYER_LABEL[k].toLowerCase()} layer on this page`}>
          {layers[k] ? <Eye size={12} /> : <EyeOff size={12} />}{LAYER_LABEL[k]}
        </button>
      ))}
    </div>
  )
}

/** The page's layers, top to bottom, with every text box (click to select). */
export function LayersList({ page, sel, onSelect, onToggle, onPatch, onRemovePatch }: {
  page: BookPage; sel: Selection; onSelect: (s: Selection) => void; onToggle: (k: LayerKey, v: boolean) => void
  onPatch?: (id: string, hidden: boolean) => void; onRemovePatch?: (id: string) => void
}) {
  const row = (k: LayerKey, icon: ReactNode, label: string, active: boolean, onClick: () => void, sub?: string) => (
    <div className={cx('flex items-center gap-2 h-7 px-2 rounded cursor-pointer', active ? 'bg-gold-500/10 text-gold-200' : 'hover:bg-ink-800 text-ink-200')} onClick={onClick}>
      <button className="text-ink-400 hover:text-ink-100" onClick={(e) => { e.stopPropagation(); onToggle(k, !page.layers[k]) }} title={page.layers[k] ? 'Hide' : 'Show'}>
        {page.layers[k] ? <Eye size={12} /> : <EyeOff size={12} />}
      </button>
      {icon}<span className={cx('text-xs flex-1 truncate', !page.layers[k] && 'opacity-50 line-through')}>{label}</span>
      {sub && <span className="text-2xs text-ink-500 truncate max-w-[7rem]">{sub}</span>}
    </div>
  )
  return (
    <div className="p-2 border-b border-ink-800" data-testid="layers-list">
      <div className="label px-1 mb-1">Layers</div>
      {row('text', <Type size={12} className="text-ink-400" />, 'Text', false, () => onSelect(page.text[0] ? { type: 'text', id: page.text[0].id } : null), `${page.text.length} boxes`)}
      <div className="ml-6 mb-1">
        {page.text.map(t => (
          <div key={t.id} className={cx('h-6 px-2 rounded text-2xs flex items-center gap-2 cursor-pointer truncate', sel?.type === 'text' && sel.id === t.id ? 'bg-gold-500/15 text-gold-200' : 'text-ink-300 hover:bg-ink-800')}
            onClick={() => onSelect({ type: 'text', id: t.id })}>
            <span className={cx('w-2 h-2 rounded-sm shrink-0', t.style.startsWith('glass') ? 'bg-slate-600 border border-slate-300/60' : 'bg-parchment-400 border border-sepia/60')} />
            <span className="truncate">{t.style === 'header' ? (t.title ?? t.text) : t.text}</span>
          </div>
        ))}
      </div>
      {row('art', <ImageIcon size={12} className="text-ink-400" />, 'Art', sel?.type === 'art', () => onSelect({ type: 'art' }), page.art ? page.art.file.replace('art/', '') : 'none')}
      {!!page.art?.patches?.length && (
        <div className="ml-6 mb-1" data-testid="patches-list">
          <div className="text-2xs text-ink-500 px-2 h-5 flex items-center">Patches · {page.art.patches.length}</div>
          {page.art.patches.map(pa => (
            <div key={pa.id} className={cx('h-6 px-2 rounded text-2xs flex items-center gap-2 cursor-pointer group', sel?.type === 'patch' && sel.id === pa.id ? 'bg-sky-500/15 text-sky-200' : 'text-ink-300 hover:bg-ink-800')}
              onClick={() => onSelect({ type: 'patch', id: pa.id })}>
              <button className="text-ink-400 hover:text-ink-100" title={pa.hidden ? 'Show' : 'Hide'} onClick={(e) => { e.stopPropagation(); onPatch?.(pa.id, !pa.hidden) }}>{pa.hidden ? <EyeOff size={11} /> : <Eye size={11} />}</button>
              <span className="w-2 h-2 rounded-sm shrink-0 bg-[#e8d8b4] border border-sepia/50" />
              <span className={cx('flex-1 truncate', pa.hidden && 'opacity-50 line-through')}>{pa.id} <span className="text-ink-500">{pa.linked ? `→ ${pa.linked}` : 'unlinked'}</span></span>
              <button className="opacity-0 group-hover:opacity-100 text-red-300" title="Remove patch" onClick={(e) => { e.stopPropagation(); onRemovePatch?.(pa.id) }}><Trash2 size={11} /></button>
            </div>
          ))}
        </div>
      )}
      {row('paper', <ScrollText size={12} className="text-ink-400" />, 'Paper', sel?.type === 'paper', () => onSelect({ type: 'paper' }), [page.paper.texture, page.paper.shloka?.source, `${page.paper.figures.length} fig`].filter(Boolean).join(' · '))}
    </div>
  )
}

/** A text input that commits on blur / Enter (one history entry per edit, not per keystroke). */
function Commit({ value, onCommit, multiline, className, placeholder, type = 'text' }: { value: string; onCommit: (v: string) => void; multiline?: boolean; className?: string; placeholder?: string; type?: string }) {
  const [v, setV] = useState(value)
  useEffect(() => setV(value), [value])
  const done = () => { if (v !== value) onCommit(v) }
  return multiline
    ? <textarea className={cx('textarea text-xs', className)} rows={4} value={v} placeholder={placeholder} onChange={(e) => setV(e.target.value)} onBlur={done} onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) done() }} />
    : <input className={cx('input', className)} type={type} value={v} placeholder={placeholder} onChange={(e) => setV(e.target.value)} onBlur={done} onKeyDown={(e) => { if (e.key === 'Enter') done() }} />
}

function NumRow({ fields, values, onCommit }: { fields: string[]; values: Record<string, number>; onCommit: (k: string, v: number) => void }) {
  return (
    <div className={cx('grid gap-1.5', fields.length === 4 ? 'grid-cols-4' : 'grid-cols-3')}>
      {fields.map(k => (
        <label key={k} className="flex flex-col gap-0.5"><span className="text-2xs text-ink-500 uppercase">{k}</span>
          <Commit type="number" className="font-mono" value={String(Math.round(values[k] ?? 0))} onCommit={(v) => { const n = Number(v); if (Number.isFinite(n)) onCommit(k, n) }} />
        </label>
      ))}
    </div>
  )
}

export function TextInspector({ box, onPatch, onDelete }: { box: TextBox; onPatch: (p: Partial<TextBox> & { z?: 'front' | 'back' }) => void; onDelete: () => void }) {
  const { data: fonts = [] } = useBookFonts()
  const house = fonts.filter(f => f.house), more = fonts.filter(f => !f.house)
  const placeholder = box.style === 'parchment' ? 50 : box.style === 'header' ? 64 : box.style === 'glass-narration' ? 44 : box.font === 'Inter Tight' ? 42 : 40
  return (
    <div className="p-3 flex flex-col gap-3" data-testid="text-inspector">
      <div className="flex items-center gap-2"><Type size={13} className="text-gold-300" /><span className="text-xs font-medium text-ink-100">Text box</span><span className="text-2xs font-mono text-ink-500">{box.id}</span></div>
      {box.style === 'header' ? (
        <>
          <Field label="Kicker"><Commit value={box.kicker ?? ''} onCommit={(v) => onPatch({ kicker: v })} /></Field>
          <Field label="Title"><Commit value={box.title ?? box.text} onCommit={(v) => onPatch({ title: v, text: [box.kicker, v].filter(Boolean).join(' · ') })} /></Field>
        </>
      ) : <Field label="Text"><Commit multiline value={box.text} onCommit={(v) => onPatch({ text: v })} /></Field>}
      <div className="grid grid-cols-2 gap-2">
        <Field label="Style">
          <select className="select" value={box.style} onChange={(e) => {
            const s = e.target.value as TextStyle
            onPatch({ style: s, kind: s === 'header' ? 'header' : s === 'glass' ? 'dialogue' : (box.kind === 'header' ? 'narration' : box.kind), ...(s === 'header' && !box.title ? { title: box.text } : {}) })
          }}>
            {(Object.keys(STYLE_LABEL) as TextStyle[]).map(s => <option key={s} value={s}>{STYLE_LABEL[s]}</option>)}
          </select>
        </Field>
        <Field label="Kind">
          <select className="select" value={box.kind} onChange={(e) => onPatch({ kind: e.target.value as TextKind })}>
            {(['narration', 'dialogue', 'header'] as TextKind[]).map(k => <option key={k}>{k}</option>)}
          </select>
        </Field>
      </div>
      <div className="grid grid-cols-[1fr_5rem] gap-2">
        <Field label="Font">
          <select className="select" value={box.font ?? ''} onChange={(e) => onPatch({ font: e.target.value || null })} style={{ fontFamily: box.font ?? undefined }}>
            <option value="">Style default</option>
            <optgroup label="House">{house.map(f => <option key={f.family} value={f.family}>{f.family}</option>)}</optgroup>
            <optgroup label="Library">{more.map(f => <option key={f.family} value={f.family}>{f.family}</option>)}</optgroup>
          </select>
        </Field>
        <Field label="Size px"><Commit type="number" className="font-mono" placeholder={String(placeholder)} value={box.size ? String(box.size) : ''} onCommit={(v) => onPatch({ size: v ? Number(v) : null })} /></Field>
      </div>
      <Field label="Align">
        <div className="flex gap-1">
          {([['left', AlignLeft], ['center', AlignCenter], ['right', AlignRight]] as [Align, typeof AlignLeft][]).map(([a, I]) => (
            <button key={a} className={cx('btn btn-sm btn-icon', box.align === a && 'btn-primary')} onClick={() => onPatch({ align: a })} title={a}><I size={12} /></button>
          ))}
          <span className="flex-1" />
          <button className="btn btn-sm" onClick={() => onPatch({ z: 'front' })} title="Bring to front"><ArrowUpToLine size={11} />Front</button>
          <button className="btn btn-sm" onClick={() => onPatch({ z: 'back' })} title="Send to back"><ArrowDownToLine size={11} />Back</button>
        </div>
      </Field>
      <Field label="Position and size (page px)"><NumRow fields={['x', 'y', 'w', 'h']} values={box as unknown as Record<string, number>} onCommit={(k, v) => onPatch({ [k]: v })} /></Field>
      {box.style === 'glass' && (
        <Field label="Tail" hint="drag the gold handle on the page toward the speaker">
          <div className="flex gap-2 items-center">
            {box.tail ? <>
              <span className="text-2xs font-mono text-ink-400">{box.tail[0]}, {box.tail[1]}</span>
              <button className="btn btn-sm" onClick={() => onPatch({ tail: null })}>Remove tail</button>
            </> : <button className="btn btn-sm" onClick={() => onPatch({ tail: [Math.round(box.x + box.w / 2), Math.round(box.y + box.h + 160)] })}><Plus size={11} />Add tail</button>}
          </div>
        </Field>
      )}
      <button className="btn btn-danger self-start" onClick={onDelete}><Trash2 size={12} />Delete text box</button>
    </div>
  )
}

export function ArtInspector({ page, book, onPatch, onReplace }: { page: BookPage; book: Book; onPatch: (p: Partial<Art>) => void; onReplace: (f: File) => void }) {
  const file = useRef<HTMLInputElement>(null)
  const a = page.art
  const focus = a?.focus ?? [0.5, 0.5]
  return (
    <div className="p-3 flex flex-col gap-3" data-testid="art-inspector">
      <div className="flex items-center gap-2"><ImageIcon size={13} className="text-sky-300" /><span className="text-xs font-medium text-ink-100">Art</span><span className="text-2xs font-mono text-ink-500 truncate">{a?.file ?? 'no painting'}</span></div>
      {page.art_url && <img src={page.art_url} alt="" className="w-full max-h-48 object-contain rounded border border-ink-700 bg-ink-900" />}
      <input ref={file} type="file" accept="image/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) onReplace(f); e.target.value = '' }} />
      <button className="btn btn-primary self-start" onClick={() => file.current?.click()}><ImageIcon size={12} />{a ? 'Replace painting…' : 'Add painting…'}</button>
      {a && <>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Fit">
            <select className="select" value={a.fit ?? 'cover'} onChange={(e) => onPatch({ fit: e.target.value as Art['fit'] })}>
              <option value="cover">Crop to fill (cover)</option><option value="contain">Whole image (contain)</option><option value="fill">Stretch (fill)</option>
            </select>
          </Field>
          <Field label="Edge">
            <label className="flex items-center gap-2 h-7 text-xs"><input type="checkbox" checked={a.torn !== false} onChange={(e) => onPatch({ torn: e.target.checked })} />Torn edge</label>
          </Field>
        </div>
        {(a.fit ?? 'cover') === 'cover' && (
          <Field label="Crop focus" hint="which part of the painting stays in the window">
            <div className="grid grid-cols-2 gap-2">
              <label className="text-2xs text-ink-400">horizontal<input type="range" min={0} max={1} step={0.05} defaultValue={focus[0]} key={`fx${page.rev}`} className="w-full" onMouseUp={(e) => onPatch({ focus: [Number((e.target as HTMLInputElement).value), focus[1]] })} /></label>
              <label className="text-2xs text-ink-400">vertical<input type="range" min={0} max={1} step={0.05} defaultValue={focus[1]} key={`fy${page.rev}`} className="w-full" onMouseUp={(e) => onPatch({ focus: [focus[0], Number((e.target as HTMLInputElement).value)] })} /></label>
            </div>
          </Field>
        )}
        <Field label="Window (page px)"><NumRow fields={['x', 'y', 'w', 'h']} values={a as unknown as Record<string, number>} onCommit={(k, v) => onPatch({ [k]: v })} /></Field>
        <button className="btn btn-sm self-start" onClick={() => onPatch({ x: book.frame.l, y: book.frame.t, w: book.page_px[0] - book.frame.l - book.frame.r, h: book.page_px[1] - book.frame.t - book.frame.b })}>Reset to the frame window</button>
      </>}
    </div>
  )
}

export function PaperInspector({ page, onPatch, onPageNumber }: { page: BookPage; onPatch: (p: { texture?: string; shloka_id?: string | null; figures?: Figure[] }) => void; onPageNumber: (v: boolean) => void }) {
  const { data: shlokas = [] } = useShlokas()
  const { data: figures = [] } = useFigures()
  const { data: textures = [] } = useTextures()
  const [q, setQ] = useState('')
  const list = useMemo(() => shlokas.filter(s => !q || `${s.source} ${s.meaning} ${s.tags.join(' ')} ${s.lines.join(' ')}`.toLowerCase().includes(q.toLowerCase())), [shlokas, q])
  const figs = page.paper.figures
  const setFig = (i: number, patch: Partial<Figure>) => onPatch({ figures: figs.map((f, k) => k === i ? { ...f, ...patch } : f) })
  return (
    <div className="p-3 flex flex-col gap-3" data-testid="paper-inspector">
      <div className="flex items-center gap-2"><ScrollText size={13} className="text-amber-300" /><span className="text-xs font-medium text-ink-100">Paper</span></div>
      <Field label="Texture">
        <div className="flex gap-1.5 flex-wrap">
          {textures.map(t => (
            <button key={t.name} onClick={() => onPatch({ texture: t.name })} title={t.name}
              className={cx('w-12 h-16 rounded border bg-cover bg-center', page.paper.texture === t.name ? 'border-gold-400 ring-1 ring-gold-400' : 'border-ink-600 hover:border-ink-400')} style={{ backgroundImage: `url(${t.url})` }} />
          ))}
        </div>
      </Field>
      <Field label="Shloka" hint={page.paper.shloka ? `on the page: ${page.paper.shloka.source}` : 'none on this page'}>
        <input className="input mb-1.5" placeholder="Search source, meaning, tag…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="max-h-72 overflow-auto flex flex-col gap-1 pr-1">
          <button className={cx('text-left rounded border px-2 py-1 text-2xs', !page.paper.shloka ? 'border-gold-500/60 bg-gold-500/10 text-gold-200' : 'border-ink-700 text-ink-400 hover:bg-ink-800')} onClick={() => onPatch({ shloka_id: null })}>No shloka</button>
          {list.map(s => (
            <button key={s.id} onClick={() => onPatch({ shloka_id: s.id })}
              className={cx('text-left rounded border px-2 py-1.5', page.paper.shloka?.id === s.id ? 'border-gold-500/60 bg-gold-500/10' : 'border-ink-700 hover:bg-ink-800')}>
              <div className="text-[0.8rem] leading-snug text-[#e9a08f]" lang="sa" style={{ fontFamily: "'Tiro Devanagari Hindi', 'Noto Serif Devanagari', serif" }}>{s.lines.map((l, i) => <div key={i}>{l}</div>)}</div>
              <div className="text-2xs text-ink-300 mt-0.5 italic">{s.source}</div>
              <div className="text-2xs text-ink-500 leading-snug">{s.meaning}</div>
            </button>
          ))}
        </div>
      </Field>
      <Field label={`Figures (${figs.length})`} hint="sepia line figures in the margins">
        <div className="flex flex-col gap-1.5">
          {figs.map((f, i) => (
            <div key={i} className="rounded border border-ink-700 p-1.5 flex flex-col gap-1">
              <div className="flex items-center gap-1.5">
                <select className="select h-6 text-2xs" value={f.name} onChange={(e) => setFig(i, { name: e.target.value })}>{figures.map(x => <option key={x.name}>{x.name}</option>)}</select>
                <label className="text-2xs text-ink-400 flex items-center gap-1 whitespace-nowrap"><input type="checkbox" checked={f.mirror} onChange={(e) => setFig(i, { mirror: e.target.checked })} />mirror</label>
                <button className="btn btn-ghost btn-sm btn-icon" title="Remove figure" onClick={() => onPatch({ figures: figs.filter((_, k) => k !== i) })}><Trash2 size={11} /></button>
              </div>
              <div className="grid grid-cols-4 gap-1">
                {(['x', 'y', 'h'] as const).map(k => <Commit key={k} type="number" className="h-6 text-2xs font-mono" value={String(Math.round(f[k]))} onCommit={(v) => setFig(i, { [k]: Number(v) })} />)}
                <Commit type="number" className="h-6 text-2xs font-mono" value={String(f.opacity)} onCommit={(v) => setFig(i, { opacity: Math.max(0, Math.min(1, Number(v))) })} />
              </div>
            </div>
          ))}
          <button className="btn btn-sm self-start" onClick={() => onPatch({ figures: [...figs, { name: figures[0]?.name ?? 'rama', x: 8, y: 1200, h: 420, opacity: 0.35, mirror: false }] })}><Plus size={11} />Add figure</button>
          <div className="text-2xs text-ink-500">x · y · height (page px) · opacity</div>
        </div>
      </Field>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={page.page_number} onChange={(e) => onPageNumber(e.target.checked)} />Print the page number</label>
    </div>
  )
}

export function PageHistory({ bid, page, onRestore }: { bid: string; page: BookPage; onRestore: (seq: number) => void }) {
  const { data: hist = [] } = usePageHistory(bid, page.id)
  return (
    <div className="p-3 border-t border-ink-800">
      <div className="label flex items-center gap-1.5 mb-1.5"><History size={11} />Page versions</div>
      {hist.length === 0 && <div className="text-2xs text-ink-500 italic">No edits yet.</div>}
      <div className="flex flex-col gap-0.5 max-h-48 overflow-auto">
        {hist.map(h => (
          <div key={h.seq} className="flex items-center gap-2 text-2xs">
            <span className="font-mono text-ink-500 w-10">v{h.seq}</span>
            <span className="flex-1 truncate text-ink-300">{h.action}</span>
            <span className="text-ink-500">{new Date(h.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            {h.kind === 'page' && <button className="btn btn-ghost btn-sm" title="Restore the page as it was before this change" onClick={() => onRestore(h.seq)}>before</button>}
          </div>
        ))}
      </div>
    </div>
  )
}

export function PatchInspector({ page, id, onPatch, onRemove, onComment }: { page: BookPage; id: string; onPatch: (hidden: boolean) => void; onRemove: () => void; onComment: () => void }) {
  const pa = page.art?.patches?.find(p => p.id === id)
  if (!pa) return null
  return (
    <div className="p-3 flex flex-col gap-3" data-testid="patch-inspector">
      <div className="flex items-center gap-2"><ImageIcon size={13} className="text-sky-300" /><span className="text-xs font-medium text-ink-100">Art patch</span><span className="text-2xs font-mono text-ink-500">{pa.id}</span></div>
      <div className="text-2xs text-ink-400">A parchment cover-up over a box the painter left empty in the art{pa.linked ? <> (under text box <span className="font-mono">{pa.linked}</span>)</> : ''}.</div>
      <div className="text-2xs font-mono text-ink-400">x {Math.round(pa.x)} · y {Math.round(pa.y)} · {Math.round(pa.w)} × {Math.round(pa.h)}</div>
      <div className="flex gap-2 flex-wrap">
        <button className="btn btn-sm" onClick={() => onPatch(!pa.hidden)}>{pa.hidden ? <Eye size={11} /> : <EyeOff size={11} />}{pa.hidden ? 'Show' : 'Hide'}</button>
        <button className="btn btn-sm btn-danger" onClick={onRemove}><Trash2 size={11} />Remove</button>
        <button className="btn btn-sm btn-primary" onClick={onComment} title="A comment on this patch: the engine repaints its area into the scene, then removes the patch">Repaint into the scene…</button>
      </div>
    </div>
  )
}
