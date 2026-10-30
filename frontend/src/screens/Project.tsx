import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Upload, Check, Circle, ChevronRight, Key, RotateCcw, Sparkles, FileText } from 'lucide-react'
import { useProject, useModels, useVolumes, useCanvases, useChapters, useLedger, useSaveModels, useSaveChapter, useApiMutation, qk, type JobResp } from '@/api/hooks'
import { api } from '@/api/client'
import { JOURNEY_STEPS, ROLES, type JourneyStep, type ModelSelection, type Role } from '@/api/types'
import { cx, Field, JobProgress, Spinner, usd, Chip, Modal } from '@/components/ui'
import { useQueryClient } from '@tanstack/react-query'
import { UpdatesCard } from '@/components/Updater'

const STEP_LABEL: Record<JourneyStep, string> = { manuscript: 'Manuscript', models: 'Models', characters: 'Characters', canvas: 'Canvas', prefill: 'Prefill', pages: 'Pages' }

export default function ProjectScreen() {
  const { data: project } = useProject()
  const { data: volumes = [] } = useVolumes()
  const { data: canvases = [] } = useCanvases()
  const { data: chapters = [] } = useChapters()
  const { data: ledger } = useLedger()
  const [step, setStep] = useState<JourneyStep | null>(null)
  const [keysOpen, setKeysOpen] = useState(false)
  const reset = useApiMutation(() => api.post('/api/project/journey/reset'), [qk.project])
  if (!project) return <Spinner />
  const current = step ?? project.journey.step
  const done = new Set(project.journey.done)

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-6xl mx-auto p-5 flex flex-col gap-5">
        {/* Stepper */}
        <section className="card">
          <div className="panel-h justify-between">
            <span>Onboarding journey</span>
            <button className="btn btn-ghost btn-sm" onClick={() => { if (confirm('Start the journey over? Nothing is deleted; the stepper returns to step 1.')) { reset.mutate(undefined); setStep('manuscript') } }}><RotateCcw size={11} /> Start over</button>
          </div>
          <ol className="flex items-stretch divide-x divide-ink-800">
            {JOURNEY_STEPS.map((s, i) => {
              const isDone = done.has(s)
              const isCur = current === s
              return (
                <li key={s} className="flex-1">
                  <button onClick={() => setStep(s)} className={cx('w-full flex items-center gap-2 px-3 py-2.5 text-left text-xs hover:bg-ink-800/60', isCur && 'bg-ink-800')}>
                    <span className={cx('w-5 h-5 rounded-full grid place-items-center border text-2xs font-mono', isDone ? 'bg-emerald-500/20 border-emerald-500/60 text-emerald-300' : isCur ? 'border-gold-400 text-gold-300' : 'border-ink-600 text-ink-500')}>{isDone ? <Check size={11} /> : i + 1}</span>
                    <span className={cx(isCur ? 'text-ink-100 font-medium' : isDone ? 'text-ink-300' : 'text-ink-500')}>{STEP_LABEL[s]}</span>
                    {s === project.journey.step && !isDone && <Circle size={6} className="ml-auto text-gold-400 fill-gold-400" />}
                  </button>
                </li>
              )
            })}
          </ol>
          <div className="border-t border-ink-800 p-4">
            {current === 'manuscript' && <ManuscriptStep chapters={chapters} project={project} onNext={() => setStep('models')} />}
            {current === 'models' && <ModelsStep onNext={() => setStep('characters')} />}
            {current === 'characters' && <CharactersStep onNext={() => setStep('canvas')} />}
            {current === 'canvas' && <StepLink text="Pick the paper and page frame per volume. Volume 1 defaults to Parchment; Books Two and Three get a suggestion card (Iron, Glass) but the author picks." to="/canvas" label="Open Canvas" onNext={() => setStep('prefill')} />}
            {current === 'prefill' && <PrefillStep onNext={() => setStep('pages')} />}
            {current === 'pages' && <StepLink text="Everything upstream is in place. Generate candidates, pick, cut the shards, approve, export." to="/pages" label="Open Pages" />}
          </div>
        </section>

        <div className="grid grid-cols-12 gap-5">
          {/* Book */}
          <section className="card col-span-7">
            <div className="panel-h">Book</div>
            <div className="p-4 grid grid-cols-2 gap-4">
              <Field label="Title"><input className="input" value={project.title} readOnly /></Field>
              <Field label="Author"><input className="input" value={project.author} readOnly /></Field>
              <Field label="Manuscript" className="col-span-2"><div className="input flex items-center gap-2 text-ink-300"><FileText size={12} />{project.manuscript_pdf ?? <span className="italic text-ink-500">not uploaded</span>}</div></Field>
            </div>
            <div className="border-t border-ink-800">
              <div className="panel-h">Volumes</div>
              {volumes.length === 0 && <div className="p-4 text-xs text-ink-500 italic">No volumes yet — upload the manuscript.</div>}
              {volumes.map(v => {
                const cv = canvases.find(c => c.id === v.canvas_id)
                const chs = chapters.filter(c => c.volume_id === v.id)
                return (
                  <div key={v.id} className="px-4 py-3 border-b border-ink-800 last:border-b-0">
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-2xs text-ink-500">VOL {v.number}</span>
                      <span className="text-sm text-ink-100 font-book">{v.title}</span>
                      <span className="ml-auto chip">{cv ? <><span className="w-2.5 h-2.5 rounded-sm border border-ink-500" style={{ background: cv.swatch ?? cv.paper_texture }} />{cv.name}</> : <span className="text-amber-300">no canvas</span>}</span>
                    </div>
                    <ul className="mt-2 grid grid-cols-2 gap-x-4 gap-y-0.5">
                      {chs.map(c => <li key={c.id} className="text-xs text-ink-300 flex gap-2 whitespace-nowrap"><span className="font-mono text-ink-500 w-5">{c.number}</span><span className="truncate">{c.title}</span><span className="ml-auto font-mono text-2xs text-ink-500">{c.pages_from}–{c.pages_to}{c.page_count ? ` · ${c.page_count}p` : ''}</span></li>)}
                      {chs.length === 0 && <li className="text-xs text-ink-500 italic">no chapters</li>}
                    </ul>
                  </div>
                )
              })}
            </div>
          </section>

          <div className="col-span-5 flex flex-col gap-5">
            <section className="card">
              <div className="panel-h"><Key size={12} /> API keys <span className="text-ink-500 font-normal">— stored privately on this Mac, never shown</span>
                <button className="btn ml-auto" onClick={() => setKeysOpen(true)}>Set keys</button></div>
              {keysOpen && <KeysModal onClose={() => setKeysOpen(false)} />}
              <div className="p-4 grid grid-cols-2 gap-2">
                {(['anthropic', 'openai', 'gemini', 'topaz'] as const).map(k => (
                  <div key={k} className={cx('flex items-center justify-between rounded border px-2.5 py-2 text-xs', project.keys[k] ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-amber-500/30 bg-amber-500/5')}>
                    <span className="capitalize text-ink-200">{k}</span>
                    <span className={cx('chip', project.keys[k] ? 'border-emerald-500/50 text-emerald-300' : 'border-amber-500/50 text-amber-300')}>{project.keys[k] ? 'configured' : 'missing'}</span>
                  </div>
                ))}
              </div>
            </section>
            <UpdatesCard />
            <section className="card">
              <div className="panel-h">Cost ledger</div>
              {ledger ? (
                <div className="p-4">
                  <div className="flex items-baseline gap-2"><span className="text-2xl font-mono text-ink-100">{usd(ledger.total)}</span><span className="text-2xs text-ink-500">total spend</span></div>
                  <div className="mt-3 flex flex-col gap-1.5">
                    {Object.entries(ledger.by_provider).sort((a, b) => b[1] - a[1]).map(([p, v]) => (
                      <div key={p} className="flex items-center gap-2 text-xs"><span className="w-20 capitalize text-ink-300">{p}</span><div className="flex-1 h-1 rounded bg-ink-700 overflow-hidden"><div className="h-full bg-gold-500" style={{ width: `${(v / Math.max(0.01, ledger.total)) * 100}%` }} /></div><span className="font-mono text-ink-300 w-14 text-right">{usd(v)}</span></div>
                    ))}
                    {Object.keys(ledger.by_provider).length === 0 && <div className="text-xs text-ink-500 italic">No spend yet.</div>}
                  </div>
                </div>
              ) : <Spinner />}
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}

function StepLink({ text, to, label, onNext }: { text: string; to: string; label: string; onNext?: () => void }) {
  return (
    <div className="flex items-center gap-4">
      <p className="text-xs text-ink-300 flex-1">{text}</p>
      <Link to={to} className="btn btn-primary">{label} <ChevronRight size={12} /></Link>
      {onNext && <button className="btn" onClick={onNext}>Next step</button>}
    </div>
  )
}

function ManuscriptStep({ chapters, project, onNext }: { chapters: { id: number; number: number; title: string; volume_id: number; pages_from: number | null; pages_to: number | null }[]; project: { manuscript_pdf: string | null }; onNext: () => void }) {
  const [jobId, setJobId] = useState<number | null>(null)
  const [drag, setDrag] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const upload = useApiMutation(async (file: File) => { const fd = new FormData(); fd.append('file', file); return api.post<JobResp>('/api/project/manuscript', fd) }, [qk.project], (r) => setJobId(r.job_id))
  const saveChapter = useSaveChapter()
  const onFiles = (files: FileList | null) => { const f = files?.[0]; if (f) upload.mutate(f) }
  return (
    <div className="grid grid-cols-2 gap-5">
      <div>
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(e.dataTransfer.files) }}
          onClick={() => fileRef.current?.click()}
          className={cx('h-36 rounded-md border-2 border-dashed grid place-items-center cursor-pointer text-xs transition-colors', drag ? 'border-gold-400 bg-gold-500/10 text-gold-200' : 'border-ink-600 text-ink-400 hover:border-ink-400')}
        >
          <div className="text-center"><Upload size={18} className="mx-auto mb-2 opacity-70" />Drop the manuscript (PDF or text) here, or click to choose<div className="text-2xs text-ink-500 mt-1">{project.manuscript_pdf ? `current: ${project.manuscript_pdf}` : 'the server extracts text and detects “Chapter N”, “Interlude”, “Prologue” headings'}</div></div>
          <input ref={fileRef} type="file" accept=".pdf,.txt,.md,text/plain,application/pdf" className="hidden" onChange={(e) => onFiles(e.target.files)} />
        </div>
        {jobId && <div className="mt-3"><JobProgress jobId={jobId} /></div>}
      </div>
      <div>
        <div className="label mb-1.5">Detected chapters — confirm titles and page ranges</div>
        {chapters.length === 0 && <div className="empty">No chapters detected yet.</div>}
        <div className="max-h-52 overflow-auto flex flex-col gap-1">
          {chapters.map(c => <ChapterRow key={c.id} c={c} onSave={(body) => saveChapter.mutate({ id: c.id, ...body })} />)}
        </div>
        <div className="mt-3 flex justify-end"><button className="btn btn-primary" onClick={onNext} disabled={!chapters.length}>Confirm chapters <ChevronRight size={12} /></button></div>
      </div>
    </div>
  )
}

