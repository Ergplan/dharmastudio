import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Scissors, Crosshair, Feather, Check, Undo2, Sparkles, ExternalLink, Clapperboard, ShieldAlert, FileCheck2 } from 'lucide-react'
import { useChapters, usePages, useRender, useGate, useCharacters, useCanvases, useSavePage, useRecut, useSilhouettes, useApiMutation, type JobResp } from '@/api/hooks'
import { api, openRenderInNewTab } from '@/api/client'
import { BEATS, type Beat, type Page, type Provider } from '@/api/types'
import { useEditor } from '@/store/editor'
import { cx, StatusBadge, Spinner, Empty, JobProgress } from '@/components/ui'
import { FittedPage, PageFrame } from '@/components/pages/PageFrame'
import { PanelOverlay, ShardEditorOverlay, MarginaliaOverlay } from '@/components/pages/Overlays'
import { ShardTools } from '@/components/pages/ShardTools'
import { MarginaliaDrawer } from '@/components/pages/MarginaliaDrawer'
import { PanelInspector } from '@/components/pages/PanelInspector'
import { DirectorModal } from '@/components/pages/DirectorModal'
import { TypePopover } from '@/components/pages/TypePopover'
import { QROverlay, QRToolbarButtons } from '@/components/pages/QRTools'
import { fitPage } from '@/lib/mm'
import { toast } from '@/store/toasts'

