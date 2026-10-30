import { useEffect, useRef, useState } from 'react'
import { Sparkles, Languages, ChevronDown, ChevronRight } from 'lucide-react'
import { useChapters, useChapter, usePages, useCharacters, useSavePanel, useApiMutation, type JobResp } from '@/api/hooks'
import { api } from '@/api/client'
import { STATES, SCALES, type Panel, type Page, type Character } from '@/api/types'
import { cx, Field, JobProgress, Spinner, Empty, StatusBadge, Chip } from '@/components/ui'
import { useEditor } from '@/store/editor'

export default function ScriptScreen() {
  const { data: chapters } = useChapters()
  const chapterId = useEditor(s => s.chapterId)
  const setChapter = useEditor(s => s.setChapter)
  useEffect(() => { if (chapters?.length && !chapters.some(c => c.id === chapterId)) setChapter(chapters[0].id) }, [chapters, chapterId, setChapter])
  const { data: chapter } = useChapter(chapterId)
  const { data: pages } = usePages(chapterId)
  const { data: chars = [] } = useCharacters()
  const [prefillJob, setPrefillJob] = useState<number | null>(null)
  const [hiJob, setHiJob] = useState<number | null>(null)
  const prefill = useApiMutation(() => api.post<JobResp>(`/api/chapters/${chapterId}/prefill`), [['pages']], (r) => setPrefillJob(r.job_id))
  const hindi = useApiMutation(() => api.post<JobResp>(`/api/chapters/${chapterId}/hindi`), [['pages']], (r) => setHiJob(r.job_id))
  if (!chapters) return <Spinner />
  return (
    <div className="h-full flex">
      <div className="w-[42%] shrink-0 border-r border-ink-800 flex flex-col min-h-0">
        <div className="panel-h gap-2">
          <select className="select w-auto max-w-[60%]" value={chapterId ?? ''} onChange={(e) => setChapter(Number(e.target.value))}>
            {chapters.map(c => <option key={c.id} value={c.id}>v{c.volume_id} · {c.number}. {c.title}</option>)}
          </select>
          <span className="text-ink-500 font-normal font-mono text-2xs">pp. {chapter?.pages_from}–{chapter?.pages_to}</span>
        </div>
        <div className="flex-1 overflow-auto px-6 py-5 bg-ink-900/40">
          {chapter ? <pre className="whitespace-pre-wrap font-book text-[13.5px] leading-[1.7] text-ink-200 max-w-[62ch]">{chapter.text || <span className="text-ink-500 italic">No text for this chapter.</span>}</pre> : <Spinner />}
        </div>
      </div>
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        <div className="panel-h gap-2">
          <span>Pages → panels</span>
          <span className="text-ink-500 font-normal">{pages?.length ?? 0} pages · {pages?.reduce((s, p) => s + (p.panels?.length ?? 0), 0) ?? 0} panels · autosave</span>
          <div className="flex-1" />
          <button className="btn" onClick={() => prefill.mutate(undefined)} disabled={prefill.isPending}><Sparkles size={12} /> Prefill from chapter</button>
          <button className="btn" onClick={() => hindi.mutate(undefined)} disabled={hindi.isPending}><Languages size={12} /> Draft Hindi</button>
        </div>
        {(prefillJob || hiJob) && <div className="px-3 pt-2 flex flex-col gap-2">{prefillJob && <JobProgress jobId={prefillJob} compact />}{hiJob && <JobProgress jobId={hiJob} compact />}</div>}
        <div className="flex-1 overflow-auto p-3 flex flex-col gap-3">
          {pages && pages.length === 0 && <Empty>No pages yet. “Prefill from chapter” asks the script writer to break the text into pages and panels.</Empty>}
          {pages?.map(p => <PageOutline key={p.id} page={p} chars={chars} />)}
        </div>
      </div>
    </div>
  )
}

function PageOutline({ page, chars }: { page: Page; chars: Character[] }) {
  const [open, setOpen] = useState(true)
  return (
    <section className="card">
      <button className="panel-h w-full text-left gap-2" onClick={() => setOpen(o => !o)}>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span>Page {page.number}</span>
        <StatusBadge status={page.status} />
        <span className="chip">{page.beat}</span>
        <span className="text-ink-500 font-normal ml-auto">{page.panels?.length ?? 0} panels</span>
      </button>
      {open && <div className="divide-y divide-ink-800">{page.panels?.map(pn => <PanelForm key={pn.id} panel={pn} chars={chars} pageNumber={page.number} />)}</div>}
    </section>
  )
}

