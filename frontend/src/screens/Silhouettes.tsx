import { useRef, useState } from 'react'
import { Sparkles, Upload, Trash2 } from 'lucide-react'
import { useSilhouettes, useApiMutation, qk, type JobResp } from '@/api/hooks'
import { api, mediaUrl } from '@/api/client'
import { cx, Field, JobProgress, Spinner, Empty } from '@/components/ui'
import { toast } from '@/store/toasts'

export default function SilhouettesScreen() {
  const { data: sils, isLoading } = useSilhouettes()
  const [filter, setFilter] = useState<string[]>([])
  const [tags, setTags] = useState('')
  const [prompt, setPrompt] = useState('')
  const [n, setN] = useState(3)
  const [jobId, setJobId] = useState<number | null>(null)
  const [drag, setDrag] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const gen = useApiMutation(() => api.post<JobResp>('/api/silhouettes/generate', { prompt, n, tags: tags.split(',').map(s => s.trim()).filter(Boolean) }), [qk.silhouettes], (r) => setJobId(r.job_id))
  const upload = useApiMutation(async (files: File[]) => { const fd = new FormData(); files.forEach(f => fd.append('files', f)); fd.append('tags', tags); return api.post('/api/silhouettes/upload', fd) }, [qk.silhouettes], () => toast('ok', 'Uploaded'))
  const del = useApiMutation((id: number) => api.del(`/api/silhouettes/${id}`), [qk.silhouettes])
  if (isLoading || !sils) return <Spinner />
  const allTags = [...new Set(sils.flatMap(s => s.tags))].sort()
  const shown = sils.filter(s => filter.every(t => s.tags.includes(t)))
  const toggle = (t: string) => setFilter(f => f.includes(t) ? f.filter(x => x !== t) : [...f, t])
  return (
    <div className="h-full flex">
      <div className="w-[21.25rem] shrink-0 border-r border-ink-800 flex flex-col min-h-0">
        <div className="panel-h">Generate <span className="text-ink-500 font-normal">— Sunburst, ink on white, no colour, auto-keyed to PNG</span></div>
        <div className="p-3 flex flex-col gap-3">
          <Field label="Tags (comma-separated)"><input className="input" placeholder="bow, rama, weapon" value={tags} onChange={(e) => setTags(e.target.value)} /></Field>
          <Field label="Prompt"><textarea className="textarea min-h-[80px] font-ui" placeholder="Fine monochrome pencil-ink drawing of a great bow, ancient Indian, ornamental, no colour, no text." value={prompt} onChange={(e) => setPrompt(e.target.value)} /></Field>
          <div className="flex items-center gap-2">
            <select className="select w-16" value={n} onChange={(e) => setN(Number(e.target.value))}>{[1, 2, 3, 4, 6, 8].map(k => <option key={k} value={k}>{k}</option>)}</select>
            <button className="btn btn-primary flex-1" disabled={gen.isPending || (!prompt.trim() && !tags.trim())} onClick={() => gen.mutate(undefined)}><Sparkles size={12} /> Generate {n}</button>
          </div>
          {jobId && <JobProgress jobId={jobId} compact />}
        </div>
        <div className="panel-h border-t">Upload your own</div>
        <div className="p-3">
          <div onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); const fs = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/')); if (fs.length) upload.mutate(fs) }} onClick={() => fileRef.current?.click()}
            className={cx('h-24 rounded-md border-2 border-dashed grid place-items-center text-xs cursor-pointer', drag ? 'border-gold-400 bg-gold-500/10 text-gold-200' : 'border-ink-600 text-ink-400 hover:border-ink-400')}>
            <div className="text-center"><Upload size={16} className="mx-auto mb-1 opacity-70" />Drop PNGs (transparent) here<div className="text-2xs text-ink-500">tags above are applied</div></div>
            <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={(e) => { const fs = Array.from(e.target.files ?? []); if (fs.length) upload.mutate(fs); e.target.value = '' }} />
          </div>
        </div>
      </div>
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        <div className="panel-h gap-1.5 flex-wrap h-auto py-1.5">
          <span className="mr-2">Library <span className="text-ink-500 font-normal">{shown.length}/{sils.length}</span></span>
          {allTags.map(t => <button key={t} className={cx('chip', filter.includes(t) && 'chip-on')} onClick={() => toggle(t)}>{t}</button>)}
          {filter.length > 0 && <button className="btn btn-ghost btn-sm" onClick={() => setFilter([])}>clear</button>}
        </div>
        <div className="flex-1 overflow-auto p-4 grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3 content-start">
          {shown.length === 0 && <div className="col-span-full"><Empty>{sils.length ? 'No silhouettes match these tags.' : 'The library is empty — generate or upload silhouettes.'}</Empty></div>}
          {shown.map(s => (
            <div key={s.id} className="card overflow-hidden group">
              <div className="aspect-square p-2" style={{ background: 'radial-gradient(ellipse at 30% 20%, #f4ecd9 0%, #e8d9b5 60%, #d9c69a 100%)' }}><img src={mediaUrl(s.path)} alt="" className="w-full h-full object-contain" /></div>
              <div className="px-2 py-1.5 flex items-center gap-1">
                <div className="flex flex-wrap gap-0.5 flex-1 min-w-0">{s.tags.map(t => <span key={t} className="chip h-4">{t}</span>)}</div>
                <span className="text-2xs text-ink-500 font-mono">{s.source === 'uploaded' ? 'up' : 'gen'}</span>
                <button className="btn btn-sm btn-icon btn-danger opacity-0 group-hover:opacity-100" title="Delete" onClick={() => confirm('Delete this silhouette?') && del.mutate(s.id)}><Trash2 size={11} /></button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
