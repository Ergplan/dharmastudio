import { Fragment, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CheckCircle2, Flag, Square, ArrowRight, Loader2, CircleSlash, Sparkles } from 'lucide-react'
import { cx, Spinner } from '@/components/ui'
import { mediaUrl } from '@/api/client'
import { useEditor } from '@/store/editor'
import type { ID } from '@/api/types'
import { useGuardrails, useRun, useStopRun, type Run, type RunCandidate } from './api'

const STEP_TONE: Record<string, string> = {
  check: 'text-ink-300', plan: 'text-sky-300', layout: 'text-indigo-300', prompt: 'text-violet-300', critic: 'text-amber-300',
  revise: 'text-orange-300', select: 'text-emerald-300', assemble: 'text-gold-300', budget: 'text-red-300', stop: 'text-red-300', error: 'text-red-400',
}
const STATUS_TONE: Record<string, string> = { done: 'border-emerald-500/50 text-emerald-300', running: 'border-sky-500/50 text-sky-300', queued: 'border-ink-500 text-ink-300', blocked: 'border-red-500/50 text-red-300', stopped: 'border-amber-500/50 text-amber-300', budget: 'border-amber-500/50 text-amber-300', failed: 'border-red-500/50 text-red-300' }

export function RunBadge({ status }: { status: string }) {
  return <span className={cx('chip uppercase', STATUS_TONE[status] ?? '')}>{status === 'running' && <Loader2 size={9} className="animate-spin" />}{status}</span>
}

