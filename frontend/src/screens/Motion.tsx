import { useEffect, useMemo, useRef, useState } from 'react'
import { Link as NavLink, useSearchParams } from 'react-router-dom'
import { Film, Play, Check, Globe, Upload, Trash2, GripVertical, Plus, QrCode, Link2, Clapperboard, Download, KeyRound, ExternalLink, Copy, Music } from 'lucide-react'
import { usePages, useChapters } from '@/api/hooks'
import { mediaUrl } from '@/api/client'
import type { Page, Panel } from '@/api/types'
import {
  useMoments, useMoment, useMotionOptions, useMotionHealth, useCreateMoment, useSaveMoment, useRenderMoment, useApproveMoment, usePublishMoment,
  useUnpublishMoment, useMomentQR, useTakes, useQRs, uploadMusic, useSite, useSiteSettings, useSitePreview, useSitePublish, useSiteExport, useSiteSecret,
  type Moment, type Shot, type MomentStatus,
} from '@/api/motion'
import { cx, Field, JobProgress, Empty, Spinner, StatusDot } from '@/components/ui'
import { useToasts } from '@/store/toasts'
import { useQueryClient } from '@tanstack/react-query'
import QRBuilder from './QRBuilder'
import { KeysModal } from './Project'
import LinksScreen from './Links'
import SeedanceScreen from './Seedance'

const TABS = [
  { id: 'moments', label: 'Moments', icon: Film },
  { id: 'seedance', label: 'Seedance', icon: Clapperboard },
  { id: 'qr', label: 'QR', icon: QrCode },
  { id: 'links', label: 'Links', icon: Link2 },
  { id: 'site', label: 'Site', icon: Globe },
]

export const MOMENT_TONE: Record<MomentStatus, string> = {
  draft: 'bg-ink-600/60 text-ink-200 border-ink-500',
  rendering: 'bg-sky-500/15 text-sky-300 border-sky-500/40',
  review: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  approved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  published: 'bg-gold-500/15 text-gold-300 border-gold-500/50',
}
export function MomentBadge({ status }: { status: MomentStatus }) {
  return <span className={cx('inline-flex items-center h-4 px-1.5 rounded-sm border text-2xs uppercase tracking-wide font-medium', MOMENT_TONE[status])}>{status}</span>
}