function ChapterRow({ c, onSave }: { c: { number: number; title: string; volume_id: number; pages_from: number | null; pages_to: number | null }; onSave: (b: { title?: string; pages_from?: number | null; pages_to?: number | null }) => void }) {
  const [title, setTitle] = useState(c.title)
  const [from, setFrom] = useState(String(c.pages_from ?? ''))
  const [to, setTo] = useState(String(c.pages_to ?? ''))
  useEffect(() => { setTitle(c.title); setFrom(String(c.pages_from ?? '')); setTo(String(c.pages_to ?? '')) }, [c.title, c.pages_from, c.pages_to])
  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-2xs text-ink-500 w-9">v{c.volume_id}·{c.number}</span>
      <input className="input flex-1" value={title} onChange={(e) => setTitle(e.target.value)} onBlur={() => title !== c.title && onSave({ title })} />
      <input className="input w-14 font-mono" value={from} onChange={(e) => setFrom(e.target.value)} onBlur={() => Number(from) !== c.pages_from && onSave({ pages_from: from ? Number(from) : null })} />
      <span className="text-ink-600">–</span>
      <input className="input w-14 font-mono" value={to} onChange={(e) => setTo(e.target.value)} onBlur={() => Number(to) !== c.pages_to && onSave({ pages_to: to ? Number(to) : null })} />
    </div>
  )
}

