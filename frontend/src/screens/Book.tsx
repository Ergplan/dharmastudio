import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BookOpenCheck, Upload, Download, Package, Undo2, Plus, Trash2, Copy, FilePlus2, ImagePlus, ExternalLink, FolderOpen, FileImage, Type, ChevronDown, MessageSquarePlus, MessageSquare, CheckCircle2, Flag, SkipForward, RotateCcw, Check, FileText } from 'lucide-react'
import { cx, Empty, Modal, Spinner, JobProgress } from '@/components/ui'
import { toast } from '@/store/toasts'
import { BookCanvas, type Selection } from '@/components/book/BookCanvas'
import { LayerToggles, LayersList, TextInspector, ArtInspector, PaperInspector, PageHistory, PatchInspector } from '@/components/book/BookInspector'
import { CommentsPanel, PageStatusControl, ApproveAnyway, STATUS_TONE } from '@/components/book/BookComments'
import { anchorLabel } from '@/components/book/targets'
import {
  useBooks, useBook, useBookPage, useBookRender, usePageEdit, bookApi, useAddPage, useAddPageFromImage, useDeletePage, useReorder, useBookUndo,
  useExportPdf, useExportPackage, useBookExports, useCandidates, useImportPath, useImportUpload, fmtBytes, STYLE_LABEL,
  useFigures, usePageHistory, useBookRenderBefore, conflictOf, STATUS_LABEL,
  type Book, type BookPage, type TextBox, type TextStyle, type LayerKey, type Anchor, type BookComment,
} from '@/components/book/api'
import type { CommentProps } from '@/components/book/BookCanvas'

const LS = 'dharma.book.v1'
const load = (): { book?: string; page?: string } => { try { return JSON.parse(localStorage.getItem(LS) ?? '{}') } catch { return {} } }
const save = (v: { book?: string; page?: string }) => { try { localStorage.setItem(LS, JSON.stringify(v)) } catch { /* private window */ } }
const META_ACTIONS = ['add comment', 'edit comment', 'dismiss comment', 'reopen comment', 'delete comment', 'status:']  // backend/book_comments.py
const KEPT = 'dharma.book.kept.v1'  // applied comments whose before / after review the author closed with Keep
const loadKept = (): string[] => { try { return JSON.parse(localStorage.getItem(KEPT) ?? '[]') } catch { return [] } }

/** Comment-mode state shared by the canvas (pins, popover) and the inspector (Comments panel). */
interface CommentState { mode: boolean; setMode: (v: boolean) => void; active: string | null; setActive: (id: string | null) => void; pending: Anchor | null; setPending: (a: Anchor | null) => void; run: number | null; setRun: (j: number | null) => void }

/**
 * Book — the finished book, page by page, as three layers (paper · art · text) that can each be edited, hidden,
 * added or removed. The book is a local package imported at runtime (it never ships with the app).
 */
