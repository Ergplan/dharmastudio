import { NavLink, useLocation } from 'react-router-dom'
import { BookOpen, Users, Layers, Type, FileText, LayoutGrid, Clapperboard, PenTool, Download, Film, Activity, X, Square, Loader2, AlertTriangle, ShieldAlert, Info, Check } from 'lucide-react'
import { useActiveJobs, useProject, useCharacters, useVolumes, useChapters, usePages, useSilhouettes, useExports, useStopJob, useLedger } from '@/api/hooks'
import { useToasts } from '@/store/toasts'
import { cx, StatusDot, ProgressBar, jobFraction, jobIsActive } from './ui'
import { MOCK } from '@/api/client'
import { useUiScale, UI_STEPS, UI_DEFAULT } from '@/lib/uiScale'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'

type Tone = 'ok' | 'warn' | 'bad' | 'idle' | 'busy'

function useRailStatus(): Record<string, { tone: Tone; title: string }> {
  const project = useProject().data
  const chars = useCharacters().data ?? []
  const vols = useVolumes().data ?? []
  const chapters = useChapters().data ?? []
  const pages = usePages(1).data ?? []
  const sils = useSilhouettes().data ?? []
  const exps = useExports().data ?? []
  const jobs = useActiveJobs().data ?? []
  const keysOk = project ? Object.values(project.keys).filter(Boolean).length : 0
  const unlocked = chars.filter(c => !c.locked).length
  const approved = pages.filter(p => p.status === 'approved').length
  return {
    project: { tone: !project ? 'idle' : keysOk >= 3 ? 'ok' : 'warn', title: project ? `${keysOk}/4 keys configured` : 'loading' },
    characters: { tone: !chars.length ? 'idle' : unlocked === 0 ? 'ok' : 'warn', title: unlocked ? `${unlocked} unlocked` : 'all locked' },
    canvas: { tone: vols.every(v => v.canvas_id) ? 'ok' : 'warn', title: `${vols.filter(v => v.canvas_id).length}/${vols.length} volumes have a canvas` },
    typography: { tone: vols.length ? 'ok' : 'idle', title: vols.map(v => `Vol ${v.number}: ${v.typography?.preset ?? 'default'} · ${v.typography?.size ?? 'L'}`).join('\n') },
    script: { tone: chapters.length ? 'ok' : 'idle', title: `${chapters.length} chapters` },
    pages: { tone: jobs.some(j => j.kind === 'panel' || j.kind === 'page' || j.kind === 'batch') ? 'busy' : approved === pages.length && pages.length ? 'ok' : pages.length ? 'warn' : 'idle', title: `${approved}/${pages.length} approved` },
    silhouettes: { tone: sils.length ? 'ok' : 'idle', title: `${sils.length} in library` },
    export: { tone: jobs.some(j => j.kind === 'export') ? 'busy' : exps.length ? 'ok' : 'idle', title: `${exps.length} exports` },
    motion: { tone: jobs.some(j => j.kind === 'motion_render' || j.kind === 'seedance' || j.kind === 'site_publish') ? 'busy' : 'idle', title: 'Moments, Seedance, QR, Links, Site' },
  }
}

const NAV = [
  { to: '/project', key: 'project', label: 'Project', icon: BookOpen },
  { to: '/characters', key: 'characters', label: 'Characters', icon: Users },
  { to: '/canvas', key: 'canvas', label: 'Canvas', icon: Layers },
  { to: '/typography', key: 'typography', label: 'Type', icon: Type },
  { to: '/script', key: 'script', label: 'Script', icon: FileText },
  { to: '/pages', key: 'pages', label: 'Pages', icon: LayoutGrid },
  { to: '/director', key: 'director', label: 'Director', icon: Clapperboard },
  { to: '/silhouettes', key: 'silhouettes', label: 'Silhouettes', icon: PenTool },
  { to: '/export', key: 'export', label: 'Export', icon: Download },
  { to: '/motion', key: 'motion', label: 'Motion', icon: Film },
]

