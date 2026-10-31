import { useEffect, useState } from 'react'
import { MessageSquare, Play, PlayCircle, X, RotateCcw, Trash2, CheckCircle2, Circle, CircleSlash, AlertTriangle, Check } from 'lucide-react'
import { cx, JobProgress, Modal } from '@/components/ui'
import { toast } from '@/store/toasts'
import { bookApi, conflictOf, STATUS_LABEL, type Book, type BookComment, type BookPage, type CommentStatus, type PageStatus } from './api'
import { anchorLabel } from './targets'

/** The page's comments: open / applied / dismissed, apply one or all (a job), dismiss, revert, delete. */
export function CommentsPanel({ book, page, active, onPick, run, onRun, edit }: {
  book: Book; page: BookPage; active: string | null; onPick: (c: BookComment) => void
  run: number | null; onRun: (jobId: number) => void; edit: (f: () => Promise<BookPage>) => void
}) {
  const [tab, setTab] = useState<CommentStatus>('open')
  const activeStatus = page.comments.find(c => c.id === active)?.status
  useEffect(() => { if (activeStatus) setTab(activeStatus) }, [active, activeStatus])
  const by = (s: CommentStatus) => page.comments.filter(c => c.status === s)
  const list = by(tab).sort((a, b) => a.n - b.n)
  const open = by('open').length
  const apply = async (c?: BookComment) => {
    try {
      const r = c ? await bookApi.applyComment(book.id, page.id, c.id) : await bookApi.applyAll(book.id, page.id)
      onRun(r.job_id)
    } catch (e) { toast('error', 'Not applied', (e as Error).message) }
  }
  return (
    <div className="p-2 border-b border-ink-800" data-testid="comments-panel">
      <div className="flex items-center gap-2 px-1 mb-1.5">
        <MessageSquare size={12} className="text-gold-300" /><span className="label flex-1">Comments</span>
        <button className="btn btn-sm btn-primary" disabled={!open} onClick={() => apply()} title="Apply every open comment on this page (one history step each)"><PlayCircle size={11} />Apply all open ({open})</button>
      </div>
      <div className="flex gap-1 px-1 mb-1.5" role="tablist">
        {(['open', 'applied', 'dismissed'] as CommentStatus[]).map(s => (
          <button key={s} role="tab" aria-selected={tab === s} onClick={() => setTab(s)}
            className={cx('chip capitalize', tab === s && 'chip-on')}>{s} {by(s).length}</button>
        ))}
      </div>
      {run && <div className="px-1 mb-1.5"><JobProgress compact jobId={run} onDone={(j) => {
        const r = j.result as { applied?: unknown[]; failed?: { error: string }[] }
        if (j.status === 'done') toast('ok', `${r?.applied?.length ?? 0} comment(s) applied`, r?.failed?.length ? `${r.failed.length} not applied` : undefined)
        else toast('error', 'Comment not applied', (j.log.split('\n').reverse().find(l => l.includes('not applied') || l.startsWith('error')) ?? '').slice(0, 200))
      }} /></div>}
      {list.length === 0 && <div className="text-2xs text-ink-500 italic px-1 py-1">{tab === 'open' ? 'No open comments. Press C (or Comment) and click an element of the page.' : `No ${tab} comments.`}</div>}
      <div className="flex flex-col gap-1 max-h-[22rem] overflow-auto">
        {list.map(c => (
          <div key={c.id} onClick={() => onPick(c)} data-comment={c.n}
            className={cx('rounded border p-1.5 cursor-pointer text-2xs', c.id === active ? 'border-gold-400/70 bg-gold-500/10' : 'border-ink-700 hover:bg-ink-800')}>
            <div className="flex items-center gap-1.5">
              <span className={cx('w-4 h-4 rounded-full grid place-items-center font-bold text-[10px] text-ink-950 shrink-0', c.status === 'applied' ? 'bg-emerald-400' : c.result?.error ? 'bg-red-400' : c.status === 'dismissed' ? 'bg-ink-500' : 'bg-gold-400')}>{c.n}</span>
              <span className="text-ink-400">{anchorLabel(c.anchor, page)}</span>
              <span className="flex-1" />
              {c.status === 'open' && <>
                <button className="btn btn-ghost btn-sm btn-icon" title="Apply (fires the engine)" onClick={(e) => { e.stopPropagation(); apply(c) }}><Play size={11} /></button>
                <button className="btn btn-ghost btn-sm btn-icon" title="Dismiss" onClick={(e) => { e.stopPropagation(); edit(() => bookApi.patchComment(book.id, page.id, c.id, { status: 'dismissed' })) }}><X size={11} /></button>
              </>}
              {c.status === 'applied' && <button className="btn btn-ghost btn-sm" title="Undo this apply" onClick={(e) => { e.stopPropagation(); edit(() => bookApi.revertComment(book.id, page.id, c.id)) }}><RotateCcw size={11} />Revert</button>}
              {c.status === 'dismissed' && <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); edit(() => bookApi.patchComment(book.id, page.id, c.id, { status: 'open' })) }}>Reopen</button>}
              {c.status !== 'applied' && <button className="btn btn-ghost btn-sm btn-icon text-red-300" title="Delete" onClick={(e) => { e.stopPropagation(); edit(() => bookApi.deleteComment(book.id, page.id, c.id)) }}><Trash2 size={11} /></button>}
            </div>
            <div className="text-ink-100 mt-0.5 whitespace-pre-wrap">{c.text}</div>
            {c.status === 'applied' && c.result?.summary && (
              <div className="mt-1 text-emerald-300/90 flex gap-1"><Check size={11} className="shrink-0 mt-px" /><span>{c.result.summary} <span className="text-ink-500 font-mono">v{c.result.history_seq} · ${(c.result.cost ?? 0).toFixed(3)}</span></span></div>
            )}
            {c.result?.notes?.map((n, i) => <div key={i} className="mt-0.5 text-amber-300/80">{n}</div>)}
            {c.status === 'open' && c.result?.error && <div className="mt-1 text-red-300 flex gap-1"><AlertTriangle size={11} className="shrink-0 mt-px" />{c.result.error}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

const ST_ICON: Record<PageStatus, typeof Circle> = { draft: Circle, review: CircleSlash, approved: CheckCircle2 }
export const STATUS_TONE: Record<PageStatus, string> = { draft: 'text-ink-400', review: 'text-sky-300', approved: 'text-emerald-300' }

/** Draft / in review / approved for the page (approving with open comments asks first). */
export function PageStatusControl({ book, page, edit }: { book: Book; page: BookPage; edit: (f: () => Promise<BookPage>) => void }) {
  const [ask, setAsk] = useState<number | null>(null)
  const set = (s: PageStatus, force = false) => edit(async () => {
    try { return await bookApi.status(book.id, page.id, s, force) } catch (e) {
      const c = conflictOf<{ open_comments: number }>(e)
      if (c?.open_comments) { setAsk(c.open_comments); return page }
      throw e
    }
  })
  return (
    <div className="p-2 border-b border-ink-800" data-testid="page-status">
      <div className="label px-1 mb-1.5">Page status</div>
      <div className="flex rounded border border-ink-600 overflow-hidden">
        {(['draft', 'review', 'approved'] as PageStatus[]).map((s, i) => {
          const I = ST_ICON[s]
          return <button key={s} onClick={() => set(s)} aria-pressed={page.status === s}
            className={cx('flex-1 h-7 text-xs flex items-center justify-center gap-1.5', i > 0 && 'border-l border-ink-600', page.status === s ? cx('bg-ink-800', STATUS_TONE[s]) : 'text-ink-500 hover:bg-ink-800')}><I size={11} />{STATUS_LABEL[s]}</button>
        })}
      </div>
      {ask !== null && <ApproveAnyway n={ask} onClose={() => setAsk(null)} onYes={() => { setAsk(null); set('approved', true) }} />}
    </div>
  )
}

export function ApproveAnyway({ n, onClose, onYes }: { n: number; onClose: () => void; onYes: () => void }) {
  return (
    <Modal title="Approve with open comments?" onClose={onClose} width="max-w-sm">
      <div className="text-xs text-ink-300 mb-3">This page still has <b>{n} open comment{n === 1 ? '' : 's'}</b>. Approve it anyway? The comments stay open.</div>
      <div className="flex justify-end gap-2"><button className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" onClick={onYes}><CheckCircle2 size={12} />Approve anyway</button></div>
    </Modal>
  )
}
