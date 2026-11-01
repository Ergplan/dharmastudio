import { useEffect, useRef, useState } from 'react'
import { Search, Plus, BookOpenCheck, FolderOpen, Upload, Sparkles, Trash2, Check, X, Crosshair, Images } from 'lucide-react'
import { cx, Modal, Spinner } from '@/components/ui'
import { toast } from '@/store/toasts'
import { useApiMutation } from '@/api/hooks'
import { useQueryClient } from '@tanstack/react-query'
import { useRepo, useRepoBooks, useRepoMutation, stitchApi, sk, cropStyle, DRAG_MIME, type Photo, type Crop, type Piece } from './api'

/**
 * The photo repo: the author's library of graphic-novel art (a Book's art layers, folders, uploads). Drag a photo or one
 * of its subjects onto a slot of the page, or click it to put it in the selected slot.
 */
export function RepoPanel({ onPick, target }: { onPick: (p: Piece) => void; target: string | null }) {
  const [q, setQ] = useState('')
  const [source, setSource] = useState<string | null>(null)
  const [tag, setTag] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [edit, setEdit] = useState<Photo | null>(null)
  const [adding, setAdding] = useState(false)
  const { data, isLoading } = useRepo(q, source, tag)
  const photos = data?.photos ?? []
  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="panel-h justify-between"><span className="flex items-center gap-1.5"><Images size={13} className="text-gold-300" />Photo repo <span className="text-ink-500 font-normal">{data ? `${photos.length}/${data.total}` : ''}</span></span>
        <button className="btn btn-sm" onClick={() => setAdding(true)}><Plus size={11} />Add</button></div>
      <div className="p-2 flex flex-col gap-1.5 border-b border-ink-800">
        <div className="relative"><Search size={11} className="absolute left-2 top-2 text-ink-500" /><input className="input pl-6" placeholder="Search name, tag, chapter, subject…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search photos" /></div>
        <div className="flex flex-wrap gap-1">
          {[null, 'book', 'folder', 'upload'].map(s => <button key={s ?? 'all'} className={cx('chip', source === s && 'chip-on')} onClick={() => setSource(s)}>{s ?? 'all'}</button>)}
          <span className="w-px bg-ink-700 mx-0.5" />
          {(data?.tags ?? []).slice(0, 10).map(([t, n]) => <button key={t} className={cx('chip', tag === t && 'chip-on')} onClick={() => setTag(tag === t ? null : t)} title={`${n} photos`}>{t}</button>)}
        </div>
        {target && <div className="text-2xs text-sky-300">Click a photo or subject to put it in the selected slot · or drag it onto any slot</div>}
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-2">
        {isLoading ? <Spinner /> : !photos.length ? (
          <div className="empty flex flex-col gap-2 items-center">No photos{q || tag || source ? ' match' : ' yet'}.
            {!data?.total && <button className="btn btn-primary" onClick={() => setAdding(true)}><Plus size={11} />Add the graphic-novel art</button>}</div>
        ) : (
          <div className="grid grid-cols-3 gap-1.5">
            {photos.map(p => (
              <div key={p.id} className={cx('contents')}>
                <PhotoTile p={p} open={open === p.id} onToggle={() => setOpen(open === p.id ? null : p.id)} onPick={() => onPick({ photo: p.id })} />
                {open === p.id && <PhotoDetail p={p} onPick={onPick} onEdit={() => setEdit(p)} />}
              </div>
            ))}
          </div>
        )}
      </div>
      {adding && <AddPhotos onClose={() => setAdding(false)} />}
      {edit && <SubjectEditor photo={photos.find(x => x.id === edit.id) ?? edit} onClose={() => setEdit(null)} />}
    </div>
  )
}

function dragPiece(e: React.DragEvent, piece: Piece) {
  e.dataTransfer.setData(DRAG_MIME, JSON.stringify(piece))
  e.dataTransfer.setData('text/plain', piece.photo)
  e.dataTransfer.effectAllowed = 'copy'
}