function ModelsStep({ onNext }: { onNext: () => void }) {
  const { data: models } = useModels()
  const save = useSaveModels()
  const [sel, setSel] = useState<ModelSelection | null>(null)
  useEffect(() => { if (models && !sel) setSel(models.selected) }, [models, sel])
  if (!models || !sel) return <Spinner />
  const dirty = ROLES.some(r => sel[r.key] !== models.selected[r.key])
  const providerLabel: Record<string, string> = { anthropic: 'ANTHROPIC_API_KEY', openai: 'OPENAI_API_KEY', gemini: 'GEMINI_API_KEY', topaz: 'TOPAZ_API_KEY' }
  return (
    <div>
      <div className="grid grid-cols-4 gap-4">
        {ROLES.map(r => {
          const choices = models.roles[r.key as Role] ?? []
          const cur = choices.find(c => c.id === sel[r.key])
          const missing = cur && !models.providers[cur.provider]
          return (
            <div key={r.key} className="flex flex-col gap-1.5">
              <div className="label">{r.label}</div>
              <div className="text-2xs text-ink-500 h-8 leading-4">{r.what}</div>
              <select className={cx('select', missing && 'border-amber-500/60')} value={sel[r.key]} onChange={(e) => setSel({ ...sel, [r.key]: e.target.value })}>
                {choices.map(c => <option key={c.id} value={c.id} disabled={!models.providers[c.provider]}>{c.label}{!models.providers[c.provider] ? ' — key missing in .env' : ''}</option>)}
              </select>
              {missing ? <div className="text-2xs text-amber-300">{providerLabel[cur!.provider]} missing in .env</div> : cur?.note ? <div className="text-2xs text-ink-500">{cur.note}</div> : <div className="text-2xs text-ink-600">&nbsp;</div>}
            </div>
          )
        })}
      </div>
      <div className="mt-4 flex items-center gap-2">
        <div className="flex gap-1.5">{(Object.keys(models.providers) as (keyof typeof models.providers)[]).map(k => <Chip key={k} on={models.providers[k]} title={models.providers[k] ? 'key present' : 'key missing in .env'}>{k}</Chip>)}</div>
        <div className="flex-1" />
        <button className="btn" disabled={!dirty || save.isPending} onClick={() => save.mutate(sel)}>{save.isPending ? 'Saving…' : 'Save models'}</button>
        <button className="btn btn-primary" onClick={() => { if (dirty) save.mutate(sel); onNext() }}>Next: Characters <ChevronRight size={12} /></button>
      </div>
    </div>
  )
}

