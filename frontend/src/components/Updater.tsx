import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, RefreshCw, CheckCircle2, AlertTriangle } from 'lucide-react'
import { api } from '@/api/client'

type BuildInfo = { build: number; sha: string; built_at: string | null; desktop?: boolean; updatable?: boolean }
type Check = { current: BuildInfo; latest: BuildInfo | null; available: boolean; error?: string }
type Status = { phase: 'idle' | 'downloading' | 'installing' | 'restarting' | 'error'; progress: number; message: string }

const short = (s?: string) => (s ? s.slice(0, 7) : '—')

/** Checks GitHub once at launch (and every 6 h); shows a slim banner when a newer build exists. */
export function UpdateBanner() {
  const { data } = useQuery({ queryKey: ['app-update-check'], queryFn: () => api.get<Check>('/api/app/update/check'), refetchInterval: 6 * 3600_000, retry: false, staleTime: 3600_000 })
  const [dismissed, setDismissed] = useState(false)
  if (!data?.available || !data.current.updatable || dismissed) return null
  return (
    <div className="flex items-center gap-3 px-4 py-1.5 text-xs bg-amber-500/10 border-b border-amber-500/30 text-amber-200">
      <Download size={13} />
      <span>A new Dharma Studio is ready (build {data.latest?.build}). Your projects and keys are kept.</span>
      <UpdateButton compact />
      <button className="ml-auto opacity-60 hover:opacity-100" onClick={() => setDismissed(true)}>Later</button>
    </div>
  )
}

export function UpdateButton({ compact }: { compact?: boolean }) {
  const [st, setSt] = useState<Status | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!busy) return
    const t = setInterval(async () => {
      try { setSt(await api.get<Status>('/api/app/update/status')) } catch { /* the app is restarting */ }
    }, 700)
    return () => clearInterval(t)
  }, [busy])
  const start = async () => { setBusy(true); await api.post('/api/app/update/apply') }
  if (busy && st) {
    if (st.phase === 'error') return <span className="text-red-300 flex items-center gap-1"><AlertTriangle size={12} />{st.message}</span>
    return <span className="flex items-center gap-2"><RefreshCw size={12} className="animate-spin" />{st.message || 'Updating…'} {Math.round(st.progress * 100)}%</span>
  }
  return <button className={compact ? 'btn btn-primary !py-0.5 !px-2 !text-xs' : 'btn btn-primary'} onClick={start}>Install and restart</button>
}

/** Project screen card: current build, latest build, check now, install. */
export function UpdatesCard() {
  const ver = useQuery({ queryKey: ['app-version'], queryFn: () => api.get<BuildInfo>('/api/app/version') })
  const [chk, setChk] = useState<Check | null>(null)
  const [checking, setChecking] = useState(false)
  const run = async () => { setChecking(true); try { setChk(await api.get<Check>('/api/app/update/check')) } finally { setChecking(false) } }
  const v = ver.data
  return (
    <section className="card">
      <div className="panel-h">App &amp; updates</div>
      <div className="p-4 flex flex-col gap-2 text-xs">
        <div className="flex justify-between"><span className="text-ink-400">This Mac</span><span>build {v?.build ?? '—'} · {short(v?.sha)}</span></div>
        {chk?.latest && <div className="flex justify-between"><span className="text-ink-400">Latest on GitHub</span><span>build {chk.latest.build} · {short(chk.latest.sha)}</span></div>}
        {!v?.updatable && <div className="text-ink-500 italic">Running from source — update with git pull.</div>}
        <div className="flex items-center gap-2 mt-1">
          <button className="btn" onClick={run} disabled={checking}><RefreshCw size={12} className={checking ? 'animate-spin' : ''} /> Check for updates</button>
          {chk && !chk.error && !chk.available && <span className="flex items-center gap-1 text-emerald-300"><CheckCircle2 size={12} /> Up to date</span>}
          {chk?.error && <span className="text-amber-300">Couldn’t reach GitHub</span>}
          {chk?.available && v?.updatable && <UpdateButton />}
        </div>
      </div>
    </section>
  )
}
