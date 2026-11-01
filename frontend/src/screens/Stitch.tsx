import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Scissors, Upload, Download, Undo2, Trash2, ArrowUp, ArrowDown, Crop as CropIcon, Sparkles, ShieldCheck, Check, X, ExternalLink, Shuffle, BookImage, Plus, FileText, Loader2 } from 'lucide-react'
import { cx, Modal, Spinner, JobProgress } from '@/components/ui'
import { toast } from '@/store/toasts'
import { useApiMutation } from '@/api/hooks'
import { useQueryClient } from '@tanstack/react-query'
import { RepoPanel } from '@/components/stitch/Repo'
import {
  useProjects, useProject, usePage, useRepo, useExports, useProjectMutation, stitchApi, sk, cropStyle, fmtBytes,
  STYLE_LABEL, SLOT_LABEL, KIND_LABEL, DRAG_MIME,
  type Project, type PageDetail, type Placement, type Piece, type Photo, type Style, type Slot, type Crop, type PlatePair, type PlateItem,
} from '@/components/stitch/api'

const LS = 'dharma.stitch.v1'
const load = (): { project?: string; page?: number } => { try { return JSON.parse(localStorage.getItem(LS) ?? '{}') } catch { return {} } }
const save = (v: { project?: string; page?: number }) => { try { localStorage.setItem(LS, JSON.stringify(v)) } catch { /* private window */ } }

type View = { type: 'page'; n: number } | { type: 'plate'; id: string; k: number }
/** What a click on a repo photo fills: an empty slot, a placed piece, or a plate (being made or placed). */
type Target = { kind: 'slot'; slot: Slot } | { kind: 'placement'; id: string } | { kind: 'plate-draft'; k: number } | { kind: 'plate'; id: string; k: number } | null
interface PlateDraft { after: number; items: (PlateItem | null)[]; focus: number }

/**
 * Stitch — the author's typeset paperback PDF, kept exactly, with graphic-novel art stitched into its blank space:
 * a torn strip above a chapter heading, a sewn collage at a chapter end, a round icon in the top outer corner, and
 * full-page plates inserted as facing pairs. Left: pages; centre: the page with its slots; right: the photo repo.
 */
export default function StitchScreen() {
  const { data: projects, isLoading } = useProjects()
  const [pid, setPid] = useState<string | null>(load().project ?? null)
  const [view, setView] = useState<View>({ type: 'page', n: load().page ?? 1 })
  const [target, setTarget] = useState<Target>(null)
  const [draft, setDraft] = useState<PlateDraft | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  useEffect(() => { if (projects && (!pid || !projects.some(p => p.id === pid))) setPid(projects[0]?.id ?? null) }, [projects]) // eslint-disable-line react-hooks/exhaustive-deps
  const { data: project } = useProject(pid)
  useEffect(() => { if (view.type === 'page') save({ project: pid ?? undefined, page: view.n }) }, [pid, view])
  useEffect(() => { if (project && view.type === 'page' && view.n > project.pages) setView({ type: 'page', n: 1 }) }, [project, view])
  useEffect(() => { if (project && view.type === 'plate' && !project.plates_list.some(p => p.id === view.id)) setView({ type: 'page', n: 1 }) }, [project, view])
  const n = view.type === 'page' ? view.n : null
  const { data: page } = usePage(pid, n)
  const repo = useRepo('', null, null).data
  const photos = useMemo(() => Object.fromEntries((repo?.photos ?? []).map(p => [p.id, p])), [repo])
  useEffect(() => { setTarget(null) }, [view.type === 'page' ? view.n : view.id, view.type === 'plate' ? view.k : 0]) // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading) return <Spinner />
  if (!projects?.length || !pid) return (
    <div className="h-full flex min-h-0">
      <div className="flex-1 grid place-items-center">
        <div className="max-w-md text-center flex flex-col items-center gap-3">
          <Scissors size={28} className="text-gold-300" />
          <div className="text-sm text-ink-100">Stitch art into the typeset book</div>
          <div className="text-xs text-ink-400">Import the finished paperback interior PDF. Its pages, fonts and text are kept exactly; the graphic-novel art is only added in the white space — above chapter headings, in the blank space at chapter ends, as a small icon in the outer corner, and as full-page plates in facing pairs.</div>
          <button className="btn btn-primary" onClick={() => setImportOpen(true)}><Upload size={12} />Import the book PDF…</button>
        </div>
      </div>
      <div className="w-[21rem] shrink-0 border-l border-ink-800 bg-ink-900/40"><RepoPanel target={null} onPick={() => toast('info', 'Import the book PDF first')} /></div>
      {importOpen && <ImportDialog onClose={() => setImportOpen(false)} onDone={(p) => { setPid(p.id); setView({ type: 'page', n: 1 }); setImportOpen(false) }} />}
    </div>
  )
  return (
    <div className="h-full flex flex-col min-h-0">
      <TopBar project={project ?? null} projects={projects} pid={pid} setPid={(id) => { setPid(id); setView({ type: 'page', n: 1 }) }} onImport={() => setImportOpen(true)} />
      {!project ? <Spinner /> : (
        <div className="flex-1 min-h-0 flex">
          <PageStrip project={project} view={view} setView={setView} />
          <Work project={project} page={page ?? null} view={view} setView={setView} target={target} setTarget={setTarget} draft={draft} setDraft={setDraft} photos={photos} />
          <div className="w-[21rem] shrink-0 border-l border-ink-800 bg-ink-900/40 min-h-0">
            <PickHandler project={project} page={page ?? null} target={target} setTarget={setTarget} draft={draft} setDraft={setDraft} photos={photos} />
          </div>
        </div>
      )}
      {importOpen && <ImportDialog onClose={() => setImportOpen(false)} onDone={(p) => { setPid(p.id); setView({ type: 'page', n: 1 }); setImportOpen(false) }} />}
    </div>
  )
}

// ---------------------------------------------------------------------------------
// placing pieces (shared by click-to-pick and drag-and-drop)
// ---------------------------------------------------------------------------------