export default function BookScreen() {
  const { data: books, isLoading } = useBooks()
  const [bid, setBid] = useState<string | null>(load().book ?? null)
  const [pid, setPid] = useState<string | null>(load().page ?? null)
  const [sel, setSel] = useState<Selection>(null)
  const [importOpen, setImportOpen] = useState(false)
  useEffect(() => { if (books && (!bid || !books.some(b => b.id === bid))) setBid(books[0]?.id ?? null) }, [books]) // eslint-disable-line react-hooks/exhaustive-deps
  const { data: book } = useBook(bid)
  const lastIdx = useRef(0)  // when the current page disappears (deleted, undone), stay at the same place in the book
  useEffect(() => {
    if (!book) return
    const i = book.pages_list.findIndex(p => p.id === pid)
    if (i >= 0) lastIdx.current = i
    else setPid(book.pages_list[Math.min(lastIdx.current, book.pages_list.length - 1)]?.id ?? null)
  }, [book, pid]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => save({ book: bid ?? undefined, page: pid ?? undefined }), [bid, pid])
  useEffect(() => setSel(null), [pid])
  const [mode, setMode] = useState(false)
  const [active, setActive] = useState<string | null>(null)
  const [pending, setPending] = useState<Anchor | null>(null)
  const [run, setRun] = useState<number | null>(null)
  useEffect(() => { setActive(null); setPending(null) }, [pid])
  const cs: CommentState = { mode, setMode: (v) => { setMode(v); if (!v) setPending(null) }, active, setActive, pending, setPending, run, setRun }
  const live = book?.pages_list.some(p => p.id === pid) ? pid : null  // never ask for a page that just left the book
  const { data: page } = useBookPage(bid, live)
  const { data: html } = useBookRender(bid, live, page?.rev)

  if (isLoading) return <Spinner />
  if (!books?.length || !bid) return (
    <div className="h-full grid place-items-center">
      <div className="max-w-md text-center flex flex-col items-center gap-3">
        <BookOpenCheck size={28} className="text-gold-300" />
        <div className="text-sm text-ink-100">No book imported yet</div>
        <div className="text-xs text-ink-400">Import the layered book package (<span className="font-mono">.dharmabook</span>, a .zip, or its folder). It is copied into the studio's data folder on this Mac; nothing is uploaded and nothing is added to the app.</div>
        <button className="btn btn-primary" onClick={() => setImportOpen(true)}><Upload size={12} />Import book…</button>
      </div>
      {importOpen && <ImportDialog onClose={() => setImportOpen(false)} onImported={(b) => { setBid(b.id); setPid(b.pages_list[0]?.id ?? null); setImportOpen(false) }} />}
    </div>
  )
  return (
    <div className="h-full flex flex-col min-h-0">
      <TopBar book={book ?? null} books={books} bid={bid} pid={pid} setBid={(id) => { setBid(id); setPid(null) }} onImport={() => setImportOpen(true)} onUndone={(p) => { if (p) setPid(p) }} />
      {!book ? <Spinner /> : (
        <div className="flex-1 min-h-0 flex">
          <PageStrip book={book} pid={pid} onPick={setPid} />
          <div className="flex-1 min-w-0 flex flex-col">
            {page ? <Centre book={book} page={page} html={html} sel={sel} setSel={setSel} cs={cs} /> : <Spinner />}
          </div>
          <div className="w-[21rem] shrink-0 border-l border-ink-800 bg-ink-900/40 overflow-auto">
            {page && <Inspector book={book} page={page} sel={sel} setSel={setSel} cs={cs} />}
          </div>
        </div>
      )}
      {importOpen && <ImportDialog onClose={() => setImportOpen(false)} onImported={(b) => { setBid(b.id); setPid(b.pages_list[0]?.id ?? null); setImportOpen(false) }} />}
    </div>
  )
}

function TopBar({ book, books, bid, pid, setBid, onImport, onUndone }: { book: Book | null; books: { id: string; title: string; volume: string }[]; bid: string; pid: string | null; setBid: (id: string) => void; onImport: () => void; onUndone: (pid: string | null) => void }) {
  const [paper, setPaper] = useState<'print' | 'screen'>('print')
  const [job, setJob] = useState<number | null>(null)
  const [done, setDone] = useState<{ url: string; name: string } | null>(null)
  const pdf = useExportPdf(bid, (r) => { setJob(r.job_id); setDone(null) })
  const pkg = useExportPackage(bid, (r) => { setDone({ url: r.url, name: r.name }); toast('ok', 'Package written', r.path) })
  const undo = useBookUndo(bid, (r) => { toast('info', 'Undone', r.undone); if (r.pid && r.book.pages_list.some(p => p.id === r.pid)) onUndone(r.pid) })
  const { data: exports = [] } = useBookExports(bid)
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) { e.preventDefault(); if (book?.undo) undo.mutate(undefined) }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [book?.undo, undo])
  return (
    <div className="shrink-0 border-b border-ink-800 bg-ink-900">
      <div className="h-10 flex items-center gap-2 px-2">
        <BookOpenCheck size={14} className="text-gold-300" />
        <select className="select h-7 w-64 text-xs" value={bid} onChange={(e) => setBid(e.target.value)} aria-label="Book">
          {books.map(b => <option key={b.id} value={b.id}>{b.title} — {b.volume}</option>)}
        </select>
        {book && <span className="text-2xs text-ink-500">{book.pages} pages · {book.trim_mm[0]}×{book.trim_mm[1]} mm + {book.bleed_mm} mm bleed</span>}
        <span className="flex-1" />
        {book?.progress && <ProgressPill book={book} />}
        {book && <FinishButton book={book} onJob={(j) => { setJob(j); setDone(null) }} onPackage={(p) => setDone(p)} />}
        <button className="btn" onClick={onImport}><Upload size={12} />Import</button>
        <div className="flex items-center rounded border border-ink-600 overflow-hidden">
          <select className="h-7 bg-ink-800 text-xs text-ink-200 px-1.5 border-r border-ink-600 outline-none" value={paper} onChange={(e) => setPaper(e.target.value as 'print' | 'screen')} aria-label="PDF paper">
            <option value="print">Print (bleed + crop marks)</option><option value="screen">Screen (trim)</option>
          </select>
          <button className="h-7 px-2.5 text-xs text-gold-300 bg-gold-500/10 hover:bg-gold-500/20 flex items-center gap-1.5" onClick={() => pdf.mutate(paper)} disabled={pdf.isPending}><Download size={12} />Export PDF</button>
        </div>
        <button className="btn" onClick={() => pkg.mutate(undefined)} disabled={pkg.isPending} title="Write a .dharmabook of the book as it is now"><Package size={12} />Export package</button>
        {pid && <a className="btn" href={`/api/book/books/${bid}/pages/${pid}/png`} download title="This page as a PNG at full resolution"><FileImage size={12} />PNG</a>}
        <button className="btn" onClick={() => undo.mutate(undefined)} disabled={!book?.undo || undo.isPending} title={`Undo the last change (⌘Z) · ${book?.undo ?? 0} in history`}><Undo2 size={12} />Undo</button>
      </div>
      {(job || done || exports.length > 0) && (
        <div className="px-2 pb-2 flex items-center gap-2 flex-wrap">
          {job && <div className="w-80"><JobProgress compact jobId={job} onDone={(j) => { const r = j.result as { url?: string; pdf?: string }; if (r?.url) setDone({ url: r.url, name: (r.pdf ?? '').split('/').pop() ?? 'book.pdf' }) }} /></div>}
          {done && <a className="chip chip-on" href={done.url} target="_blank" rel="noreferrer"><ExternalLink size={10} />{done.name}</a>}
          {exports.slice(0, 4).filter(e => e.url !== done?.url).map(e => <a key={e.name} className="chip" href={e.url} target="_blank" rel="noreferrer" title={e.modified}>{e.name} · {fmtBytes(e.bytes)}</a>)}
        </div>
      )}
    </div>
  )
}

