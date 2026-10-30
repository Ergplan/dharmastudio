import type { PolygonMm, ShapeKind, EdgeTreatment } from '@/api/types'
import { PAGE_W, PAGE_H, BLEED, MARGIN, bbox, round05, closestOnSegment } from './mm'

/** Deterministic pseudo-random for stable tear noise per shape. */
function rng(seed: number) {
  let s = seed >>> 0 || 1
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296 }
}

export const DEFAULT_EDGE: Record<ShapeKind, EdgeTreatment> = {
  torn: 'torn', crisp: 'crisp', fracture: 'chipped', hex: 'rim', rect: 'crisp', inset: 'feathered', bleed: 'crisp', custom: 'torn',
}

/** Build a preset polygon of `kind` filling bbox {x0,y0,x1,y1} (mm). */
export function presetPolygon(kind: ShapeKind, box: { x0: number; y0: number; x1: number; y1: number }, seed = 7): PolygonMm {
  const { x0, y0, x1, y1 } = box
  const w = x1 - x0, h = y1 - y0
  const r = rng(seed * 7919 + Math.round(w * h))
  const rect: PolygonMm = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
  const jitter = (poly: PolygonMm, amp: number, perEdge: number): PolygonMm => {
    const out: PolygonMm = []
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length]
      for (let k = 0; k < perEdge; k++) {
        const t = k / perEdge
        const nx = -(b[1] - a[1]), ny = b[0] - a[0]
        const L = Math.hypot(nx, ny) || 1
        const off = k === 0 ? 0 : (r() - 0.5) * amp
        out.push([a[0] + (b[0] - a[0]) * t + (nx / L) * off, a[1] + (b[1] - a[1]) * t + (ny / L) * off])
      }
    }
    return out.map(([x, y]) => [round05(x), round05(y)])
  }
  switch (kind) {
    case 'torn': return jitter(rect, Math.min(4, w * 0.08), 4)
    case 'crisp': {
      const d = Math.min(w, h) * 0.08
      return [[x0 + d * r(), y0], [x1, y0 + d * r()], [x1 - d * r(), y1], [x0, y1 - d * r()]].map(([x, y]) => [round05(x), round05(y)])
    }
    case 'fracture': {
      const d = Math.min(w, h) * 0.18
      return [[x0 + d, y0], [x1, y0 + d * 0.4], [x1 - d * 0.5, y1], [x0, y1 - d * 0.7], [x0 + d * 0.3, y0 + h * 0.5]].map(([x, y]) => [round05(x), round05(y)])
    }
    case 'hex': {
      const cx = x0 + w / 2, cy = y0 + h / 2, R = Math.min(w, h) / 2
      return Array.from({ length: 6 }, (_, i) => {
        const a = (Math.PI / 3) * i - Math.PI / 6
        return [round05(cx + R * Math.cos(a)), round05(cy + R * Math.sin(a))] as [number, number]
      })
    }
    case 'inset': {
      const cx = x0 + w / 2, cy = y0 + h / 2, rx = w / 2, ry = h / 2
      return Array.from({ length: 16 }, (_, i) => {
        const a = (Math.PI * 2 * i) / 16
        return [round05(cx + rx * Math.cos(a)), round05(cy + ry * Math.sin(a))] as [number, number]
      })
    }
    case 'bleed': return [[-BLEED, -BLEED], [PAGE_W + BLEED, -BLEED], [PAGE_W + BLEED, PAGE_H + BLEED], [-BLEED, PAGE_H + BLEED]]
    case 'rect':
    case 'custom':
    default: return rect
  }
}

export interface SnapTarget { x?: number; y?: number }

/** Snap candidates: page margins and the edges/vertices of neighbouring polygons (offset by the gutter). */
export function snapPoint(
  p: [number, number],
  neighbours: PolygonMm[],
  gutterMm: number,
  tolMm = 1.5,
): { p: [number, number]; snappedX: boolean; snappedY: boolean } {
  let [x, y] = p
  let snappedX = false, snappedY = false
  // Margins
  const mx = [MARGIN, PAGE_W - MARGIN, -BLEED, PAGE_W + BLEED]
  const my = [MARGIN, PAGE_H - MARGIN, -BLEED, PAGE_H + BLEED]
  for (const gx of mx) if (Math.abs(x - gx) <= tolMm) { x = gx; snappedX = true; break }
  for (const gy of my) if (Math.abs(y - gy) <= tolMm) { y = gy; snappedY = true; break }
  // Neighbour vertices with gutter offsets on both axes
  for (const poly of neighbours) {
    for (const [vx, vy] of poly) {
      for (const d of [-gutterMm, 0, gutterMm]) {
        if (!snappedX && Math.abs(x - (vx + d)) <= tolMm) { x = vx + d; snappedX = true }
        if (!snappedY && Math.abs(y - (vy + d)) <= tolMm) { y = vy + d; snappedY = true }
      }
    }
    // Neighbour edges: snap onto the edge offset by the gutter
    if (!snappedX || !snappedY) {
      for (let i = 0; i < poly.length; i++) {
        const a = poly[i], b = poly[(i + 1) % poly.length]
        const { q, d } = closestOnSegment(a, b, [x, y])
        if (d <= gutterMm + tolMm && d >= gutterMm - tolMm && d > 0.01) {
          const nx = (x - q[0]) / d, ny = (y - q[1]) / d
          x = q[0] + nx * gutterMm; y = q[1] + ny * gutterMm
          snappedX = snappedY = true
          break
        }
      }
    }
  }
  return { p: [round05(x), round05(y)], snappedX, snappedY }
}

export const polyBBox = bbox

export function translatePolygon(poly: PolygonMm, dx: number, dy: number): PolygonMm {
  return poly.map(([x, y]) => [round05(x + dx), round05(y + dy)])
}
