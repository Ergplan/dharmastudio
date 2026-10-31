import { useEffect, useState } from 'react'
import { Brush, LayoutGrid, CheckCircle2, XCircle, CircleSlash, Sparkles, PenLine, RefreshCw, ScrollText } from 'lucide-react'
import { cx } from '@/components/ui'
import { mediaUrl } from '@/api/client'
import type { ID } from '@/api/types'
import { toast } from '@/store/toasts'
import {
  usePainted, usePaintedStyle, useSetVolumeMode, useSetPageMode, useSelectPainting, useReverify, useEditBoxes,
  type Brief, type DChapterDetail, type PageMode, type PaintedCandidate, type Run, type RunCandidate, type TextCheck,
} from './api'

/** The page-mode toggle (per volume, with a per-page override) and the house style, read-only. */
export function PageModeControl({ ch, brief }: { ch: DChapterDetail; brief: Brief }) {
  const setVol = useSetVolumeMode()
  const setPage = useSetPageMode()
  const { data: style } = usePaintedStyle()
  const page = ch.pages_list.find(p => p.id === brief.page_id)
  const effective: PageMode = brief.mode ?? page?.mode ?? ch.volume_mode
  return (
    <div className="flex flex-col gap-1.5">
      <span className="label">Page mode <span className="normal-case tracking-normal text-ink-500">(Book {ch.volume} default)</span></span>
      <div className="flex rounded border border-ink-600 overflow-hidden self-start">
        {([['painted', Brush, 'Painted page'], ['shards', LayoutGrid, 'Shards']] as const).map(([m, Icon, label]) => (
          <button key={m} className={cx('h-7 px-3 text-2xs flex items-center gap-1.5', ch.volume_mode === m ? 'bg-gold-500/20 text-gold-300' : 'text-ink-400 hover:bg-ink-800')}
            disabled={setVol.isPending} onClick={() => setVol.mutate({ vid: ch.volume_id, mode: m })}
            title={m === 'painted' ? 'The image model paints the whole page in the house style, lettering included; the critic proofreads every box' : 'The compositor: panel images cut into shards, captions typeset by the studio'}>
            <Icon size={11} />{label}
          </button>
        ))}
      </div>
      {page && (
        <label className="flex items-center gap-1.5 text-2xs text-ink-400">page {page.number}:
          <select className="select h-6 w-auto text-2xs" value={page.mode_override ?? ''} disabled={page.status === 'approved' || setPage.isPending}
            onChange={(e) => setPage.mutate({ pid: page.id, mode: (e.target.value || null) as PageMode | null })}>
            <option value="">as the book ({ch.volume_mode === 'painted' ? 'painted' : 'shards'})</option>
            <option value="painted">painted page</option>
            <option value="shards">shards</option>
          </select>
        </label>
      )}
      {effective === 'painted' && style && (
        <details className="rounded border border-ink-700 bg-ink-900 text-2xs" open>
          <summary className="cursor-pointer px-2 py-1 text-ink-300 flex items-center gap-1.5"><ScrollText size={11} className="text-gold-300" />House style · constant, used verbatim on every page</summary>
          <div className="px-2 pb-2 flex flex-col gap-1 font-book text-[0.72rem] leading-4 text-parchment-400 select-text">
            <p className="text-ink-100">{style.house_style}</p>
            <p>{style.typography}</p>
            <p>{style.pacing}</p>
            <p className="text-ink-400">{style.safe_area}</p>
            <p className="font-sans text-ink-500">{style.size[0]}×{style.size[1]} portrait, quality high · text check {style.text_model_default} (fallback {style.text_model_fallback}) · at most {style.max_box_words} words per box</p>
          </div>
        </details>
      )}
    </div>
  )
}