function ProgressPill({ book }: { book: Book }) {
  const p = book.progress
  const f = p.pages ? p.approved / p.pages : 0
  return (
    <div className="flex items-center gap-2 mr-1" data-testid="book-progress" title={`${p.approved} approved · ${p.review} in review · ${p.draft} draft`}>
      <div className="w-36 h-1.5 rounded-full bg-ink-800 overflow-hidden flex">
        <div className="h-full bg-emerald-400" style={{ width: `${f * 100}%` }} />
        <div className="h-full bg-sky-400/60" style={{ width: `${p.pages ? p.review / p.pages * 100 : 0}%` }} />
      </div>
      <span className="text-2xs text-ink-300 whitespace-nowrap"><b className="text-emerald-300 font-mono">{p.approved}</b> / {p.pages} approved, <b className={cx('font-mono', p.open_comments ? 'text-gold-300' : 'text-ink-400')}>{p.open_comments}</b> open comment{p.open_comments === 1 ? '' : 's'}</span>
    </div>
  )
}

function FinishButton({ book, onJob, onPackage }: { book: Book; onJob: (j: number) => void; onPackage: (p: { url: string; name: string }) => void }) {
  const [warn, setWarn] = useState<{ unapproved: { id: string; number: number }[]; open_comments: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const go = async (force: boolean) => {
    setBusy(true)
    try {
      const r = await bookApi.finish(book.id, force)
      setWarn(null); onJob(r.job_id); onPackage({ url: r.package.url, name: r.package.name })
      toast('ok', 'Finishing the comic', `print PDF rendering · ${r.package.name} written`)
    } catch (e) {
      const c = conflictOf<{ unapproved: { id: string; number: number }[]; open_comments: number }>(e)
      if (c?.unapproved) setWarn(c)
      else toast('error', 'Finish failed', (e as Error).message)
    } finally { setBusy(false) }
  }
  const all = book.progress.approved === book.progress.pages
  return (
    <>
      <button className={cx('btn', all && 'btn-primary')} onClick={() => go(false)} disabled={busy} title="Export the print PDF + package of the finished comic (every page approved)"><Flag size={12} />Finish</button>
      {warn && (
        <Modal title="Not every page is approved" onClose={() => setWarn(null)} width="max-w-md">
          <div className="text-xs text-ink-300 mb-2"><b>{warn.unapproved.length}</b> of {book.pages} pages are not approved{warn.open_comments ? <>, and <b>{warn.open_comments}</b> comments are still open</> : ''}:</div>
          <div className="max-h-40 overflow-auto font-mono text-2xs text-ink-400 mb-3 leading-5">{warn.unapproved.map(u => u.number).join(', ')}</div>
          <div className="flex justify-end gap-2"><button className="btn" onClick={() => setWarn(null)}>Keep reviewing</button><button className="btn btn-primary" disabled={busy} onClick={() => go(true)}><Flag size={12} />Export anyway</button></div>
        </Modal>
      )}
    </>
  )
}

type StripFilter = 'all' | 'open' | 'unapproved'

function PageStrip({ book, pid, onPick }: { book: Book; pid: string | null; onPick: (id: string) => void }) {
  const [filter, setFilter] = useState<StripFilter>('all')
  const [drag, setDrag] = useState<string | null>(null)
  const [over, setOver] = useState<{ id: string; after: boolean } | null>(null)
  const [menu, setMenu] = useState(false)
  const [confirm, setConfirm] = useState<string | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const reorder = useReorder(book.id)
  const add = useAddPage(book.id, (p) => { onPick(p.id); toast('ok', `Page ${p.number} added`) })
  const addImg = useAddPageFromImage(book.id, (p) => { onPick(p.id); toast('ok', `Page ${p.number} added from the image`) })
  const del = useDeletePage(book.id)
  const all = book.pages_list
  const list = filter === 'open' ? all.filter(p => p.open_comments > 0 || p.id === pid) : filter === 'unapproved' ? all.filter(p => p.status !== 'approved' || p.id === pid) : all
  const nextOpen = () => {
    const i = all.findIndex(p => p.id === pid)
    const n = [...all.slice(i + 1), ...all.slice(0, i + 1)].find(p => p.open_comments > 0 && p.id !== pid)
    if (n) onPick(n.id); else toast('info', 'No other page with open comments')
  }
  const active = useRef<HTMLButtonElement>(null)
  useEffect(() => { active.current?.scrollIntoView({ block: 'nearest' }) }, [pid])
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return
      const i = list.findIndex(p => p.id === pid)
      if (e.key === 'PageDown' && i < list.length - 1) { e.preventDefault(); onPick(list[i + 1].id) }
      if (e.key === 'PageUp' && i > 0) { e.preventDefault(); onPick(list[i - 1].id) }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [list, pid, onPick])
  const drop = () => {
    if (!drag || !over || drag === over.id) { setDrag(null); setOver(null); return }
    const ids = list.map(p => p.id).filter(x => x !== drag)
    const at = ids.indexOf(over.id) + (over.after ? 1 : 0)
    ids.splice(at, 0, drag)
    reorder.mutate(ids)
    setDrag(null); setOver(null)
  }
  const doomed = list.find(p => p.id === confirm)
  return (
    <div className="w-[11.5rem] shrink-0 border-r border-ink-800 flex flex-col min-h-0" data-testid="page-strip">
      <div className="panel-h justify-between relative">
        <span>Pages <span className="text-ink-500 font-normal">{list.length}</span></span>
        <button className="btn btn-sm btn-primary" onClick={() => setMenu(m => !m)}><Plus size={11} />Add page<ChevronDown size={10} /></button>
        {menu && (
          <div className="absolute right-2 top-8 z-30 card shadow-xl shadow-black/60 w-48 py-1" onMouseLeave={() => setMenu(false)}>
            <button className="w-full text-left px-3 py-1.5 text-xs hover:bg-ink-800 flex items-center gap-2" onClick={() => { setMenu(false); add.mutate({ mode: 'blank', after: pid ?? undefined }) }}><FilePlus2 size={12} />Blank page</button>
            <button className="w-full text-left px-3 py-1.5 text-xs hover:bg-ink-800 flex items-center gap-2 disabled:opacity-40" disabled={!pid} onClick={() => { setMenu(false); if (pid) add.mutate({ mode: 'duplicate', source: pid, after: pid }) }}><Copy size={12} />Duplicate this page</button>
            <button className="w-full text-left px-3 py-1.5 text-xs hover:bg-ink-800 flex items-center gap-2" onClick={() => { setMenu(false); file.current?.click() }}><ImagePlus size={12} />From an image…</button>
          </div>
        )}
        <input ref={file} type="file" accept="image/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) addImg.mutate({ file: f, after: pid ?? undefined }); e.target.value = '' }} />
      </div>
      <div className="px-2 py-1.5 border-b border-ink-800 flex flex-col gap-1.5" data-testid="strip-filters">
        <div className="flex gap-1">
          {([['all', 'All'], ['open', 'Comments'], ['unapproved', 'Not approved']] as [StripFilter, string][]).map(([k, l]) => (
            <button key={k} className={cx('chip flex-1 justify-center', filter === k && 'chip-on')} onClick={() => setFilter(k)}>{l}</button>
          ))}
        </div>
        <button className="btn btn-sm justify-center" onClick={nextOpen} disabled={!all.some(p => p.open_comments > 0)} title="Next page with open comments"><SkipForward size={11} />Next with comments</button>
      </div>
      <div className="flex-1 overflow-auto p-2 flex flex-col gap-2" onDragOver={(e) => e.preventDefault()} onDrop={drop}>
        {list.map(p => (
          <div key={p.id} className="relative group"
            draggable onDragStart={(e) => { setDrag(p.id); e.dataTransfer.effectAllowed = 'move' }} onDragEnd={() => { setDrag(null); setOver(null) }}
            onDragOver={(e) => { e.preventDefault(); const r = (e.currentTarget as HTMLElement).getBoundingClientRect(); setOver({ id: p.id, after: e.clientY > r.top + r.height / 2 }) }}>
            {p.status === 'approved' && <div className="absolute left-1.5 top-1.5 z-10 w-4 h-4 rounded-full bg-emerald-500 grid place-items-center pointer-events-none"><Check size={10} className="text-ink-950" /></div>}
            {over?.id === p.id && drag && drag !== p.id && <div className={cx('absolute left-0 right-0 h-0.5 bg-gold-400 z-10', over.after ? '-bottom-1.5' : '-top-1.5')} />}
            <button ref={p.id === pid ? active : undefined} onClick={() => onPick(p.id)} data-page={p.id}
              className={cx('w-full rounded border p-1 flex gap-2 items-start text-left', p.id === pid ? 'border-gold-500/70 bg-gold-500/10' : 'border-ink-700 hover:border-ink-500', drag === p.id && 'opacity-40')}>
              <img src={p.thumb} alt="" loading="lazy" className="w-[4.5rem] aspect-[2/3] object-cover rounded-sm bg-ink-800 shrink-0" draggable={false} />
              <div className="min-w-0 flex-1 pt-0.5">
                <div className="text-xs font-mono text-ink-100">{p.number}</div>
                <div className="text-2xs text-ink-500 truncate">{p.header ?? p.template ?? ''}</div>
                <div className="text-2xs text-ink-500">{p.texts} text{p.texts === 1 ? '' : 's'}{p.has_art ? '' : ' · no art'}</div>
                <div className={cx('text-2xs flex items-center gap-1', STATUS_TONE[p.status ?? 'draft'])} data-status={p.status}>
                  {p.status === 'approved' ? <CheckCircle2 size={10} /> : <span className="w-1.5 h-1.5 rounded-full bg-current" />}{STATUS_LABEL[p.status ?? 'draft']}
                </div>
                {p.open_comments > 0 && <div className="text-2xs text-gold-300 flex items-center gap-1"><MessageSquare size={10} />{p.open_comments} open</div>}
                {(!p.layers.paper || !p.layers.art || !p.layers.text) && <div className="text-2xs text-amber-300/80">hidden: {(['paper', 'art', 'text'] as LayerKey[]).filter(k => !p.layers[k]).join(', ')}</div>}
              </div>
            </button>
            <button className="absolute right-1 bottom-1 btn btn-ghost btn-sm btn-icon opacity-0 group-hover:opacity-100 text-red-300" title={`Delete page ${p.number}`} onClick={() => setConfirm(p.id)}><Trash2 size={11} /></button>
          </div>
        ))}
      </div>
      {doomed && (
        <Modal title={`Delete page ${doomed.number}?`} onClose={() => setConfirm(null)} width="max-w-sm">
          <div className="text-xs text-ink-300 mb-3">The page and its text boxes leave the book; the pages after it are renumbered. <b>Undo</b> brings it back.</div>
          <div className="flex justify-end gap-2">
            <button className="btn" onClick={() => setConfirm(null)}>Cancel</button>
            <button className="btn btn-danger" onClick={() => {
              const i = list.findIndex(x => x.id === doomed.id)
              if (doomed.id === pid) onPick((list[i + 1] ?? list[i - 1])?.id)
              del.mutate(doomed.id); setConfirm(null)
            }}><Trash2 size={12} />Delete page</button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function Centre({ book, page, html, sel, setSel, cs }: { book: Book; page: BookPage; html: string | undefined; sel: Selection; setSel: (s: Selection) => void; cs: CommentState }) {
  const edit = usePageEdit(book.id, (f: () => Promise<BookPage>) => f())
  const { data: figs = [] } = useFigures()
  const aspects = useMemo(() => Object.fromEntries(figs.map(f => [f.name, f.aspect])), [figs])
  const [askApprove, setAskApprove] = useState<number | null>(null)
  const approve = (force = false) => edit.mutate(async () => {
    try { return await bookApi.status(book.id, page.id, 'approved', force) } catch (e) {
      const c = conflictOf<{ open_comments: number }>(e)
      if (c?.open_comments) { setAskApprove(c.open_comments); return page }
      throw e
    }
  })
  const submit = (anchor: Anchor, text: string, apply: boolean) => edit.mutate(async () => {
    const r = await bookApi.addComment(book.id, page.id, { anchor, text })
    cs.setActive(r.created)
    if (apply) { try { cs.setRun((await bookApi.applyComment(book.id, page.id, r.created)).job_id) } catch (e) { toast('error', 'Not applied', (e as Error).message) } }
    return r
  })
  const comment: CommentProps = { on: cs.mode, comments: page.comments, active: cs.active, aspects, pending: cs.pending, setPending: cs.setPending, onSubmit: submit,
    onPick: (id) => { cs.setActive(id); const c = page.comments.find(x => x.id === id); if (c) setSel(selOf(c)) } }
  // C toggles comment mode
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable) || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'c' || e.key === 'C') { e.preventDefault(); cs.setMode(!cs.mode) }
      else if (e.key === 'Escape' && cs.mode) { if (cs.pending) cs.setPending(null); else cs.setMode(false) }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [cs])
  // before / after of the last applied comment (while it is still the page's last change)
  const { data: hist = [] } = usePageHistory(book.id, page.id)
  const lastSeq = hist.find(h => h.kind === 'page' && !META_ACTIONS.some(m => h.action.startsWith(m)))?.seq  // comment / status steps do not end the review
  const last = page.comments.filter(c => c.status === 'applied' && c.result?.history_seq).sort((a, b) => (b.result!.history_seq! - a.result!.history_seq!))[0]
  const [kept, setKept] = useState<string[]>(loadKept)
  const review = last && last.result?.history_seq === lastSeq && !kept.includes(`${book.id}:${last.id}`) ? last : null
  const [showBefore, setShowBefore] = useState(false)
  useEffect(() => setShowBefore(false), [review?.id, page.id])
  const { data: beforeHtml } = useBookRenderBefore(book.id, page.id, review && showBefore ? review.result!.history_seq! : null)
  const keep = () => { const k = [...kept, `${book.id}:${review!.id}`].slice(-500); setKept(k); try { localStorage.setItem(KEPT, JSON.stringify(k)) } catch { /* ignore */ } }
  const [addMenu, setAddMenu] = useState(false)
  const toggle = (k: LayerKey, v: boolean) => edit.mutate(() => bookApi.layers(book.id, page.id, { [k]: v }))
  const commitBox = useCallback((id: string, patch: Partial<TextBox>) => edit.mutate(() => bookApi.patchText(book.id, page.id, id, patch)), [book.id, page.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const addText = (style: TextStyle) => { setAddMenu(false); edit.mutate(async () => { const r = await bookApi.addText(book.id, page.id, { style }); setSel({ type: 'text', id: r.created }); return r }) }
  // keyboard: nudge / delete the selected text box
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT') || sel?.type !== 'text') return
      const box = page.text.find(x => x.id === sel.id)
      if (!box) return
      const step = e.shiftKey ? 20 : 4
      const mv: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }
      if (mv[e.key]) { e.preventDefault(); commitBox(box.id, { x: box.x + mv[e.key][0], y: box.y + mv[e.key][1] }) }
      else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); edit.mutate(() => bookApi.deleteText(book.id, page.id, box.id)); setSel(null) }
      else if (e.key === 'Escape') setSel(null)
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [sel, page, book.id, commitBox]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <div className="h-10 shrink-0 border-b border-ink-800 bg-ink-900/60 flex items-center gap-2 px-2">
        <span className="text-xs text-ink-100 font-mono">Page {page.number}</span>
        <span className="text-2xs text-ink-500 font-mono">{page.id}</span>
        <span className="flex-1" />
        <button className={cx('btn', cs.mode && 'btn-primary')} onClick={() => cs.setMode(!cs.mode)} aria-pressed={cs.mode} title="Comment mode (C): click any element of the page to pin a comment" data-testid="comment-toggle"><MessageSquarePlus size={12} />Comment</button>
        {cs.mode && <button className="btn" onClick={() => cs.setPending({ layer: 'page', element: null, x: Math.round(book.page_px[0] / 2), y: 60 })} title="A comment on the page as a whole"><FileText size={12} />Whole page</button>}
        <LayerToggles layers={page.layers} onToggle={toggle} />
        <div className="relative">
          <button className="btn" onClick={() => setAddMenu(m => !m)}><Type size={12} />Add text<ChevronDown size={10} /></button>
          {addMenu && (
            <div className="absolute right-0 top-8 z-30 card shadow-xl shadow-black/60 w-44 py-1" onMouseLeave={() => setAddMenu(false)}>
              {(Object.keys(STYLE_LABEL) as TextStyle[]).map(s => <button key={s} className="w-full text-left px-3 py-1.5 text-xs hover:bg-ink-800" onClick={() => addText(s)}>{STYLE_LABEL[s]}</button>)}
            </div>
          )}
        </div>
        <button className={cx('btn', page.status === 'approved' ? 'text-emerald-300 border-emerald-500/50' : '')} onClick={() => approve()} disabled={page.status === 'approved'} title="Approve this page" data-testid="approve"><CheckCircle2 size={12} />{page.status === 'approved' ? 'Approved' : 'Approve'}</button>
        <a className="btn btn-ghost btn-icon" href={`/api/book/books/${book.id}/pages/${page.id}/render`} target="_blank" rel="noreferrer" title="Open the page render in a new tab"><ExternalLink size={12} /></a>
      </div>
      {review && (
        <div className="shrink-0 border-b border-ink-800 bg-emerald-950/40 px-2 h-9 flex items-center gap-2 text-xs" data-testid="before-after">
          <span className="w-5 h-5 rounded-full bg-emerald-400 text-ink-950 text-[10px] font-bold grid place-items-center">{review.n}</span>
          <span className="text-emerald-200 truncate">{review.result?.summary}</span>
          <span className="text-2xs text-ink-500 font-mono shrink-0">{anchorLabel(review.anchor, page)} · v{review.result?.history_seq} · ${(review.result?.cost ?? 0).toFixed(3)}</span>
          <span className="flex-1" />
          <div className="flex rounded border border-ink-600 overflow-hidden shrink-0">
            <button className={cx('h-6 px-2.5 text-2xs', showBefore ? 'bg-ink-700 text-ink-100' : 'text-ink-400 hover:bg-ink-800')} onClick={() => setShowBefore(true)}>Before</button>
            <button className={cx('h-6 px-2.5 text-2xs border-l border-ink-600', !showBefore ? 'bg-emerald-500/20 text-emerald-200' : 'text-ink-400 hover:bg-ink-800')} onClick={() => setShowBefore(false)}>After</button>
          </div>
          <button className="btn btn-sm shrink-0" onClick={keep}><Check size={11} />Keep</button>
          <button className="btn btn-sm shrink-0" onClick={() => edit.mutate(() => bookApi.revertComment(book.id, page.id, review.id))}><RotateCcw size={11} />Revert</button>
        </div>
      )}
      <div className="flex-1 min-h-0 relative">
        {showBefore && review && <div className="absolute left-3 top-3 z-40 chip chip-on pointer-events-none">Before comment {review.n}</div>}
        <BookCanvas book={book} page={page} html={showBefore && review ? (beforeHtml ?? html) : html} comment={showBefore ? undefined : comment} sel={sel} onSelect={setSel} onCommitBox={commitBox}
          onEditText={(box, text) => commitBox(box.id, box.style === 'header' ? { title: text, text: [box.kicker, text].filter(Boolean).join(' · ') } : { text })} />
      </div>
      <div className="h-7 shrink-0 border-t border-ink-800 px-3 flex items-center gap-4 text-2xs text-ink-500">
        <span>{cs.mode ? 'comment mode · click an element to pin a comment · drag on the painting to mark a region · Esc leaves' : 'click a box to select · drag to move · corner to resize · double-click to edit · arrows nudge · Delete removes'}</span>
        <span className="flex-1" />
        <span>C comment · PageUp / PageDown · ⌘Z undo</span>
      </div>
      {askApprove !== null && <ApproveAnyway n={askApprove} onClose={() => setAskApprove(null)} onYes={() => { setAskApprove(null); approve(true) }} />}
    </>
  )
}

