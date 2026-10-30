import { useEffect, useState } from 'react'
import { Clapperboard, Wand2, Upload, Send, Play } from 'lucide-react'
import { useChapters, usePages } from '@/api/hooks'
import { mediaUrl } from '@/api/client'
import { useTakes, useCreateTake, useSendTake, useMotionPrompt, useMotionOptions, useMoments, uploadStill, fetchEstimate, type Estimate, type Take } from '@/api/motion'
import { cx, Field, JobProgress, Empty, Spinner, usd } from '@/components/ui'

/** SEEDANCE VIDEO BUILDER: a panel (its selected image) or an uploaded still -> image-to-video takes. */
export default function SeedanceScreen() {
  const { data: opts } = useMotionOptions()
  const { data: chapters = [] } = useChapters()
  const [ch, setCh] = useState(1)
  const { data: pages = [] } = usePages(ch)
  const [pageNo, setPageNo] = useState<number | null>(null)
  const page = pages.find(p => p.number === pageNo) ?? pages[0]
  const panels = (page?.panels ?? []).filter(p => p.selected_candidate_id)
  const [panelId, setPanelId] = useState<number | null>(null)
  const panel = panels.find(p => p.id === panelId) ?? null
  const [still, setStill] = useState<{ path: string; url: string } | null>(null)
  const [camera, setCamera] = useState('push_in')
  const [prompt, setPrompt] = useState('')
  const [duration, setDuration] = useState(5)
  const [resolution, setResolution] = useState('1080p')
  const [aspect, setAspect] = useState('16:9')
  const [seed, setSeed] = useState('')
  const [provider, setProvider] = useState<'fal' | 'byteplus'>('fal')
  const [est, setEst] = useState<Estimate | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  const writer = useMotionPrompt()
  const create = useCreateTake()
  const { data: takes = [] } = useTakes(panel?.id ?? null)
  useEffect(() => { fetchEstimate(provider, duration, resolution).then(setEst).catch(() => setEst(null)) }, [provider, duration, resolution])
  useEffect(() => { setPrompt('') }, [panelId, camera])
  if (!opts) return <Spinner />
  const stillUrl = still?.url ?? (panel ? mediaUrl(panel.candidates.find(c => c.id === panel.selected_candidate_id)?.path) : null)
  const autoPrompt = () => writer.mutate({ panel_id: panel?.id ?? null, camera }, { onSuccess: r => setPrompt(r.prompt) })
  const run = () => create.mutate({ panel_id: still ? null : panel?.id, still_path: still?.path, prompt, duration, resolution, aspect, seed: seed ? Number(seed) : null, camera, provider },
    { onSuccess: r => { setJobId(r.job_id); setPrompt(r.take.prompt) } })
  return (
    <div className="h-full flex min-h-0">
      <div className="w-[25rem] shrink-0 border-r border-ink-800 overflow-auto p-4 flex flex-col gap-3 text-xs">
        <div className="flex gap-1.5">
          <select className="select w-20" value={ch} onChange={e => setCh(Number(e.target.value))}>{chapters.map(c => <option key={c.id} value={c.id}>ch {c.number}</option>)}</select>
          <select className="select flex-1" value={page?.number ?? ''} onChange={e => { setPageNo(Number(e.target.value)); setPanelId(null) }}>{pages.map(p => <option key={p.id} value={p.number}>page {p.number}</option>)}</select>
          <label className="btn cursor-pointer" title="Upload a still instead"><Upload size={12} /><input type="file" accept="image/*" className="hidden" onChange={async e => { const f = e.target.files?.[0]; if (f) { const r = await uploadStill(f); setStill({ path: r.still_path, url: r.url }); setPanelId(null) } }} /></label>
        </div>
        <div className="grid grid-cols-4 gap-1.5">
          {panels.map(p => {
            const c = p.candidates.find(x => x.id === p.selected_candidate_id)
            return <button key={p.id} onClick={() => { setPanelId(p.id); setStill(null) }} className={cx('rounded overflow-hidden border h-14', panelId === p.id ? 'border-gold-400' : 'border-ink-700')} title={p.scene}><img src={mediaUrl(c?.path)} className="w-full h-full object-cover" alt={`panel ${p.n}`} /></button>
          })}
        </div>
        <div className="rounded bg-ink-900 border border-ink-700 h-44 grid place-items-center overflow-hidden">{stillUrl ? <img src={stillUrl} className="max-h-full" alt="" /> : <span className="text-ink-500">Pick a panel or upload a still</span>}</div>
        {panel && <div className="text-ink-400 italic">“{panel.scene}”</div>}
        <Field label="Camera"><div className="grid grid-cols-3 gap-1">{opts.camera_presets.map(c => <button key={c.id} className={cx('btn btn-sm', camera === c.id && 'btn-primary')} title={c.text} onClick={() => setCamera(c.id)}>{c.label}</button>)}</div></Field>
        <Field label="Motion prompt" hint={<button className="btn btn-sm ml-auto normal-case" disabled={!panel && !still} onClick={autoPrompt}><Wand2 size={11} />{writer.isPending ? 'Writing…' : 'Write it (prompt writer)'}</button>}>
          <textarea className="textarea h-32" value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="Left empty, the prompt writer writes it from the scene line + camera + the lock line." />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label={`Duration ${duration} s`}><input type="range" min={5} max={10} value={duration} onChange={e => setDuration(Number(e.target.value))} className="accent-gold-500" /></Field>
          <Field label="Seed"><input className="input font-mono" placeholder="random" value={seed} onChange={e => setSeed(e.target.value.replace(/\D/g, ''))} /></Field>
          <Field label="Resolution"><select className="select" value={resolution} onChange={e => setResolution(e.target.value)}>{opts.resolutions.map(r => <option key={r}>{r}</option>)}</select></Field>
          <Field label="Aspect"><select className="select" value={aspect} onChange={e => setAspect(e.target.value)}>{opts.aspects.map(a => <option key={a}>{a}</option>)}</select></Field>
        </div>
        <Field label="Provider"><div className="flex gap-1.5">{opts.providers.map(p => <button key={p.id} className={cx('btn btn-sm flex-1', provider === p.id && 'btn-primary')} onClick={() => setProvider(p.id)}>{p.label}{!p.key && <span className="text-2xs text-amber-300 ml-1">dry run</span>}</button>)}</div></Field>
        <div className="rounded border border-ink-700 bg-ink-900 p-2.5 flex items-center gap-2">
          <span className="label">Before running</span>
          <span className="flex-1 text-ink-300">{est?.note ?? '…'}</span>
          {est && <span className="font-mono text-gold-300">{usd(est.usd)}</span>}
        </div>
        <button className="btn btn-primary" disabled={(!panel && !still) || create.isPending} onClick={run}><Clapperboard size={12} />Run take</button>
        {jobId && <JobProgress jobId={jobId} />}
      </div>
      <div className="flex-1 min-w-0 overflow-auto p-4">
        <div className="label mb-2">Takes {panel ? `for panel ${panel.n}` : '(all)'} — every take is kept; compare side by side</div>
        {takes.length === 0 ? <Empty>No takes yet.</Empty> : <div className="grid grid-cols-[repeat(auto-fill,minmax(19rem,1fr))] gap-3">{takes.map(t => <TakeCard key={t.id} t={t} />)}</div>}
      </div>
    </div>
  )
}

