import type { CSSProperties } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useApiMutation, type JobResp } from '@/api/hooks'

/** Stitch: graphic-novel art stitched into the blank space of the typeset book PDF. Routes: backend/stitch_api.py. */

export type Style = 'strip' | 'collage' | 'icon' | 'torn'
export type SlotId = 'top' | 'bottom' | 'corner' | 'custom'
export type Rect4 = [number, number, number, number]
export interface Crop { x: number; y: number; w: number; h: number }
export interface Subject extends Crop { id: string; label: string; drama?: number; what?: string; ai?: boolean }
export interface Photo {
  id: string; name: string; file: string; w: number; h: number; source: 'book' | 'folder' | 'upload'; origin: string
  book?: string | null; book_id?: string | null; page?: number | null; era?: string | null; chapter?: string | null
  tags: string[]; subjects: Subject[]; added: string; url: string; thumb: string
}
export interface Piece { photo: string; subject?: string; crop?: Crop }
export interface Placement { id: string; page: number; slot: SlotId; rect: Rect4; style: Style; pieces: Piece[]; tilt: number; size: number; sepia: number; seed: number }
export interface PlateItem extends Piece { caption: string; tilt?: number; sepia?: number }
export interface PlatePair { id: string; after: number; items: PlateItem[]; seed: number }
export interface Slot { id: SlotId; kind: 'strip' | 'collage' | 'icon'; rect: Rect4; label: string }
export interface PageSummary { n: number; kind: 'opener' | 'text' | 'end' | 'blank'; side: 'recto' | 'verso'; outer: 'left' | 'right'; chapter: string | null
  slots: { id: SlotId; kind: string; filled: boolean }[]; placed: number; thumb: string; rev: string; suggestions: number; flags: number }
export interface Suggestion { slot: SlotId; style: Style; pieces: Piece[]; why: string; accepted?: string }
export interface ReviewItem { placement: string; ok: boolean; issue: string; replace?: Piece & { piece: number }; accepted?: boolean }
export interface PageDetail {
  n: number; w: number; h: number; side: string; outer: string; kind: string; chapter: string | null; text: string
  blocks: Rect4[]; folio: Rect4[]; images: Rect4[]; slots: Slot[]; free_top: number; free_bottom: number
  rev: string; preview: string; plain: string; placements: Placement[]; plates_after: PlatePair[]
  suggestions: { at: string; items: Suggestion[] } | null; review: { at: string; items: ReviewItem[] } | null
}
export interface ProjectSummary { id: string; title: string; source_name: string; pages: number; size: [number, number]; placements: number; plates: number; updated: string }
export interface Project extends ProjectSummary { pages_list: PageSummary[]; placements_list: Placement[]; plates_list: PlatePair[]; undo: number; body: { top: number; bottom: number } }
export interface RepoResp { photos: Photo[]; total: number; tags: [string, number][] }
export interface ExportFile { name: string; url: string; bytes: number; modified: string }

const A = '/api/stitch'
export const sk = {
  projects: ['stitch-projects'] as const,
  project: (id: string) => ['stitch-project', id] as const,
  page: (id: string, n: number) => ['stitch-page', id, n] as const,
  repo: ['stitch-repo'] as const,
  exports: (id: string) => ['stitch-exports', id] as const,
}

export const useProjects = () => useQuery({ queryKey: sk.projects, queryFn: () => api.get<ProjectSummary[]>(`${A}/projects`) })
export const useProject = (id: string | null) => useQuery({ queryKey: sk.project(id ?? ''), queryFn: () => api.get<Project>(`${A}/projects/${id}`), enabled: !!id })
export const usePage = (id: string | null, n: number | null) => useQuery({ queryKey: sk.page(id ?? '', n ?? 0), queryFn: () => api.get<PageDetail>(`${A}/projects/${id}/pages/${n}`), enabled: !!id && !!n })
export const useRepo = (q: string, source: string | null, tag: string | null) => useQuery({
  queryKey: [...sk.repo, q, source, tag], placeholderData: (prev) => prev,
  queryFn: () => api.get<RepoResp>(`${A}/repo?${new URLSearchParams({ q, ...(source ? { source } : {}), ...(tag ? { tag } : {}) })}`),
})
export const useRepoBooks = (enabled: boolean) => useQuery({ queryKey: ['stitch-repo-books'], queryFn: () => api.get<{ id: string; title: string; volume: string; pages: number; in_repo: number }[]>(`${A}/repo/books`), enabled })
export const useExports = (id: string | null) => useQuery({ queryKey: sk.exports(id ?? ''), queryFn: () => api.get<ExportFile[]>(`${A}/projects/${id}/exports`), enabled: !!id })

/** A mutation that changes the project: the project, its pages and the thumbs refresh. */
export function useProjectMutation<A, R>(pid: string | null, fn: (a: A) => Promise<R>, onOk?: (r: R, a: A) => void) {
  const qc = useQueryClient()
  return useApiMutation(fn, [], (r: R, a: A) => {
    if (pid) { qc.invalidateQueries({ queryKey: sk.project(pid) }); qc.invalidateQueries({ queryKey: ['stitch-page', pid] }) }
    onOk?.(r, a)
  })
}
export function useRepoMutation<A, R>(fn: (a: A) => Promise<R>, onOk?: (r: R, a: A) => void) {
  return useApiMutation(fn, [sk.repo], onOk)
}

