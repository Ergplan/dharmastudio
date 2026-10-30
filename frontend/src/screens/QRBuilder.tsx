import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { QrCode, ShieldCheck, ShieldAlert, Download, Upload, MapPin, Trash2, Plus, Save } from 'lucide-react'
import { useChapters, usePages } from '@/api/hooks'
import {
  useQRs, useQROptions, useLinks, useCreateQR, useSaveQR, useDeleteQR, useTestQR, useApproveQR, usePlaceQR, useQRLive, uploadEmblem,
  type QRStyle, type QRLive, type QRRow,
} from '@/api/motion'
import { cx, Field, Empty, Spinner } from '@/components/ui'
import { useQueryClient } from '@tanstack/react-query'

const EMBLEM_LABEL: Record<string, string> = { none: 'None', chakra: 'Chakra', lotus: 'Lotus', om: 'ॐ', upload: 'Upload…' }

/** QR BUILDER: every code encodes a short URL; live preview at printed size on the parchment; decode test gate. */
export default function QRBuilder() {
  const { data: qrs = [], isLoading } = useQRs()
  const { data: opts } = useQROptions()
  const { data: links = [] } = useLinks()
  const [sp, setSp] = useSearchParams()
  const selId = Number(sp.get('q')) || null
  const sel = qrs.find(q => q.id === selId) ?? null
  const [linkId, setLinkId] = useState<number | null>(null)
  const [newCode, setNewCode] = useState('')
  const [style, setStyle] = useState<QRStyle | null>(null)
  const [live, setLive] = useState<QRLive | null>(null)
  const [printed, setPrinted] = useState(true)
  const liveM = useQRLive()
  const create = useCreateQR()
  const saveQ = useSaveQR()
  const del = useDeleteQR()
  const test = useTestQR()
  const approve = useApproveQR()
  const qc = useQueryClient()

  useEffect(() => { if (sel) { setStyle(sel.style); setLinkId(sel.link_id) } else if (opts && !style) setStyle(opts.defaults) }, [sel?.id, opts]) // eslint-disable-line react-hooks/exhaustive-deps
  const link = links.find(l => l.id === linkId) ?? null
  const code = link?.code ?? (newCode || null)
  const key = JSON.stringify([code, style])
  useEffect(() => {
    if (!code || !style) return
    const t = setTimeout(() => liveM.mutateAsync({ code, style, dpi: 220 }).then(setLive).catch(() => {}), 220)
    return () => clearTimeout(t)
  }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  if (isLoading || !opts || !style) return <Spinner />
  const S = (patch: Partial<QRStyle>) => setStyle(s => ({ ...(s as QRStyle), ...patch }))
  const dirty = sel && (JSON.stringify(sel.style) !== JSON.stringify(style) || sel.link_id !== linkId)
  const tooSmall = style.size_mm < opts.min_mm

  const saveNew = () => {
    const body = link ? { link_id: link.id, style } : { target_type: 'url', target_ref: 'https://cycleofdharma.world/', code: newCode, style }
    create.mutate(body, { onSuccess: q => setSp({ tab: 'qr', q: String(q.id) }) })
  }
  return (
    <div className="h-full flex min-h-0">
      <aside className="w-60 shrink-0 border-r border-ink-800 flex flex-col min-h-0">
        <div className="panel-h justify-between"><span>Saved QRs</span><button className="btn btn-sm" onClick={() => { setSp({ tab: 'qr' }); setStyle(opts.defaults) }}><Plus size={11} />New</button></div>
        <div className="flex-1 overflow-auto">
          {qrs.length === 0 && <Empty>No saved QRs.</Empty>}
          {qrs.map(q => (
            <button key={q.id} onClick={() => setSp({ tab: 'qr', q: String(q.id) })} className={cx('w-full flex gap-2 items-center p-2 border-b border-ink-850 text-left hover:bg-ink-850', q.id === selId && 'bg-ink-850')}>
              <img src={`${q.preview_url}?dpi=96&v=${encodeURIComponent(JSON.stringify(q.style))}`} className="w-10 h-12 object-contain bg-parchment-400 rounded-sm" alt="" />
              <div className="min-w-0 text-xs">
                <div className="font-mono text-ink-100 truncate">/v/{q.code}</div>
                <div className="text-2xs text-ink-400">{q.style.size_mm} mm · {q.style.module} · {EMBLEM_LABEL[q.style.emblem]}</div>
                {q.tested ? <span className="text-2xs text-emerald-300">✓ tested</span> : <span className="text-2xs text-red-300">untested</span>}
              </div>
            </button>
          ))}
        </div>
      </aside>

      <div className="w-[22rem] shrink-0 border-r border-ink-800 overflow-auto p-4 flex flex-col gap-3 text-xs">
        <Field label="Short link (every QR encodes one)">
          <select className="select" value={linkId ?? ''} onChange={e => setLinkId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">— create a link inline —</option>
            {links.map(l => <option key={l.id} value={l.id}>/v/{l.code} {l.title ? `· ${l.title}` : ''}{l.print_locked ? ' · printed' : ''}</option>)}
          </select>
        </Field>
        {!link && <Field label="New code" hint={<span className="normal-case text-ink-500">a–z 0–9 -; points at the landing page until you retarget it in Links</span>}><input className="input font-mono" value={newCode} onChange={e => setNewCode(e.target.value.toLowerCase())} placeholder="e.g. 1-9" /></Field>}
        <Field label="Colour">
          <div className="flex gap-1.5">
            {opts.colours.map(c => <button key={c.id} className={cx('btn btn-sm flex-1', style.colour === c.hex && 'btn-primary')} onClick={() => S({ colour: c.hex })}><span className="w-3 h-3 rounded-sm border border-ink-500" style={{ background: c.hex }} />{c.label}</button>)}
            <input type="color" className="w-9 h-7 bg-transparent" value={style.colour} onChange={e => S({ colour: e.target.value })} title="Custom / the volume canvas ink" />
          </div>
        </Field>
        <Field label="Modules"><div className="flex gap-1.5">{opts.modules.map(m => <button key={m} className={cx('btn btn-sm flex-1 capitalize', style.module === m && 'btn-primary')} onClick={() => S({ module: m as QRStyle['module'] })}>{m}</button>)}</div></Field>
        <Field label="Centre emblem" hint={<span className="normal-case text-ink-500">≤ {Math.round(opts.max_emblem_area * 100)} % of the area</span>}>
          <div className="flex gap-1.5">{opts.emblems.map(e => <button key={e} className={cx('btn btn-sm flex-1', style.emblem === e && 'btn-primary', e === 'om' && 'font-book')} disabled={e === 'upload' && !sel} title={e === 'upload' && !sel ? 'Save the QR first' : undefined} onClick={() => S({ emblem: e as QRStyle['emblem'] })}>{EMBLEM_LABEL[e]}</button>)}</div>
        </Field>
        {style.emblem === 'upload' && sel && <label className="btn cursor-pointer"><Upload size={12} />{sel.has_emblem_upload ? 'Replace emblem (SVG/PNG)' : 'Upload emblem (SVG/PNG)'}<input type="file" accept=".svg,.png,image/png,image/svg+xml" className="hidden" onChange={async e => { const f = e.target.files?.[0]; if (f) { await uploadEmblem(sel.id, f); qc.invalidateQueries() } }} /></label>}
        {style.emblem !== 'none' && <Field label={`Emblem size ${Math.round(style.emblem_scale * 100)} % of the side`}><input type="range" min={0.1} max={Math.sqrt(opts.max_emblem_area)} step={0.01} value={style.emblem_scale} onChange={e => S({ emblem_scale: Number(e.target.value) })} className="accent-gold-500" /></Field>}
        <div className="grid grid-cols-2 gap-2">
          <Field label="Error correction"><select className="select" value={style.ec} onChange={e => S({ ec: e.target.value as QRStyle['ec'] })}>{opts.ec_levels.map(l => <option key={l} value={l}>{l}{l === 'H' ? ' (30 %, default)' : ''}</option>)}</select></Field>
          <Field label="Quiet zone (modules)"><input type="number" min={4} className="input" value={style.quiet} onChange={e => S({ quiet: Math.max(4, Number(e.target.value)) })} /></Field>
          <Field label="Label"><select className="select" value={style.label} onChange={e => S({ label: e.target.value as QRStyle['label'] })}><option value="en">EN — {opts.labels.en}</option><option value="hi">HI — {opts.labels.hi}</option><option value="none">none</option></select></Field>
          <Field label={`Size (mm, min ${opts.min_mm})`}><input type="number" min={opts.min_mm} step={1} className={cx('input', tooSmall && 'border-red-500')} value={style.size_mm} onChange={e => S({ size_mm: Number(e.target.value) })} /></Field>
        </div>
        <label className="flex items-center gap-2"><input type="checkbox" className="accent-gold-500" checked={style.show_url} onChange={e => S({ show_url: e.target.checked })} />print the short URL beneath</label>
        {tooSmall && <div className="text-red-300">A printed QR must be at least {opts.min_mm} mm wide.</div>}
        <div className="flex gap-1.5 flex-wrap mt-1">
          {sel ? <button className="btn btn-primary" disabled={!dirty || tooSmall} onClick={() => saveQ.mutate({ id: sel.id, style, link_id: linkId ?? undefined })}><Save size={12} />Save</button>
            : <button className="btn btn-primary" disabled={(!link && !newCode) || tooSmall || create.isPending} onClick={saveNew}><Save size={12} />Save QR</button>}
          {sel && <button className="btn" disabled={!!dirty || test.isPending} onClick={() => test.mutate(sel.id)}><QrCode size={12} />{test.isPending ? 'Testing…' : 'Decode test'}</button>}
          {sel && <button className="btn" disabled={!sel.tested || sel.approved} onClick={() => approve.mutate(sel.id)}>Approve</button>}
          {sel && sel.placements.length === 0 && <button className="btn btn-ghost btn-icon" title="Delete" onClick={() => del.mutate(sel.id, { onSuccess: () => setSp({ tab: 'qr' }) })}><Trash2 size={12} /></button>}
        </div>
      </div>

      <div className="flex-1 min-w-0 overflow-auto p-4 flex flex-col gap-4">
        <div className="flex items-center gap-2 text-xs">
          <span className="label">Preview</span>
          <label className="flex items-center gap-1.5"><input type="checkbox" className="accent-gold-500" checked={printed} onChange={e => setPrinted(e.target.checked)} />at printed size (CSS mm)</label>
          {live && <span className="font-mono text-2xs text-ink-400">{live.width_mm.toFixed(1)} × {live.height_mm.toFixed(1)} mm · {live.url}</span>}
        </div>
        <div className="rounded-md p-8 grid place-items-center min-h-[18rem]" style={{ background: 'url(/api/textures/page_warm.jpg) center/cover, #efe4c9' }}>
          {live ? <img src={live.png} alt={live.url} style={printed ? { width: `${live.width_mm}mm` } : { width: '18rem' }} className={cx(liveM.isPending && 'opacity-70')} /> : <span className="text-sepia text-xs">Pick a link or type a code</span>}
        </div>
        {sel && <TestPanel q={sel} dirty={!!dirty} />}
        {sel && <ExportPlace q={sel} />}
      </div>
    </div>
  )
}

function TestPanel({ q, dirty }: { q: QRRow; dirty: boolean }) {
  const t = q.test
  return (
    <div className={cx('card p-3 text-xs flex gap-3 items-start', q.tested ? 'border-emerald-500/40' : 'border-red-500/40')}>
      {q.tested ? <ShieldCheck size={20} className="text-emerald-400 shrink-0" /> : <ShieldAlert size={20} className="text-red-400 shrink-0" />}
      <div className="flex-1">
        <div className={cx('font-medium', q.tested ? 'text-emerald-300' : 'text-red-300')}>{q.tested ? 'PASS — decodes to the exact short URL' : dirty ? 'Unsaved changes — save, then test' : t && !t.ok ? 'FAIL — this QR cannot be placed or approved' : 'Not tested for this link and style'}</div>
        <div className="text-ink-400 mt-0.5">Rasterised at {q.style.size_mm} mm on the parchment, read back with zxing-cpp.</div>
        {t && <div className="mt-1.5 grid grid-cols-2 gap-2 font-mono text-2xs">{Object.entries(t.dpis).map(([dpi, r]) => <div key={dpi} className={cx('rounded border px-2 py-1', r.ok ? 'border-emerald-500/40 text-emerald-200' : 'border-red-500/40 text-red-200')}>{dpi} dpi · {r.px.join('×')} px · {r.ok ? '✓' : '✗'} {r.read ?? 'no read'}</div>)}</div>}
      </div>
    </div>
  )
}

function ExportPlace({ q }: { q: QRRow }) {
  const { data: chapters = [] } = useChapters()
  const [ch, setCh] = useState<number>(chapters[0]?.id ?? 1)
  const { data: pages = [] } = usePages(ch)
  const [pageId, setPageId] = useState<number | ''>('')
  const place = usePlaceQR()
  const pageNo = useMemo(() => Object.fromEntries(pages.map(p => [p.id, p.number])), [pages])
  return (
    <div className="card p-3 text-xs flex flex-col gap-3">
      <div className="flex gap-1.5 items-center">
        <span className="label w-20">Export</span>
        {(['svg', 'png', 'pdf'] as const).map(f => <a key={f} className="btn btn-sm" href={`/api/qr/${q.id}/export.${f}`} download><Download size={11} />{f.toUpperCase()}{f === 'png' ? ' 600 dpi' : ''}</a>)}
      </div>
      <div className="flex gap-1.5 items-center">
        <span className="label w-20">Place on page…</span>
        <select className="select w-24" value={ch} onChange={e => setCh(Number(e.target.value))}>{chapters.map(c => <option key={c.id} value={c.id}>ch {c.number}</option>)}</select>
        <select className="select w-28" value={pageId} onChange={e => setPageId(e.target.value ? Number(e.target.value) : '')}><option value="">page…</option>{pages.map(p => <option key={p.id} value={p.id}>page {p.number}</option>)}</select>
        <button className="btn btn-sm btn-primary" disabled={!pageId || !q.tested} title={q.tested ? 'Drops it into free parchment (lower outer corner preferred)' : 'Pass the decode test first'} onClick={() => pageId && place.mutate({ id: q.id, page_id: pageId })}><MapPin size={11} />Place</button>
      </div>
      {q.placements.length > 0 && <div className="text-ink-400">Placed: {q.placements.map(p => `page ${pageNo[p.page_id] ?? `#${p.page_id}`} at ${p.x_mm.toFixed(0)},${p.y_mm.toFixed(0)} mm (${p.w_mm} mm)`).join(' · ')}{q.link_locked && ' · printed: code locked'}</div>}
    </div>
  )
}