export function Rail() {
  const st = useRailStatus()
  return (
    <nav className="w-[4.75rem] shrink-0 border-r border-ink-800 bg-ink-900 flex flex-col items-stretch py-2 select-none">
      <div className="h-10 flex items-center justify-center mb-1" title="Dharma Studio">
        <div className="w-7 h-7 rounded-md bg-gradient-to-br from-gold-500 to-crimson/80 grid place-items-center text-ink-950 font-book font-bold text-sm shadow-inner">ध</div>
      </div>
      {NAV.map((n, i) => (
        <NavLink key={n.to} to={n.to} className={({ isActive }) => cx('relative flex flex-col items-center gap-1 py-2.5 text-2xs text-ink-400 hover:text-ink-100 hover:bg-ink-850', isActive && 'text-gold-300 bg-ink-850 before:absolute before:left-0 before:top-2 before:bottom-2 before:w-0.5 before:bg-gold-400')}>
          <n.icon size={18} strokeWidth={1.75} />
          <span className="flex items-center gap-1">{n.label}<StatusDot tone={st[n.key]?.tone ?? 'idle'} title={st[n.key]?.title} pulse={st[n.key]?.tone === 'busy'} /></span>
          <span className="absolute top-1 right-2 text-[0.58rem] text-ink-600 font-mono">{i + 1}</span>
        </NavLink>
      ))}
      <div className="mt-auto px-2 pb-1 text-[0.58rem] text-ink-600 text-center leading-tight">{MOCK ? 'MOCK MODE' : 'localhost:8787'}</div>
    </nav>
  )
}

const TITLES: Record<string, string> = { '/project': 'Project', '/characters': 'Characters', '/canvas': 'Canvas', '/typography': 'Typography', '/script': 'Script', '/pages': 'Pages', '/director': 'Art Director', '/silhouettes': 'Silhouettes', '/export': 'Export', '/motion': 'Motion & Links' }

export function Header({ right }: { right?: ReactNode }) {
  const loc = useLocation()
  const project = useProject().data
  const ledger = useLedger().data
  const t = Object.keys(TITLES).find(k => loc.pathname.startsWith(k))
  return (
    <header className="h-11 shrink-0 border-b border-ink-800 bg-ink-900 flex items-center px-3 gap-3">
      <div className="flex items-baseline gap-2 min-w-0">
        <span className="text-xs font-semibold text-ink-100 truncate">{project?.title ?? 'Dharma Studio'}</span>
        <span className="text-ink-600">/</span>
        <span className="text-xs text-ink-300">{t ? TITLES[t] : ''}</span>
      </div>
      <div className="flex-1" />
      {right}
      <TextSize />
      {ledger && <span className="font-mono text-2xs text-ink-400" title="Ledger total">ledger ${ledger.total.toFixed(2)}</span>}
      <JobsTray />
    </header>
  )
}

/** A− / A / A+ : the app's text size (scales the rem root; remembered in this browser). */
export function TextSize() {
  const { step, set } = useUiScale()
  return (
    <div className="flex items-center rounded border border-ink-600 overflow-hidden" title={`Text size ${Math.round(UI_STEPS[step] * 100)}%`}>
      <button className="h-7 px-2 text-xs text-ink-300 hover:bg-ink-800 disabled:opacity-40" disabled={step === 0} onClick={() => set(step - 1)} aria-label="Smaller text">A−</button>
      <button className={cx('h-7 px-2 text-sm border-x border-ink-600', step === UI_DEFAULT ? 'text-gold-300' : 'text-ink-300 hover:bg-ink-800')} onClick={() => set(UI_DEFAULT)} aria-label="Default text size">A</button>
      <button className="h-7 px-2 text-base text-ink-300 hover:bg-ink-800 disabled:opacity-40" disabled={step === UI_STEPS.length - 1} onClick={() => set(step + 1)} aria-label="Larger text">A+</button>
    </div>
  )
}