function TakeCard({ t }: { t: Take }) {
  const { data: moments = [] } = useMoments()
  const send = useSendTake()
  const [mid, setMid] = useState<number | ''>('')
  return (
    <div className={cx('card overflow-hidden text-xs', t.picked && 'border-gold-500/60')} data-testid="take">
      <div className="aspect-video bg-black">{t.url ? <video src={mediaUrl(t.url)} poster={mediaUrl(t.thumb)} controls loop muted playsInline className="w-full h-full" /> : <div className="h-full grid place-items-center text-ink-500"><Play size={16} />{t.status}</div>}</div>
      <div className="p-2 flex flex-col gap-1">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-ink-100">#{t.id}</span>
          <span className="chip">{t.provider}{t.dry_run ? ' · dry run' : ''}</span>
          <span className="chip">{t.params.camera} · {t.params.duration}s · {t.params.resolution} · {t.params.aspect}</span>
          <span className="ml-auto font-mono text-gold-300">{usd(t.cost_usd)}</span>
        </div>
        <div className="text-2xs text-ink-400 line-clamp-3" title={t.prompt}>{t.prompt}</div>
        <div className="flex gap-1.5 items-center">
          <select className="select flex-1" value={mid} onChange={e => setMid(e.target.value ? Number(e.target.value) : '')}><option value="">moment…</option>{moments.map(m => <option key={m.id} value={m.id}>/v/{m.code} · {m.title_en}</option>)}</select>
          <button className="btn btn-sm btn-primary" disabled={!mid || t.status !== 'done'} onClick={() => mid && send.mutate({ id: t.id, moment_id: mid })}><Send size={11} />Send to moment</button>
        </div>
      </div>
    </div>
  )
}