export const stitchApi = {
  addPlacement: (p: string, body: Partial<Placement>) => api.post<{ placement: Placement; page: PageDetail }>(`${A}/projects/${p}/placements`, body),
  patchPlacement: (p: string, id: string, body: Partial<Placement>) => api.patch<{ placement: Placement; page: PageDetail }>(`${A}/projects/${p}/placements/${id}`, body),
  deletePlacement: (p: string, id: string) => api.del<{ deleted: string }>(`${A}/projects/${p}/placements/${id}`),
  addPlates: (p: string, body: { after: number; items: PlateItem[] }) => api.post<{ plate: PlatePair }>(`${A}/projects/${p}/plates`, body),
  patchPlates: (p: string, id: string, body: { after?: number; items?: PlateItem[] }) => api.patch<{ plate: PlatePair }>(`${A}/projects/${p}/plates/${id}`, body),
  deletePlates: (p: string, id: string) => api.del(`${A}/projects/${p}/plates/${id}`),
  undo: (p: string) => api.post<{ undone: string; remaining: number }>(`${A}/projects/${p}/undo`),
  export: (p: string) => api.post<JobResp>(`${A}/projects/${p}/export`),
  suggest: (p: string, page: number) => api.post<{ items: Suggestion[] }>(`${A}/projects/${p}/suggest`, { page }),
  acceptSuggestion: (p: string, page: number, k: number) => api.post(`${A}/projects/${p}/suggestions/${page}/${k}/accept`),
  clearSuggestions: (p: string, page: number) => api.del(`${A}/projects/${p}/suggestions/${page}`),
  review: (p: string, page?: number) => api.post<{ items?: ReviewItem[] } & Partial<JobResp>>(`${A}/projects/${p}/review`, page ? { page } : {}),
  acceptReview: (p: string, page: number, k: number) => api.post(`${A}/projects/${p}/reviews/${page}/${k}/accept`),
  clearReview: (p: string, page: number) => api.del(`${A}/projects/${p}/reviews/${page}`),
  importPath: (path: string, title?: string) => api.post<Project>(`${A}/projects/import`, { path, title }),
  upload: (file: File, title?: string) => { const fd = new FormData(); fd.append('file', file); if (title) fd.append('title', title); return api.post<Project>(`${A}/projects/upload`, fd) },
  deleteProject: (p: string) => api.del(`${A}/projects/${p}`),
  repoUpload: (files: File[], tags: string) => { const fd = new FormData(); files.forEach(f => fd.append('files', f)); if (tags) fd.append('tags', tags); return api.post<{ added: number; already: number; skipped: string[] }>(`${A}/repo/upload`, fd) },
  repoFolder: (path: string, tags: string, recursive: boolean) => api.post<{ added: number; already: number; skipped: string[] }>(`${A}/repo/import-folder`, { path, tags, recursive }),
  repoBook: (book_id: string) => api.post<{ added: number; already: number }>(`${A}/repo/import-book`, { book_id }),
  patchPhoto: (id: string, body: Partial<Pick<Photo, 'name' | 'tags' | 'era' | 'chapter' | 'page'>>) => api.patch<Photo>(`${A}/repo/${id}`, body),
  deletePhoto: (id: string) => api.del(`${A}/repo/${id}`),
  addSubject: (id: string, s: Omit<Subject, 'id'>) => api.post<Photo>(`${A}/repo/${id}/subjects`, s),
  addSubjects: (id: string, subjects: Omit<Subject, 'id'>[]) => api.post<Photo>(`${A}/repo/${id}/subjects/bulk`, { subjects }),
  patchSubject: (id: string, sid: string, s: Partial<Subject>) => api.patch<Photo>(`${A}/repo/${id}/subjects/${sid}`, s),
  deleteSubject: (id: string, sid: string) => api.del<Photo>(`${A}/repo/${id}/subjects/${sid}`),
  findSubjects: (id: string) => api.post<{ proposals: Subject[] }>(`${A}/repo/${id}/find-subjects`),
}

export const STYLE_LABEL: Record<Style, string> = { strip: 'Torn strip', collage: 'Sewn collage', icon: 'Round icon', torn: 'Torn single' }
export const SLOT_LABEL: Record<string, string> = { top: 'Top strip', bottom: 'Bottom collage', corner: 'Corner icon', custom: 'Custom' }
export const KIND_LABEL: Record<string, string> = { opener: 'Chapter opener', text: 'Text page', end: 'Chapter end', blank: 'Blank' }
export const DRAG_MIME = 'application/x-stitch-piece'
export const fmtBytes = (n: number) => n > 1 << 20 ? `${(n / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`

/** CSS for showing the crop box of a photo filling a w x h box (cover around the crop's centre, like the engine). */
export function cropStyle(photo: Pick<Photo, 'w' | 'h'>, crop: Crop | undefined, boxW: number, boxH: number): CSSProperties {
  const c = crop ?? { x: 0, y: 0, w: 1, h: 1 }
  let bw = c.w * photo.w, bh = c.h * photo.h
  const a = boxW / boxH
  if (bw / bh > a) bh = bw / a; else bw = bh * a
  bw = Math.min(bw, photo.w); bh = Math.min(bh, photo.h)
  const cx = (c.x + c.w / 2) * photo.w, cy = (c.y + c.h / 2) * photo.h
  const x0 = Math.max(0, Math.min(photo.w - bw, cx - bw / 2)), y0 = Math.max(0, Math.min(photo.h - bh, cy - bh / 2))
  const s = boxW / bw
  return { backgroundSize: `${photo.w * s}px ${photo.h * s}px`, backgroundPosition: `${-x0 * s}px ${-y0 * s}px`, backgroundRepeat: 'no-repeat' }
}