export default function PagesScreen() {
  const { data: chapters } = useChapters()
  const ed = useEditor()
  const nav = useNavigate()
  useEffect(() => { if (chapters?.length && !chapters.some(c => c.id === ed.chapterId)) ed.setChapter(chapters[0].id) }, [chapters]) // eslint-disable-line react-hooks/exhaustive-deps
  const { data: pages, isLoading } = usePages(ed.chapterId, { refetchInterval: 3000 })
  const { data: chars = [] } = useCharacters()
  const { data: canvases = [] } = useCanvases()
  const { data: sils = [] } = useSilhouettes()
  useEffect(() => { if (pages?.length && !pages.some(p => p.id === ed.pageId)) ed.setPage(pages[0].id) }, [pages]) // eslint-disable-line react-hooks/exhaustive-deps
  const page = pages?.find(p => p.id === ed.pageId) ?? null
  const panels = useMemo(() => [...(page?.panels ?? [])].sort((a, b) => a.n - b.n), [page])
  const panel = panels.find(p => p.id === ed.panelId) ?? null
  const { data: html } = useRender(page?.id ?? null, ed.canvasOverride ?? page?.canvas_override ?? null, ed.lang)
  const { data: gate } = useGate(page?.id ?? null)
  const savePage = useSavePage()
  const recut = useRecut()
  const [provider, setProvider] = useState<Provider>('sunburst')
  const [n, setN] = useState(2)
  const [director, setDirector] = useState(false)
  const [pageJob, setPageJob] = useState<number | null>(null)
  const genAll = useApiMutation(() => api.post<JobResp>(`/api/pages/${page!.id}/generate-all`, { provider, n }), [['pages'], ['jobs']], (r) => setPageJob(r.job_id))
  const gateBlocked = gate && !gate.ok ? `Lock before generating: ${gate.unlocked.join(', ')}` : null
  const frozen = page?.status === 'approved'

  // load shard drafts when the editor opens or the page's panels change (and nothing is dirty)
  useEffect(() => { if (ed.shardEditor && page && !ed.dirty) ed.loadDrafts(panels) }, [ed.shardEditor, page?.id, JSON.stringify(panels.map(p => [p.id, p.shape, p.locked_shape, p.image_group]))]) // eslint-disable-line react-hooks/exhaustive-deps

  // keyboard
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.tagName === 'SELECT' || tgt.isContentEditable)) return
      if (!pages?.length) return
      const idx = pages.findIndex(p => p.id === ed.pageId)
      if (e.key === 'ArrowLeft' && idx > 0) { ed.setPage(pages[idx - 1].id); e.preventDefault() }
      else if (e.key === 'ArrowRight' && idx < pages.length - 1) { ed.setPage(pages[idx + 1].id); e.preventDefault() }
      else if (/^[1-9]$/.test(e.key) && !e.altKey && !e.ctrlKey && !e.metaKey) { const p = panels[Number(e.key) - 1]; if (p) ed.setPanel(p.id) }
      else if (e.key.toLowerCase() === 'g' && !e.ctrlKey && !e.metaKey) { if (panel) window.dispatchEvent(new CustomEvent('dharma:generate', { detail: panel.id })); else if (page && !gateBlocked && !frozen) genAll.mutate(undefined) }
      else if (e.key.toLowerCase() === 'a' && !e.ctrlKey && !e.metaKey && page) savePage.mutate({ id: page.id, status: page.status === 'approved' ? 'review' : 'approved' })
      else if (e.key.toLowerCase() === 'e' && !e.ctrlKey && !e.metaKey) ed.toggleShardEditor()
      else if (e.key.toLowerCase() === 'm' && !e.ctrlKey && !e.metaKey) ed.toggleMarginalia()
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z' && ed.shardEditor) { e.preventDefault(); e.shiftKey ? ed.redo() : ed.undo() }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y' && ed.shardEditor) { e.preventDefault(); ed.redo() }
      else if ((e.key === 'Backspace' || e.key === 'Delete')) {
        if (ed.shardEditor && panel && ed.selectedVertex !== null) { const d = ed.drafts[panel.id]; if (d && !d.locked_shape && d.shape.polygon_mm.length > 3) { ed.commit(ds => { ds[panel.id].shape.polygon_mm = ds[panel.id].shape.polygon_mm.filter((_, k) => k !== ed.selectedVertex); ds[panel.id].shape.kind = 'custom'; return ds }); ed.setSelectedVertex(null) } }
        else if (ed.marginalia && page && ed.selectedMarginalia !== null) { const d = ed.margDraft ?? page.marginalia; ed.setMargDraft(d.filter((_, i) => i !== ed.selectedMarginalia)); ed.setSelectedMarginalia(null) }
      }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [pages, panels, panel, page, ed, gateBlocked, frozen, savePage, genAll])

  if (isLoading || !chapters) return <Spinner />
  return (
    <div className="h-full flex min-h-0">
      {/* LEFT: thumbnails */}
      <div className="w-[12.25rem] shrink-0 border-r border-ink-800 flex flex-col min-h-0">
        <div className="panel-h">
          <select className="select h-6 text-2xs" value={ed.chapterId ?? ''} onChange={(e) => ed.setChapter(Number(e.target.value))}>{chapters.map(c => <option key={c.id} value={c.id}>v{c.volume_id} · ch {c.number}</option>)}</select>
        </div>
        <div className="flex-1 overflow-auto p-2 flex flex-col gap-2">
          {pages?.length === 0 && <Empty>No pages — prefill the chapter from Script.</Empty>}
          {pages?.map(p => <Thumb key={p.id} p={p} active={p.id === ed.pageId} onClick={() => ed.setPage(p.id)} lang={ed.lang} canvas={ed.canvasOverride ?? p.canvas_override ?? null} />)}
        </div>
        <div className="px-2 py-1.5 border-t border-ink-800 text-[0.625rem] text-ink-500 flex flex-wrap gap-x-2 gap-y-0.5"><span><span className="kbd">←</span><span className="kbd">→</span> pages</span><span><span className="kbd">1</span>–<span className="kbd">9</span> panel</span><span><span className="kbd">G</span> generate</span><span><span className="kbd">A</span> approve</span><span><span className="kbd">E</span> shards</span><span><span className="kbd">M</span> marginalia</span></div>
      </div>

      {/* CENTRE */}
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        {page && (
          <div className="min-h-9 shrink-0 border-b border-ink-800 bg-ink-900 flex flex-wrap items-center gap-1.5 px-2 py-1">
            <span className="text-xs font-medium text-ink-100 mr-1">Page {page.number}</span>
            <StatusBadge status={page.status} />
            {page.artifact && <span className="chip border-emerald-500/40 text-emerald-300" title={page.artifact}><FileCheck2 size={9} /> artifact saved</span>}
            <span className="w-px h-4 bg-ink-700 mx-1" />
            <select className="select h-6 w-auto text-2xs" value={page.beat} disabled={frozen} onChange={(e) => savePage.mutate({ id: page.id, beat: e.target.value as Beat })} title="Beat">{BEATS.map(b => <option key={b} value={b}>beat: {b}</option>)}</select>
            <button className="btn btn-sm" disabled={frozen || recut.isPending} title="Re-cut unlocked shards from the beat (POST recut)" onClick={() => recut.mutate(page.id)}><Scissors size={11} /> Re-cut</button>
            <button className={cx('btn btn-sm', ed.shardEditor && 'border-sky-400/70 text-sky-200 bg-sky-500/10')} title="Shard editor (E)" onClick={() => ed.toggleShardEditor()}><Crosshair size={11} /> Shards</button>
            <button className={cx('btn btn-sm', ed.marginalia && 'border-sky-400/70 text-sky-200 bg-sky-500/10')} title="Marginalia (M)" onClick={() => ed.toggleMarginalia()}><Feather size={11} /> Marginalia</button>
            <span className="w-px h-4 bg-ink-700 mx-1" />
            <div className="flex rounded border border-ink-600 overflow-hidden">{(['en', 'hi'] as const).map(l => <button key={l} className={cx('h-6 px-2 text-2xs uppercase', ed.lang === l ? 'bg-gold-500/20 text-gold-300' : 'text-ink-400 hover:bg-ink-800')} onClick={() => ed.setLang(l)}>{l}</button>)}</div>
            <select className="select h-6 w-auto text-2xs" value={ed.canvasOverride ?? page.canvas_override ?? ''} onChange={(e) => { const v = e.target.value || null; ed.setCanvasOverride(v); savePage.mutate({ id: page.id, canvas_override: v }) }} title="Canvas override for this page"><option value="">canvas: volume default</option>{canvases.map(c => <option key={c.key} value={c.key}>canvas: {c.name}</option>)}</select>
            <TypePopover page={page} />
            <div className="flex-1" />
            <QRToolbarButtons page={page} />
            <button className="btn btn-sm" title="Open the page's standalone HTML artifact in a new tab" onClick={() => openRenderInNewTab(page.id, { lang: ed.lang, ...(ed.canvasOverride ? { canvas: ed.canvasOverride } : {}) })}><ExternalLink size={11} /> Page HTML</button>
            <button className="btn btn-sm" onClick={() => setDirector(true)} title="Make pages in one instruction (SPEC §9)"><Clapperboard size={11} /> Director</button>
            <button className="btn btn-sm border-gold-500/50 text-gold-200" disabled={frozen} title={frozen ? 'Approved pages are frozen' : 'Plan, paint, critique and assemble this page under the master art direction'} onClick={() => nav(`/director?chapter=${page.chapter_id}&page=${page.id}`)}><Clapperboard size={11} /> Direct with Art Director</button>
            {page.status === 'approved'
              ? <button className="btn btn-sm" title="Un-approve (A)" onClick={() => savePage.mutate({ id: page.id, status: 'review' })}><Undo2 size={11} /> Unapprove</button>
              : <button className="btn btn-sm border-emerald-500/50 text-emerald-200 hover:bg-emerald-500/10" title="Approve — freezes the page and saves its HTML artifact (A)" onClick={() => savePage.mutate({ id: page.id, status: 'approved' }, { onSuccess: () => toast('ok', `Page ${page.number} approved`, 'Artifact saved. Regenerate requires un-approving.') })}><Check size={11} /> Approve</button>}
            <button className="btn btn-sm btn-primary" disabled={!!gateBlocked || frozen || genAll.isPending || !panels.length} title={gateBlocked ?? (frozen ? 'Approved pages are frozen' : `Generate ${n} candidates for every panel (${provider})`)} onClick={() => genAll.mutate(undefined)}>{gateBlocked ? <ShieldAlert size={11} /> : <Sparkles size={11} />} Generate all</button>
          </div>
        )}
        {gateBlocked && page && <div className="shrink-0 px-3 py-1.5 bg-amber-500/10 border-b border-amber-500/30 text-2xs text-amber-200 flex items-center gap-2"><ShieldAlert size={12} />{gateBlocked}. <a href="#/characters" className="underline">Open Characters</a></div>}
        {pageJob && <div className="shrink-0 p-2 border-b border-ink-800"><JobProgress jobId={pageJob} compact /></div>}
        <div className="flex-1 min-h-0 bg-[radial-gradient(ellipse_at_center,#1a1a1f_0%,#0d0d0f_70%)] p-4" onClick={() => { if (!ed.shardEditor) ed.setPanel(null) }}>
          {!page ? <div className="h-full grid place-items-center text-ink-500 text-xs">Select a page.</div> : (
            <FittedPage html={html} pad={0}>
              {(t) => ed.shardEditor
                ? <ShardEditorOverlay panels={panels} t={t} selectedId={ed.panelId} onSelect={ed.setPanel} />
                : ed.marginalia
                  ? <><MarginaliaOverlay page={page} panels={panels} t={t} silhouettes={sils} /><QROverlay page={page} t={t} /></>
                  : <PanelOverlay panels={panels} t={t} selectedId={ed.panelId} onSelect={ed.setPanel} />}
            </FittedPage>
          )}
        </div>
        {page?.balance && (
          <div className="shrink-0 h-6 border-t border-ink-800 bg-ink-900 flex items-center gap-2 px-3 text-2xs text-ink-400">
            <span>balance</span><BalanceMeter b={page.balance} className="w-40" />
            <span className="font-mono">image {Math.round(page.balance.image * 100)}% · parchment {Math.round(page.balance.parchment * 100)}% · ink {Math.round(page.balance.ink * 100)}%</span>
            <span className="text-ink-600">target 70 / 20 / 10</span>
            <span className="ml-auto font-mono">{panels.length} panels · seed {page.seed}</span>
          </div>
        )}
      </div>

      {/* RIGHT */}
      <div className="w-[25rem] shrink-0 border-l border-ink-800 flex flex-col min-h-0 bg-ink-900/40">
        {!page ? null : ed.shardEditor ? <ShardTools panels={panels} selected={panel} frozen={!!frozen} /> : ed.marginalia ? <MarginaliaDrawer page={page} frozen={!!frozen} /> : panel ? (
          <PanelInspector key={panel.id} panel={panel} page={page} chars={chars} gateBlocked={gateBlocked} provider={provider} setProvider={setProvider} n={n} setN={setN} pageNumber={page.number} />
        ) : (
          <div className="p-5 text-xs text-ink-500 flex flex-col gap-3">
            <p>Click a panel on the page (or press <span className="kbd">1</span>–<span className="kbd">9</span>) to see its scene, candidates and feedback box.</p>
            <ul className="text-2xs leading-5 text-ink-500">
              {panels.map(p => <li key={p.id} className="flex gap-2 cursor-pointer hover:text-ink-200" onClick={() => ed.setPanel(p.id)}><span className="font-mono text-ink-400 w-4">{p.n}</span><span className="truncate">{p.scene}</span><span className="ml-auto font-mono shrink-0">{p.candidates.length}c{p.selected_candidate_id ? ' ✓' : ''}</span></li>)}
            </ul>
          </div>
        )}
      </div>
      {director && ed.chapterId && pages && <DirectorModal chapterId={ed.chapterId} pages={pages} onClose={() => setDirector(false)} onStarted={() => { /* tray shows the batch */ }} />}
    </div>
  )
}