export function RunTimeline({ runId, onPickRun, onReuse }: { runId: ID | null; onPickRun?: (id: ID) => void; onReuse?: () => void }) {
  const { data: run, isLoading } = useRun(runId)
  const stop = useStopRun()
  const nav = useNavigate()
  const ed = useEditor()
  if (!runId) return <div className="p-6 text-xs text-ink-500">No run yet. Fill the brief and press <b>Direct this page</b>.</div>
  if (isLoading || !run) return <Spinner />
  const active = run.status === 'running' || run.status === 'queued'
  const panels = run.plan?.panels ?? []
  return (
    <div className="h-full overflow-auto p-4 flex flex-col gap-4 text-xs [&>*]:shrink-0">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm text-ink-100 font-medium">Run #{run.id}</span>
        <RunBadge status={run.status} />
        <span className="text-ink-400">{run.manuscript.label}{run.page_number ? ` · page ${run.page_number}` : ''}</span>
        <span className="font-mono text-2xs text-ink-400">${run.cost_usd.toFixed(3)}{run.estimate?.usd !== undefined ? ` / est. $${run.estimate.usd.toFixed(2)} · cap $${(run.settings.budget_usd ?? 0).toFixed(2)}` : ''}</span>
        <div className="flex-1" />
        {onReuse && run.kind === 'page' && run.brief?.action && <button className="btn btn-sm" onClick={onReuse} title="Put this run's brief back in the form (for a new page)">Reuse brief</button>}
        {active && <button className="btn btn-sm btn-danger" onClick={() => stop.mutate(run.id)}><Square size={10} /> Stop</button>}
        {run.page_id && !active && (
          <button className="btn btn-sm btn-primary" onClick={() => { ed.setChapter(run.chapter_id); setTimeout(() => ed.setPage(run.page_id!), 0); nav('/pages') }}>Open in Pages <ArrowRight size={11} /></button>
        )}
      </div>

      {run.kind === 'chapter' && run.children && (
        <div className="card p-2 flex flex-col gap-1">
          <div className="label">Pages in this batch</div>
          {run.children.map(c => <button key={c.id} className="flex items-center gap-2 text-left hover:bg-ink-800 rounded px-1 py-0.5" onClick={() => onPickRun?.(c.id)}><RunBadge status={c.status} /><span>page {c.page_number}</span><span className="text-ink-500">run #{c.id} · {c.panels} panels · {c.flags.length} flagged</span></button>)}
        </div>
      )}

      {/* steps */}
      <ol className="relative border-l border-ink-700 ml-1.5 flex flex-col gap-1">
        {(run.steps ?? []).map((s, i) => (
          <li key={i} className="pl-3 relative">
            <span className={cx('absolute -left-[4.5px] top-1.5 w-2 h-2 rounded-full bg-ink-600', s.step === 'assemble' && 'bg-gold-400', s.step === 'critic' && 'bg-amber-400')} />
            <span className="font-mono text-2xs text-ink-500 mr-2">{s.t}</span>
            <span className={cx('font-mono text-2xs uppercase mr-2', STEP_TONE[s.step] ?? 'text-ink-300')}>{s.step}</span>
            <span className="text-ink-200">{s.msg}</span>
          </li>
        ))}
      </ol>

      {run.flags.length > 0 && run.kind === 'page' && (
        <div className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-2xs text-amber-100">
          <div className="flex items-center gap-1.5 font-medium mb-1"><Flag size={11} />Flagged for the author — never silently accepted</div>
          {run.flags.map((f, i) => <div key={i}>panel {f.panel}: {(f.reasons ?? []).slice(0, 3).join('; ')}</div>)}
        </div>
      )}

      {panels.length > 0 && (
        <div className="flex items-center gap-2 text-2xs text-ink-400"><span className="label">Plan</span>source: <span className="text-ink-200">{run.plan?.source}</span>· beat {run.plan?.page_beat} · {panels.length} panels</div>
      )}
      {panels.map(p => <PanelBlock key={p.n} run={run} n={p.n} />)}
    </div>
  )
}

function PanelBlock({ run, n }: { run: Run; n: number }) {
  const p = run.plan!.panels.find(x => x.n === n)!
  const prompts = (run.prompts ?? []).filter(x => x.panel === n)
  const cands = (run.candidates ?? []).filter(x => x.panel === n)
  const attempts = Array.from(new Set(cands.map(c => c.attempt))).sort()
  const [open, setOpen] = useState<number | null>(null)
  return (
    <div className="card overflow-hidden">
      <div className="px-3 py-2 border-b border-ink-700 flex items-center gap-2 flex-wrap">
        <span className="font-mono text-ink-400">{n}</span>
        <span className={cx('chip uppercase', p.role === 'dominant' ? 'chip-on' : p.role === 'detail' ? 'border-violet-500/50 text-violet-200' : p.role === 'plate' ? 'border-gold-400 text-gold-200' : '')}>{p.role}</span>
        <span className="chip font-mono">{p.scale}</span><span className="chip">{p.beat}</span>
        {p.characters.map(c => <span key={c} className="chip border-emerald-600/40 text-emerald-200">{c}</span>)}
        <span className="text-ink-300 truncate flex-1 min-w-[12rem]" title={p.scene}>{p.scene}</span>
      </div>
      <div className="px-3 py-2 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1">
        {p.narration && <><div className="font-book text-[0.8rem] text-parchment-400 bg-[#3a2d1a]/40 rounded px-2 py-1">{p.narration}</div><span className="chip border-emerald-500/50 text-emerald-300 self-start"><CheckCircle2 size={9} />narration · verbatim</span></>}
        {p.dialogue && <><div className="font-book text-[0.8rem] text-ink-100 bg-ink-800 rounded-xl px-2 py-1"><span className="text-2xs text-ink-400 mr-1">{p.speaker ?? '—'}:</span>{p.dialogue}</div><span className="chip border-emerald-500/50 text-emerald-300 self-start"><CheckCircle2 size={9} />dialogue · verbatim</span></>}
      </div>
      {attempts.map(a => {
        const pr = prompts.find(x => x.attempt === a)
        return (
          <div key={a} className="border-t border-ink-800 px-3 py-2">
            <div className="flex items-center gap-2 text-2xs text-ink-400 mb-1.5">
              <span className={cx('font-mono uppercase', a ? 'text-orange-300' : 'text-violet-300')}>{a ? `revision ${a}` : 'first paint'}</span>
              {pr && <button className="underline" onClick={() => setOpen(open === a ? null : a)}>prompt · {pr.chars} chars · refs {pr.references.join(', ') || 'none'}{pr.lint.length ? ` · lint: ${pr.lint.join(', ')}` : ' · lint ok'}</button>}
            </div>
            {open === a && pr && <pre className="mb-2 max-h-56 overflow-auto whitespace-pre-wrap text-2xs leading-4 bg-ink-950 border border-ink-800 rounded p-2 text-ink-300">{pr.prompt}</pre>}
            <div className="grid grid-cols-2 xl:grid-cols-3 gap-2">
              {cands.filter(c => c.attempt === a).map(c => <CandidateCard key={c.candidate_id} c={c} />)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CandidateCard({ c }: { c: RunCandidate }) {
  const { data: g } = useGuardrails()
  const v = c.verdict
  return (
    <div className={cx('rounded border overflow-hidden bg-ink-900', c.selected ? 'border-gold-500 ring-1 ring-gold-500/30' : 'border-ink-700')}>
      <div className="relative">
        <img src={mediaUrl(c.url || c.path)} className="w-full aspect-[3/2] object-cover" alt="" />
        <span className="absolute top-1 left-1 chip bg-black/70">#{c.candidate_id}{c.dry_run ? ' · dry run' : ''}</span>
        {c.selected && <span className="absolute top-1 right-1 chip chip-on bg-black/70"><Sparkles size={9} />pre-selected</span>}
      </div>
      <div className="p-1.5 flex flex-col gap-1">
        <div className="flex items-center gap-1.5 text-2xs">
          {v.pass ? <span className="chip border-emerald-500/60 text-emerald-300"><CheckCircle2 size={9} />pass</span>
            : !v.judged ? <span className="chip border-amber-500/60 text-amber-300"><CircleSlash size={9} />unjudged</span>
              : <span className="chip border-red-500/60 text-red-300"><Flag size={9} />fail</span>}
          {v.mean !== null && <span className="font-mono text-ink-300">mean {v.mean}</span>}
        </div>
        <div className="grid grid-cols-10 gap-0.5" title="FINAL QUALITY TEST — hover a bar for the question">
          {Array.from({ length: 10 }, (_, i) => {
            const s = c.critic.scores[String(i + 1)]
            return (
              <div key={i} className="flex flex-col items-center gap-0.5" title={`${i + 1}. ${g?.quality_test[i] ?? ''}${s !== undefined ? ` — ${s}/10` : ' — not scored'}`}>
                <div className="w-full h-6 bg-ink-800 rounded-sm flex items-end overflow-hidden"><div className={cx('w-full', s === undefined ? 'bg-ink-700' : s >= 7 ? 'bg-emerald-500/80' : s >= 6 ? 'bg-amber-400/80' : 'bg-red-500/80')} style={{ height: `${s === undefined ? 12 : s * 10}%` }} /></div>
                <span className="text-[0.55rem] font-mono text-ink-500">{i + 1}</span>
              </div>
            )
          })}
        </div>
        <div className="flex flex-wrap gap-0.5">
          {c.checks.checks.map(k => <span key={k.check} className={cx('chip text-[0.58rem]', k.skipped ? 'text-ink-500' : k.ok ? 'border-emerald-600/40 text-emerald-300' : 'border-red-500/50 text-red-300')} title={k.detail}>{k.check}{k.skipped ? ' · skipped' : ''}</span>)}
        </div>
        {(c.critic.violations.length > 0 || c.critic.note) && (
          <div className="text-[0.62rem] leading-3.5 text-ink-400">
            {c.critic.note && <div className="italic">{c.critic.note}</div>}
            {c.critic.violations.map((x, i) => <Fragment key={i}><div className="text-red-300">{x.rule}: {x.detail}</div></Fragment>)}
          </div>
        )}
        {c.critic.fix_prompt && <div className="text-[0.62rem] text-orange-200">fix → {c.critic.fix_prompt}</div>}
      </div>
    </div>
  )
}
