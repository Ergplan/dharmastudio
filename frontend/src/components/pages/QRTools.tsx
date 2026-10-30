import { useRef, useState, type PointerEvent as RPointerEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Film, QrCode, X } from 'lucide-react'
import type { Page } from '@/api/types'
import { mmToPx, pxToMm, round05, PAGE_W, PAGE_H, type Transform } from '@/lib/mm'
import { usePageQR, usePageMoment, useCreateMoment, useMomentQR, useMovePageQR, useRemovePageQR, useQRs, usePlaceQR, type PageQREl } from '@/api/motion'
import { toast } from '@/store/toasts'
import { Modal, cx } from '@/components/ui'

const MIN_MM = 20

/** The QR page elements: drag to move, drag the corner to resize (≥ 20 mm), × to remove. Saved on release. */
export function QROverlay({ page, t }: { page: Page; t: Transform }) {
  const { data: els = [] } = usePageQR(page.id)
  const move = useMovePageQR()
  const remove = useRemovePageQR()
  const [live, setLive] = useState<Record<number, Partial<PageQREl>>>({})
  const svgRef = useRef<SVGSVGElement>(null)
  const drag = useRef<{ id: number; mode: 'move' | 'size'; dx: number; dy: number; el: PageQREl } | null>(null)
  const toMm = (e: { clientX: number; clientY: number }) => { const r = svgRef.current!.getBoundingClientRect(); return pxToMm(t, e.clientX - r.left, e.clientY - r.top) }
  if (!els.length) return null
  const down = (e: RPointerEvent, el: PageQREl, mode: 'move' | 'size') => {
    e.stopPropagation()
    const [x, y] = toMm(e)
    drag.current = { id: el.id, mode, dx: x - el.x_mm, dy: y - el.y_mm, el }
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
  }
  const onMove = (e: RPointerEvent) => {
    const g = drag.current; if (!g) return
    const [x, y] = toMm(e)
    if (g.mode === 'move') setLive(l => ({ ...l, [g.id]: { x_mm: round05(Math.max(0, Math.min(PAGE_W - g.el.w_mm, x - g.dx))), y_mm: round05(Math.max(0, Math.min(PAGE_H - g.el.h_mm, y - g.dy))) } }))
    else setLive(l => ({ ...l, [g.id]: { size_mm: round05(Math.max(MIN_MM, Math.min(60, g.el.size_mm * (x - g.el.x_mm) / g.el.w_mm))) } }))
  }
  const up = () => {
    const g = drag.current; drag.current = null; if (!g) return
    const p = live[g.id]; if (!p) return
    // the element's x is the printed box; the API stores the symbol's left edge (a URL label can be wider than the symbol)
    const body = g.mode === 'move' ? { x_mm: (p.x_mm ?? g.el.x_mm) + (g.el.sym_x_mm - g.el.x_mm), y_mm: p.y_mm } : { w_mm: p.size_mm }
    move.mutate({ id: g.id, ...body }, { onSettled: () => setLive(l => { const n = { ...l }; delete n[g.id]; return n }) })
  }
  return (
    <svg ref={svgRef} className="absolute inset-0 pointer-events-none" width={t.w} height={t.h} viewBox={`0 0 ${t.w} ${t.h}`} onPointerMove={onMove} onPointerUp={up}>
      {els.map(el => {
        const v = { ...el, ...(live[el.id] ?? {}) }
        const scale = v.size_mm / el.size_mm
        const [x, y] = mmToPx(t, v.x_mm, v.y_mm)
        const w = el.w_mm * scale * t.k, h = el.h_mm * scale * t.k
        return (
          <g key={el.id} className="pointer-events-auto" data-testid="qr-element">
            <rect x={x} y={y} width={w} height={h} fill="rgba(242,196,90,0.06)" stroke={el.tested ? '#f2c45a' : '#f87171'} strokeDasharray="4 2" className="cursor-move" onPointerDown={e => down(e, el, 'move')} />
            <text x={x + 2} y={y - 3} fontSize={10} fill={el.tested ? '#f2c45a' : '#f87171'} fontFamily="ui-monospace,monospace">QR /v/{el.code} · {Math.round(v.size_mm)} mm{el.tested ? '' : ' · UNTESTED'}</text>
            <rect x={x + w - 7} y={y + h - 7} width={10} height={10} fill="#f2c45a" className="cursor-nwse-resize" onPointerDown={e => down(e, el, 'size')} />
            <g className="cursor-pointer" onClick={e => { e.stopPropagation(); if (confirm(`Remove the QR /v/${el.code} from this page?`)) remove.mutate(el.id) }}>
              <circle cx={x + w} cy={y} r={7} fill="#0d0d0f" stroke="#f2c45a" /><text x={x + w} y={y + 3.5} fontSize={10} textAnchor="middle" fill="#f2c45a">×</text>
            </g>
          </g>
        )
      })}
    </svg>
  )
}

/** Toolbar buttons for the Pages screen: "Make this page a QR moment" and "Place a QR". */
export function QRToolbarButtons({ page }: { page: Page }) {
  const nav = useNavigate()
  const { data: moment } = usePageMoment(page.id)
  const create = useCreateMoment()
  const mqr = useMomentQR()
  const [picker, setPicker] = useState(false)
  return (
    <>
      {moment
        ? <button className="btn btn-sm" title={`Open the moment /v/${moment.code}`} onClick={() => nav(`/motion/moments?m=${moment.id}`)}><Film size={11} /> Moment</button>
        : <button className="btn btn-sm" disabled={create.isPending} title="Make this page a QR moment: a 30 s film from its approved panels, a short link /v/{volume}-{page} and a tested QR"
            onClick={() => create.mutate({ page_id: page.id }, { onSuccess: m => { toast('ok', 'Moment created', `/v/${m.code} — render it in Motion`); mqr.mutate({ id: m.id, test: true }); nav(`/motion/moments?m=${m.id}`) } })}><Film size={11} /> Make this page a QR moment</button>}
      <button className="btn btn-sm" title="Place a tested QR in free parchment (lower outer corner)" onClick={() => moment?.qr_id && moment.qr_tested ? mqr.mutate({ id: moment.id, place: true, test: false }, { onSuccess: () => toast('ok', 'QR placed', 'Drag it in Marginalia mode (M) to move or resize') }) : setPicker(true)}><QrCode size={11} /> Place a QR</button>
      {picker && <QRPicker page={page} onClose={() => setPicker(false)} />}
    </>
  )
}

function QRPicker({ page, onClose }: { page: Page; onClose: () => void }) {
  const { data: qrs = [] } = useQRs()
  const place = usePlaceQR()
  return (
    <Modal title={`Place a QR on page ${page.number}`} onClose={onClose}>
      <div className="flex flex-col gap-1.5 max-h-80 overflow-auto text-xs">
        {qrs.length === 0 && <div className="text-ink-400">No saved QRs — make one in Motion → QR.</div>}
        {qrs.map(q => (
          <button key={q.id} disabled={!q.tested} className={cx('btn justify-start', !q.tested && 'opacity-60')} title={q.tested ? '' : 'Pass the decode test first'}
            onClick={() => place.mutate({ id: q.id, page_id: page.id }, { onSuccess: () => { toast('ok', 'QR placed', `/v/${q.code}`); onClose() } })}>
            <img src={`${q.preview_url}?dpi=72`} className="w-6 h-7 object-contain bg-parchment-400" alt="" />/v/{q.code} · {q.style.size_mm} mm {q.tested ? '✓' : <X size={11} />}
          </button>
        ))}
      </div>
    </Modal>
  )
}