function selOf(c: BookComment): Selection {
  const a = c.anchor
  if (a.layer === 'text' && a.element) return { type: 'text', id: a.element }
  if (a.layer === 'art') return a.element?.startsWith('patch:') ? { type: 'patch', id: a.element.slice(6) } : { type: 'art' }
  if (a.layer === 'paper') return { type: 'paper' }
  return null
}

function Inspector({ book, page, sel, setSel, cs }: { book: Book; page: BookPage; sel: Selection; setSel: (s: Selection) => void; cs: CommentState }) {
  const edit = usePageEdit(book.id, (f: () => Promise<BookPage>) => f())
  const box = sel?.type === 'text' ? page.text.find(t => t.id === sel.id) : undefined
  const toggle = (k: LayerKey, v: boolean) => edit.mutate(() => bookApi.layers(book.id, page.id, { [k]: v }))
  const patch = sel?.type === 'patch' ? page.art?.patches?.find(p => p.id === sel.id) : undefined
  return (
    <div className="flex flex-col">
      <PageStatusControl book={book} page={page} edit={(f) => edit.mutate(f)} />
      <CommentsPanel book={book} page={page} active={cs.active} run={cs.run} onRun={cs.setRun} edit={(f) => edit.mutate(f)}
        onPick={(c) => { cs.setActive(c.id); setSel(selOf(c)) }} />
      <LayersList page={page} sel={sel} onSelect={setSel} onToggle={toggle}
        onPatch={(id, hidden) => edit.mutate(() => bookApi.patchPatch(book.id, page.id, id, { hidden }))}
        onRemovePatch={(id) => { edit.mutate(() => bookApi.deletePatch(book.id, page.id, id)); if (sel?.type === 'patch' && sel.id === id) setSel(null) }} />
      {patch ? <PatchInspector page={page} id={patch.id} onPatch={(hidden) => edit.mutate(() => bookApi.patchPatch(book.id, page.id, patch.id, { hidden }))}
        onRemove={() => { edit.mutate(() => bookApi.deletePatch(book.id, page.id, patch.id)); setSel(null) }}
        onComment={() => { cs.setMode(true); cs.setPending({ layer: 'art', element: `patch:${patch.id}`, x: Math.round(patch.x + patch.w / 2), y: Math.round(patch.y + patch.h / 2), rect: { x: patch.x, y: patch.y, w: patch.w, h: patch.h } }) }} />
        : box ? <TextInspector box={box} onPatch={(p) => edit.mutate(() => bookApi.patchText(book.id, page.id, box.id, p))} onDelete={() => { edit.mutate(() => bookApi.deleteText(book.id, page.id, box.id)); setSel(null) }} />
        : sel?.type === 'art' ? <ArtInspector page={page} book={book} onPatch={(p) => edit.mutate(() => bookApi.art(book.id, page.id, p))} onReplace={(f) => edit.mutate(() => bookApi.replaceArt(book.id, page.id, f))} />
          : <PaperInspector page={page} onPatch={(p) => edit.mutate(() => bookApi.paper(book.id, page.id, p))} onPageNumber={(v) => edit.mutate(() => bookApi.page(book.id, page.id, { page_number: v }))} />}
      <PageHistory bid={book.id} page={page} onRestore={(seq) => edit.mutate(() => bookApi.restore(book.id, page.id, seq))} />
    </div>
  )
}