function TextCheckList({ v }: { v?: TextCheck }) {
  const [all, setAll] = useState(false)
  if (!v) return null
  return (
    <div className="flex flex-col gap-1 text-[0.66rem] leading-4">
      {!v.judged && <div className="italic text-amber-200/80">{v.note}</div>}
      {v.header && (
        <div className="flex gap-1.5"><Mark ok={v.header.match} judged={v.judged} /><span className="text-ink-300">header “{v.header.text}”{!v.header.match && v.judged && <> → <span className="text-red-300">“{v.header.found || '—'}”</span></>}</span></div>
      )}
      {v.boxes.map(b => (
        <div key={b.index} className="flex gap-1.5">
          <Mark ok={!!b.match} judged={v.judged} />
          <div className="min-w-0">
            <span className="text-ink-500">p{b.panel} {b.kind === 'speech' ? `${b.speaker ?? 'balloon'}:` : 'box:'} </span>
            <span className="font-book text-ink-100">“{b.text}”</span>
            {v.judged && !b.match && <div className="text-red-300">painted: “{b.found || '— missing —'}”</div>}
          </div>
        </div>
      ))}
      {v.extra.length > 0 && <div className="text-red-300">extra text: {v.extra.map(x => `“${x}”`).join(', ')}</div>}
      {v.judged && (
        <button className="self-start underline text-ink-500" onClick={() => setAll(!all)}>{all ? 'hide' : 'show'} full transcription ({v.transcription.length}) · {v.model}</button>
      )}
      {all && <pre className="whitespace-pre-wrap bg-ink-950 border border-ink-800 rounded p-1.5 text-ink-300">{v.transcription.join('\n')}</pre>}
    </div>
  )
}

function Mark({ ok, judged }: { ok: boolean; judged: boolean }) {
  if (!judged) return <CircleSlash size={11} className="shrink-0 mt-0.5 text-amber-300" />
  return ok ? <CheckCircle2 size={11} className="shrink-0 mt-0.5 text-emerald-300" /> : <XCircle size={11} className="shrink-0 mt-0.5 text-red-400" />
}

function PaintedCard({ c, pageId, selected, frozen }: { c: RunCandidate | (PaintedCandidate & { candidate_id?: number }); pageId: ID; selected: boolean; frozen: boolean }) {
  const pick = useSelectPainting()
  const recheck = useReverify()
  const id = 'candidate_id' in c && c.candidate_id !== undefined ? Number(c.candidate_id) : Number((c as PaintedCandidate).id)
  const v = c.verification
  const pass = !!v?.pass && (c.verdict?.pass ?? true)
  return (
    <div className={cx('rounded border overflow-hidden bg-ink-900 flex flex-col', selected ? 'border-gold-500 ring-1 ring-gold-500/30' : 'border-ink-700')}>
      <a className="relative block" href={mediaUrl(c.url || c.path)} target="_blank" rel="noreferrer">
        <img src={mediaUrl(c.url || c.path)} className="w-full aspect-[2/3] object-cover bg-ink-950" alt="" />
        <span className="absolute top-1 left-1 chip bg-black/70">#{id}{c.dry_run ? ' · dry run' : ''}</span>
        {selected && <span className="absolute top-1 right-1 chip chip-on bg-black/70"><Sparkles size={9} />page artifact</span>}
      </a>
      <div className="p-1.5 flex flex-col gap-1.5">
        <div className="flex items-center gap-1.5 text-2xs flex-wrap">
          {pass ? <span className="chip border-emerald-500/60 text-emerald-300"><CheckCircle2 size={9} />text exact</span>
            : !v?.judged ? <span className="chip border-amber-500/60 text-amber-300"><CircleSlash size={9} />unproven</span>
              : <span className="chip border-red-500/60 text-red-300"><XCircle size={9} />text check failed</span>}
          {v?.judged && <span className="font-mono text-ink-400">{v.boxes.filter(b => b.match).length}/{v.boxes.length} boxes</span>}
          <div className="flex-1" />
          {!selected && !frozen && <button className="btn btn-sm" disabled={pick.isPending} onClick={() => pick.mutate({ pid: pageId, candidate_id: id })}>Use this</button>}
          <button className="btn btn-sm btn-ghost" title="Re-run only the text check on this painting" disabled={recheck.isPending} onClick={() => recheck.mutate({ pid: pageId, candidate_id: id })}><RefreshCw size={10} /></button>
        </div>
        <TextCheckList v={v} />
        {c.correction && <div className="text-[0.62rem] text-orange-200">repainted with → {c.correction}</div>}
      </div>
    </div>
  )
}