function BalanceMeter({ b, className }: { b: { image: number; parchment: number; ink: number }; className?: string }) {
  return (
    <div className={cx('h-1.5 flex rounded-sm overflow-hidden', className)} title={`image ${Math.round(b.image * 100)}% · parchment ${Math.round(b.parchment * 100)}% · ink ${Math.round(b.ink * 100)}%`}>
      <div className="bg-amber-600/80" style={{ width: `${b.image * 100}%` }} /><div className="bg-parchment-400" style={{ width: `${b.parchment * 100}%` }} /><div className="bg-sepia" style={{ width: `${b.ink * 100}%` }} />
    </div>
  )
}

function Thumb({ p, active, onClick, lang, canvas }: { p: Page; active: boolean; onClick: () => void; lang: 'en' | 'hi'; canvas: string | null }) {
  const { data: html } = useRender(p.id, canvas, lang)
  const t = fitPage(164, 248, 0)
  return (
    <button onClick={onClick} className={cx('rounded-md border text-left overflow-hidden bg-ink-900 hover:border-ink-400 transition-colors', active ? 'border-gold-500 ring-1 ring-gold-500/30' : 'border-ink-700')}>
      <div className="relative" style={{ height: t.h }}>
        {p.thumb ? <img src={p.thumb} alt="" className="w-full h-full object-cover" /> : <PageFrame html={html} t={t} title={`page ${p.number}`} />}
        <span className="absolute top-1 left-1 font-mono text-[0.625rem] px-1 rounded bg-black/70 text-ink-200">{p.number}</span>
        <StatusBadge status={p.status} className="absolute top-1 right-1" />
      </div>
      {p.balance && <div className="px-1.5 py-1"><BalanceMeter b={p.balance} /></div>}
    </button>
  )
}