function ImportDialog({ onClose, onImported }: { onClose: () => void; onImported: (b: Book) => void }) {
  const { data: cands, isLoading } = useCandidates(true)
  const [path, setPath] = useState('')
  const file = useRef<HTMLInputElement>(null)
  const done = (b: Book) => { toast('ok', 'Book imported', `${b.title}: ${b.pages} pages`); onImported(b) }
  const byPath = useImportPath(done)
  const upload = useImportUpload(done)
  const busy = byPath.isPending || upload.isPending
  const list = useMemo(() => cands?.candidates ?? [], [cands])
  return (
    <Modal title="Import a book package" onClose={onClose} width="max-w-xl">
      <div className="flex flex-col gap-4 text-xs" data-testid="import-dialog">
        <div className="text-ink-400">A layered book package (<span className="font-mono">manifest.json</span> + <span className="font-mono">art/</span>) — a folder, a <span className="font-mono">.dharmabook</span> or a .zip. It is copied into the studio's data folder on this Mac and is never added to the app or the repository.</div>
        <div>
          <div className="label mb-1.5">Found on this Mac</div>
          {isLoading ? <Spinner label="Looking…" /> : list.length === 0
            ? <Empty>No <span className="font-mono">{cands?.name}</span> in {cands?.searched.map(s => s.replace(/^.*?\/(apps|Documents|Downloads)/, '~/$1')).join(', ')}.</Empty>
            : <div className="flex flex-col gap-1.5">{list.map(c => (
              <div key={c.path} className={cx('rounded border p-2 flex items-center gap-2', c.preferred ? 'border-gold-500/50 bg-gold-500/5' : 'border-ink-700')}>
                <Package size={14} className={c.preferred ? 'text-gold-300' : 'text-ink-400'} />
                <div className="min-w-0 flex-1"><div className="text-ink-100 truncate">{c.name}</div><div className="text-2xs text-ink-500 truncate">{c.dir} · {fmtBytes(c.bytes)} · {new Date(c.modified).toLocaleString()}</div></div>
                <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => byPath.mutate(c.path)}>Import</button>
              </div>
            ))}</div>}
        </div>
        <div>
          <div className="label mb-1.5">From a path</div>
          <div className="flex gap-2">
            <input className="input font-mono" placeholder="~/apps/dharma-pipeline/exports/book_v3  or  …/Cycle_of_Dharma_V1_V3.dharmabook" value={path} onChange={(e) => setPath(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && path.trim()) byPath.mutate(path.trim()) }} />
            <button className="btn btn-primary" disabled={!path.trim() || busy} onClick={() => byPath.mutate(path.trim())}><FolderOpen size={12} />Import</button>
          </div>
        </div>
        <div>
          <div className="label mb-1.5">Or choose a file</div>
          <input ref={file} type="file" accept=".dharmabook,.zip,application/zip" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = '' }} />
          <button className="btn" disabled={busy} onClick={() => file.current?.click()}><Upload size={12} />Choose .dharmabook / .zip…</button>
        </div>
        {busy && <Spinner label="Importing… (a full book copies a few hundred MB of art)" />}
      </div>
    </Modal>
  )
}