function CharactersStep({ onNext }: { onNext: () => void }) {
  const [jobId, setJobId] = useState<number | null>(null)
  const propose = useApiMutation(() => api.post<JobResp>('/api/characters/propose'), [qk.characters], (r) => setJobId(r.job_id))
  return (
    <div className="flex items-start gap-4">
      <p className="text-xs text-ink-300 flex-1">The script writer proposes the cast from the manuscript: name, forms, a first look paragraph. Then edit looks, generate or upload references, approve a primary and <b>lock</b>. The journey cannot advance to pages until every character in Chapter 1 is locked.
        {jobId && <div className="mt-3"><JobProgress jobId={jobId} /></div>}
      </p>
      <button className="btn" onClick={() => propose.mutate(undefined)} disabled={propose.isPending}><Sparkles size={12} /> Propose cast from manuscript</button>
      <Link to="/characters" className="btn btn-primary">Open Characters <ChevronRight size={12} /></Link>
      <button className="btn" onClick={onNext}>Next step</button>
    </div>
  )
}

function PrefillStep({ onNext }: { onNext: () => void }) {
  const [jobId, setJobId] = useState<number | null>(null)
  const prefill = useApiMutation(() => api.post<JobResp>('/api/chapters/1/prefill'), [['pages'], qk.project], (r) => setJobId(r.job_id))
  return (
    <div className="flex items-start gap-4">
      <div className="flex-1 text-xs text-ink-300">Prefill Chapter 1: the script writer breaks the chapter into pages and panels, captions verbatim from the book (EN) with a Hindi draft column. Then edit text on the Script screen.
        {jobId && <div className="mt-3"><JobProgress jobId={jobId} /></div>}
      </div>
      <button className="btn" onClick={() => prefill.mutate(undefined)} disabled={prefill.isPending}><Sparkles size={12} /> Prefill Chapter 1</button>
      <Link to="/script" className="btn btn-primary">Open Script <ChevronRight size={12} /></Link>
      <button className="btn" onClick={onNext}>Next step</button>
    </div>
  )
}


export function KeysModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [vals, setVals] = useState<Record<string, string>>({ anthropic: '', openai: '', gemini: '', topaz: '', fal: '', byteplus: '', elevenlabs: '', blob: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const labels: Record<string, string> = { anthropic: 'Anthropic (Claude)', openai: 'OpenAI (Sunburst, GPT)', gemini: 'Google Gemini', topaz: 'Topaz Labs', fal: 'fal.ai — Seedance (FAL_KEY)', byteplus: 'BytePlus ModelArk — Seedance', elevenlabs: 'ElevenLabs — narration', blob: 'Vercel Blob read-write token (publishing)' }
  const save = async () => {
    setBusy(true)
    const body: Record<string, string> = {}
    for (const [k, v] of Object.entries(vals)) if (v.trim()) body[k] = v.trim()
    try {
      await api.put('/api/settings/keys', body)
      await qc.invalidateQueries()
      setMsg('Saved.'); setTimeout(onClose, 600)
    } catch (e) { setMsg(String(e)) } finally { setBusy(false) }
  }
  return (
    <Modal title="API keys" onClose={onClose}>
      <div className="flex flex-col gap-3">
        <p className="text-xs text-ink-400">Paste only the keys you want to set or replace. They are saved privately on this Mac (readable only by your user account) and are never displayed again. Leave a field empty to keep the current key.</p>
        {Object.keys(labels).map(k => (
          <Field key={k} label={labels[k]}>
            <input type="password" autoComplete="off" spellCheck={false} className="input w-full font-mono text-xs" placeholder="paste key" value={vals[k]} onChange={e => setVals({ ...vals, [k]: e.target.value })} />
          </Field>
        ))}
        <div className="flex items-center gap-2 justify-end">
          {msg && <span className="text-xs text-ink-400 mr-auto">{msg}</span>}
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save keys'}</button>
        </div>
      </div>
    </Modal>
  )
}