export function JobsTray() {
  const { data: jobs = [] } = useActiveJobs()
  const [open, setOpen] = useState(false)
  const stop = useStopJob()
  const qc = useQueryClient()
  const prevActive = useRef<string>('')
  const active = jobs.filter(jobIsActive)
  // When a job leaves the active set, refresh everything it may have touched.
  useEffect(() => {
    const key = active.map(j => j.id).join(',')
    if (prevActive.current && prevActive.current !== key) qc.invalidateQueries()
    prevActive.current = key
  }, [active.map(j => j.id).join(','), qc]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="relative">
      <button className={cx('btn btn-sm', active.length > 0 && 'border-sky-500/50 text-sky-200')} onClick={() => setOpen(o => !o)} title="Jobs">
        {active.length ? <Loader2 size={12} className="animate-spin" /> : <Activity size={12} />}
        <span>{active.length ? `${active.length} running` : 'jobs'}</span>
      </button>
      {open && (
        <div className="absolute right-0 top-8 w-[23.75rem] card shadow-xl shadow-black/60 z-40">
          <div className="panel-h justify-between"><span>Jobs</span><button className="btn btn-ghost btn-sm btn-icon" onClick={() => setOpen(false)}><X size={12} /></button></div>
          <div className="max-h-[60vh] overflow-auto divide-y divide-ink-800">
            {jobs.length === 0 && <div className="p-4 text-xs text-ink-500 italic">No active jobs.</div>}
            {jobs.map(j => {
              const f = jobFraction(j)
              const p = j.progress
              return (
                <div key={j.id} className="p-2.5 text-xs">
                  <div className="flex items-center gap-2">
                    {jobIsActive(j) ? <Loader2 size={12} className="animate-spin text-sky-300 shrink-0" /> : <Check size={12} className="text-emerald-400 shrink-0" />}
                    <span className="truncate flex-1">{j.label ?? `${j.kind} #${j.id}`}</span>
                    <span className="font-mono text-2xs text-ink-400">{typeof p === 'number' ? `${Math.round(f * 100)}%` : `${p.done}/${p.total}`}</span>
                    {jobIsActive(j) && <button className="btn btn-sm btn-icon" title="Stop" onClick={() => stop.mutate(j.id)}><Square size={10} /></button>}
                  </div>
                  <ProgressBar value={f} tone={jobIsActive(j) ? 'sky' : 'gold'} className="mt-1.5" />
                  {typeof p !== 'number' && (
                    <div className="mt-1 grid grid-cols-4 gap-1 text-2xs font-mono text-ink-400">
                      <span>page <b className="text-ink-200">{p.page}</b></span><span>panel <b className="text-ink-200">{p.panel}</b></span><span>{p.done}/{p.total} panels</span><span>${p.cost_so_far.toFixed(2)}</span>
                    </div>
                  )}
                  {j.log && <pre className="mt-1 max-h-16 overflow-auto text-2xs leading-4 text-ink-500 font-mono whitespace-pre-wrap">{j.log.split('\n').slice(-3).join('\n')}</pre>}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export function Toasts() {
  const { toasts, dismiss } = useToasts()
  return (
    <div className="fixed bottom-3 right-3 z-[60] flex flex-col gap-2 w-[22.5rem]">
      {toasts.map(t => (
        <div key={t.id} className={cx('card p-3 pr-8 relative text-xs shadow-xl shadow-black/60 border-l-2', t.kind === 'gate' ? 'border-l-amber-400' : t.kind === 'error' ? 'border-l-red-500' : t.kind === 'ok' ? 'border-l-emerald-400' : 'border-l-sky-400')}>
          <div className="flex items-start gap-2">
            {t.kind === 'gate' ? <ShieldAlert size={14} className="text-amber-400 shrink-0 mt-0.5" /> : t.kind === 'error' ? <AlertTriangle size={14} className="text-red-400 shrink-0 mt-0.5" /> : t.kind === 'ok' ? <Check size={14} className="text-emerald-400 shrink-0 mt-0.5" /> : <Info size={14} className="text-sky-300 shrink-0 mt-0.5" />}
            <div className="min-w-0"><div className="font-medium text-ink-100">{t.title}</div>{t.message && <div className="text-ink-300 mt-0.5 break-words">{t.message}</div>}</div>
          </div>
          <button className="absolute top-2 right-2 text-ink-500 hover:text-ink-200" onClick={() => dismiss(t.id)}><X size={12} /></button>
        </div>
      ))}
    </div>
  )
}