function usePlace(project: Project, page: PageDetail | null, setTarget: (t: Target) => void) {
  const add = useProjectMutation(project.id, (a: { body: Partial<Placement> }) => stitchApi.addPlacement(project.id, a.body), (r) => setTarget({ kind: 'placement', id: r.placement.id }))
  const patch = useProjectMutation(project.id, (a: { id: string; body: Partial<Placement> }) => stitchApi.patchPlacement(project.id, a.id, a.body))
  /** Put a piece into a slot: an empty slot gets a new placement; a collage slot collects up to 4 pieces. */
  const toSlot = useCallback((slot: Slot, piece: Piece) => {
    if (!page) return
    const cur = page.placements.find(p => p.slot === slot.id)
    if (!cur) {
      const style: Style = slot.kind === 'collage' ? 'torn' : slot.kind
      add.mutate({ body: { page: page.n, slot: slot.id, style, pieces: [piece] } })
      if (slot.kind === 'collage') toast('info', 'Torn piece placed', 'Drop 1–3 more pieces on this slot to sew them into a collage')
      return
    }
    toPlacement(cur, piece)
  }, [page]) // eslint-disable-line react-hooks/exhaustive-deps
  const toPlacement = (cur: Placement, piece: Piece) => {
    const isBottom = cur.slot === 'bottom' || cur.slot === 'custom'
    if (cur.style === 'collage' || (isBottom && cur.style === 'torn')) {
      if (cur.pieces.length >= 4) { toast('error', 'A collage takes at most 4 pieces', 'Remove one first'); return }
      patch.mutate({ id: cur.id, body: { style: 'collage', pieces: [...cur.pieces, piece] } })
      setTarget({ kind: 'placement', id: cur.id })
    } else {
      patch.mutate({ id: cur.id, body: { pieces: [piece] } })
    }
  }
  return { toSlot, toPlacement, busy: add.isPending || patch.isPending }
}

function PickHandler({ project, page, target, setTarget, draft, setDraft, photos }: { project: Project; page: PageDetail | null; target: Target; setTarget: (t: Target) => void; draft: PlateDraft | null; setDraft: (d: PlateDraft | null) => void; photos: Record<string, Photo> }) {
  const { toSlot, toPlacement } = usePlace(project, page, setTarget)
  const patchPlate = useProjectMutation(project.id, (a: { id: string; items: PlateItem[] }) => stitchApi.patchPlates(project.id, a.id, { items: a.items }))
  const onPick = (piece: Piece) => {
    if (!target) { toast('info', 'Choose where it goes', 'Click a dashed slot on the page (or drag the photo onto it)'); return }
    if (target.kind === 'slot') toSlot(target.slot, piece)
    else if (target.kind === 'placement') { const cur = page?.placements.find(p => p.id === target.id); if (cur) toPlacement(cur, piece) }
    else if (target.kind === 'plate-draft' && draft) {
      const items = [...draft.items]; items[target.k] = { ...piece, caption: items[target.k]?.caption ?? '' }
      setDraft({ ...draft, items, focus: target.k }); if (target.k === 0 && !items[1]) setTarget({ kind: 'plate-draft', k: 1 })
    } else if (target.kind === 'plate') {
      const pp = project.plates_list.find(p => p.id === target.id); if (!pp) return
      patchPlate.mutate({ id: pp.id, items: pp.items.map((it, k) => k === target.k ? { ...piece, caption: it.caption, tilt: it.tilt } : it) })
    }
  }
  void photos
  const label = !target ? null : target.kind === 'slot' ? SLOT_LABEL[target.slot.id] : target.kind === 'placement' ? 'the selected piece' : `plate ${target.k + 1}`
  return <RepoPanel target={label} onPick={onPick} />
}

// ---------------------------------------------------------------------------------
// top bar
// ---------------------------------------------------------------------------------