/** "Edit box text": the page's boxes as fields; saving validates (verbatim, ≤14 words) and re-runs only the repaint + text check. */
function EditBoxes({ pageId, onRun, frozen }: { pageId: ID; onRun: (id: ID) => void; frozen: boolean }) {
  const { data: st } = usePainted(pageId)
  const { data: style } = usePaintedStyle()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<Record<number, string>>({})
  const edit = useEditBoxes((r) => { toast('ok', 'Repainting with the new box text', 'Only the painting and the text check run again.'); setOpen(false); onRun(r.run.id) })
  useEffect(() => { setDraft({}) }, [st?.spec])
  if (!st?.boxes.length) return null
  const max = style?.max_box_words ?? 14
  const words = (t: string) => (t.match(/[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*/gu) ?? []).length
  const changed = st.boxes.filter(b => draft[b.index] !== undefined && draft[b.index] !== b.text)
  return (
    <div className="card p-2 flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <span className="label">Box text</span>
        <span className="text-2xs text-ink-500">verbatim from the manuscript, at most {max} words per box</span>
        <div className="flex-1" />
        <button className="btn btn-sm" disabled={frozen} onClick={() => setOpen(!open)} title={frozen ? 'Approved pages are frozen' : ''}><PenLine size={10} />Edit box text</button>
      </div>
      {open && (
        <>
          {st.boxes.map(b => {
            const val = draft[b.index] ?? b.text
            const n = words(val)
            return (
              <label key={b.index} className="flex flex-col gap-0.5 text-2xs">
                <span className="text-ink-400">panel {b.panel} · {b.kind === 'speech' ? `speech balloon (${b.speaker ?? '—'})` : 'narration box'} <span className={cx('font-mono', n > max ? 'text-red-300' : 'text-ink-500')}>{n}/{max} words</span></span>
                <textarea className={cx('textarea text-2xs min-h-[2.25rem] font-book', n > max && 'border-red-500/60')} value={val} onChange={(e) => setDraft({ ...draft, [b.index]: e.target.value })} />
                {n > max && <span className="text-red-300">Over {max} words: split it into two boxes (two lines in the brief), or trim at a clause boundary with “…”.</span>}
              </label>
            )
          })}
          <button className="btn btn-primary btn-sm self-start" disabled={!changed.length || edit.isPending || changed.some(b => words(draft[b.index]) > max)}
            onClick={() => edit.mutate({ pid: pageId, boxes: changed.map(b => ({ panel: b.panel, box: b.box, text: draft[b.index] })), settings: { candidates: 1 } })}>
            <Brush size={11} /> Save, repaint &amp; re-check text
          </button>
        </>
      )}
    </div>
  )
}

/** A painted-page run: every painting with its per-box text check (✓/✗ with the transcription) and Edit box text. */
export function PaintedRunBlock({ run, onPickRun }: { run: Run; onPickRun?: (id: ID) => void }) {
  const active = run.status === 'running' || run.status === 'queued'
  const { data: st } = usePainted(run.page_id, active)
  const cands = (run.candidates ?? []).filter(c => c.mode === 'painted')
  const attempts = Array.from(new Set(cands.map(c => c.attempt))).sort()
  const prompts = run.prompts ?? []
  const [open, setOpen] = useState<number | null>(null)
  const frozen = st?.status === 'approved'
  const sel = st?.selected_id ?? null
  return (
    <div className="flex flex-col gap-3">
      {run.page_id && <EditBoxes pageId={run.page_id} onRun={(id) => onPickRun?.(id)} frozen={frozen} />}
      {attempts.map(a => {
        const pr = prompts.find(x => x.attempt === a)
        return (
          <div key={a} className="card px-3 py-2">
            <div className="flex items-center gap-2 text-2xs text-ink-400 mb-1.5">
              <span className={cx('font-mono uppercase', a ? 'text-orange-300' : 'text-violet-300')}>{a ? `repaint ${a}` : 'first painting'}</span>
              {pr && <button className="underline" onClick={() => setOpen(open === a ? null : a)}>prompt · {pr.chars} chars · refs {pr.references.join(', ') || 'none'}</button>}
            </div>
            {open === a && pr && <pre className="mb-2 max-h-72 overflow-auto whitespace-pre-wrap text-2xs leading-4 bg-ink-950 border border-ink-800 rounded p-2 text-ink-300">{pr.prompt}</pre>}
            <div className="grid grid-cols-2 xl:grid-cols-3 gap-2">
              {cands.filter(c => c.attempt === a).map(c => {
                const fresh = st?.candidates.find(x => x.id === Number(c.candidate_id))
                return <PaintedCard key={c.candidate_id} c={fresh ? { ...c, verification: fresh.verification ?? c.verification } : c} pageId={run.page_id!} selected={sel === Number(c.candidate_id)} frozen={frozen} />
              })}
            </div>
          </div>
        )
      })}
      {!cands.length && !active && <div className="text-2xs text-ink-500 italic">No painting in this run.</div>}
    </div>
  )
}
