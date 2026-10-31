import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BookOpenCheck, Upload, Download, Package, Undo2, Plus, Trash2, Copy, FilePlus2, ImagePlus, ExternalLink, FolderOpen, FileImage, Type, ChevronDown } from 'lucide-react'
import { cx, Empty, Modal, Spinner, JobProgress } from '@/components/ui'
import { toast } from '@/store/toasts'
import { BookCanvas, type Selection } from '@/components/book/BookCanvas'
import { LayerToggles, LayersList, TextInspector, ArtInspector, PaperInspector, PageHistory } from '@/components/book/BookInspector'
import {
  useBooks, useBook, useBookPage, useBookRender, usePageEdit, bookApi, useAddPage, useAddPageFromImage, useDeletePage, useReorder, useBookUndo,
  useExportPdf, useExportPackage, useBookExports, useCandidates, useImportPath, useImportUpload, fmtBytes, STYLE_LABEL,
  type Book, type BookPage, type TextBox, type TextStyle, type LayerKey,
} from '@/components/book/api'

const LS = 'dharma.book.v1'
const load = (): { book?: string; page?: string } => { try { return JSON.parse(localStorage.getItem(LS) ?? '{}') } catch { return {} } }
const save = (v: { book?: string; page?: string }) => { try { localStorage.setItem(LS, JSON.stringify(v)) } catch { /* private window */ } }

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
            {page ? <Centre book={book} page={page} html={html} sel={sel} setSel={setSel} /> : <Spinner />}
          </div>
          <div className="w-[21rem] shrink-0 border-l border-ink-800 bg-ink-900/40 overflow-auto">
            {page && <Inspector book={book} page={page} sel={sel} setSel={setSel} />}
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

function PageStrip({ book, pid, onPick }: { book: Book; pid: string | null; onPick: (id: string) => void }) {
  const [drag, setDrag] = useState<string | null>(null)
  const [over, setOver] = useState<{ id: string; after: boolean } | null>(null)
  const [menu, setMenu] = useState(false)
  const [confirm, setConfirm] = useState<string | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const reorder = useReorder(book.id)
  const add = useAddPage(book.id, (p) => { onPick(p.id); toast('ok', `Page ${p.number} added`) })
  const addImg = useAddPageFromImage(book.id, (p) => { onPick(p.id); toast('ok', `Page ${p.number} added from the image`) })
  const del = useDeletePage(book.id)
  const list = book.pages_list
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
      <div className="flex-1 overflow-auto p-2 flex flex-col gap-2" onDragOver={(e) => e.preventDefault()} onDrop={drop}>
        {list.map(p => (
          <div key={p.id} className="relative group"
            draggable onDragStart={(e) => { setDrag(p.id); e.dataTransfer.effectAllowed = 'move' }} onDragEnd={() => { setDrag(null); setOver(null) }}
            onDragOver={(e) => { e.preventDefault(); const r = (e.currentTarget as HTMLElement).getBoundingClientRect(); setOver({ id: p.id, after: e.clientY > r.top + r.height / 2 }) }}>
            {over?.id === p.id && drag && drag !== p.id && <div className={cx('absolute left-0 right-0 h-0.5 bg-gold-400 z-10', over.after ? '-bottom-1.5' : '-top-1.5')} />}
            <button ref={p.id === pid ? active : undefined} onClick={() => onPick(p.id)} data-page={p.id}
              className={cx('w-full rounded border p-1 flex gap-2 items-start text-left', p.id === pid ? 'border-gold-500/70 bg-gold-500/10' : 'border-ink-700 hover:border-ink-500', drag === p.id && 'opacity-40')}>
              <img src={p.thumb} alt="" loading="lazy" className="w-[4.5rem] aspect-[2/3] object-cover rounded-sm bg-ink-800 shrink-0" draggable={false} />
              <div className="min-w-0 flex-1 pt-0.5">
                <div className="text-xs font-mono text-ink-100">{p.number}</div>
                <div className="text-2xs text-ink-500 truncate">{p.header ?? p.template ?? ''}</div>
                <div className="text-2xs text-ink-500">{p.texts} text{p.texts === 1 ? '' : 's'}{p.has_art ? '' : ' · no art'}</div>
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

function Centre({ book, page, html, sel, setSel }: { book: Book; page: BookPage; html: string | undefined; sel: Selection; setSel: (s: Selection) => void }) {
  const edit = usePageEdit(book.id, (f: () => Promise<BookPage>) => f())
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
        <LayerToggles layers={page.layers} onToggle={toggle} />
        <div className="relative">
          <button className="btn" onClick={() => setAddMenu(m => !m)}><Type size={12} />Add text<ChevronDown size={10} /></button>
          {addMenu && (
            <div className="absolute right-0 top-8 z-30 card shadow-xl shadow-black/60 w-44 py-1" onMouseLeave={() => setAddMenu(false)}>
              {(Object.keys(STYLE_LABEL) as TextStyle[]).map(s => <button key={s} className="w-full text-left px-3 py-1.5 text-xs hover:bg-ink-800" onClick={() => addText(s)}>{STYLE_LABEL[s]}</button>)}
            </div>
          )}
        </div>
        <a className="btn btn-ghost btn-icon" href={`/api/book/books/${book.id}/pages/${page.id}/render`} target="_blank" rel="noreferrer" title="Open the page render in a new tab"><ExternalLink size={12} /></a>
      </div>
      <div className="flex-1 min-h-0">
        <BookCanvas book={book} page={page} html={html} sel={sel} onSelect={setSel} onCommitBox={commitBox}
          onEditText={(box, text) => commitBox(box.id, box.style === 'header' ? { title: text, text: [box.kicker, text].filter(Boolean).join(' · ') } : { text })} />
      </div>
      <div className="h-7 shrink-0 border-t border-ink-800 px-3 flex items-center gap-4 text-2xs text-ink-500">
        <span>click a box to select · drag to move · corner to resize · double-click to edit · arrows nudge · Delete removes</span>
        <span className="flex-1" />
        <span>PageUp / PageDown · ⌘Z undo</span>
      </div>
    </>
  )
}

function Inspector({ book, page, sel, setSel }: { book: Book; page: BookPage; sel: Selection; setSel: (s: Selection) => void }) {
  const edit = usePageEdit(book.id, (f: () => Promise<BookPage>) => f())
  const box = sel?.type === 'text' ? page.text.find(t => t.id === sel.id) : undefined
  const toggle = (k: LayerKey, v: boolean) => edit.mutate(() => bookApi.layers(book.id, page.id, { [k]: v }))
  return (
    <div className="flex flex-col">
      <LayersList page={page} sel={sel} onSelect={setSel} onToggle={toggle} />
      {box ? <TextInspector box={box} onPatch={(p) => edit.mutate(() => bookApi.patchText(book.id, page.id, box.id, p))} onDelete={() => { edit.mutate(() => bookApi.deleteText(book.id, page.id, box.id)); setSel(null) }} />
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
