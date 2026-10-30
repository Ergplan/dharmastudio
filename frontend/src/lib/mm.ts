// The single place for page millimetre maths.
// Trim page is 170 x 260 mm; the render HTML's page includes 3 mm bleed on every side → 176 x 266 mm.
// Panel polygons are stored in TRIM millimetres (origin = top-left of the trim box).

export const PAGE_W = 170
export const PAGE_H = 260
export const BLEED = 3
export const MARGIN = 6 // mm inside trim before any shard edge (SPEC/layout.py)
export const RENDER_W = PAGE_W + 2 * BLEED // 176
export const RENDER_H = PAGE_H + 2 * BLEED // 266

/** CSS reference pixels per millimetre (the render HTML is laid out in CSS mm). */
export const CSS_PX_PER_MM = 96 / 25.4

export interface Transform {
  /** px per mm */
  k: number
  /** px offset of the trim origin within the stage */
  ox: number
  oy: number
  /** stage size in px (full bleed page) */
  w: number
  h: number
}

/** Fit the full-bleed page into a box; returns the mm→px transform. */
export function fitPage(boxW: number, boxH: number, pad = 12): Transform {
  const k = Math.max(0.1, Math.min((boxW - 2 * pad) / RENDER_W, (boxH - 2 * pad) / RENDER_H))
  const w = RENDER_W * k
  const h = RENDER_H * k
  return { k, ox: BLEED * k, oy: BLEED * k, w, h }
}

export const mmToPx = (t: Transform, x: number, y: number): [number, number] => [t.ox + x * t.k, t.oy + y * t.k]
export const pxToMm = (t: Transform, px: number, py: number): [number, number] => [(px - t.ox) / t.k, (py - t.oy) / t.k]

/** Scale factor to apply to an iframe laid out in CSS mm so it matches the transform. */
export const iframeScale = (t: Transform) => t.k / CSS_PX_PER_MM

export const round05 = (v: number) => Math.round(v * 2) / 2
export const clampMm = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function bbox(poly: [number, number][]) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const [x, y] of poly) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y) }
  return { x0, y0, x1, y1, w: x1 - x0, h: y1 - y0, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 }
}

export function centroid(poly: [number, number][]): [number, number] {
  const b = bbox(poly)
  return [b.cx, b.cy]
}

export function polygonArea(poly: [number, number][]) {
  let a = 0
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i]; const [x2, y2] = poly[(i + 1) % poly.length]
    a += x1 * y2 - x2 * y1
  }
  return Math.abs(a) / 2
}

export function pointInPolygon(poly: [number, number][], x: number, y: number) {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i]; const [xj, yj] = poly[j]
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

/** Closest point on segment ab to p, with distance. */
export function closestOnSegment(a: [number, number], b: [number, number], p: [number, number]) {
  const dx = b[0] - a[0], dy = b[1] - a[1]
  const len2 = dx * dx + dy * dy
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2))
  const q: [number, number] = [a[0] + t * dx, a[1] + t * dy]
  return { q, t, d: Math.hypot(p[0] - q[0], p[1] - q[1]) }
}

export const fmtMm = (v: number) => `${v.toFixed(1)} mm`
