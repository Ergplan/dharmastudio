import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { RENDER_W, RENDER_H, fitPage, iframeScale, type Transform } from '@/lib/mm'
import { cx } from '@/components/ui'

/** Observe an element's size. */
export function useBoxSize<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => { const r = e.contentRect; setSize({ w: r.width, h: r.height }) })
    ro.observe(el)
    setSize({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])
  return { ref, size }
}

/** The render HTML in an iframe scaled by the mm→px transform. Pointer events pass to the overlay above it. */
export function PageFrame({ html, t, className, style, title }: { html: string | undefined; t: Transform; className?: string; style?: CSSProperties; title?: string }) {
  const s = iframeScale(t)
  return (
    <div className={cx('relative overflow-hidden bg-ink-900', className)} style={{ width: t.w, height: t.h, ...style }}>
      {html ? (
        <iframe
          title={title ?? 'page'}
          srcDoc={html}
          sandbox="allow-same-origin"
          scrolling="no"
          className="absolute left-0 top-0 border-0 pointer-events-none select-none bg-transparent"
          style={{ width: `${RENDER_W}mm`, height: `${RENDER_H}mm`, transform: `scale(${s})`, transformOrigin: '0 0' }}
        />
      ) : (
        <div className="absolute inset-0 grid place-items-center text-ink-600 text-2xs">rendering…</div>
      )}
    </div>
  )
}

/** Fit-to-box wrapper: computes the transform from the parent's size. */
export function FittedPage({ html, pad = 12, children, className, maxScale }: { html: string | undefined; pad?: number; children?: (t: Transform) => ReactNode; className?: string; maxScale?: number }) {
  const { ref, size } = useBoxSize<HTMLDivElement>()
  let t = fitPage(Math.max(1, size.w), Math.max(1, size.h), pad)
  if (maxScale && t.k > maxScale) t = fitPage(RENDER_W * maxScale + 2 * pad, RENDER_H * maxScale + 2 * pad, pad)
  return (
    <div ref={ref} className={cx('w-full h-full grid place-items-center overflow-hidden', className)}>
      {size.w > 0 && (
        <div className="relative shadow-2xl shadow-black/70" style={{ width: t.w, height: t.h }}>
          <PageFrame html={html} t={t} />
          {children?.(t)}
        </div>
      )}
    </div>
  )
}