function PhotoTile({ p, open, onToggle, onPick }: { p: Photo; open: boolean; onToggle: () => void; onPick: () => void }) {
  return (
    <button draggable onDragStart={(e) => dragPiece(e, { photo: p.id })} onClick={onPick} onDoubleClick={onToggle}
      className={cx('group relative aspect-[2/3] rounded overflow-hidden border bg-ink-800 text-left', open ? 'border-gold-400' : 'border-ink-700 hover:border-ink-400')}
      title={`${p.name}${p.chapter ? `\n${p.chapter}` : ''}\n${p.tags.join(', ')}\nClick: place · drag onto a slot · ⋯ for subjects`}>
      <img src={p.thumb} alt={p.name} className="w-full h-full object-cover" loading="lazy" draggable={false} />
      <span className="absolute left-0 right-0 bottom-0 px-1 py-0.5 bg-black/65 text-[0.6rem] text-ink-200 truncate">{p.page ? `p${p.page} · ` : ''}{p.name}</span>
      {p.subjects.length > 0 && <span className="absolute top-1 left-1 chip h-4 px-1 bg-black/60 border-gold-500/50 text-gold-300"><Crosshair size={8} />{p.subjects.length}</span>}
      <span role="button" tabIndex={0} onClick={(e) => { e.stopPropagation(); onToggle() }} onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onToggle() } }}
        className="absolute top-1 right-1 w-5 h-5 grid place-items-center rounded bg-black/60 text-ink-200 opacity-0 group-hover:opacity-100 hover:text-gold-300" title="Subjects and details">⋯</span>
    </button>
  )
}

function PhotoDetail({ p, onPick, onEdit }: { p: Photo; onPick: (pc: Piece) => void; onEdit: () => void }) {
  return (
    <div className="col-span-3 card p-2 flex flex-col gap-1.5">
      <div className="flex items-center gap-2 text-2xs text-ink-300"><span className="truncate flex-1 text-ink-100">{p.name}</span><span className="font-mono text-ink-500">{p.w}×{p.h}</span></div>
      <div className="text-2xs text-ink-400 truncate">{[p.book, p.page && `page ${p.page}`, p.era, p.chapter].filter(Boolean).join(' · ') || p.origin}</div>
      {p.subjects.length ? (
        <div className="grid grid-cols-3 gap-1">
          {p.subjects.map(s => (
            <button key={s.id} draggable onDragStart={(e) => dragPiece(e, { photo: p.id, subject: s.id, crop: s })} onClick={() => onPick({ photo: p.id, subject: s.id, crop: s })}
              className="relative aspect-square rounded overflow-hidden border border-ink-700 hover:border-gold-400" title={`${s.label}${s.what ? `\n${s.what}` : ''}${s.drama != null ? `\ndrama ${s.drama}` : ''}`}>
              <SubjectThumb p={p} s={s} />
              <span className="absolute left-0 right-0 bottom-0 px-1 bg-black/65 text-[0.58rem] text-ink-200 truncate">{s.label}</span>
            </button>
          ))}
        </div>
      ) : <div className="text-2xs text-ink-500 italic">No subjects yet: draw crop boxes around the clear subjects (or ask the AI).</div>}
      <button className="btn btn-sm self-start" onClick={onEdit}><Crosshair size={10} />Subjects & tags…</button>
    </div>
  )
}

/** A subject's crop shown in its tile (measured, so it fills whatever size the tile has). */
function SubjectThumb({ p, s }: { p: Photo; s: Crop }) {
  const ref = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(80)
  useEffect(() => { if (ref.current) setW(ref.current.clientWidth || 80) }, [])
  return <div ref={ref} className="absolute inset-0" style={{ backgroundImage: `url(${p.thumb})`, ...cropStyle(p, s, w, w) }} />
}

