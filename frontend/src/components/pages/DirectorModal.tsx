import { useEffect, useState } from 'react'
import { Clapperboard, Play } from 'lucide-react'
import type { Page, Provider, DirectorRequest, DirectorEstimate } from '@/api/types'
import { PROVIDERS } from '@/api/types'
import { Modal, Field, cx, usd } from '@/components/ui'
import { useDirectorEstimate, useApiMutation, type JobResp } from '@/api/hooks'
import { api } from '@/api/client'
import { toast } from '@/store/toasts'

export function DirectorModal({ chapterId, pages, onClose, onStarted }: { chapterId: number; pages: Page[]; onClose: () => void; onStarted: (jobId: number) => void }) {
  const [mode, setMode] = useState<'range' | 'next'>('range')
  const [from, setFrom] = useState(1)
  const [to, setTo] = useState(Math.min(5, pages.length))
  const [next, setNext] = useState(3)
  const [cpp, setCpp] = useState(2)
  const [provider, setProvider] = useState<Provider>('sunburst')
  const [prefill, setPrefill] = useState(true)
  const [critic, setCritic] = useState(true)
  const [est, setEst] = useState<DirectorEstimate | null>(null)
  const estimate = useDirectorEstimate()
  const run = useApiMutation((req: DirectorRequest) => api.post<JobResp>('/api/director/batch', req), [['pages'], ['jobs']], (r) => { toast('info', 'Director batch started', 'Pages flip to review as the batch finishes them.'); onStarted(r.job_id); onClose() })
  const req: DirectorRequest = { chapter_id: chapterId, pages: mode === 'range' ? Array.from({ length: Math.max(0, to - from + 1) }, (_, i) => from + i) : { next }, candidates_per_panel: cpp, provider, prefill_text: prefill, run_critic: critic }
  const key = JSON.stringify(req)
  useEffect(() => { let alive = true; setEst(null); estimate.mutateAsync(req).then(e => alive && setEst(e)).catch(() => {}); return () => { alive = false } }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Modal title="Director — make pages in one instruction" onClose={onClose} width="max-w-xl">
      <div className="flex flex-col gap-4">
        <div>
          <div className="label mb-1.5">Pages</div>
          <div className="flex items-center gap-2 text-xs">
            <button className={cx('btn', mode === 'range' && 'btn-primary')} onClick={() => setMode('range')}>Range</button>
            <input type="number" className="input w-16 font-mono" min={1} max={pages.length} value={from} disabled={mode !== 'range'} onChange={(e) => setFrom(Number(e.target.value))} /><span className="text-ink-500">to</span>
            <input type="number" className="input w-16 font-mono" min={1} max={pages.length} value={to} disabled={mode !== 'range'} onChange={(e) => setTo(Number(e.target.value))} />
            <span className="text-ink-600 mx-1">|</span>
            <button className={cx('btn', mode === 'next' && 'btn-primary')} onClick={() => setMode('next')}>Next</button>
            <input type="number" className="input w-16 font-mono" min={1} max={pages.length} value={next} disabled={mode !== 'next'} onChange={(e) => setNext(Number(e.target.value))} /><span className="text-ink-500">empty/draft pages</span>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Candidates per panel"><select className="select" value={cpp} onChange={(e) => setCpp(Number(e.target.value))}>{[1, 2, 3, 4].map(k => <option key={k} value={k}>{k}</option>)}</select></Field>
          <Field label="Image provider"><select className="select" value={provider} onChange={(e) => setProvider(e.target.value as Provider)}>{PROVIDERS.map(p => <option key={p.key} value={p.key}>{p.label} · {p.cost}</option>)}</select></Field>
        </div>
        <div className="flex gap-4 text-xs">
          <label className="flex items-center gap-2"><input type="checkbox" checked={prefill} onChange={(e) => setPrefill(e.target.checked)} className="accent-gold-500" /> Prefill text for pages without panels</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={critic} onChange={(e) => setCritic(e.target.checked)} className="accent-gold-500" /> Run critic (pre-selects the top candidate; never auto-approves)</label>
        </div>
        <div className="rounded border border-ink-700 bg-ink-900 px-3 py-2 text-xs flex items-center gap-3">
          <Clapperboard size={14} className="text-gold-300" />
          {est ? <span><b className="text-ink-100">{est.images} images</b> across {est.panels} panels{est.pages ? ` on pages ${est.pages.join(', ')}` : ''} ≈ <b className="text-gold-300">{usd(est.usd)}</b>{est.images === 0 && <span className="text-ink-500"> — nothing to do: every panel in range already has a selected candidate (or the pages are approved)</span>}</span> : <span className="text-ink-500">estimating…</span>}
        </div>
        <div className="text-2xs text-ink-500 leading-4">Per page: gate check (unlocked characters skip the page with a logged reason; the batch continues) → prefill if empty → generate for every panel without a selected candidate → critic → page set to <b>review</b>. Stop finishes the current panel and halts.</div>
        <div className="flex justify-end gap-2"><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={!est || run.isPending || est.images === 0} onClick={() => run.mutate(req)}><Play size={12} /> Run batch</button></div>
      </div>
    </Modal>
  )
}
