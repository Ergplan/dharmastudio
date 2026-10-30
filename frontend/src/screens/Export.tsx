import { useEffect, useState } from 'react'
import { Download, FileDown, AlertTriangle, Play } from 'lucide-react'
import { useChapters, useVolumes, useExports, useProject, useExportEstimate, useApiMutation, qk, usePages, type JobResp } from '@/api/hooks'
import { api } from '@/api/client'
import type { ExportRequest, ExportEstimate } from '@/api/types'
import { cx, Field, JobProgress, Spinner, Empty, usd, StatusDot } from '@/components/ui'

export default function ExportScreen() {
  const { data: chapters = [] } = useChapters()
  const { data: volumes = [] } = useVolumes()
  const { data: exports, isLoading } = useExports()
  const { data: project } = useProject()
  const [scope, setScope] = useState<'chapter' | 'volume'>('chapter')
  const [chapterId, setChapterId] = useState<number>(1)
  const [volumeId, setVolumeId] = useState<number>(1)
  const [langs, setLangs] = useState<('en' | 'hi')[]>(['en', 'hi'])
  const [paper, setPaper] = useState<'screen' | 'print'>('screen')
  const [upscale, setUpscale] = useState(false)
  const [est, setEst] = useState<ExportEstimate | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  const estimate = useExportEstimate()
  const req: ExportRequest = { ...(scope === 'chapter' ? { chapter_id: chapterId } : { volume_id: volumeId }), lang: langs, paper, upscale }
  const key = JSON.stringify(req)
  useEffect(() => { let alive = true; setEst(null); estimate.mutateAsync(req).then(e => alive && setEst(e)).catch(() => {}); return () => { alive = false } }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  const run = useApiMutation((r: ExportRequest) => api.post<JobResp>('/api/export', r), [qk.exports, qk.ledger], (r) => setJobId(r.job_id))
  const { data: pages = [] } = usePages(scope === 'chapter' ? chapterId : null)
  const toggleLang = (l: 'en' | 'hi') => setLangs(ls => ls.includes(l) ? ls.filter(x => x !== l) : [...ls, l])
  const topazMissing = upscale && project && !project.keys.topaz
  return (
    <div className="h-full flex">
      <div className="w-[26.25rem] shrink-0 border-r border-ink-800 flex flex-col min-h-0 overflow-auto">
        <div className="panel-h">Export <span className="text-ink-500 font-normal">— 170×260 mm + 3 mm bleed, crop marks, 300 ppi</span></div>
        <div className="p-4 flex flex-col gap-4">
          <div>
            <div className="label mb-1.5">Scope</div>
            <div className="flex gap-1.5">
              <button className={cx('btn', scope === 'chapter' && 'btn-primary')} onClick={() => setScope('chapter')}>Chapter</button>
              <button className={cx('btn', scope === 'volume' && 'btn-primary')} onClick={() => setScope('volume')}>Volume</button>
              {scope === 'chapter'
                ? <select className="select flex-1" value={chapterId} onChange={(e) => setChapterId(Number(e.target.value))}>{chapters.map(c => <option key={c.id} value={c.id}>v{c.volume_id} · {c.number}. {c.title}</option>)}</select>
                : <select className="select flex-1" value={volumeId} onChange={(e) => setVolumeId(Number(e.target.value))}>{volumes.map(v => <option key={v.id} value={v.id}>{v.title}</option>)}</select>}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Languages"><div className="flex gap-1.5">{(['en', 'hi'] as const).map(l => <button key={l} className={cx('btn flex-1 uppercase', langs.includes(l) && 'btn-primary')} onClick={() => toggleLang(l)}>{l}</button>)}</div></Field>
            <Field label="Paper"><select className="select" value={paper} onChange={(e) => setPaper(e.target.value as 'screen' | 'print')}><option value="screen">screen — paper texture in the page</option><option value="print">print — ink only, paper is the stock</option></select></Field>
          </div>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" className="accent-gold-500" checked={upscale} onChange={(e) => setUpscale(e.target.checked)} /> Upscale selected images with Topaz (plates and hero shards) {project && <span className={cx('chip', project.keys.topaz ? 'border-emerald-500/50 text-emerald-300' : 'border-amber-500/50 text-amber-300')}>{project.keys.topaz ? 'key configured' : 'key missing'}</span>}</label>
          {topazMissing && <div className="text-2xs text-amber-300 -mt-2">TOPAZ key is missing in .env — the export will be refused with upscale on.</div>}

          <div className="rounded border border-ink-700 bg-ink-900 p-3 text-xs flex flex-col gap-2">
            <div className="label">Before running</div>
            {est ? (
              <>
                <div className="flex items-center gap-2"><StatusDot tone={est.unapproved ? 'warn' : 'ok'} /><span><b className="text-ink-100">{est.approved}</b> of <b className="text-ink-100">{est.total}</b> pages approved · {est.images} images{upscale ? ' to upscale' : ''}</span><span className="ml-auto font-mono text-gold-300">≈ {usd(est.usd)}</span></div>
                {est.unapproved > 0 && <div className="flex gap-2 rounded border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-amber-200"><AlertTriangle size={14} className="shrink-0 mt-0.5" /><span><b>{est.unapproved} page{est.unapproved === 1 ? '' : 's'} unapproved</b> — only approved pages are exported. {scope === 'chapter' && pages.length > 0 && <>Unapproved: {pages.filter(p => p.status !== 'approved').map(p => p.number).join(', ')}.</>}</span></div>}
                {est.approved === 0 && <div className="text-red-300">Nothing to export: approve at least one page first.</div>}
              </>
            ) : <div className="text-ink-500">estimating…</div>}
          </div>
          <button className="btn btn-primary h-8" disabled={!est || est.approved === 0 || !langs.length || run.isPending || !!topazMissing} onClick={() => run.mutate({ ...req, allow_partial: (est?.unapproved ?? 0) > 0 })}><Play size={12} /> Export {langs.map(l => l.toUpperCase()).join(' + ')} PDF{langs.length > 1 ? 's' : ''}</button>
          {jobId && <JobProgress jobId={jobId} />}
        </div>
      </div>
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        <div className="panel-h">History <span className="text-ink-500 font-normal">{exports?.length ?? 0}</span></div>
        <div className="flex-1 overflow-auto p-4 flex flex-col gap-2">
          {isLoading && <Spinner />}
          {exports?.length === 0 && <Empty>No exports yet.</Empty>}
          {exports?.map(x => (
            <div key={x.id} className="card p-3 text-xs">
              <div className="flex items-center gap-2">
                <FileDown size={14} className="text-ink-400" />
                <span className="text-ink-100 font-medium">{x.scope}</span>
                <span className="chip uppercase">{x.lang.join(' + ')}</span><span className="chip">{x.paper}</span>{x.upscale && <span className="chip">Topaz</span>}
                <span className={cx('chip', x.status === 'done' ? 'border-emerald-500/50 text-emerald-300' : x.status === 'failed' ? 'border-red-500/50 text-red-300' : 'border-sky-500/50 text-sky-300')}>{x.status}</span>
                <span className="ml-auto font-mono text-2xs text-ink-500">{new Date(x.created_at).toLocaleString()}{x.cost_usd ? ` · ${usd(x.cost_usd)}` : ''}</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {x.files.length === 0 && <span className="text-ink-500 italic">no files yet</span>}
                {x.files.map(f => <a key={f.url} href={f.url} download className="btn btn-sm" title={f.url}><Download size={11} /> {f.name} <span className="text-ink-500">{(f.bytes / 1e6).toFixed(1)} MB</span></a>)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
