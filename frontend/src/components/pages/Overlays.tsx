import { useRef, useState, type PointerEvent as RPointerEvent, type WheelEvent as RWheelEvent } from 'react'
import type { Panel, Page, Marginalia, Silhouette } from '@/api/types'
import { mmToPx, pxToMm, round05, bbox, closestOnSegment, pointInPolygon, PAGE_W, PAGE_H, MARGIN, BLEED, clampMm, type Transform } from '@/lib/mm'
import { snapPoint } from '@/lib/shapes'
import { useEditor } from '@/store/editor'
import { mediaUrl } from '@/api/client'

const GUTTER_MM = 3

/** View-mode overlay: selectable panel outlines with numbers. */
export function PanelOverlay({ panels, t, selectedId, onSelect }: { panels: Panel[]; t: Transform; selectedId: number | null; onSelect: (id: number) => void }) {
  return (
    <svg className="absolute inset-0" width={t.w} height={t.h} viewBox={`0 0 ${t.w} ${t.h}`}>
      {panels.map(p => {
        const pts = p.shape.polygon_mm.map(([x, y]) => mmToPx(t, x, y).join(',')).join(' ')
        const sel = p.id === selectedId
        const b = bbox(p.shape.polygon_mm)
        const [lx, ly] = mmToPx(t, Math.max(b.x0, 0) + 2, Math.max(b.y0, 0) + 2)
        return (
          <g key={p.id} className="cursor-pointer" onClick={(e) => { e.stopPropagation(); onSelect(p.id) }}>
            <polygon points={pts} fill={sel ? 'rgba(242,196,90,0.08)' : 'rgba(255,255,255,0)'} stroke={sel ? '#f2c45a' : 'rgba(242,196,90,0.35)'} strokeWidth={sel ? 2 : 1} strokeDasharray={sel ? undefined : '4 3'} className="hover:stroke-gold-300" />
            <g transform={`translate(${lx},${ly})`}>
              <rect width={22} height={16} rx={2} fill={sel ? '#f2c45a' : 'rgba(13,13,15,0.75)'} />
              <text x={11} y={11.5} textAnchor="middle" fontSize={10} fontFamily="ui-monospace,monospace" fill={sel ? '#0d0d0f' : '#e2b53a'}>{p.n}</text>
            </g>
            {p.image_group && <text {...labelAt(t, b, 24)} fontSize={9} fill="#8fa3d6" fontFamily="ui-monospace,monospace">⧉ {p.image_group}</text>}
            {p.locked_shape && <text {...labelAt(t, b, p.image_group ? 60 : 24)} fontSize={9} fill="#cfcfd6" fontFamily="ui-monospace,monospace">🔒</text>}
          </g>
        )
      })}
    </svg>
  )
}
function labelAt(t: Transform, b: ReturnType<typeof bbox>, dx: number) { const [x, y] = mmToPx(t, Math.max(b.x0, 0) + 2, Math.max(b.y0, 0) + 2); return { x: x + dx, y: y + 11.5 } }

