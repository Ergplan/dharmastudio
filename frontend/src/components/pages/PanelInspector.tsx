import { useEffect, useRef, useState } from 'react'
import { Sparkles, Check, Ban, ChevronDown, ChevronRight, Wand2, Lock, Unlock } from 'lucide-react'
import type { Panel, Page, Character, Provider } from '@/api/types'
import { PROVIDERS, STATES, SCALES } from '@/api/types'
import { useSavePanel, useSelectCandidate, useRejectCandidate, useApiMutation, type JobResp } from '@/api/hooks'
import { api, mediaUrl } from '@/api/client'
import { cx, Field, Chip, JobProgress, usd } from '@/components/ui'
import { useEditor } from '@/store/editor'

export function PanelInspector({ panel, page, chars, gateBlocked, provider, setProvider, n, setN, pageNumber }: {
  panel: Panel; page: Page; chars: Character[]; gateBlocked: string | null; provider: Provider; setProvider: (p: Provider) => void; n: number; setN: (n: number) => void; pageNumber: number
}) {
  const frozen = page.status === 'approved'
  const save = useSavePanel()
  const select = useSelectCandidate()
  const reject = useRejectCandidate()
  const [scene, setScene] = useState(panel.scene)
  useEffect(() => setScene(panel.scene), [panel.scene, panel.id])
  const [feedback, setFeedback] = useState('')
  const [jobId, setJobId] = useState<number | null>(null)
  const [proposed, setProposed] = useState<string | null>(null)
  const [promptOpen, setPromptOpen] = useState(false)
  const [hover, setHover] = useState<number | null>(null)
  const gen = useApiMutation(() => api.post<JobResp>(`/api/panels/${panel.id}/generate`, { provider, n, feedback: feedback.trim() || undefined }), [['pages'], ['page'], ['jobs']], (r) => setJobId(r.job_id))
  const rewrite = useApiMutation(() => api.post<{ scene: string }>(`/api/panels/${panel.id}/rewrite`, { feedback }), [], (r) => setProposed(r.scene))
  const sel = panel.candidates.find(c => c.id === panel.selected_candidate_id) ?? null
  const shown = hover !== null ? panel.candidates.find(c => c.id === hover) ?? sel : sel
  const genRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { const h = (e: Event) => { if ((e as CustomEvent).detail === panel.id) genRef.current?.click() }; window.addEventListener('dharma:generate', h); return () => window.removeEventListener('dharma:generate', h) }, [panel.id])
  const toggleChar = (form: string) => save.mutate({ id: panel.id, characters: panel.characters.includes(form) ? panel.characters.filter(f => f !== form) : [...panel.characters, form] })
  const shardEditor = useEditor(s => s.shardEditor)

  return (
    <div className="flex-1 min-h-0 overflow-auto flex flex-col">
      <div className="panel-h gap-2">
        <span>Panel {pageNumber}.{panel.n}</span>
        <span className="chip">{panel.kind}</span>
        {panel.locked_shape ? <span className="chip" title="shape locked"><Lock size={9} /> shape</span> : <span className="chip text-ink-500" title="shape unlocked"><Unlock size={9} /> shape</span>}
        {panel.image_group && <span className="chip">⧉ {panel.image_group}</span>}
        <span className="ml-auto text-ink-500 font-normal">{panel.candidates.length} candidates</span>
      </div>
      <div className="p-3 flex flex-col gap-3">
        <Field label="Scene (SCENE line of the prompt)">
          <textarea className="textarea min-h-[72px]" value={scene} onChange={(e) => setScene(e.target.value)} onBlur={() => scene !== panel.scene && save.mutate({ id: panel.id, scene })} />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="State"><select className="select" value={panel.state} onChange={(e) => save.mutate({ id: panel.id, state: e.target.value as Panel['state'] })}>{STATES.map(s => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Scale"><select className="select" value={panel.scale} onChange={(e) => save.mutate({ id: panel.id, scale: e.target.value as Panel['scale'] })}>{SCALES.map(s => <option key={s}>{s}</option>)}</select></Field>
        </div>
        <div>
          <div className="label mb-1">Characters</div>
          <div className="flex flex-wrap gap-1">
            {chars.map(c => <Chip key={c.id} on={panel.characters.includes(c.form_key)} onClick={() => toggleChar(c.form_key)} title={c.locked ? 'locked' : 'unlocked — blocks generation'}><span className={cx('w-1.5 h-1.5 rounded-full', c.locked ? 'bg-emerald-400' : 'bg-amber-400')} />{c.name}</Chip>)}
            {panel.characters.filter(f => !chars.some(c => c.form_key === f)).map(f => <Chip key={f} on onClick={() => toggleChar(f)}>{f}</Chip>)}
          </div>
        </div>

        <div>
          <div className="label mb-1 flex items-center gap-2">Candidates {shown && <span className="ml-auto normal-case tracking-normal font-mono text-ink-500">{shown.provider} · {shown.model} · {usd(shown.cost_usd)}{shown.qa && typeof shown.qa.score === 'number' ? ` · critic ${shown.qa.score}` : ''}</span>}</div>
          {panel.candidates.length === 0 ? <div className="empty">No candidates yet — regenerate below{gateBlocked ? ' once the gate is clear' : ''}.</div> : (
            <div className="grid grid-cols-2 gap-2">
              {panel.candidates.map(c => {
                const isSel = c.id === panel.selected_candidate_id
                return (
                  <div key={c.id} className={cx('relative rounded-md overflow-hidden border-2 group bg-ink-900', isSel ? 'border-gold-400 shadow-[0_0_0_2px_rgba(212,160,23,0.25)]' : 'border-ink-700 hover:border-ink-400', c.rejected && 'opacity-40')}
                    onMouseEnter={() => setHover(c.id)} onMouseLeave={() => setHover(null)} title={`${c.provider} · ${c.model} · ${usd(c.cost_usd)}${c.feedback_used ? `\nfeedback: ${c.feedback_used}` : ''}`}>
                    <button className="block w-full aspect-[3/2] disabled:cursor-not-allowed" disabled={frozen} onClick={() => !isSel && select.mutate({ id: panel.id, candidate_id: c.id })}>
                      <img src={mediaUrl(c.path)} alt="" className="w-full h-full object-cover" />
                    </button>
                    {isSel && <span className="absolute top-1 left-1 chip chip-on"><Check size={9} /> selected</span>}
                    {c.rejected && <span className="absolute top-1 left-1 chip border-red-500/60 text-red-300"><Ban size={9} /> rejected</span>}
                    <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent px-1.5 py-1 flex items-center gap-1 text-2xs text-ink-200 opacity-0 group-hover:opacity-100 transition-opacity">
                      <span className="font-mono truncate">{c.provider} · {usd(c.cost_usd)}</span>
                      <button className={cx('ml-auto btn btn-sm btn-icon', c.rejected && 'text-red-300')} title={c.rejected ? 'Un-reject' : 'Reject'} onClick={(e) => { e.stopPropagation(); reject.mutate({ id: panel.id, cid: c.id, rejected: !c.rejected }) }}><Ban size={10} /></button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {shown && (
          <div className="rounded border border-ink-700 bg-ink-900">
            <button className="w-full flex items-center gap-2 px-2.5 py-1.5 text-2xs text-ink-300" onClick={() => setPromptOpen(o => !o)}>{promptOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}Full prompt of {hover !== null && shown.id !== sel?.id ? 'hovered' : 'selected'} candidate{shown.feedback_used && <span className="ml-auto chip">feedback: {shown.feedback_used}</span>}</button>
            {promptOpen && <pre className="px-2.5 pb-2 text-2xs leading-4 font-mono text-ink-400 whitespace-pre-wrap max-h-48 overflow-auto">{shown.prompt_full}</pre>}
          </div>
        )}

        <div className="rounded border border-ink-700 bg-ink-850 p-2.5 flex flex-col gap-2">
          <Field label="Feedback" hint={<span className="normal-case tracking-normal text-ink-600">e.g. “eyes open”, “wider, no giants”</span>}>
            <textarea className="textarea min-h-[48px] font-ui" value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="What should change?" />
          </Field>
          <div className="flex items-center gap-1.5">
            <select className="select w-auto flex-1" value={provider} onChange={(e) => setProvider(e.target.value as Provider)}>{PROVIDERS.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}</select>
            <select className="select w-14" value={n} onChange={(e) => setN(Number(e.target.value))}>{[1, 2, 3, 4].map(k => <option key={k} value={k}>{k}</option>)}</select>
            <button ref={genRef} className="btn btn-primary" disabled={!!gateBlocked || frozen || gen.isPending || shardEditor} title={gateBlocked ?? (frozen ? 'Approved pages are frozen — un-approve to regenerate' : `POST /api/panels/${panel.id}/generate (G)`)} onClick={() => gen.mutate(undefined)}><Sparkles size={12} /> Regenerate {n}</button>
          </div>
          {gateBlocked && <div className="text-2xs text-amber-300">{gateBlocked}</div>}
          <button className="btn" disabled={!feedback.trim() || rewrite.isPending} onClick={() => rewrite.mutate(undefined)}><Wand2 size={12} /> {rewrite.isPending ? 'Rewriting…' : 'Rewrite scene only'} <span className="text-ink-500 font-normal">— no generation</span></button>
          {proposed && (
            <div className="rounded border border-sky-500/40 bg-sky-500/5 p-2 text-xs">
              <div className="label mb-1 text-sky-300">Proposed scene</div>
              <p className="font-book text-ink-100 leading-relaxed">{proposed}</p>
              <div className="mt-2 flex gap-1.5"><button className="btn btn-primary btn-sm" onClick={() => { save.mutate({ id: panel.id, scene: proposed }); setScene(proposed); setProposed(null) }}><Check size={11} /> Accept</button><button className="btn btn-sm" onClick={() => setProposed(null)}>Discard</button></div>
            </div>
          )}
          {jobId && <JobProgress jobId={jobId} compact onDone={() => { setFeedback('') }} />}
        </div>
      </div>
    </div>
  )
}