function TopBar({ project, projects, pid, setPid, onImport }: { project: Project | null; projects: { id: string; title: string; pages: number }[]; pid: string; setPid: (id: string) => void; onImport: () => void }) {
  const [job, setJob] = useState<number | null>(null)
  const [reviewJob, setReviewJob] = useState<number | null>(null)
  const [done, setDone] = useState<{ url: string; name: string } | null>(null)
  const qc = useQueryClient()
  const { data: exports = [] } = useExports(pid)
  const undo = useProjectMutation(pid, () => stitchApi.undo(pid), (r) => toast('info', 'Undone', r.undone))
  const exp = useApiMutation(() => stitchApi.export(pid), [['jobs']], (r) => { setJob(r.job_id); setDone(null) })
  const review = useApiMutation(() => stitchApi.review(pid), [['jobs']], (r) => r.job_id && setReviewJob(r.job_id))
  const del = useApiMutation(() => stitchApi.deleteProject(pid), [sk.projects], () => toast('ok', 'Project removed'))
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) { e.preventDefault(); if (project?.undo) undo.mutate(undefined) }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [project?.undo, undo])
  return (
    <div className="shrink-0 border-b border-ink-800 bg-ink-900">
      <div className="h-10 flex items-center gap-2 px-2">
        <Scissors size={14} className="text-gold-300" />
        <select className="select h-7 w-64 text-xs" value={pid} onChange={(e) => setPid(e.target.value)} aria-label="Stitch project">
          {projects.map(p => <option key={p.id} value={p.id}>{p.title} · {p.pages} pages</option>)}
        </select>
        {project && <span className="text-2xs text-ink-500">{project.source_name} · {project.size[0]}×{project.size[1]} pt · {project.placements} pieces · {project.plates} plate pair{project.plates === 1 ? '' : 's'}</span>}
        <span className="flex-1" />
        <button className="btn" onClick={onImport}><Upload size={12} />Import PDF</button>
        <button className="btn" onClick={() => review.mutate(undefined)} disabled={!project?.placements || review.isPending} title="An independent AI reviewer checks every placed piece against its page and chapter (flags only; nothing changes until you Accept)"><ShieldCheck size={12} />Review all</button>
        <button className="btn btn-primary" onClick={() => exp.mutate(undefined)} disabled={exp.isPending}><Download size={12} />Export PDF</button>
        <button className="btn" onClick={() => undo.mutate(undefined)} disabled={!project?.undo || undo.isPending} title={`Undo the last change (⌘Z) · ${project?.undo ?? 0} in history`}><Undo2 size={12} />Undo</button>
        <button className="btn btn-ghost btn-icon" title="Remove this project (the source PDF copy and its placements)" onClick={() => { if (confirm('Remove this stitch project? The photo repo is kept.')) del.mutate(undefined) }}><Trash2 size={12} /></button>
      </div>
      {(job || reviewJob || done || exports.length > 0) && (
        <div className="px-2 pb-2 flex items-center gap-2 flex-wrap">
          {job && <div className="w-80"><JobProgress compact jobId={job} onDone={(j) => { const r = j.result as { url?: string; pdf?: string; errors?: string[] }; if (r?.url) setDone({ url: r.url, name: (r.pdf ?? '').split('/').pop() ?? 'book.pdf' }); if (r?.errors?.length) toast('error', `${r.errors.length} piece(s) skipped`, r.errors.slice(0, 3).join('\n')); qc.invalidateQueries({ queryKey: sk.exports(pid) }) }} /></div>}
          {reviewJob && <div className="w-80"><JobProgress compact jobId={reviewJob} onDone={(j) => { const r = j.result as { flags?: number }; toast(r?.flags ? 'gate' : 'ok', r?.flags ? `${r.flags} piece(s) flagged` : 'Every piece fits its page', r?.flags ? 'Pages with flags show a red badge' : '') }} /></div>}
          {done && <a className="chip chip-on" href={done.url} target="_blank" rel="noreferrer"><ExternalLink size={10} />{done.name}</a>}
          {exports.slice(0, 3).filter(e => e.url !== done?.url).map(e => <a key={e.name} className="chip" href={e.url} target="_blank" rel="noreferrer" title={e.modified}>{e.name} · {fmtBytes(e.bytes)}</a>)}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------------
// left: the pages
// ---------------------------------------------------------------------------------

const SLOT_TONE: Record<string, string> = { top: 'bg-sky-400', bottom: 'bg-amber-400', corner: 'bg-emerald-400' }

function PageStrip({ project, view, setView }: { project: Project; view: View; setView: (v: View) => void }) {
  const [filter, setFilter] = useState<'all' | 'slots' | 'placed'>('all')
  const ref = useRef<HTMLDivElement>(null)
  const plates = useMemo(() => Object.fromEntries(project.plates_list.map(p => [p.after, p])), [project.plates_list])
  const pages = project.pages_list.filter(p => filter === 'all' || (filter === 'slots' ? p.slots.length > 0 : p.placed > 0))
  useEffect(() => { ref.current?.querySelector('[data-current="1"]')?.scrollIntoView({ block: 'nearest' }) }, [view])
  return (
    <div className="w-44 shrink-0 border-r border-ink-800 bg-ink-900/40 flex flex-col min-h-0">
      <div className="p-1.5 flex gap-1 border-b border-ink-800">{(['all', 'slots', 'placed'] as const).map(f => <button key={f} className={cx('chip flex-1 justify-center', filter === f && 'chip-on')} onClick={() => setFilter(f)}>{f}</button>)}</div>
      <div ref={ref} className="flex-1 overflow-auto p-1.5 flex flex-col gap-1.5">
        {pages.map(p => {
          const cur = view.type === 'page' && view.n === p.n
          const pp = plates[p.n]
          return (
            <div key={p.n} className="flex flex-col gap-1.5">
              <button data-current={cur ? '1' : '0'} onClick={() => setView({ type: 'page', n: p.n })} className={cx('flex gap-1.5 p-1 rounded border text-left', cur ? 'border-gold-400 bg-ink-800' : 'border-transparent hover:bg-ink-850')}>
                <div className="relative w-14 shrink-0 aspect-[2/3] bg-white rounded-sm overflow-hidden"><img src={p.thumb} alt="" className="w-full h-full object-cover" loading="lazy" /></div>
                <div className="min-w-0 flex flex-col gap-0.5 text-2xs">
                  <span className="text-ink-100 font-mono">p{p.n} <span className="text-ink-500">{p.side === 'recto' ? 'R' : 'L'}</span></span>
                  <span className="text-ink-400 truncate">{KIND_LABEL[p.kind]}</span>
                  <span className="flex gap-1 items-center">{p.slots.map(s => <span key={s.id} title={`${SLOT_LABEL[s.id]}${s.filled ? ' · filled' : ''}`} className={cx('w-2 h-2 rounded-full', s.filled ? SLOT_TONE[s.id] : 'border border-ink-500')} />)}</span>
                  {(p.flags > 0 || p.suggestions > 0) && <span className="flex gap-1">{p.flags > 0 && <span className="chip h-4 px-1 border-red-500/50 text-red-300">{p.flags} flag</span>}{p.suggestions > 0 && <span className="chip h-4 px-1 border-sky-500/50 text-sky-300">{p.suggestions} idea</span>}</span>}
                </div>
              </button>
              {pp && filter !== 'slots' && [0, 1].map(k => {
                const on = view.type === 'plate' && view.id === pp.id && view.k === k
                return <button key={k} data-current={on ? '1' : '0'} onClick={() => setView({ type: 'plate', id: pp.id, k })} className={cx('ml-3 flex items-center gap-1.5 px-1.5 py-1 rounded border text-2xs', on ? 'border-gold-400 bg-ink-800 text-gold-300' : 'border-ink-700 border-dashed text-ink-300 hover:bg-ink-850')}><BookImage size={11} />Plate {k === 0 ? 'left' : 'right'} <span className="text-ink-500 truncate">{pp.items[k]?.caption}</span></button>
              })}
            </div>
          )
        })}
        {!pages.length && <div className="empty">No pages</div>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------
// centre: the page and the inspector
// ---------------------------------------------------------------------------------

function Work(props: { project: Project; page: PageDetail | null; view: View; setView: (v: View) => void; target: Target; setTarget: (t: Target) => void; draft: PlateDraft | null; setDraft: (d: PlateDraft | null) => void; photos: Record<string, Photo> }) {
  const { project, page, view, target, setTarget, draft, setDraft, photos } = props
  const plate = view.type === 'plate' ? project.plates_list.find(p => p.id === view.id) ?? null : null
  return (
    <div className="flex-1 min-w-0 flex">
      <div className="flex-1 min-w-0 flex flex-col bg-ink-950">
        {view.type === 'page' ? (page ? <PageCanvas project={project} page={page} target={target} setTarget={setTarget} photos={photos} /> : <Spinner />)
          : plate ? <PlateCanvas project={project} plate={plate} k={view.k} /> : <Spinner />}
      </div>
      <div className="w-[18rem] shrink-0 border-l border-ink-800 bg-ink-900/40 overflow-auto">
        {draft ? <PlateDraftPanel project={project} draft={draft} setDraft={setDraft} target={target} setTarget={setTarget} photos={photos} onMade={(pp) => props.setView({ type: 'plate', id: pp.id, k: 0 })} />
          : view.type === 'plate' ? (plate && <PlateInspector project={project} plate={plate} k={view.k} target={target} setTarget={setTarget} photos={photos} />)
          : page && <PageInspector project={project} page={page} target={target} setTarget={setTarget} photos={photos} onPlates={() => { setDraft({ after: page.n, items: [null, null], focus: 0 }); setTarget({ kind: 'plate-draft', k: 0 }) }} />}
      </div>
    </div>
  )
}

/** The server-rendered page at size; the previous render stays on screen until the new one has loaded. */
function useLivePng(src: string | null) {
  const [shown, setShown] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!src) return
    let alive = true
    setBusy(true)
    const im = new Image()
    im.onload = () => { if (alive) { setShown(src); setBusy(false) } }
    im.onerror = () => { if (alive) setBusy(false) }
    im.src = src
    return () => { alive = false }
  }, [src])
  return { shown, busy }
}

function useFitScale(pageW: number, pageH: number) {
  const ref = useRef<HTMLDivElement>(null)
  const [s, setS] = useState(1)
  useEffect(() => {
    const el = ref.current; if (!el) return
    const ro = new ResizeObserver(() => setS(Math.max(0.3, Math.min((el.clientWidth - 48) / pageW, (el.clientHeight - 48) / pageH))))
    ro.observe(el); return () => ro.disconnect()
  }, [pageW, pageH])
  return { ref, s }
}

function PageCanvas({ project, page, target, setTarget, photos }: { project: Project; page: PageDetail; target: Target; setTarget: (t: Target) => void; photos: Record<string, Photo> }) {
  const { ref, s } = useFitScale(page.w, page.h)
  const dpi = Math.min(220, Math.max(96, Math.round(s * 72 * (window.devicePixelRatio || 1))))
  const { shown, busy } = useLivePng(`${page.preview}&dpi=${dpi}`)
  const [showText, setShowText] = useState(false)
  const [over, setOver] = useState<string | null>(null)
  const { toSlot, busy: placing } = usePlace(project, page, setTarget)
  const selId = target?.kind === 'placement' ? target.id : target?.kind === 'slot' ? target.slot.id : null
  const drop = (slot: Slot) => (e: React.DragEvent) => {
    e.preventDefault(); setOver(null)
    const raw = e.dataTransfer.getData(DRAG_MIME)
    if (raw) toSlot(slot, JSON.parse(raw) as Piece)
  }
  void photos
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="h-9 shrink-0 flex items-center gap-2 px-3 border-b border-ink-800 text-2xs text-ink-400">
        <span className="text-ink-100 font-mono">Page {page.n}</span><span>{page.side === 'recto' ? 'right-hand (odd)' : 'left-hand (even)'}</span><span>·</span><span>{KIND_LABEL[page.kind]}</span>
        {page.chapter && <span className="truncate max-w-[16rem] text-ink-300" title={page.chapter}>· {page.chapter}</span>}
        <span className="flex-1" />
        {(busy || placing) && <span className="flex items-center gap-1 text-sky-300"><Loader2 size={11} className="animate-spin" />rendering</span>}
        <label className="flex items-center gap-1"><input type="checkbox" checked={showText} onChange={(e) => setShowText(e.target.checked)} />text boxes</label>
      </div>
      <div ref={ref} className="flex-1 min-h-0 grid place-items-center overflow-hidden" onClick={() => setTarget(null)}>
        <div className="relative bg-white shadow-2xl shadow-black/60" style={{ width: page.w * s, height: page.h * s }} data-testid="stitch-page">
          {shown && <img src={shown} alt={`page ${page.n}`} className="absolute inset-0 w-full h-full" draggable={false} />}
          {showText && page.blocks.concat(page.folio).map((b, i) => <div key={i} className="absolute bg-sky-400/10 border border-sky-400/40 pointer-events-none" style={box(b, s)} />)}
          {page.slots.map(sl => {
            const pl = page.placements.find(p => p.slot === sl.id)
            const sel = pl ? selId === pl.id : selId === sl.id
            return (
              <button key={sl.id} type="button" data-slot={sl.id}
                onClick={(e) => { e.stopPropagation(); setTarget(pl ? { kind: 'placement', id: pl.id } : { kind: 'slot', slot: sl }) }}
                onDragOver={(e) => { if (e.dataTransfer.types.includes(DRAG_MIME)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; setOver(sl.id) } }}
                onDragLeave={() => setOver(null)} onDrop={drop(sl)}
                className={cx('absolute rounded-sm transition-colors', pl ? 'border border-transparent hover:border-gold-400/70' : 'border-2 border-dashed bg-gold-400/5 hover:bg-gold-400/15',
                  !pl && (sl.id === 'top' ? 'border-sky-500/70' : sl.id === 'bottom' ? 'border-amber-500/70' : 'border-emerald-500/70'),
                  sel && '!border-gold-300 ring-2 ring-gold-300/60', over === sl.id && '!bg-gold-300/25 !border-gold-300')}
                style={box(sl.rect, s)} title={pl ? `${STYLE_LABEL[pl.style]} · click to edit · drop to ${pl.style === 'collage' || sl.id === 'bottom' ? 'add a piece' : 'replace'}` : `${sl.label} — drop a photo here, or click and pick from the repo`}>
                {!pl && <span className="absolute inset-0 grid place-items-center text-[0.62rem] font-medium text-ink-700/80 pointer-events-none">{sl.id === 'corner' ? '◎' : SLOT_LABEL[sl.id]}</span>}
              </button>
            )
          })}
          {page.placements.filter(p => p.slot === 'custom').map(pl => <button key={pl.id} className={cx('absolute border', selId === pl.id ? 'border-gold-300' : 'border-transparent hover:border-gold-400/70')} style={box(pl.rect, s)} onClick={(e) => { e.stopPropagation(); setTarget({ kind: 'placement', id: pl.id }) }} />)}
        </div>
      </div>
      {!page.slots.length && <div className="text-center text-2xs text-ink-500 pb-2">No blank area on this page for art.</div>}
    </div>
  )
}

const box = (r: number[], s: number): React.CSSProperties => ({ left: r[0] * s, top: r[1] * s, width: (r[2] - r[0]) * s, height: (r[3] - r[1]) * s })

function PlateCanvas({ project, plate, k }: { project: Project; plate: PlatePair; k: number }) {
  const { ref, s } = useFitScale(project.size[0], project.size[1])
  const v = encodeURIComponent(JSON.stringify(plate.items[k] ?? null) + plate.seed)
  const { shown, busy } = useLivePng(`/api/stitch/projects/${project.id}/plates/${plate.id}/${k}/preview.png?dpi=${Math.min(200, Math.round(s * 72 * (window.devicePixelRatio || 1)))}&v=${v}`)
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="h-9 shrink-0 flex items-center gap-2 px-3 border-b border-ink-800 text-2xs text-ink-400">
        <span className="text-ink-100">Plate {k === 0 ? 'left' : 'right'}</span><span>· inserted after page {plate.after} as page {plate.after + 1 + k} of the export</span><span className="flex-1" />{busy && <Loader2 size={11} className="animate-spin text-sky-300" />}
      </div>
      <div ref={ref} className="flex-1 min-h-0 grid place-items-center"><div className="relative bg-white shadow-2xl shadow-black/60" style={{ width: project.size[0] * s, height: project.size[1] * s }}>{shown && <img src={shown} alt="plate" className="w-full h-full" />}</div></div>
    </div>
  )
}

// ---------------------------------------------------------------------------------
// inspector
// ---------------------------------------------------------------------------------

/** A range input that sends its value when released (one undo step per gesture). */
function Slider({ label, value, min, max, step, onCommit, fmt }: { label: string; value: number; min: number; max: number; step: number; onCommit: (v: number) => void; fmt: (v: number) => string }) {
  const [v, setV] = useState(value)
  useEffect(() => setV(value), [value])
  const commit = () => { if (v !== value) onCommit(v) }
  return (
    <label className="flex flex-col gap-0.5">
      <span className="flex justify-between text-2xs"><span className="label">{label}</span><span className="font-mono text-ink-300">{fmt(v)}</span></span>
      <input type="range" min={min} max={max} step={step} value={v} onChange={(e) => setV(Number(e.target.value))} onPointerUp={commit} onKeyUp={commit} onBlur={commit} className="accent-amber-400" aria-label={label} />
    </label>
  )
}

function PieceThumb({ piece, photo, size = 44 }: { piece: Piece; photo?: Photo; size?: number }) {
  if (!photo) return <div className="bg-ink-700 rounded" style={{ width: size, height: size }} />
  return <div className="rounded border border-ink-600 shrink-0" style={{ width: size, height: size, backgroundImage: `url(${photo.thumb})`, ...cropStyle(photo, piece.crop, size, size) }} />
}

function PageInspector({ project, page, target, setTarget, photos, onPlates }: { project: Project; page: PageDetail; target: Target; setTarget: (t: Target) => void; photos: Record<string, Photo>; onPlates: () => void }) {
  const pl = target?.kind === 'placement' ? page.placements.find(p => p.id === target.id) : null
  return (
    <div className="flex flex-col">
      {pl ? <PlacementInspector project={project} page={page} pl={pl} photos={photos} onClose={() => setTarget(null)} />
        : target?.kind === 'slot' ? (
          <div className="p-3 flex flex-col gap-2 border-b border-ink-800">
            <div className="label">{SLOT_LABEL[target.slot.id]}</div>
            <div className="text-xs text-ink-300">{target.slot.label} · {Math.round(target.slot.rect[2] - target.slot.rect[0])} × {Math.round(target.slot.rect[3] - target.slot.rect[1])} pt</div>
            <div className="text-2xs text-sky-300">Click a photo or a subject in the repo to place it here{target.slot.kind === 'collage' ? ' (2–4 pieces make a sewn collage)' : ''}.</div>
          </div>
        ) : (
          <div className="p-3 flex flex-col gap-1.5 border-b border-ink-800 text-xs">
            <div className="label">Page {page.n}</div>
            <div className="text-ink-300">{KIND_LABEL[page.kind]} · {page.side === 'recto' ? 'right-hand' : 'left-hand'} page · outer edge {page.outer}</div>
            <div className="text-2xs text-ink-400">Blank above the text {Math.round(page.free_top)} pt · below {Math.round(page.free_bottom)} pt</div>
            <div className="flex flex-col gap-1 mt-1">
              {page.slots.map(sl => { const p = page.placements.find(x => x.slot === sl.id); return (
                <button key={sl.id} className="flex items-center gap-2 text-left px-1.5 py-1 rounded hover:bg-ink-800" onClick={() => setTarget(p ? { kind: 'placement', id: p.id } : { kind: 'slot', slot: sl })}>
                  <span className={cx('w-2 h-2 rounded-full', p ? SLOT_TONE[sl.id] : 'border border-ink-500')} /><span className="flex-1">{SLOT_LABEL[sl.id]}</span><span className="text-2xs text-ink-500">{p ? `${STYLE_LABEL[p.style]} · ${p.pieces.length}` : 'empty'}</span>
                </button>) })}
              {!page.slots.length && <span className="text-2xs text-ink-500 italic">No blank area for art on this page.</span>}
            </div>
          </div>
        )}
      <AiPanel project={project} page={page} photos={photos} onSelect={(id) => setTarget({ kind: 'placement', id })} />
      <div className="p-3 flex flex-col gap-1.5 border-t border-ink-800">
        <div className="label">Full-page plates</div>
        {page.plates_after.map(pp => <div key={pp.id} className="text-2xs text-ink-300">A plate pair follows this page ({pp.items.map(i => `“${i.caption}”`).join(' · ')}).</div>)}
        {page.n % 2 === 1 && !page.plates_after.length
          ? <button className="btn self-start" onClick={onPlates}><Plus size={11} />Add plate pair after page {page.n}</button>
          : !page.plates_after.length && <div className="text-2xs text-ink-500">Plates go in as a facing pair after an odd (right-hand) page, so every later page keeps its side.</div>}
      </div>
      <details className="p-3 border-t border-ink-800 text-2xs text-ink-400"><summary className="cursor-pointer label flex items-center gap-1"><FileText size={10} />Page text</summary><div className="mt-1.5 whitespace-pre-wrap font-book text-ink-300 max-h-64 overflow-auto">{page.text || '—'}</div></details>
    </div>
  )
}

function PlacementInspector({ project, page, pl, photos, onClose }: { project: Project; page: PageDetail; pl: Placement; photos: Record<string, Photo>; onClose: () => void }) {
  const patch = useProjectMutation(project.id, (body: Partial<Placement>) => stitchApi.patchPlacement(project.id, pl.id, body))
  const del = useProjectMutation(project.id, () => stitchApi.deletePlacement(project.id, pl.id), onClose)
  const [cropping, setCropping] = useState<number | null>(null)
  const pieces = pl.pieces
  const setPieces = (ps: Piece[]) => {
    const style = pl.style === 'collage' && ps.length < 2 ? 'torn' : pl.style
    patch.mutate({ pieces: ps, style })
  }
  const move = (i: number, d: number) => { const ps = [...pieces]; const [x] = ps.splice(i, 1); ps.splice(i + d, 0, x); setPieces(ps) }
  const aspect = pl.style === 'icon' ? 1 : pl.style === 'strip' ? Math.max(2, (pl.rect[2] - pl.rect[0]) / Math.max(1, pl.rect[3] - pl.rect[1])) : pl.style === 'collage' ? 1.1 : 1.5
  return (
    <div className="p-3 flex flex-col gap-3 border-b border-ink-800">
      <div className="flex items-center gap-2"><span className="label flex-1">{SLOT_LABEL[pl.slot]} · page {page.n}</span>
        <button className="btn btn-sm btn-ghost btn-icon" onClick={onClose} title="Done"><X size={11} /></button></div>
      <label className="flex flex-col gap-1"><span className="label">Style</span>
        <select className="select" value={pl.style} onChange={(e) => {
          const st = e.target.value as Style
          if (st === 'collage' && pieces.length < 2) { toast('info', 'Add another piece first', 'A collage sews 2–4 pieces: drop or pick more photos onto this slot'); return }
          patch.mutate({ style: st, pieces: st === 'collage' ? pieces : pieces.slice(0, 1) })
        }} aria-label="Style">
          {(['strip', 'collage', 'icon', 'torn'] as Style[]).map(s => <option key={s} value={s}>{STYLE_LABEL[s]}</option>)}
        </select>
      </label>
      <div className="flex flex-col gap-1">
        <span className="label">{pl.style === 'collage' ? `Pieces (${pieces.length}/4)` : 'Piece'}</span>
        {pieces.map((pc, i) => { const ph = photos[pc.photo]; const sub = ph?.subjects.find(s => s.id === pc.subject); return (
          <div key={i} className="flex items-center gap-2">
            <PieceThumb piece={pc} photo={ph} />
            <div className="flex-1 min-w-0 text-2xs"><div className="truncate text-ink-200">{sub?.label ?? ph?.name ?? pc.photo}</div><div className="text-ink-500 truncate">{pc.crop ? 'crop set' : 'auto crop'}{ph?.page ? ` · p${ph.page}` : ''}</div></div>
            <button className="btn btn-sm btn-icon" title="Crop: pan and zoom inside the piece" onClick={() => setCropping(i)}><CropIcon size={10} /></button>
            {pieces.length > 1 && <>
              <button className="btn btn-sm btn-icon" disabled={i === 0} onClick={() => move(i, -1)} title="Earlier"><ArrowUp size={10} /></button>
              <button className="btn btn-sm btn-icon" disabled={i === pieces.length - 1} onClick={() => move(i, 1)} title="Later"><ArrowDown size={10} /></button>
              <button className="btn btn-sm btn-icon" onClick={() => setPieces(pieces.filter((_, j) => j !== i))} title="Remove this piece"><X size={10} /></button>
            </>}
          </div>) })}
        <div className="text-2xs text-ink-500">{pl.style === 'collage' || pl.slot === 'bottom' ? 'Drop or click photos to add pieces (up to 4).' : 'Drop or click a photo to replace it.'}</div>
      </div>
      <Slider label="Size" value={pl.size} min={0.3} max={1} step={0.05} fmt={(v) => `${Math.round(v * 100)}%`} onCommit={(v) => patch.mutate({ size: v })} />
      <Slider label="Tilt" value={pl.tilt} min={-8} max={8} step={0.25} fmt={(v) => `${v.toFixed(1)}°`} onCommit={(v) => patch.mutate({ tilt: v })} />
      <Slider label="Sepia" value={pl.sepia} min={0} max={0.6} step={0.02} fmt={(v) => `${Math.round(v * 100)}%`} onCommit={(v) => patch.mutate({ sepia: v })} />
      <div className="flex gap-1.5">
        <button className="btn btn-sm" onClick={() => patch.mutate({ seed: Math.floor(Math.random() * 1e6) + 1 })} title="A new torn edge, stitch spacing and piece tilts"><Shuffle size={10} />Re-tear</button>
        <span className="flex-1" />
        <button className="btn btn-sm btn-danger" onClick={() => del.mutate(undefined)}><Trash2 size={10} />Remove</button>
      </div>
      {cropping !== null && photos[pieces[cropping]?.photo] && (
        <CropEditor photo={photos[pieces[cropping].photo]} crop={pieces[cropping].crop} aspect={aspect} onClose={() => setCropping(null)}
          onSave={(c) => { setPieces(pieces.map((p, j) => j === cropping ? { ...p, crop: c ?? undefined, ...(c ? {} : { subject: undefined }) } : p)); setCropping(null) }} />
      )}
    </div>
  )
}

/** Pan (drag) and zoom (wheel / slider) the window of the photo that fills the piece; the box keeps the piece's shape. */
function CropEditor({ photo, crop, aspect, onSave, onClose }: { photo: Photo; crop?: Crop; aspect: number; onSave: (c: Crop | null) => void; onClose: () => void }) {
  const pa = photo.w / photo.h
  const fitBox = (c: Crop): Crop => {  // grow the box to the piece's aspect (in pixels), keep it inside the photo
    let w = c.w, h = c.h
    if ((w * photo.w) / (h * photo.h) > aspect) h = (w * photo.w) / aspect / photo.h; else w = (h * photo.h * aspect) / photo.w
    if (w > 1) { h = h / w; w = 1 } if (h > 1) { w = w / h; h = 1 }
    const cx = c.x + c.w / 2, cy = c.y + c.h / 2
    return { x: Math.max(0, Math.min(1 - w, cx - w / 2)), y: Math.max(0, Math.min(1 - h, cy - h / 2)), w, h }
  }
  const [c, setC] = useState<Crop>(() => fitBox(crop ?? { x: 0.25, y: 0.25, w: 0.5, h: 0.5 }))
  const maxW = Math.min(1, aspect / pa)  // the widest box of this aspect that fits
  const zoom = maxW / c.w
  const ref = useRef<HTMLDivElement>(null)
  const drag = useRef<{ x: number; y: number; c: Crop } | null>(null)
  const setZoom = (z: number) => { const w = Math.min(maxW, maxW / Math.max(1, z)); const h = (w * photo.w) / aspect / photo.h; setC(fitBox({ x: c.x + c.w / 2 - w / 2, y: c.y + c.h / 2 - h / 2, w, h })) }
  return (
    <Modal title={`Crop · ${photo.name}`} onClose={onClose} width="max-w-3xl">
      <div className="flex flex-col gap-3">
        <div className="flex gap-3">
          <div ref={ref} className="relative select-none touch-none flex-1 min-w-0" style={{ aspectRatio: `${pa}`, maxHeight: '62vh' }}
            onWheel={(e) => setZoom(zoom * (e.deltaY < 0 ? 1.08 : 1 / 1.08))}
            onPointerMove={(e) => { const d = drag.current; if (!d || !ref.current) return; const r = ref.current.getBoundingClientRect(); setC(fitBox({ ...d.c, x: d.c.x + (e.clientX - d.x) / r.width, y: d.c.y + (e.clientY - d.y) / r.height })) }}
            onPointerUp={() => { drag.current = null }}>
            <img src={photo.url} alt="" className="absolute inset-0 w-full h-full object-contain opacity-50 pointer-events-none" draggable={false} />
            <div className="absolute border-2 border-gold-300 cursor-move overflow-hidden" style={{ left: `${c.x * 100}%`, top: `${c.y * 100}%`, width: `${c.w * 100}%`, height: `${c.h * 100}%` }}
              onPointerDown={(e) => { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); drag.current = { x: e.clientX, y: e.clientY, c } }}>
              <div className="absolute" style={{ left: `${(-c.x / c.w) * 100}%`, top: `${(-c.y / c.h) * 100}%`, width: `${100 / c.w}%`, height: `${100 / c.h}%`, backgroundImage: `url(${photo.url})`, backgroundSize: '100% 100%' }} />
            </div>
          </div>
          <div className="w-44 shrink-0 flex flex-col gap-2 text-xs">
            <span className="label">Preview</span>
            <div className="rounded border border-ink-600" style={{ width: 160, height: 160 / aspect, backgroundImage: `url(${photo.url})`, ...cropStyle(photo, c, 160, 160 / aspect) }} />
            <label className="flex flex-col gap-0.5"><span className="label">Zoom {zoom.toFixed(1)}×</span><input type="range" min={1} max={6} step={0.05} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} className="accent-amber-400" /></label>
            {photo.subjects.length > 0 && <label className="flex flex-col gap-0.5"><span className="label">Centre on a subject</span>
              <select className="select" value="" onChange={(e) => { const s = photo.subjects.find(x => x.id === e.target.value); if (s) setC(fitBox(s)) }}><option value="">—</option>{photo.subjects.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}</select></label>}
            <span className="text-2xs text-ink-500">Drag the box to pan, wheel or slider to zoom.</span>
          </div>
        </div>
        <div className="flex gap-2"><button className="btn btn-primary" onClick={() => onSave({ x: +c.x.toFixed(4), y: +c.y.toFixed(4), w: +c.w.toFixed(4), h: +c.h.toFixed(4) })}><Check size={11} />Use this crop</button>
          <button className="btn" onClick={() => onSave(null)} title="Let the studio pick the most detailed window">Auto crop</button><span className="flex-1" /><button className="btn" onClick={onClose}>Cancel</button></div>
      </div>
    </Modal>
  )
}