/** Shard editor overlay: editable polygons (SPEC §2). */
export function ShardEditorOverlay({ panels, t, selectedId, onSelect }: { panels: Panel[]; t: Transform; selectedId: number | null; onSelect: (id: number) => void }) {
  const drafts = useEditor(s => s.drafts)
  const selectedVertex = useEditor(s => s.selectedVertex)
  const setSelectedVertex = useEditor(s => s.setSelectedVertex)
  const setPolygon = useEditor(s => s.setPolygon)
  const setFocal = useEditor(s => s.setFocal)
  const beginGesture = useEditor(s => s.beginGesture)
  const commit = useEditor(s => s.commit)
  const svgRef = useRef<SVGSVGElement>(null)
  const [snapGuide, setSnapGuide] = useState<{ x?: number; y?: number } | null>(null)
  const drag = useRef<{ kind: 'vertex' | 'focal'; id: number; i: number; startMm: [number, number]; startFocal?: { x: number; y: number; scale: number } } | null>(null)

  const toMm = (e: { clientX: number; clientY: number }): [number, number] => {
    const r = svgRef.current!.getBoundingClientRect()
    return pxToMm(t, e.clientX - r.left, e.clientY - r.top)
  }
  const neighboursOf = (id: number) => panels.filter(p => p.id !== id && drafts[p.id]).map(p => drafts[p.id].shape.polygon_mm)

  const onVertexDown = (e: RPointerEvent, id: number, i: number) => {
    e.stopPropagation(); e.preventDefault()
    if (drafts[id]?.locked_shape) return
    if (e.button === 2) return
    onSelect(id); setSelectedVertex(i)
    beginGesture()
    drag.current = { kind: 'vertex', id, i, startMm: toMm(e) }
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
  }
  const onFocalDown = (e: RPointerEvent, id: number) => {
    if (e.button !== 0) return
    e.stopPropagation()
    onSelect(id); setSelectedVertex(null)
    const d = drafts[id]; if (!d) return
    beginGesture()
    drag.current = { kind: 'focal', id, i: -1, startMm: toMm(e), startFocal: { ...d.shape.focal } }
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
  }
  const onMove = (e: RPointerEvent) => {
    const g = drag.current; if (!g) return
    const mm = toMm(e)
    if (g.kind === 'vertex') {
      const poly = drafts[g.id].shape.polygon_mm.map(p => [...p] as [number, number])
      let p: [number, number] = [clampMm(mm[0], -BLEED, PAGE_W + BLEED), clampMm(mm[1], -BLEED, PAGE_H + BLEED)]
      if (!e.altKey) { const s = snapPoint(p, neighboursOf(g.id), GUTTER_MM); p = s.p; setSnapGuide(s.snappedX || s.snappedY ? { x: s.snappedX ? p[0] : undefined, y: s.snappedY ? p[1] : undefined } : null) }
      else { p = [round05(p[0]), round05(p[1])]; setSnapGuide(null) }
      poly[g.i] = p
      setPolygon(g.id, poly)
    } else {
      const d = drafts[g.id]; const b = bbox(d.shape.polygon_mm)
      const f = g.startFocal!
      const iw = b.w * f.scale, ih = (b.w * 2 / 3) * f.scale * Math.max(1, b.h / (b.w * 2 / 3))
      const nx = Math.min(1, Math.max(0, f.x - (mm[0] - g.startMm[0]) / iw))
      const ny = Math.min(1, Math.max(0, f.y - (mm[1] - g.startMm[1]) / ih))
      setFocal(g.id, { x: +nx.toFixed(3), y: +ny.toFixed(3), scale: f.scale })
    }
  }
  const onUp = () => { drag.current = null; setSnapGuide(null) }
  const onWheel = (e: RWheelEvent, id: number) => {
    const d = drafts[id]; if (!d) return
    e.stopPropagation()
    const scale = Math.min(4, Math.max(1, +(d.shape.focal.scale * (e.deltaY < 0 ? 1.08 : 1 / 1.08)).toFixed(3)))
    setFocal(id, { ...d.shape.focal, scale }, true)
  }
  const onEdgeDoubleClick = (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    const d = drafts[id]; if (!d || d.locked_shape) return
    const mm = toMm(e)
    const poly = d.shape.polygon_mm
    let best = { i: 0, d: Infinity, q: mm }
    for (let i = 0; i < poly.length; i++) { const r = closestOnSegment(poly[i], poly[(i + 1) % poly.length], mm); if (r.d < best.d) best = { i, d: r.d, q: r.q } }
    const next = [...poly.slice(0, best.i + 1), [round05(best.q[0]), round05(best.q[1])] as [number, number], ...poly.slice(best.i + 1)]
    commit(ds => { ds[id].shape.polygon_mm = next; ds[id].shape.kind = 'custom'; return ds })
    setSelectedVertex(best.i + 1)
  }
  const deleteVertex = (id: number, i: number) => {
    const d = drafts[id]; if (!d || d.locked_shape || d.shape.polygon_mm.length <= 3) return
    commit(ds => { ds[id].shape.polygon_mm = ds[id].shape.polygon_mm.filter((_, k) => k !== i); ds[id].shape.kind = 'custom'; return ds })
    setSelectedVertex(null)
  }

  const [mx0, my0] = mmToPx(t, MARGIN, MARGIN); const [mx1, my1] = mmToPx(t, PAGE_W - MARGIN, PAGE_H - MARGIN)
  const [tx0, ty0] = mmToPx(t, 0, 0); const [tx1, ty1] = mmToPx(t, PAGE_W, PAGE_H)
  const ordered = [...panels].sort((a, b) => (a.id === selectedId ? 1 : b.id === selectedId ? -1 : (drafts[a.id]?.shape.z ?? 0) - (drafts[b.id]?.shape.z ?? 0)))
  return (
    <svg ref={svgRef} className="absolute inset-0 select-none" width={t.w} height={t.h} viewBox={`0 0 ${t.w} ${t.h}`} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp} onContextMenu={(e) => e.preventDefault()}>
      {/* trim + margin guides */}
      <rect x={tx0} y={ty0} width={tx1 - tx0} height={ty1 - ty0} fill="none" stroke="rgba(143,163,214,0.5)" strokeWidth={1} />
      <rect x={mx0} y={my0} width={mx1 - mx0} height={my1 - my0} fill="none" stroke="rgba(143,163,214,0.35)" strokeWidth={1} strokeDasharray="3 3" />
      {snapGuide?.x !== undefined && <line x1={mmToPx(t, snapGuide.x, 0)[0]} x2={mmToPx(t, snapGuide.x, 0)[0]} y1={0} y2={t.h} stroke="#38bdf8" strokeWidth={1} strokeDasharray="2 2" />}
      {snapGuide?.y !== undefined && <line y1={mmToPx(t, 0, snapGuide.y)[1]} y2={mmToPx(t, 0, snapGuide.y)[1]} x1={0} x2={t.w} stroke="#38bdf8" strokeWidth={1} strokeDasharray="2 2" />}
      {ordered.map(p => {
        const d = drafts[p.id]; if (!d) return null
        const poly = d.shape.polygon_mm
        const pts = poly.map(([x, y]) => mmToPx(t, x, y).join(',')).join(' ')
        const sel = p.id === selectedId
        const locked = d.locked_shape
        const b = bbox(poly)
        const [lx, ly] = mmToPx(t, Math.max(b.x0, 0) + 2, Math.max(b.y0, 0) + 2)
        return (
          <g key={p.id}>
            <polygon points={pts} fill={sel ? 'rgba(56,189,248,0.10)' : 'rgba(255,255,255,0.01)'} stroke={sel ? '#38bdf8' : locked ? 'rgba(207,207,214,0.5)' : 'rgba(56,189,248,0.45)'} strokeWidth={sel ? 1.5 : 1}
              className={locked ? 'cursor-not-allowed' : 'cursor-move'} onPointerDown={(e) => onFocalDown(e, p.id)} onWheel={(e) => onWheel(e, p.id)} onDoubleClick={(e) => onEdgeDoubleClick(e, p.id)} />
            {/* fat invisible edges for double-click to add vertices */}
            {!locked && poly.map((a, i) => { const bb = poly[(i + 1) % poly.length]; const [x1, y1] = mmToPx(t, a[0], a[1]); const [x2, y2] = mmToPx(t, bb[0], bb[1]); return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={10} className="cursor-copy" onDoubleClick={(e) => onEdgeDoubleClick(e, p.id)} onPointerDown={(e) => { e.stopPropagation(); onSelect(p.id) }} /> })}
            <g transform={`translate(${lx},${ly})`}><rect width={22} height={16} rx={2} fill={sel ? '#38bdf8' : 'rgba(13,13,15,0.75)'} /><text x={11} y={11.5} textAnchor="middle" fontSize={10} fontFamily="ui-monospace,monospace" fill={sel ? '#0d0d0f' : '#7dd3fc'}>{p.n}</text></g>
            {sel && !locked && poly.map(([x, y], i) => { const [px, py] = mmToPx(t, x, y); const vs = selectedVertex === i; return (
              <g key={i}>
                <circle cx={px} cy={py} r={vs ? 6 : 4.5} fill={vs ? '#f2c45a' : '#0d0d0f'} stroke={vs ? '#f2c45a' : '#38bdf8'} strokeWidth={1.5} className="cursor-grab active:cursor-grabbing"
                  onPointerDown={(e) => onVertexDown(e, p.id, i)} onContextMenu={(e) => { e.preventDefault(); e.stopPropagation(); deleteVertex(p.id, i) }} onClick={(e) => { e.stopPropagation(); setSelectedVertex(i) }} />
                {vs && <text x={px + 8} y={py - 8} fontSize={9} fill="#f2c45a" fontFamily="ui-monospace,monospace">{x.toFixed(1)}, {y.toFixed(1)}</text>}
              </g>
            ) })}
            {sel && (() => { const f = d.shape.focal; const [fx, fy] = mmToPx(t, b.x0 + b.w * f.x, b.y0 + b.h * f.y); return <g pointerEvents="none"><circle cx={fx} cy={fy} r={5} fill="none" stroke="#f2c45a" strokeWidth={1} /><line x1={fx - 8} x2={fx + 8} y1={fy} y2={fy} stroke="#f2c45a" strokeWidth={1} /><line y1={fy - 8} y2={fy + 8} x1={fx} x2={fx} stroke="#f2c45a" strokeWidth={1} /><text x={fx + 8} y={fy + 12} fontSize={9} fill="#f2c45a" fontFamily="ui-monospace,monospace">×{f.scale.toFixed(2)}</text></g> })()}
          </g>
        )
      })}
    </svg>
  )
}

