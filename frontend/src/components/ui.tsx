import { useEffect, type ReactNode } from 'react'
import { X, Loader2, Square } from 'lucide-react'
import type { Job, PageStatus } from '@/api/types'
import { useJob, useStopJob, useInvalidateAll } from '@/api/hooks'

export const cx = (...a: (string | false | null | undefined)[]) => a.filter(Boolean).join(' ')

export function StatusDot({ tone, title, pulse }: { tone: 'ok' | 'warn' | 'bad' | 'idle' | 'busy'; title?: string; pulse?: boolean }) {
  const c = { ok: 'bg-emerald-400', warn: 'bg-amber-400', bad: 'bg-red-500', idle: 'bg-ink-500', busy: 'bg-sky-400' }[tone]
  return <span title={title} className={cx('inline-block w-1.5 h-1.5 rounded-full shrink-0', c, pulse && 'animate-pulse')} />
}

export const STATUS_TONE: Record<PageStatus, string> = {
  empty: 'bg-ink-700 text-ink-300 border-ink-600',
  draft: 'bg-ink-600/60 text-ink-200 border-ink-500',
  generating: 'bg-sky-500/15 text-sky-300 border-sky-500/40',
  review: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  approved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
}
export function StatusBadge({ status, className }: { status: PageStatus; className?: string }) {
  return <span className={cx('inline-flex items-center h-4 px-1.5 rounded-sm border text-2xs uppercase tracking-wide font-medium', STATUS_TONE[status], className)}>{status === 'generating' && <Loader2 size={9} className="animate-spin mr-1" />}{status}</span>
}

export function Chip({ on, children, onClick, title, className }: { on?: boolean; children: ReactNode; onClick?: () => void; title?: string; className?: string }) {
  return <button type="button" title={title} onClick={onClick} className={cx('chip', on && 'chip-on', onClick && 'hover:border-ink-400 cursor-pointer', !onClick && 'cursor-default', className)}>{children}</button>
}

export function Field({ label, children, hint, className }: { label: string; children: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <label className={cx('flex flex-col gap-1', className)}>
      <span className="label flex items-center gap-2">{label}{hint}</span>
      {children}
    </label>
  )
}

export function Empty({ children }: { children: ReactNode }) { return <div className="empty">{children}</div> }

export function ProgressBar({ value, tone = 'gold', className }: { value: number; tone?: 'gold' | 'sky' | 'red'; className?: string }) {
  const c = { gold: 'bg-gold-500', sky: 'bg-sky-400', red: 'bg-red-500' }[tone]
  return <div className={cx('h-1 rounded-full bg-ink-700 overflow-hidden', className)}><div className={cx('h-full transition-[width] duration-300', c)} style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%` }} /></div>
}

export function jobFraction(j: Job) { return typeof j.progress === 'number' ? j.progress : j.progress.total ? j.progress.done / j.progress.total : 0 }
export function jobIsActive(j: Job) { return j.status === 'queued' || j.status === 'running' }

/** Inline progress for a job id; invalidates queries when the job finishes. */
export function JobProgress({ jobId, onDone, compact }: { jobId: number | null; onDone?: (j: Job) => void; compact?: boolean }) {
  const { data: job } = useJob(jobId)
  const inval = useInvalidateAll()
  const stop = useStopJob()
  useEffect(() => {
    if (job && !jobIsActive(job)) { inval(); onDone?.(job) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status])
  if (!jobId || !job) return null
  const f = jobFraction(job)
  const active = jobIsActive(job)
  const p = job.progress
  return (
    <div className={cx('rounded border border-ink-700 bg-ink-900 px-2.5 py-2 text-xs', compact && 'py-1.5')}>
      <div className="flex items-center gap-2">
        {active ? <Loader2 size={12} className="animate-spin text-sky-300" /> : <StatusDot tone={job.status === 'done' ? 'ok' : job.status === 'stopped' ? 'warn' : 'bad'} />}
        <span className="truncate flex-1 text-ink-200">{job.label ?? `${job.kind} #${job.id}`}</span>
        <span className="font-mono text-2xs text-ink-400">{typeof p === 'number' ? `${Math.round(f * 100)}%` : `${p.done}/${p.total}`}{job.cost_usd ? ` · $${job.cost_usd.toFixed(2)}` : ''}</span>
        {active && <button className="btn btn-sm btn-icon" title="Stop" onClick={() => stop.mutate(job.id)}><Square size={10} /></button>}
      </div>
      <ProgressBar value={f} tone={job.status === 'failed' ? 'red' : active ? 'sky' : 'gold'} className="mt-1.5" />
      {typeof p !== 'number' && <div className="mt-1 text-2xs text-ink-400 font-mono">page {p.page} · panel {p.panel} · ${p.cost_so_far.toFixed(2)} so far</div>}
      {!compact && job.log && <pre className="mt-1.5 max-h-24 overflow-auto text-2xs leading-4 text-ink-400 font-mono whitespace-pre-wrap">{job.log}</pre>}
    </div>
  )
}

export function Modal({ title, onClose, children, width = 'max-w-lg' }: { title: string; onClose: () => void; children: ReactNode; width?: string }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-6" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className={cx('card w-full shadow-2xl shadow-black/60', width)} role="dialog" aria-label={title}>
        <div className="panel-h justify-between"><span>{title}</span><button className="btn btn-ghost btn-sm btn-icon" onClick={onClose}><X size={13} /></button></div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return <div className="flex items-center gap-2 text-xs text-ink-400 p-4"><Loader2 size={13} className="animate-spin" />{label ?? 'Loading…'}</div>
}

export const usd = (v: number) => `$${v.toFixed(2)}`