function AiPanel({ project, page, photos, onSelect }: { project: Project; page: PageDetail; photos: Record<string, Photo>; onSelect: (id: string) => void }) {
  const suggest = useProjectMutation(project.id, () => stitchApi.suggest(project.id, page.n), (r) => { if (!r.items.length) toast('info', 'No suggestion', 'Nothing in the repo matched this page') })
  const accept = useProjectMutation(project.id, (k: number) => stitchApi.acceptSuggestion(project.id, page.n, k))
  const clearS = useProjectMutation(project.id, () => stitchApi.clearSuggestions(project.id, page.n))
  const review = useProjectMutation(project.id, () => stitchApi.review(project.id, page.n))
  const acceptR = useProjectMutation(project.id, (k: number) => stitchApi.acceptReview(project.id, page.n, k))
  const clearR = useProjectMutation(project.id, () => stitchApi.clearReview(project.id, page.n))
  const sug = page.suggestions?.items ?? []
  const rev = page.review?.items ?? []
  return (
    <div className="p-3 flex flex-col gap-2 border-t border-ink-800">
      <div className="flex items-center gap-1.5">
        <button className="btn btn-sm" disabled={!page.slots.length || suggest.isPending} onClick={() => suggest.mutate(undefined)} title="The AI picture editor picks pieces from the repo that match this page's text"><Sparkles size={10} />{suggest.isPending ? 'Thinking…' : 'Suggest'}</button>
        <button className="btn btn-sm" disabled={!page.placements.length || review.isPending} onClick={() => review.mutate(undefined)} title="An independent AI reviewer checks each piece against the page and chapter text"><ShieldCheck size={10} />{review.isPending ? 'Reviewing…' : 'Review'}</button>
        <span className="text-2xs text-ink-500">nothing changes until you Accept</span>
      </div>
      {sug.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center"><span className="label flex-1">Suggestions</span><button className="btn btn-ghost btn-sm" onClick={() => clearS.mutate(undefined)}>clear</button></div>
          {sug.map((s, k) => (
            <div key={k} className="card p-1.5 flex flex-col gap-1">
              <div className="flex items-center gap-1">{s.pieces.map((pc, i) => <PieceThumb key={i} piece={pc} photo={photos[pc.photo]} size={30} />)}<span className="flex-1 text-2xs text-ink-300 ml-1">{SLOT_LABEL[s.slot]} · {STYLE_LABEL[s.style]}</span></div>
              {s.why && <div className="text-2xs text-ink-400">{s.why}</div>}
              {s.accepted ? <span className="text-2xs text-emerald-300 flex items-center gap-1"><Check size={10} />placed</span>
                : <button className="btn btn-sm btn-primary self-start" disabled={accept.isPending} onClick={() => accept.mutate(k)}><Check size={10} />Accept</button>}
            </div>
          ))}
        </div>
      )}
      {rev.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center"><span className="label flex-1">Review</span><button className="btn btn-ghost btn-sm" onClick={() => clearR.mutate(undefined)}>clear</button></div>
          {rev.map((r, k) => (
            <div key={k} className={cx('card p-1.5 flex flex-col gap-1 border-l-2', r.ok ? 'border-l-emerald-400' : 'border-l-red-500')}>
              <button className="text-left text-2xs text-ink-200" onClick={() => onSelect(r.placement)}>{SLOT_LABEL[page.placements.find(p => p.id === r.placement)?.slot ?? 'custom']}: {r.ok ? 'fits the page' : r.issue}</button>
              {!r.ok && r.replace && !r.accepted && <div className="flex items-center gap-1.5"><PieceThumb piece={r.replace} photo={photos[r.replace.photo]} size={30} /><span className="text-2xs text-ink-400 flex-1">{photos[r.replace.photo]?.name}</span>
                <button className="btn btn-sm btn-primary" onClick={() => acceptR.mutate(k)}><Check size={10} />Accept</button></div>}
              {r.accepted && <span className="text-2xs text-emerald-300">replacement applied</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------------
// plates
// ---------------------------------------------------------------------------------

function PlateItemEditor({ k, item, photos, active, onActivate, onCaption, onCrop }: { k: number; item: PlateItem | null; photos: Record<string, Photo>; active: boolean; onActivate: () => void; onCaption: (c: string) => void; onCrop?: () => void }) {
  const ph = item ? photos[item.photo] : undefined
  const [cap, setCap] = useState(item?.caption ?? '')
  useEffect(() => setCap(item?.caption ?? ''), [item?.caption])
  return (
    <div className={cx('card p-2 flex flex-col gap-1.5', active && 'border-sky-400/70')}>
      <div className="flex items-center gap-2">
        <button className={cx('w-12 aspect-[2/3] rounded border grid place-items-center text-2xs', active ? 'border-sky-400' : 'border-ink-600 border-dashed')} onClick={onActivate} title="Then click a photo in the repo"
          style={ph ? { backgroundImage: `url(${ph.thumb})`, ...cropStyle(ph, item?.crop, 48, 72) } : undefined}>{!ph && '+'}</button>
        <div className="flex-1 min-w-0 text-2xs"><div className="text-ink-200">{k === 0 ? 'Left plate' : 'Right plate'}</div><div className="text-ink-500 truncate">{ph?.name ?? (active ? 'click a photo in the repo →' : 'choose a photo')}</div></div>
        {onCrop && ph && <button className="btn btn-sm btn-icon" onClick={onCrop} title="Crop"><CropIcon size={10} /></button>}
      </div>
      <input className="input font-book italic" placeholder="Caption (a line from the book)" value={cap} onChange={(e) => setCap(e.target.value)} onBlur={() => cap !== (item?.caption ?? '') && onCaption(cap)} aria-label={`Plate ${k + 1} caption`} />
    </div>
  )
}

function PlateDraftPanel({ project, draft, setDraft, target, setTarget, photos, onMade }: { project: Project; draft: PlateDraft; setDraft: (d: PlateDraft | null) => void; target: Target; setTarget: (t: Target) => void; photos: Record<string, Photo>; onMade: (pp: PlatePair) => void }) {
  const make = useProjectMutation(project.id, () => stitchApi.addPlates(project.id, { after: draft.after, items: draft.items as PlateItem[] }), (r) => { setDraft(null); setTarget(null); onMade(r.plate) })
  const ready = draft.items.every(i => i && i.photo)
  return (
    <div className="p-3 flex flex-col gap-2">
      <div className="label">New plate pair after page {draft.after}</div>
      <div className="text-2xs text-ink-400">Two full-page torn-out paintings face each other as pages {draft.after + 1} (left) and {draft.after + 2} (right); every later page keeps its side.</div>
      {[0, 1].map(k => <PlateItemEditor key={k} k={k} item={draft.items[k]} photos={photos} active={target?.kind === 'plate-draft' && target.k === k} onActivate={() => setTarget({ kind: 'plate-draft', k })}
        onCaption={(c) => { const items = [...draft.items]; items[k] = items[k] ? { ...items[k]!, caption: c } : null; if (!items[k]) toast('info', 'Choose the photo first'); setDraft({ ...draft, items }) }} />)}
      <div className="flex gap-1.5"><button className="btn btn-primary" disabled={!ready || make.isPending} onClick={() => make.mutate(undefined)}><Check size={11} />Insert the pair</button><button className="btn" onClick={() => { setDraft(null); setTarget(null) }}>Cancel</button></div>
    </div>
  )
}

function PlateInspector({ project, plate, k, target, setTarget, photos }: { project: Project; plate: PlatePair; k: number; target: Target; setTarget: (t: Target) => void; photos: Record<string, Photo> }) {
  const patch = useProjectMutation(project.id, (items: PlateItem[]) => stitchApi.patchPlates(project.id, plate.id, { items }))
  const del = useProjectMutation(project.id, () => stitchApi.deletePlates(project.id, plate.id))
  const [cropping, setCropping] = useState<number | null>(null)
  const item = plate.items[k]
  return (
    <div className="p-3 flex flex-col gap-2">
      <div className="label">Plate pair after page {plate.after}</div>
      {[0, 1].map(j => <PlateItemEditor key={j} k={j} item={plate.items[j]} photos={photos} active={target?.kind === 'plate' && target.k === j} onActivate={() => setTarget({ kind: 'plate', id: plate.id, k: j })}
        onCaption={(c) => patch.mutate(plate.items.map((it, i) => i === j ? { ...it, caption: c } : it))} onCrop={() => setCropping(j)} />)}
      {item && <Slider label={`Tilt (${k === 0 ? 'left' : 'right'})`} value={item.tilt ?? (k === 0 ? -1.3 : 1.2)} min={-6} max={6} step={0.1} fmt={(v) => `${v.toFixed(1)}°`} onCommit={(v) => patch.mutate(plate.items.map((it, i) => i === k ? { ...it, tilt: v } : it))} />}
      <button className="btn btn-sm btn-danger self-start" onClick={() => { if (confirm('Remove this plate pair?')) del.mutate(undefined) }}><Trash2 size={10} />Remove the pair</button>
      {cropping !== null && photos[plate.items[cropping]?.photo] && (
        <CropEditor photo={photos[plate.items[cropping].photo]} crop={plate.items[cropping].crop} aspect={(photos[plate.items[cropping].photo].w / photos[plate.items[cropping].photo].h)} onClose={() => setCropping(null)}
          onSave={(c) => { patch.mutate(plate.items.map((it, i) => i === cropping ? { ...it, crop: c ?? undefined } : it)); setCropping(null) }} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------------
// import
// ---------------------------------------------------------------------------------

function ImportDialog({ onClose, onDone }: { onClose: () => void; onDone: (p: Project) => void }) {
  const [path, setPath] = useState('')
  const [title, setTitle] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const byPath = useApiMutation(() => stitchApi.importPath(path.trim(), title || undefined), [sk.projects], onDone)
  const byFile = useApiMutation((f: File) => stitchApi.upload(f, title || undefined), [sk.projects], onDone)
  const busy = byPath.isPending || byFile.isPending
  return (
    <Modal title="Import the typeset book PDF" onClose={onClose}>
      <div className="flex flex-col gap-3 text-xs">
        <div className="text-ink-400">The PDF is copied into the studio's data folder on this Mac and never changed: every export is a new file with the art added on top.</div>
        <label className="flex flex-col gap-1"><span className="label">Title (optional)</span><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="The Cycle of Dharma — paperback" /></label>
        <input ref={fileRef} type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) byFile.mutate(f) }} />
        <button className="btn btn-primary self-start" disabled={busy} onClick={() => fileRef.current?.click()}><Upload size={11} />Choose the PDF…</button>
        <div className="flex gap-1.5"><input className="input font-mono" value={path} onChange={(e) => setPath(e.target.value)} placeholder="or a path: ~/Documents/Paperback_Interior_6x9.pdf" />
          <button className="btn" disabled={!path.trim() || busy} onClick={() => byPath.mutate(undefined)}>Import</button></div>
        {busy && <Spinner label="Reading the pages…" />}
      </div>
    </Modal>
  )
}