function useDebouncedSave(panel: Panel) {
  const save = useSavePanel()
  const timer = useRef<number | null>(null)
  const pending = useRef<Record<string, unknown>>({})
  return (patch: Record<string, unknown>) => {
    pending.current = { ...pending.current, ...patch }
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => { const body = pending.current; pending.current = {}; save.mutate({ id: panel.id, ...(body as object) }) }, 600)
  }
}

function PanelForm({ panel, chars, pageNumber }: { panel: Panel; chars: Character[]; pageNumber: number }) {
  const [v, setV] = useState(panel)
  useEffect(() => setV(panel), [panel])
  const queue = useDebouncedSave(panel)
  const set = <K extends keyof Panel>(k: K, val: Panel[K]) => { setV(x => ({ ...x, [k]: val })); queue({ [k]: val }) }
  const toggleChar = (form: string) => set('characters', v.characters.includes(form) ? v.characters.filter(f => f !== form) : [...v.characters, form])
  return (
    <div className="p-3 grid grid-cols-12 gap-x-3 gap-y-2">
      <div className="col-span-12 flex items-center gap-2">
        <span className="font-mono text-2xs text-ink-500">PANEL {pageNumber}.{panel.n}</span>
        <span className="chip">{panel.kind}</span>
        <span className="chip">{panel.shape.kind}</span>
        {panel.hi_is_draft && <span className="chip border-amber-500/50 text-amber-300">hindi draft</span>}
        <span className="ml-auto text-2xs text-ink-500">{panel.candidates.length} candidates{panel.selected_candidate_id ? ' · selected' : ''}</span>
      </div>
      <Field label="Caption EN" className="col-span-6"><textarea className="textarea min-h-[56px]" value={v.caption_en} onChange={(e) => set('caption_en', e.target.value)} /></Field>
      <Field label="Caption HI" className="col-span-6" hint={v.hi_is_draft ? <span className="chip border-amber-500/50 text-amber-300 normal-case tracking-normal">draft</span> : undefined}><textarea className="textarea min-h-[56px]" lang="hi" value={v.caption_hi} onChange={(e) => set('caption_hi', e.target.value)} /></Field>
      <Field label="Balloon EN" className="col-span-4"><input className="input font-book" value={v.balloon_en} onChange={(e) => set('balloon_en', e.target.value)} /></Field>
      <Field label="Balloon HI" className="col-span-4"><input className="input font-book" lang="hi" value={v.balloon_hi} onChange={(e) => set('balloon_hi', e.target.value)} /></Field>
      <Field label="Speaker" className="col-span-2"><input className="input" value={v.speaker} onChange={(e) => set('speaker', e.target.value)} /></Field>
      <Field label="State" className="col-span-1"><select className="select" value={v.state} onChange={(e) => set('state', e.target.value as Panel['state'])}>{STATES.map(s => <option key={s}>{s}</option>)}</select></Field>
      <Field label="Scale" className="col-span-1"><select className="select" value={v.scale} onChange={(e) => set('scale', e.target.value as Panel['scale'])}>{SCALES.map(s => <option key={s}>{s}</option>)}</select></Field>
      <div className="col-span-12 flex flex-col gap-1">
        <span className="label">Characters</span>
        <div className="flex flex-wrap gap-1">
          {chars.map(c => <Chip key={c.id} on={v.characters.includes(c.form_key)} onClick={() => toggleChar(c.form_key)} title={c.locked ? 'locked' : 'unlocked'}><span className={cx('w-1.5 h-1.5 rounded-full', c.locked ? 'bg-emerald-400' : 'bg-amber-400')} />{c.name}<span className="text-ink-500">{c.form_key.includes('/') ? '/' + c.form_key.split('/')[1] : ''}</span></Chip>)}
          {v.characters.filter(f => !chars.some(c => c.form_key === f)).map(f => <Chip key={f} on onClick={() => toggleChar(f)} title="not in the character list">{f}</Chip>)}
        </div>
      </div>
      <Field label="Scene (the prompt's SCENE line)" className="col-span-12"><textarea className="textarea min-h-[48px]" value={v.scene} onChange={(e) => set('scene', e.target.value)} /></Field>
    </div>
  )
}