/** Motion & Links: one rail entry, five tabs. */
export default function MotionScreen() {
  const [sp] = useSearchParams()
  const tab = sp.get('tab') || 'moments'
  const health = useMotionHealth().data
  return (
    <div className="h-full flex flex-col">
      <div className="h-9 shrink-0 border-b border-ink-800 bg-ink-900 flex items-center gap-1 px-2">
        {TABS.map(t => (
          <NavLink key={t.id} to={`/motion?tab=${t.id}`} className={cx('h-7 px-3 rounded flex items-center gap-1.5 text-xs', tab === t.id ? 'bg-ink-800 text-gold-300' : 'text-ink-400 hover:text-ink-100')}>
            <t.icon size={13} />{t.label}
          </NavLink>
        ))}
        <div className="flex-1" />
        {health && <span className="flex items-center gap-1.5 text-2xs text-ink-400" title={health.ffmpeg.version ?? health.ffmpeg.error}>
          <StatusDot tone={health.ffmpeg.ok ? 'ok' : 'bad'} />ffmpeg <StatusDot tone={health.zxing ? 'ok' : 'bad'} />QR decoder
          <StatusDot tone={health.keys.fal || health.keys.byteplus ? 'ok' : 'idle'} />Seedance {health.keys.fal || health.keys.byteplus ? '' : '(dry run)'}
          <StatusDot tone={health.keys.elevenlabs ? 'ok' : 'idle'} />voice
        </span>}
      </div>
      <div className="flex-1 min-h-0">
        {tab === 'moments' && <MomentsTab />}
        {tab === 'seedance' && <SeedanceScreen />}
        {tab === 'qr' && <QRBuilder />}
        {tab === 'links' && <LinksScreen />}
        {tab === 'site' && <SiteTab />}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------
// moments
// ---------------------------------------------------------------------------------

function MomentsTab() {
  const { data: moments = [], isLoading } = useMoments()
  const [sp, setSp] = useSearchParams()
  const sel = Number(sp.get('m')) || moments[0]?.id || null
  const { data: chapters = [] } = useChapters()
  const [chapterId, setChapterId] = useState(1)
  const { data: pages = [] } = usePages(chapterId)
  const create = useCreateMoment()
  const free = pages.filter(p => !moments.some(m => m.page_id === p.id))
  const [newPage, setNewPage] = useState<number | ''>('')
  return (
    <div className="h-full flex">
      <aside className="w-64 shrink-0 border-r border-ink-800 flex flex-col min-h-0">
        <div className="panel-h">Moments <span className="text-ink-500 font-normal">— a page with a 30 s film</span></div>
        <div className="p-2 border-b border-ink-800 flex flex-col gap-1.5">
          <div className="flex gap-1.5">
            <select className="select w-20" value={chapterId} onChange={e => setChapterId(Number(e.target.value))}>{chapters.map(c => <option key={c.id} value={c.id}>ch {c.number}</option>)}</select>
            <select className="select flex-1" value={newPage} onChange={e => setNewPage(e.target.value ? Number(e.target.value) : '')}>
              <option value="">page…</option>{free.map(p => <option key={p.id} value={p.id}>page {p.number}</option>)}
            </select>
            <button className="btn btn-primary btn-icon" disabled={!newPage || create.isPending} title="Make this page a QR moment"
              onClick={() => newPage && create.mutate({ page_id: newPage }, { onSuccess: (m) => { setSp({ tab: 'moments', m: String(m.id) }); setNewPage('') } })}><Plus size={13} /></button>
          </div>
        </div>
        <div className="flex-1 overflow-auto">
          {isLoading && <Spinner />}
          {!isLoading && moments.length === 0 && <Empty>No moments yet. Pick a page above, or use “Make this page a QR moment” in Pages.</Empty>}
          {moments.map(m => (
            <button key={m.id} onClick={() => setSp({ tab: 'moments', m: String(m.id) })} className={cx('w-full text-left flex gap-2 p-2 border-b border-ink-850 hover:bg-ink-850', sel === m.id && 'bg-ink-850')}>
              <div className="w-20 h-[2.8rem] rounded bg-ink-800 overflow-hidden shrink-0">{(m.outputs.poster || m.shots[0]?.thumb) && <img src={mediaUrl(m.outputs.poster || m.shots[0]?.thumb)} className="w-full h-full object-cover" alt="" />}</div>
              <div className="min-w-0 flex-1">
                <div className="text-xs text-ink-100 truncate">{m.title_en || `Page ${m.page}`}</div>
                <div className="text-2xs text-ink-400 font-mono">/v/{m.code} · p{m.page}</div>
                <MomentBadge status={m.status} />
              </div>
            </button>
          ))}
        </div>
      </aside>
      <div className="flex-1 min-w-0">{sel ? <MomentEditor id={sel} /> : <Empty>Select a moment.</Empty>}</div>
    </div>
  )
}

const SIZE_LABEL: Record<string, string> = { full: 'Full (1080p)', preview: 'Preview (540p)' }

function MomentEditor({ id }: { id: number }) {
  const { data: m } = useMoment(id)
  const { data: opts } = useMotionOptions()
  const { data: pages = [] } = usePages(m?.chapter_id ?? null)
  const save = useSaveMoment()
  const render = useRenderMoment()
  const approve = useApproveMoment()
  const publish = usePublishMoment()
  const unpublish = useUnpublishMoment()
  const mqr = useMomentQR()
  const push = useToasts(s => s.push)
  const qc = useQueryClient()
  const [jobId, setJobId] = useState<number | null>(null)
  const [pubJob, setPubJob] = useState<number | null>(null)
  const [size, setSize] = useState('full')
  const [draft, setDraft] = useState<Partial<Moment>>({})
  useEffect(() => { setDraft({}) }, [id])
  if (!m || !opts) return <Spinner />
  const page = pages.find(p => p.id === m.page_id)
  const v = { ...m, ...draft } as Moment
  const dirty = Object.keys(draft).length > 0
  const set = (k: keyof Moment, val: unknown) => setDraft(d => ({ ...d, [k]: val }))
  const commit = () => save.mutate({ id: m.id, ...draft }, { onSuccess: () => setDraft({}) })
  const shots = v.shots
  const setShots = (s: Shot[]) => set('shots', s.map(({ thumb: _t, ...x }) => x))
  return (
    <div className="h-full flex min-h-0">
      <div className="flex-1 min-w-0 overflow-auto p-4 flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <Film size={16} className="text-gold-400" />
          <div className="min-w-0">
            <div className="text-sm text-ink-100">{v.title_en} <span className="text-ink-500">· Book {m.volume}, page {m.page}</span></div>
            <div className="text-2xs font-mono text-ink-400">{m.short_url} {m.link_locked && <span className="chip ml-1 border-amber-500/50 text-amber-300">printed · code locked</span>}</div>
          </div>
          <MomentBadge status={m.status} />
          <div className="flex-1" />
          {dirty && <button className="btn btn-primary" onClick={commit} disabled={save.isPending}>Save</button>}
        </div>

        <section>
          <div className="label mb-1.5">Shots <span className="normal-case text-ink-500">— drag to reorder; each 5–10 s; scaled so the film is exactly 30 s</span></div>
          <ShotList shots={shots} page={page} setShots={setShots} moves={opts.moves} />
          <TimeBar m={v} />
        </section>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Title (EN)"><input className="input" value={v.title_en} onChange={e => set('title_en', e.target.value)} /></Field>
          <Field label="शीर्षक (HI)"><input className="input font-book" lang="hi" value={v.title_hi} onChange={e => set('title_hi', e.target.value)} /></Field>
          <Field label="Narration / captions (EN)" hint={<span className="text-ink-500 normal-case">default: the page's captions</span>}><textarea className="textarea h-28" value={v.narration_en} onChange={e => set('narration_en', e.target.value)} /></Field>
          <Field label="कथन / उपशीर्षक (HI)"><textarea className="textarea h-28 font-book" lang="hi" value={v.narration_hi} onChange={e => set('narration_hi', e.target.value)} /></Field>
        </div>
        <div className="grid grid-cols-3 gap-3 items-end">
          <Field label="Voice">
            <select className="select" value={v.voice} onChange={e => set('voice', e.target.value)}>
              <option value="none">none — captions only</option>
              <option value="elevenlabs" disabled={!opts.voice.elevenlabs}>ElevenLabs {opts.voice.elevenlabs ? '' : '(no key)'}</option>
            </select>
          </Field>
          <Field label="Voice id"><input className="input font-mono" placeholder={opts.voice.default_voice_id} value={v.voice_id} onChange={e => set('voice_id', e.target.value)} disabled={v.voice !== 'elevenlabs'} /></Field>
          <Field label="Music (ducked −14 dB under narration)">
            <div className="flex gap-1.5 items-center">
              <label className="btn flex-1 cursor-pointer"><Music size={12} />{m.music_path ? m.music_path.split('/').pop() : 'Upload…'}
                <input type="file" accept="audio/*" className="hidden" onChange={async e => { const f = e.target.files?.[0]; if (f) { await uploadMusic(m.id, f); qc.invalidateQueries() } }} /></label>
              {m.music_path && <button className="btn btn-icon" title="Remove music" onClick={() => save.mutate({ id: m.id, music_path: '' })}><Trash2 size={12} /></button>}
            </div>
          </Field>
        </div>

        <section className="flex items-center gap-2 flex-wrap">
          <select className="select w-40" value={size} onChange={e => setSize(e.target.value)}>{Object.entries(SIZE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
          <button className="btn btn-primary" disabled={render.isPending || m.status === 'rendering' || dirty} title={dirty ? 'Save first' : 'EN + HI × 16:9 + 9:16 + poster'}
            onClick={() => render.mutate({ id: m.id, size }, { onSuccess: r => setJobId(r.job_id) })}><Play size={12} />Render</button>
          <button className="btn" disabled={!(m.status === 'review') || approve.isPending} onClick={() => approve.mutate(m.id)}><Check size={12} />Approve</button>
          <button className="btn" disabled={!(m.status === 'approved' || m.status === 'published') || publish.isPending}
            title={!m.qr_tested && m.qr_id ? 'The QR must pass the decode test first' : 'Rebuild the site; publish to Vercel Blob when configured'}
            onClick={() => publish.mutate({ id: m.id, deploy: true }, { onSuccess: r => { setPubJob(r.job_id); push({ kind: 'ok', title: 'Published', message: `${m.short_url}` }) } })}><Globe size={12} />Publish</button>
          {m.status === 'published' && <button className="btn btn-ghost" onClick={() => unpublish.mutate(m.id)}>Unpublish</button>}
        </section>
        {jobId && <JobProgress jobId={jobId} />}
        {pubJob && <JobProgress jobId={pubJob} compact />}
      </div>

      <aside className="w-[24rem] shrink-0 border-l border-ink-800 overflow-auto flex flex-col">
        <div className="panel-h">Film</div>
        <Player m={m} />
        <div className="panel-h">QR</div>
        <div className="p-3 flex flex-col gap-2">
          {m.qr_id ? <QRCard qrId={m.qr_id} /> : <div className="text-xs text-ink-400">No QR yet for <span className="font-mono">/v/{m.code}</span>.</div>}
          <div className="flex gap-1.5 flex-wrap">
            <button className="btn btn-sm" onClick={() => mqr.mutate({ id: m.id, test: true })}><QrCode size={12} />{m.qr_id ? 'Re-test' : 'Make + test QR'}</button>
            <button className="btn btn-sm" disabled={!m.qr_id || !m.qr_tested} title={m.qr_tested ? 'Place in the lower outer corner of free parchment' : 'Test first'} onClick={() => mqr.mutate({ id: m.id, place: true, test: false })}>Place on page {m.page}</button>
            {m.qr_id && <NavLink className="btn btn-sm btn-ghost" to={`/motion?tab=qr&q=${m.qr_id}`}>Style…</NavLink>}
          </div>
        </div>
      </aside>
    </div>
  )
}

function ShotList({ shots, page, setShots, moves }: { shots: Shot[]; page?: Page; setShots: (s: Shot[]) => void; moves: { id: string; label: string }[] }) {
  const drag = useRef<number | null>(null)
  const panels = (page?.panels ?? []).filter(p => p.selected_candidate_id)
  const { data: takes = [] } = useTakes(null)
  const done = takes.filter(t => t.status === 'done' && (!page || page.panels?.some(p => p.id === t.panel_id)))
  const thumbOf = (s: Shot) => s.thumb ?? (s.panel_id ? panelThumb(panels.find(p => p.id === s.panel_id)) : null)
  const move = (from: number, to: number) => { const a = [...shots]; const [x] = a.splice(from, 1); a.splice(to, 0, x); setShots(a) }
  const upd = (i: number, patch: Partial<Shot>) => setShots(shots.map((s, k) => k === i ? { ...s, ...patch } : s))
  const [adding, setAdding] = useState(false)
  return (
    <div className="flex gap-2 overflow-x-auto pb-2">
      {shots.map((s, i) => (
        <div key={i} draggable onDragStart={() => { drag.current = i }} onDragOver={e => e.preventDefault()} onDrop={() => { if (drag.current !== null && drag.current !== i) move(drag.current, i); drag.current = null }}
          className="w-44 shrink-0 card p-1.5 flex flex-col gap-1.5" data-testid="shot">
          <div className="relative h-24 rounded bg-ink-800 overflow-hidden">
            {thumbOf(s) && <img src={mediaUrl(thumbOf(s))} className="w-full h-full object-cover" alt="" />}
            <span className="absolute top-1 left-1 chip bg-ink-950/80">{i + 1} · {s.source === 'seedance' ? `Seedance #${s.take_id}` : 'Ken Burns'}</span>
            <GripVertical size={14} className="absolute top-1 right-1 text-ink-200 cursor-grab" />
          </div>
          <select className="select" value={s.move} disabled={s.source === 'seedance'} onChange={e => upd(i, { move: e.target.value })}>{moves.map(mv => <option key={mv.id} value={mv.id}>{mv.label}</option>)}</select>
          <div className="flex items-center gap-1.5 text-2xs">
            <input type="range" min={5} max={10} step={0.5} value={s.duration_s} onChange={e => upd(i, { duration_s: Number(e.target.value) })} className="flex-1 accent-gold-500" />
            <span className="font-mono w-8 text-right">{s.duration_s}s</span>
            <button className="btn btn-sm btn-icon btn-ghost" title="Remove" onClick={() => setShots(shots.filter((_, k) => k !== i))}><Trash2 size={11} /></button>
          </div>
        </div>
      ))}
      <div className="w-44 shrink-0 card p-2 flex flex-col gap-1.5">
        <button className="btn btn-sm" onClick={() => setAdding(a => !a)}><Plus size={12} />Add shot</button>
        {adding && (
          <div className="flex flex-col gap-1 max-h-40 overflow-auto">
            {panels.map(p => <button key={p.id} className="btn btn-sm justify-start" onClick={() => { setShots([...shots, { panel_id: p.id, source: 'kenburns', duration_s: 6, move: 'push_in' }]); setAdding(false) }}>Panel {p.n}</button>)}
            {done.map(t => <button key={t.id} className="btn btn-sm justify-start" onClick={() => { setShots([...shots, { take_id: t.id, panel_id: t.panel_id ?? undefined, source: 'seedance', duration_s: Math.min(10, Math.max(5, t.params.duration)), move: 'push_in' }]); setAdding(false) }}>Take #{t.id}{t.dry_run ? ' (dry)' : ''}</button>)}
          </div>
        )}
      </div>
    </div>
  )
}

function panelThumb(p?: Panel): string | null {
  if (!p) return null
  const c = p.candidates.find(x => x.id === p.selected_candidate_id)
  return c ? c.path : null
}

/** The 30 s bar: title card, shots (scaled), end card. */
function TimeBar({ m }: { m: Moment }) {
  const want = m.shots.reduce((a, s) => a + Number(s.duration_s || 0), 0)
  const k = m.shots.length + 2
  const avail = 30 - 1.5 - 2 + (k - 1) * 0.5
  const scale = want ? avail / want : 0
  const segs = [{ label: 'title', s: 1.5, cls: 'bg-parchment-500/70 text-sepia' }, ...m.shots.map((s, i) => ({ label: `${i + 1}`, s: s.duration_s * scale, cls: s.source === 'seedance' ? 'bg-sky-600/70' : 'bg-gold-500/60 text-ink-950' })), { label: 'end', s: 2, cls: 'bg-parchment-500/70 text-sepia' }]
  const total = segs.reduce((a, x) => a + x.s, 0)
  return (
    <div className="mt-2">
      <div className="flex h-6 rounded overflow-hidden border border-ink-700 text-2xs">
        {segs.map((x, i) => <div key={i} className={cx('flex items-center justify-center border-r border-ink-950/40 truncate', x.cls)} style={{ width: `${(x.s / total) * 100}%` }} title={`${x.s.toFixed(1)} s`}>{x.label} {x.s.toFixed(1)}s</div>)}
      </div>
      <div className="flex justify-between text-2xs text-ink-400 font-mono mt-1"><span>shots {want.toFixed(1)} s → scaled ×{scale.toFixed(2)}</span><span>12-frame crossfades · total 30.0 s</span></div>
    </div>
  )
}

function Player({ m }: { m: Moment }) {
  const [lang, setLang] = useState<'en' | 'hi'>('en')
  const [aspect, setAspect] = useState<'16x9' | '9x16'>('16x9')
  const key = `${lang}_${aspect}` as const
  const src = m.outputs[key]
  const meta = m.render_meta.variants?.[key]
  return (
    <div className="p-3 flex flex-col gap-2">
      <div className="flex gap-1.5">
        {(['en', 'hi'] as const).map(l => <button key={l} className={cx('btn btn-sm flex-1', lang === l && 'btn-primary')} onClick={() => setLang(l)}>{l === 'en' ? 'EN' : 'हिंदी'}</button>)}
        {(['16x9', '9x16'] as const).map(a => <button key={a} className={cx('btn btn-sm flex-1', aspect === a && 'btn-primary')} onClick={() => setAspect(a)}>{a.replace('x', ':')}</button>)}
      </div>
      <div className={cx('rounded bg-black overflow-hidden mx-auto', aspect === '16x9' ? 'w-full aspect-video' : 'h-[26rem] aspect-[9/16]')}>
        {src ? <video key={src} src={mediaUrl(src)} poster={mediaUrl(m.outputs.poster)} controls playsInline className="w-full h-full" /> : <div className="h-full grid place-items-center text-xs text-ink-500">Not rendered yet</div>}
      </div>
      {meta && <div className="text-2xs font-mono text-ink-400">{meta.width}×{meta.height} · {meta.duration.toFixed(2)} s · {(meta.bytes / 1e6).toFixed(1)} MB</div>}
    </div>
  )
}

export function QRCard({ qrId }: { qrId: number }) {
  const { data: qrs = [] } = useQRs()
  const q = qrs.find(x => x.id === qrId)
  const [printed, setPrinted] = useState(false)
  if (!q) return null
  return (
    <div className="flex gap-3 items-start">
      <div className="rounded bg-parchment-400 p-1 shrink-0" style={printed ? { width: `${q.width_mm + 2}mm` } : { width: '7rem' }}>
        <img src={`${q.preview_url}?v=${encodeURIComponent(JSON.stringify(q.style))}`} alt={q.url} className="w-full" />
      </div>
      <div className="text-xs flex flex-col gap-1 min-w-0">
        <span className={cx('chip w-fit', q.tested ? 'border-emerald-500/50 text-emerald-300' : 'border-red-500/50 text-red-300')}>{q.tested ? 'decodes ✓ 300 + 150 dpi' : 'not tested'}</span>
        <span className="font-mono text-2xs text-ink-300 truncate">{q.url}</span>
        <span className="text-2xs text-ink-400">{q.style.size_mm} mm · {q.style.module} · {q.style.emblem}</span>
        <label className="flex items-center gap-1.5 text-2xs text-ink-400"><input type="checkbox" className="accent-gold-500" checked={printed} onChange={e => setPrinted(e.target.checked)} />printed size (mm on screen)</label>
        <span className="text-2xs text-ink-500">{q.placements.length ? `on page id ${q.placements.map(p => p.page_id).join(', ')}` : 'not placed'}</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------
// site
// ---------------------------------------------------------------------------------

function SiteTab() {
  const { data: s } = useSite()
  const save = useSiteSettings()
  const preview = useSitePreview()
  const publish = useSitePublish()
  const exp = useSiteExport()
  const secret = useSiteSecret()
  const push = useToasts(x => x.push)
  const [jobId, setJobId] = useState<number | null>(null)
  const [siteUrl, setSiteUrl] = useState('')
  const [mediaBase, setMediaBase] = useState('')
  const [shown, setShown] = useState<string | null>(null)
  const [keys, setKeys] = useState(false)
  useEffect(() => { if (s) { setSiteUrl(s.site_url); setMediaBase(s.media_base ?? '') } }, [s?.site_url, s?.media_base]) // eslint-disable-line react-hooks/exhaustive-deps
  const done = useMemo(() => new Set<string>([...(s?.blob_token ? ['blob'] : []), ...(s?.manifest_url ? ['publish'] : [])]), [s])
  if (!s) return <Spinner />
  return (
    <div className="h-full overflow-auto p-4 grid grid-cols-[1fr_24rem] gap-4 items-start">
      {keys && <KeysModal onClose={() => setKeys(false)} />}
      <div className="flex flex-col gap-4">
        <div className="card">
          <div className="panel-h justify-between"><span>cycleofdharma.world</span><span className="text-ink-500 font-normal">Next.js in web/ · Vercel deploys from git · content from the studio</span></div>
          <div className="p-4 flex flex-col gap-3 text-xs">
            <div className="flex gap-2 items-center flex-wrap">
              <button className="btn" onClick={() => preview.mutate(undefined, { onSuccess: () => window.open('/site-preview/', '_blank') })}><Play size={12} />Preview site locally</button>
              <button className="btn btn-primary" disabled={!s.blob_token} title={s.blob_token ? 'Upload changed media + manifest.json to Vercel Blob, then revalidate' : 'Set BLOB_READ_WRITE_TOKEN first'} onClick={() => publish.mutate(undefined, { onSuccess: r => setJobId(r.job_id) })}><Globe size={12} />Publish</button>
              <button className="btn" onClick={() => exp.mutate(undefined, { onSuccess: r => { window.open(r.url, '_blank'); push({ kind: 'ok', title: 'Site exported', message: `${(r.bytes / 1e6).toFixed(1)} MB zip (offline backup)` }) } })}><Download size={12} />Export site .zip</button>
              {s.preview_url && <a className="btn btn-ghost" href={s.preview_url} target="_blank" rel="noreferrer"><ExternalLink size={12} />/site-preview/</a>}
            </div>
            <div className="text-ink-400">{s.published_moments} published moment{s.published_moments === 1 ? '' : 's'} · {s.links} links</div>
            {jobId && <JobProgress jobId={jobId} />}
            {s.manifest_url && <div className="flex items-center gap-2"><span className="label">Manifest URL</span><span className="font-mono text-2xs truncate">{s.manifest_url}</span><button className="btn btn-sm btn-icon" title="Copy (paste into Vercel as MANIFEST_URL)" onClick={() => navigator.clipboard.writeText(s.manifest_url!)}><Copy size={11} /></button></div>}
            {s.last && <div className="rounded border border-ink-700 bg-ink-900 p-2 font-mono text-2xs whitespace-pre-wrap text-ink-300">{JSON.stringify(s.last, null, 1)}</div>}
          </div>
        </div>
        <div className="card">
          <div className="panel-h">Publishing settings</div>
          <div className="p-4 grid grid-cols-2 gap-3 text-xs">
            <Field label="Site URL"><input className="input font-mono" value={siteUrl} onChange={e => setSiteUrl(e.target.value)} /></Field>
            <Field label="External media base URL (optional)" hint={<span className="normal-case text-ink-500">R2 / S3 / another Blob; same pathnames</span>}><input className="input font-mono" placeholder="(Vercel Blob)" value={mediaBase} onChange={e => setMediaBase(e.target.value)} /></Field>
            <div className="col-span-2 flex gap-2 items-center flex-wrap">
              <button className="btn btn-primary" onClick={() => save.mutate({ site_url: siteUrl, media_base: mediaBase })}>Save</button>
              <span className={cx('chip', s.blob_token ? 'border-emerald-500/50 text-emerald-300' : 'border-amber-500/50 text-amber-300')}>BLOB_READ_WRITE_TOKEN {s.blob_token ? 'set' : 'missing'}</span>
              <span className={cx('chip', s.revalidate_secret ? 'border-emerald-500/50 text-emerald-300' : 'border-amber-500/50 text-amber-300')}>REVALIDATE_SECRET {s.revalidate_secret ? 'set' : 'missing'}</span>
              <button className="btn btn-sm" onClick={() => setKeys(true)}><KeyRound size={11} />Set keys…</button>
              <button className="btn btn-sm" onClick={() => secret.mutate(undefined, { onSuccess: r => setShown(r.secret) })}>Generate revalidate secret</button>
            </div>
            {shown && <div className="col-span-2 rounded border border-gold-500/50 bg-gold-500/10 p-2"><div className="text-gold-300 mb-1">Shown once — paste into Vercel → Settings → Environment Variables as REVALIDATE_SECRET</div><div className="flex gap-2 items-center"><code className="font-mono text-2xs break-all flex-1">{shown}</code><button className="btn btn-sm btn-icon" onClick={() => navigator.clipboard.writeText(shown)}><Copy size={11} /></button></div></div>}
          </div>
        </div>
        <div className="card">
          <div className="panel-h">History</div>
          <div className="divide-y divide-ink-800 text-2xs font-mono">
            {s.history.length === 0 && <div className="p-3 text-ink-500">Nothing published yet.</div>}
            {s.history.map(h => <div key={h.id} className="p-2 flex gap-2"><StatusDot tone={h.ok ? 'ok' : 'bad'} /><span className="w-16">{h.kind}</span><span className="text-ink-400">{h.at?.slice(0, 19).replace('T', ' ')}</span><span className="truncate text-ink-300">{String(h.manifest_url ?? h.path ?? h.error ?? '')}</span></div>)}
          </div>
        </div>
      </div>
      <div className="card">
        <div className="panel-h">Domain checklist</div>
        <ol className="p-3 flex flex-col gap-2.5 text-xs">
          {s.checklist.map((c, i) => (
            <li key={c.id} className="flex gap-2"><span className={cx('w-5 h-5 rounded-full grid place-items-center text-2xs shrink-0', done.has(c.id) ? 'bg-emerald-500/20 text-emerald-300' : 'bg-ink-800 text-ink-300')}>{done.has(c.id) ? '✓' : i + 1}</span>
              <div><div className="text-ink-100">{c.label}</div><div className="text-ink-400">{c.detail}</div></div></li>
          ))}
        </ol>
        <div className="px-3 pb-3 text-2xs text-ink-500">Full steps: web/README.md. Upload icon <Upload size={10} className="inline" /> media is skipped when unchanged (sha1).</div>
      </div>
    </div>
  )
}
