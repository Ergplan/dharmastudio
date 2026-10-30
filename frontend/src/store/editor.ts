// Editor state for the Pages screen: selection, toggles, and the shard editor's working copy with undo/redo.
import { create } from 'zustand'
import type { ID, Shape, PolygonMm, ShapeKind, EdgeTreatment, Focal, Marginalia } from '@/api/types'
import { presetPolygon, DEFAULT_EDGE } from '@/lib/shapes'
import { bbox } from '@/lib/mm'

export interface ShardDraft { shape: Shape; locked_shape: boolean; image_group: string | null }
type Drafts = Record<ID, ShardDraft>

interface EditorState {
  chapterId: ID | null
  pageId: ID | null
  panelId: ID | null
  lang: 'en' | 'hi'
  canvasOverride: string | null
  shardEditor: boolean
  marginalia: boolean
  selectedMarginalia: number | null
  // shard editor working copy
  drafts: Drafts
  past: Drafts[]
  future: Drafts[]
  dirty: boolean
  selectedVertex: number | null

  setChapter: (id: ID | null) => void
  setPage: (id: ID | null) => void
  setPanel: (id: ID | null) => void
  setLang: (l: 'en' | 'hi') => void
  setCanvasOverride: (k: string | null) => void
  toggleShardEditor: (on?: boolean) => void
  toggleMarginalia: (on?: boolean) => void
  setSelectedMarginalia: (i: number | null) => void
  setSelectedVertex: (i: number | null) => void

  loadDrafts: (panels: { id: ID; shape: Shape; locked_shape: boolean; image_group: string | null }[]) => void
  commit: (fn: (d: Drafts) => Drafts) => void
  setPolygon: (id: ID, poly: PolygonMm, pushHistory?: boolean) => void
  beginGesture: () => void
  applyPreset: (id: ID, kind: ShapeKind) => void
  setEdge: (id: ID, edge: EdgeTreatment) => void
  bumpZ: (id: ID, dir: 1 | -1) => void
  setFocal: (id: ID, focal: Focal, pushHistory?: boolean) => void
  setLocked: (id: ID, locked: boolean) => void
  setImageGroup: (id: ID, g: string | null) => void
  undo: () => void
  redo: () => void
  discard: () => void
  markSaved: () => void

  // marginalia working copy
  margDraft: Marginalia[] | null
  setMargDraft: (m: Marginalia[] | null) => void
}

const clone = (d: Drafts): Drafts => JSON.parse(JSON.stringify(d))

export const useEditor = create<EditorState>((set, get) => ({
  chapterId: 1, pageId: null, panelId: null, lang: 'en', canvasOverride: null,
  shardEditor: false, marginalia: false, selectedMarginalia: null,
  drafts: {}, past: [], future: [], dirty: false, selectedVertex: null,
  margDraft: null,

  setChapter: (id) => set({ chapterId: id, pageId: null, panelId: null }),
  setPage: (id) => set(s => (s.pageId === id ? {} : { pageId: id, panelId: null, selectedVertex: null, selectedMarginalia: null, drafts: {}, past: [], future: [], dirty: false, margDraft: null })),
  setPanel: (id) => set({ panelId: id, selectedVertex: null }),
  setLang: (lang) => set({ lang }),
  setCanvasOverride: (k) => set({ canvasOverride: k }),
  toggleShardEditor: (on) => set(s => ({ shardEditor: on ?? !s.shardEditor, marginalia: (on ?? !s.shardEditor) ? false : s.marginalia, selectedVertex: null })),
  toggleMarginalia: (on) => set(s => ({ marginalia: on ?? !s.marginalia, shardEditor: (on ?? !s.marginalia) ? false : s.shardEditor, selectedMarginalia: null })),
  setSelectedMarginalia: (i) => set({ selectedMarginalia: i }),
  setSelectedVertex: (i) => set({ selectedVertex: i }),

  loadDrafts: (panels) => {
    const drafts: Drafts = {}
    for (const p of panels) drafts[p.id] = { shape: JSON.parse(JSON.stringify(p.shape)), locked_shape: p.locked_shape, image_group: p.image_group }
    set({ drafts, past: [], future: [], dirty: false, selectedVertex: null })
  },
  commit: (fn) => set(s => ({ past: [...s.past.slice(-60), clone(s.drafts)], future: [], drafts: fn(clone(s.drafts)), dirty: true })),
  beginGesture: () => set(s => ({ past: [...s.past.slice(-60), clone(s.drafts)], future: [] })),
  setPolygon: (id, poly, pushHistory = false) => {
    if (pushHistory) get().commit(d => { d[id].shape.polygon_mm = poly; d[id].shape.kind = 'custom'; return d })
    else set(s => { const d = clone(s.drafts); if (!d[id]) return {}; d[id].shape.polygon_mm = poly; d[id].shape.kind = 'custom'; return { drafts: d, dirty: true } })
  },
  applyPreset: (id, kind) => get().commit(d => {
    const sh = d[id].shape
    const b = bbox(sh.polygon_mm)
    sh.polygon_mm = presetPolygon(kind, b, Math.floor(Math.random() * 1e6))
    sh.kind = kind
    sh.edge = DEFAULT_EDGE[kind]
    if (kind === 'inset') sh.z = Math.max(sh.z, 10)
    return d
  }),
  setEdge: (id, edge) => get().commit(d => { d[id].shape.edge = edge; return d }),
  bumpZ: (id, dir) => get().commit(d => { d[id].shape.z = Math.max(0, d[id].shape.z + dir); return d }),
  setFocal: (id, focal, pushHistory = false) => {
    if (pushHistory) get().commit(d => { d[id].shape.focal = focal; return d })
    else set(s => { const d = clone(s.drafts); if (!d[id]) return {}; d[id].shape.focal = focal; return { drafts: d, dirty: true } })
  },
  setLocked: (id, locked) => get().commit(d => { d[id].locked_shape = locked; return d }),
  setImageGroup: (id, g) => get().commit(d => { d[id].image_group = g; return d }),
  undo: () => set(s => { if (!s.past.length) return {}; const prev = s.past[s.past.length - 1]; return { drafts: prev, past: s.past.slice(0, -1), future: [clone(s.drafts), ...s.future], dirty: true, selectedVertex: null } }),
  redo: () => set(s => { if (!s.future.length) return {}; const next = s.future[0]; return { drafts: next, future: s.future.slice(1), past: [...s.past, clone(s.drafts)], dirty: true, selectedVertex: null } }),
  discard: () => set({ drafts: {}, past: [], future: [], dirty: false, selectedVertex: null }),
  markSaved: () => set({ past: [], future: [], dirty: false }),

  setMargDraft: (m) => set({ margDraft: m }),
}))