function AddPhotos({ onClose }: { onClose: () => void }) {
  const [path, setPath] = useState('')
  const [tags, setTags] = useState('')
  const [recursive, setRecursive] = useState(false)
  const books = useRepoBooks(true).data ?? []
  const fileRef = useRef<HTMLInputElement>(null)
  const done = (r: { added: number; already: number; skipped?: string[] }) => toast('ok', `${r.added} photo${r.added === 1 ? '' : 's'} added`, `${r.already} already in the repo${r.skipped?.length ? ` · ${r.skipped.length} skipped` : ''}`)
  const folder = useRepoMutation(() => stitchApi.repoFolder(path, tags, recursive), (r) => { done(r); onClose() })
  const upload = useRepoMutation((files: File[]) => stitchApi.repoUpload(files, tags), (r) => { done(r); onClose() })
  const qc = useQueryClient()
  const book = useRepoMutation((id: string) => stitchApi.repoBook(id), (r) => { done(r); qc.invalidateQueries({ queryKey: ['stitch-repo-books'] }) })
  return (
    <Modal title="Add photos to the repo" onClose={onClose} width="max-w-xl">
      <div className="flex flex-col gap-4 text-xs">
        <section className="flex flex-col gap-1.5">
          <div className="label flex items-center gap-1.5"><BookOpenCheck size={11} />From an imported Book (each page's art layer)</div>
          {!books.length && <div className="text-ink-500 italic">No Book imported yet (Rail → Book → Import).</div>}
          {books.map(b => (
            <div key={b.id} className="flex items-center gap-2"><span className="flex-1 truncate text-ink-200">{b.title} — {b.volume} <span className="text-ink-500">· {b.pages} pages · {b.in_repo} in repo</span></span>
              <button className="btn btn-sm" disabled={book.isPending} onClick={() => book.mutate(b.id)}>Add its art</button></div>
          ))}
        </section>
        <section className="flex flex-col gap-1.5">
          <div className="label flex items-center gap-1.5"><FolderOpen size={11} />A folder on this Mac (e.g. the pipeline's chosen art)</div>
          <div className="flex gap-1.5"><input className="input font-mono" placeholder="~/apps/dharma-pipeline/exports/chosen" value={path} onChange={(e) => setPath(e.target.value)} />
            <button className="btn btn-primary" disabled={!path.trim() || folder.isPending} onClick={() => folder.mutate(undefined)}>Import</button></div>
          <label className="flex items-center gap-1.5 text-ink-400"><input type="checkbox" checked={recursive} onChange={(e) => setRecursive(e.target.checked)} />include sub-folders</label>
        </section>
        <section className="flex flex-col gap-1.5">
          <div className="label flex items-center gap-1.5"><Upload size={11} />Files</div>
          <input ref={fileRef} type="file" multiple accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => { const f = Array.from(e.target.files ?? []); if (f.length) upload.mutate(f) }} />
          <button className="btn self-start" disabled={upload.isPending} onClick={() => fileRef.current?.click()}><Upload size={11} />Choose images…</button>
        </section>
        <label className="flex flex-col gap-1"><span className="label">Tags for the folder / files (comma separated)</span><input className="input" placeholder="Book One, Lanka" value={tags} onChange={(e) => setTags(e.target.value)} /></label>
        <div className="text-2xs text-ink-500">Photos are copied into the studio's data folder on this Mac (data/stitch/repo); the same image added twice is kept once.</div>
      </div>
    </Modal>
  )
}

type Box = Crop & { id?: string; label: string; drama?: number; what?: string; ai?: boolean }

/** Draw, move and name subject crop boxes on a photo; the AI can propose some (kept only when the author says so). */
export function SubjectEditor({ photo, onClose }: { photo: Photo; onClose: () => void }) {
  const qc = useQueryClient()
  const [sel, setSel] = useState<string | null>(null)
  const [draft, setDraft] = useState<Box | null>(null)
  const [proposals, setProposals] = useState<(Box & { keep: boolean })[]>([])
  const [meta, setMeta] = useState({ name: photo.name, tags: photo.tags.join(', '), era: photo.era ?? '', chapter: photo.chapter ?? '' })
  const ref = useRef<HTMLDivElement>(null)
  const drag = useRef<{ mode: 'draw' | 'move' | 'size'; id?: string; x0: number; y0: number; box: Box } | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: sk.repo })
  const add = useApiMutation((b: Box) => stitchApi.addSubject(photo.id, b), [], () => { setDraft(null); refresh() })
  const patch = useApiMutation((a: { id: string; b: Partial<Box> }) => stitchApi.patchSubject(photo.id, a.id, a.b), [], refresh)
  const del = useApiMutation((id: string) => stitchApi.deleteSubject(photo.id, id), [], () => { setSel(null); refresh() })
  const keep = useApiMutation((bs: Box[]) => stitchApi.addSubjects(photo.id, bs), [], () => { setProposals([]); refresh() })
  const find = useApiMutation(() => stitchApi.findSubjects(photo.id), [], (r) => { setProposals(r.proposals.map(p => ({ ...p, keep: true }))); if (!r.proposals.length) toast('info', 'No subjects proposed') })
  const save = useApiMutation(() => stitchApi.patchPhoto(photo.id, { name: meta.name, tags: meta.tags.split(',').map(t => t.trim()).filter(Boolean), era: meta.era || null, chapter: meta.chapter || null }), [sk.repo], () => toast('ok', 'Saved'))
  const delPhoto = useApiMutation(() => stitchApi.deletePhoto(photo.id), [sk.repo], onClose)
  const [live, setLive] = useState<Record<string, Box>>({})
  const boxes: Box[] = photo.subjects.map(s => live[s.id] ?? s)
  const pt = (e: React.PointerEvent) => { const r = ref.current!.getBoundingClientRect(); return { x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)) } }
  const down = (e: React.PointerEvent, mode: 'draw' | 'move' | 'size', b?: Box) => {
    e.stopPropagation(); e.preventDefault()
    const p = pt(e)
    ;(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId)
    if (mode === 'draw') { setSel(null); const nb = { x: p.x, y: p.y, w: 0, h: 0, label: '' }; drag.current = { mode, x0: p.x, y0: p.y, box: nb }; setDraft(nb) }
    else { setSel(b!.id!); drag.current = { mode, id: b!.id, x0: p.x, y0: p.y, box: { ...b! } } }
  }
  const move = (e: React.PointerEvent) => {
    const d = drag.current; if (!d) return
    const p = pt(e)
    if (d.mode === 'draw') setDraft({ ...d.box, x: Math.min(d.x0, p.x), y: Math.min(d.y0, p.y), w: Math.abs(p.x - d.x0), h: Math.abs(p.y - d.y0) })
    else if (d.mode === 'move') setLive(l => ({ ...l, [d.id!]: { ...d.box, x: Math.max(0, Math.min(1 - d.box.w, d.box.x + p.x - d.x0)), y: Math.max(0, Math.min(1 - d.box.h, d.box.y + p.y - d.y0)) } }))
    else setLive(l => ({ ...l, [d.id!]: { ...d.box, w: Math.max(0.03, Math.min(1 - d.box.x, d.box.w + p.x - d.x0)), h: Math.max(0.03, Math.min(1 - d.box.y, d.box.h + p.y - d.y0)) } }))
  }
  const up = () => {
    const d = drag.current; drag.current = null; if (!d) return
    if (d.mode === 'draw') { if (!draft || draft.w < 0.03 || draft.h < 0.03) setDraft(null) }
    else { const b = live[d.id!]; if (b) patch.mutate({ id: d.id!, b: { x: b.x, y: b.y, w: b.w, h: b.h } }, { onSettled: () => setLive(l => { const n = { ...l }; delete n[d.id!]; return n }) }) }
  }
  const selected = boxes.find(b => b.id === sel)
  const aspect = photo.w / photo.h
  return (
    <Modal title={`Subjects · ${photo.name}`} onClose={onClose} width="max-w-5xl">
      <div className="flex gap-4">
        <div className="flex-1 min-w-0 grid place-items-center bg-ink-950 rounded p-2">
          <div ref={ref} className="relative select-none touch-none cursor-crosshair" style={{ width: `min(100%, ${70 * aspect}vh)`, aspectRatio: `${aspect}` }}
            onPointerDown={(e) => down(e, 'draw')} onPointerMove={move} onPointerUp={up} data-testid="subject-canvas">
            <img src={photo.url} alt={photo.name} className="absolute inset-0 w-full h-full object-contain pointer-events-none" draggable={false} />
            {boxes.map(b => (
              <div key={b.id} className={cx('absolute border-2 cursor-move', b.id === sel ? 'border-gold-300 bg-gold-300/10' : 'border-sky-300/80 hover:bg-sky-300/10')}
                style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` }} onPointerDown={(e) => down(e, 'move', b)}>
                <span className="absolute -top-5 left-0 px-1 text-[0.62rem] bg-black/75 text-ink-100 whitespace-nowrap">{b.label}{b.drama != null ? ` · ${b.drama}` : ''}</span>
                <span className="absolute -right-1.5 -bottom-1.5 w-3 h-3 bg-gold-300 cursor-nwse-resize" onPointerDown={(e) => down(e, 'size', b)} />
              </div>
            ))}
            {proposals.map((b, i) => (
              <div key={`p${i}`} className={cx('absolute border-2 border-dashed pointer-events-none', b.keep ? 'border-emerald-300' : 'border-ink-500')}
                style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` }}>
                <span className="absolute -top-5 left-0 px-1 text-[0.62rem] bg-emerald-900/80 text-emerald-100 whitespace-nowrap">AI · {b.label} · {b.drama ?? '–'}</span>
              </div>
            ))}
            {draft && <div className="absolute border-2 border-gold-300 bg-gold-300/10" style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`, width: `${draft.w * 100}%`, height: `${draft.h * 100}%` }} />}
          </div>
        </div>
        <div className="w-72 shrink-0 flex flex-col gap-3 text-xs">
          <div className="text-2xs text-ink-400">Drag on the painting to draw a crop box around a clear subject; drag a box to move it, its corner to resize.</div>
          {draft && draft.w >= 0.03 && !drag.current && (
            <form className="card p-2 flex flex-col gap-1.5" onSubmit={(e) => { e.preventDefault(); add.mutate({ ...draft, label: draft.label || 'subject' }) }}>
              <span className="label">New subject</span>
              <input className="input" autoFocus placeholder="e.g. Ravana's crowned heads" value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} />
              <div className="flex gap-1.5"><button className="btn btn-primary btn-sm" type="submit"><Check size={10} />Save</button><button className="btn btn-sm" type="button" onClick={() => setDraft(null)}>Cancel</button></div>
            </form>
          )}
          {selected && (
            <div className="card p-2 flex flex-col gap-1.5">
              <span className="label">Selected subject</span>
              <input className="input" defaultValue={selected.label} key={selected.id} onBlur={(e) => e.target.value !== selected.label && patch.mutate({ id: selected.id!, b: { label: e.target.value } })} aria-label="Subject label" />
              {selected.what && <div className="text-2xs text-ink-400">{selected.what}</div>}
              <button className="btn btn-danger btn-sm self-start" onClick={() => del.mutate(selected.id!)}><Trash2 size={10} />Delete</button>
            </div>
          )}
          <div className="flex flex-col gap-1">
            <span className="label">Subjects ({boxes.length})</span>
            {boxes.map(b => <button key={b.id} className={cx('text-left px-1.5 py-1 rounded hover:bg-ink-800', b.id === sel && 'bg-ink-800 text-gold-300')} onClick={() => setSel(b.id!)}>{b.label}{b.drama != null && <span className="text-ink-500"> · drama {b.drama}</span>}{b.ai && <span className="text-emerald-400"> · AI</span>}</button>)}
          </div>
          <div className="card p-2 flex flex-col gap-1.5">
            <button className="btn self-start" disabled={find.isPending} onClick={() => find.mutate(undefined)}><Sparkles size={11} />{find.isPending ? 'Looking…' : 'Find subjects (AI)'}</button>
            <span className="text-2xs text-ink-500">The OpenAI vision model proposes 4–8 crops with a drama score. Nothing is saved until you keep them.</span>
            {proposals.map((p, i) => (
              <label key={i} className="flex items-start gap-1.5"><input type="checkbox" checked={p.keep} onChange={(e) => setProposals(ps => ps.map((x, j) => j === i ? { ...x, keep: e.target.checked } : x))} />
                <span><span className="text-ink-100">{p.label}</span> <span className="text-ink-500">· {p.drama ?? '–'}</span>{p.what && <span className="block text-2xs text-ink-400">{p.what}</span>}</span></label>
            ))}
            {proposals.length > 0 && <div className="flex gap-1.5"><button className="btn btn-primary btn-sm" disabled={keep.isPending || !proposals.some(p => p.keep)} onClick={() => keep.mutate(proposals.filter(p => p.keep).map(({ keep: _k, ...b }) => b))}><Check size={10} />Keep selected</button>
              <button className="btn btn-sm" onClick={() => setProposals([])}><X size={10} />Discard</button></div>}
          </div>
          <div className="card p-2 flex flex-col gap-1.5">
            <span className="label">Details</span>
            <input className="input" value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} aria-label="Name" />
            <input className="input" placeholder="tags, comma separated" value={meta.tags} onChange={(e) => setMeta({ ...meta, tags: e.target.value })} aria-label="Tags" />
            <div className="flex gap-1.5"><input className="input" placeholder="era" value={meta.era} onChange={(e) => setMeta({ ...meta, era: e.target.value })} aria-label="Era" />
              <input className="input" placeholder="chapter" value={meta.chapter} onChange={(e) => setMeta({ ...meta, chapter: e.target.value })} aria-label="Chapter" /></div>
            <div className="flex gap-1.5"><button className="btn btn-sm" onClick={() => save.mutate(undefined)}>Save details</button><span className="flex-1" />
              <button className="btn btn-danger btn-sm" onClick={() => { if (confirm('Remove this photo from the repo?')) delPhoto.mutate(undefined) }}><Trash2 size={10} />Remove photo</button></div>
          </div>
        </div>
      </div>
    </Modal>
  )
}