/** Marginalia overlay: drop silhouettes in the margins, move/select/delete. */
export function MarginaliaOverlay({ page, panels, t, silhouettes }: { page: Page; panels: Panel[]; t: Transform; silhouettes: Silhouette[] }) {
  const margDraft = useEditor(s => s.margDraft) ?? page.marginalia
  const setMargDraft = useEditor(s => s.setMargDraft)
  const selected = useEditor(s => s.selectedMarginalia)
  const setSelected = useEditor(s => s.setSelectedMarginalia)
  const svgRef = useRef<SVGSVGElement>(null)
  const drag = useRef<{ i: number; dx: number; dy: number } | null>(null)
  const toMm = (e: { clientX: number; clientY: number }): [number, number] => { const r = svgRef.current!.getBoundingClientRect(); return pxToMm(t, e.clientX - r.left, e.clientY - r.top) }
  const inShard = (x: number, y: number) => panels.some(p => pointInPolygon(p.shape.polygon_mm, x, y))
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const id = Number(e.dataTransfer.getData('text/silhouette'))
    if (!id) return
    const [x, y] = toMm(e)
    const w = 14
    const item: Marginalia = { silhouette_id: id, x_mm: round05(clampMm(x - w / 2, -BLEED, PAGE_W + BLEED - w)), y_mm: round05(clampMm(y - w / 2, -BLEED, PAGE_H + BLEED - w)), w_mm: w, rotation: 0, tint: '#3a2d1a' }
    const next = [...margDraft, item]
    setMargDraft(next); setSelected(next.length - 1)
  }
  const onDown = (e: RPointerEvent, i: number) => {
    e.stopPropagation(); setSelected(i)
    const [x, y] = toMm(e); const m = margDraft[i]
    drag.current = { i, dx: x - m.x_mm, dy: y - m.y_mm }
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
  }
  const onMove = (e: RPointerEvent) => {
    const g = drag.current; if (!g) return
    const [x, y] = toMm(e)
    const next = margDraft.map((m, i) => i === g.i ? { ...m, x_mm: round05(clampMm(x - g.dx, -BLEED, PAGE_W + BLEED - m.w_mm)), y_mm: round05(clampMm(y - g.dy, -BLEED, PAGE_H + BLEED - m.w_mm)) } : m)
    setMargDraft(next)
  }
  const [mx0, my0] = mmToPx(t, MARGIN, MARGIN); const [mx1, my1] = mmToPx(t, PAGE_W - MARGIN, PAGE_H - MARGIN)
  return (
    <svg ref={svgRef} className="absolute inset-0 select-none" width={t.w} height={t.h} viewBox={`0 0 ${t.w} ${t.h}`} onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy' }} onDrop={onDrop} onPointerMove={onMove} onPointerUp={() => (drag.current = null)} onClick={() => setSelected(null)}>
      <defs><mask id="margin-mask"><rect width={t.w} height={t.h} fill="white" />{panels.map(p => <polygon key={p.id} points={p.shape.polygon_mm.map(([x, y]) => mmToPx(t, x, y).join(',')).join(' ')} fill="black" />)}</mask></defs>
      <rect width={t.w} height={t.h} fill="rgba(143,163,214,0.10)" mask="url(#margin-mask)" />
      <rect x={mx0} y={my0} width={mx1 - mx0} height={my1 - my0} fill="none" stroke="rgba(143,163,214,0.35)" strokeDasharray="3 3" />
      {margDraft.map((m, i) => {
        const s = silhouettes.find(x => x.id === m.silhouette_id)
        const [x, y] = mmToPx(t, m.x_mm, m.y_mm); const w = m.w_mm * t.k
        const sel = selected === i
        const over = inShard(m.x_mm + m.w_mm / 2, m.y_mm + m.w_mm / 2)
        return (
          <g key={i} transform={`translate(${x + w / 2},${y + w / 2}) rotate(${m.rotation}) translate(${-w / 2},${-w / 2})`} className="cursor-move" onPointerDown={(e) => onDown(e, i)} onClick={(e) => e.stopPropagation()}>
            {s && <image href={mediaUrl(s.path)} width={w} height={w} opacity={0.9} />}
            <rect width={w} height={w} fill="transparent" stroke={sel ? '#f2c45a' : over ? '#f87171' : 'rgba(242,196,90,0.5)'} strokeWidth={sel ? 1.5 : 1} strokeDasharray={sel ? undefined : '3 2'} />
          </g>
        )
      })}
    </svg>
  )
}
