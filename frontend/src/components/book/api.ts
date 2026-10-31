import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useApiMutation, type JobResp } from '@/api/hooks'

/** The Book section: a layered book package (paper / art / text per page) imported at runtime. Routes: backend/book_api.py. */

export type TextStyle = 'parchment' | 'glass' | 'glass-narration' | 'header'
export type TextKind = 'narration' | 'dialogue' | 'header'
export type Align = 'left' | 'center' | 'right'
export type LayerKey = 'paper' | 'art' | 'text'
export type Layers = Record<LayerKey, boolean>

export interface TextBox {
  id: string; kind: TextKind; text: string; x: number; y: number; w: number; h: number; style: TextStyle; font?: string | null
  size?: number | null; align?: Align; tail?: [number, number] | null; kicker?: string; title?: string
}
export interface Figure { name: string; x: number; y: number; h: number; opacity: number; mirror: boolean }
export interface Shloka { id: string; lines: string[]; source: string }
export interface Paper { texture: string; shloka: Shloka | null; figures: Figure[] }
export interface ArtPatch { id: string; x: number; y: number; w: number; h: number; linked: string | null; hidden?: boolean }
export interface Art { file: string; x: number; y: number; w: number; h: number; torn?: boolean; fit?: 'cover' | 'contain' | 'fill'; focus?: [number, number]; patches?: ArtPatch[] }
export type PageStatus = 'draft' | 'review' | 'approved'
export type CommentStatus = 'open' | 'applied' | 'dismissed'
export type AnchorLayer = 'text' | 'paper' | 'art' | 'page'
export interface Rect { x: number; y: number; w: number; h: number }
export interface Anchor { layer: AnchorLayer; element: string | null; x: number; y: number; rect?: Rect }
export interface CommentResult { summary?: string; history_seq?: number; cost?: number; model?: string | null; notes?: string[]; applied?: string; error?: string; at?: string }
export interface BookComment { id: string; n: number; anchor: Anchor; text: string; status: CommentStatus; created: string; result: CommentResult | null }
export interface Progress { pages: number; approved: number; review: number; draft: number; open_comments: number }
export interface BookPage {
  id: string; number: number | null; era?: string | null; template?: string | null; paper: Paper; art: Art | null; text: TextBox[]
  page_number: boolean; layers: Layers; rev: string; thumb: string; art_url: string | null
  status: PageStatus; comments: BookComment[]
}
export interface PageSummary { id: string; number: number; rev: string; thumb: string; texts: number; has_art: boolean; layers: Layers; template?: string; era?: string; header?: string | null
  status: PageStatus; open_comments: number; comments: number; patches: number }
export interface BookSummary { id: string; title: string; volume: string; author: string; pages: number; imported_at: string; source: string; updated_at?: string }
export interface Book extends BookSummary {
  page_px: [number, number]; trim_mm: [number, number]; bleed_mm: number; frame: { l: number; r: number; t: number; b: number }
  cover_url: string | null; pages_list: PageSummary[]; undo: number; format: string; progress: Progress
}
export interface ShlokaInfo { id: string; source: string; lines: string[]; iast: string; meaning: string; tags: string[] }
export interface FontFam { family: string; house: boolean; faces: { file: string; weight: string; style: string; url: string }[] }
export interface Candidate { path: string; name: string; dir: string; bytes: number; preferred: boolean; modified: string }
export interface HistoryEntry { seq: number; at: string; action: string; kind: string; pid?: string | null }
export interface ExportFile { name: string; url: string; bytes: number; kind: string; modified: string }

const B = '/api/book'
export const bk = {
  books: ['book-books'] as const,
  book: (id: string) => ['book', id] as const,
  page: (b: string, p: string) => ['book-page', b, p] as const,
  render: (b: string, p: string, rev: string) => ['book-render', b, p, rev] as const,
  history: (b: string, p: string) => ['book-history', b, p] as const,
  exports: (b: string) => ['book-exports', b] as const,
}

export const useBooks = () => useQuery({ queryKey: bk.books, queryFn: () => api.get<BookSummary[]>(`${B}/books`) })
export const useBook = (id: string | null) => useQuery({ queryKey: bk.book(id ?? ''), queryFn: () => api.get<Book>(`${B}/books/${id}`), enabled: !!id })
export const useBookPage = (b: string | null, p: string | null) => useQuery({ queryKey: bk.page(b ?? '', p ?? ''), queryFn: () => api.get<BookPage>(`${B}/books/${b}/pages/${p}`), enabled: !!b && !!p })
export const useBookRender = (b: string | null, p: string | null, rev: string | undefined) => useQuery({
  queryKey: bk.render(b ?? '', p ?? '', rev ?? ''), queryFn: () => api.get<string>(`${B}/books/${b}/pages/${p}/render`), enabled: !!b && !!p && !!rev, staleTime: Infinity,
  placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[2] === p ? prev : undefined),  // keep showing this page while its new render loads
})
/** The page as it was before history entry `seq` (the "before" of an applied comment). */
export const useBookRenderBefore = (b: string | null, p: string | null, seq: number | null) => useQuery({
  queryKey: ['book-render-before', b, p, seq], queryFn: () => api.get<string>(`${B}/books/${b}/pages/${p}/render?seq=${seq}`), enabled: !!b && !!p && !!seq, staleTime: Infinity,
})
export const usePageHistory = (b: string | null, p: string | null) => useQuery({ queryKey: bk.history(b ?? '', p ?? ''), queryFn: () => api.get<HistoryEntry[]>(`${B}/books/${b}/pages/${p}/history`), enabled: !!b && !!p })
export const useBookExports = (b: string | null) => useQuery({ queryKey: bk.exports(b ?? ''), queryFn: () => api.get<ExportFile[]>(`${B}/books/${b}/exports`), enabled: !!b })
export const useShlokas = () => useQuery({ queryKey: ['book-shlokas'], queryFn: () => api.get<ShlokaInfo[]>(`${B}/shlokas`), staleTime: Infinity })
export const useFigures = () => useQuery({ queryKey: ['book-figures'], queryFn: () => api.get<{ name: string; url: string | null; aspect: number }[]>(`${B}/figures`), staleTime: Infinity })
export const useTextures = () => useQuery({ queryKey: ['book-textures'], queryFn: () => api.get<{ name: string; url: string }[]>(`${B}/textures`), staleTime: Infinity })
export const useBookFonts = () => useQuery({ queryKey: ['book-fonts'], queryFn: () => api.get<FontFam[]>(`${B}/fonts`), staleTime: Infinity })
export const useCandidates = (enabled: boolean) => useQuery({ queryKey: ['book-candidates'], queryFn: () => api.get<{ candidates: Candidate[]; searched: string[]; name: string }>(`${B}/import/candidates`), enabled })

/** A page-edit mutation: the response is the page; it lands in the cache, and the book (thumbs, undo count) refreshes. */
export function usePageEdit<A>(bid: string | null, fn: (a: A) => Promise<BookPage>) {
  const qc = useQueryClient()
  return useApiMutation(fn, [], (page: BookPage) => {
    if (!bid) return
    qc.setQueryData(bk.page(bid, page.id), page)
    qc.invalidateQueries({ queryKey: bk.book(bid) })
    qc.invalidateQueries({ queryKey: ['book-history', bid, page.id] })
  })
}

export const bookApi = {
  patchText: (b: string, p: string, tid: string, body: Partial<TextBox> & { z?: 'front' | 'back' }) => api.patch<BookPage>(`${B}/books/${b}/pages/${p}/text/${tid}`, body),
  addText: (b: string, p: string, body: Partial<TextBox>) => api.post<BookPage & { created: string }>(`${B}/books/${b}/pages/${p}/text`, body),
  deleteText: (b: string, p: string, tid: string) => api.del<BookPage>(`${B}/books/${b}/pages/${p}/text/${tid}`),
  layers: (b: string, p: string, body: Partial<Layers>) => api.put<BookPage>(`${B}/books/${b}/pages/${p}/layers`, body),
  paper: (b: string, p: string, body: { texture?: string; shloka_id?: string | null; figures?: Figure[] }) => api.patch<BookPage>(`${B}/books/${b}/pages/${p}/paper`, body),
  art: (b: string, p: string, body: Partial<Art>) => api.patch<BookPage>(`${B}/books/${b}/pages/${p}/art`, body),
  page: (b: string, p: string, body: { page_number?: boolean }) => api.patch<BookPage>(`${B}/books/${b}/pages/${p}`, body),
  replaceArt: (b: string, p: string, file: File) => { const fd = new FormData(); fd.append('file', file); return api.post<BookPage>(`${B}/books/${b}/pages/${p}/art`, fd) },
  restore: (b: string, p: string, seq: number) => api.post<BookPage>(`${B}/books/${b}/pages/${p}/restore`, { seq }),
  addComment: (b: string, p: string, body: { anchor: Anchor; text: string }) => api.post<BookPage & { created: string }>(`${B}/books/${b}/pages/${p}/comments`, body),
  patchComment: (b: string, p: string, c: string, body: { text?: string; status?: 'open' | 'dismissed' }) => api.patch<BookPage>(`${B}/books/${b}/pages/${p}/comments/${c}`, body),
  deleteComment: (b: string, p: string, c: string) => api.del<BookPage>(`${B}/books/${b}/pages/${p}/comments/${c}`),
  applyComment: (b: string, p: string, c: string) => api.post<JobResp>(`${B}/books/${b}/pages/${p}/comments/${c}/apply`),
  applyAll: (b: string, p: string) => api.post<JobResp>(`${B}/books/${b}/pages/${p}/comments/apply-all`),
  revertComment: (b: string, p: string, c: string) => api.post<BookPage>(`${B}/books/${b}/pages/${p}/comments/${c}/revert`),
  status: (b: string, p: string, status: PageStatus, force = false) => api.put<BookPage>(`${B}/books/${b}/pages/${p}/status`, { status, force }),
  patchPatch: (b: string, p: string, id: string, body: Partial<ArtPatch>) => api.patch<BookPage>(`${B}/books/${b}/pages/${p}/art/patches/${id}`, body),
  deletePatch: (b: string, p: string, id: string) => api.del<BookPage>(`${B}/books/${b}/pages/${p}/art/patches/${id}`),
  finish: (b: string, force = false) => api.post<JobResp & { package: { url: string; name: string }; unapproved: { id: string; number: number }[] }>(`${B}/books/${b}/finish`, { force }),
  pageUndo: (b: string, p: string) => api.post<{ page: BookPage; undone: string }>(`${B}/books/${b}/pages/${p}/undo`),
}

export const useImportPath = (onOk: (b: Book) => void) => useApiMutation((path: string) => api.post<Book>(`${B}/import`, { path }), [bk.books], onOk)
export const useImportUpload = (onOk: (b: Book) => void) => useApiMutation((file: File) => { const fd = new FormData(); fd.append('file', file); return api.post<Book>(`${B}/import/upload`, fd) }, [bk.books], onOk)

function useBookMutation<A, R>(bid: string | null, fn: (a: A) => Promise<R>, onOk?: (r: R, a: A) => void) {
  const qc = useQueryClient()
  return useApiMutation(fn, [], (r: R, a: A) => {
    const fresh = (r as { book?: Book } | null)?.book
    const next = fresh?.pages_list ? fresh : (r as Book | null)?.pages_list ? (r as Book) : null
    if (bid && next) {
      qc.setQueryData(bk.book(bid), next)  // the new order at once (no flash of the old one)
      const alive = new Set(next.pages_list.map(p => p.id))  // forget pages that left the book (no refetch of a 404)
      for (const key of ['book-page', 'book-history']) qc.removeQueries({ predicate: (q) => q.queryKey[0] === key && q.queryKey[1] === bid && !alive.has(String(q.queryKey[2])) })
    }
    if (bid) { qc.invalidateQueries({ queryKey: bk.book(bid) }); qc.invalidateQueries({ queryKey: ['book-page', bid] }); qc.invalidateQueries({ queryKey: ['book-history', bid] }) }
    onOk?.(r, a)
  })
}

export const useAddPage = (bid: string | null, onOk: (p: BookPage) => void) => useBookMutation(bid, (a: { mode: 'blank' | 'duplicate'; source?: string; after?: string }) =>
  api.post<{ page: BookPage; book: Book }>(`${B}/books/${bid}/pages`, a), (r) => onOk(r.page))
export const useAddPageFromImage = (bid: string | null, onOk: (p: BookPage) => void) => useBookMutation(bid, (a: { file: File; after?: string }) => {
  const fd = new FormData(); fd.append('file', a.file); if (a.after) fd.append('after', a.after); return api.post<{ page: BookPage; book: Book }>(`${B}/books/${bid}/pages/from-image`, fd)
}, (r) => onOk(r.page))
export const useDeletePage = (bid: string | null, onOk?: () => void) => useBookMutation(bid, (pid: string) => api.del<{ deleted: string; book: Book }>(`${B}/books/${bid}/pages/${pid}`), () => onOk?.())
export const useReorder = (bid: string | null) => useBookMutation(bid, (order: string[]) => api.put<Book>(`${B}/books/${bid}/order`, { order }))
export const useBookUndo = (bid: string | null, onOk?: (r: { undone: string; pid: string | null; book: Book }) => void) => useBookMutation(bid, () => api.post<{ undone: string; pid: string | null; book: Book }>(`${B}/books/${bid}/undo`), (r) => onOk?.(r))
export const useExportPdf = (bid: string | null, onOk: (r: JobResp) => void) => useApiMutation((paper: 'print' | 'screen') => api.post<JobResp>(`${B}/books/${bid}/export/pdf`, { paper }), [['jobs']], onOk)
export const useExportPackage = (bid: string | null, onOk: (r: { url: string; name: string; path: string }) => void) =>
  useApiMutation(() => api.post<{ url: string; name: string; path: string; bytes: number }>(`${B}/books/${bid}/export/package`), [bk.exports(bid ?? '')], onOk)
export const useDeleteBook = (onOk: () => void) => useApiMutation((bid: string) => api.del(`${B}/books/${bid}`), [bk.books], onOk)

export const STYLE_LABEL: Record<TextStyle, string> = { parchment: 'Parchment card', glass: 'Glass balloon', 'glass-narration': 'Glass narration', header: 'Header' }
export const fmtBytes = (n: number) => n > 1 << 30 ? `${(n / (1 << 30)).toFixed(1)} GB` : n > 1 << 20 ? `${(n / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`

/** A 409 from the server carries {message, …} as JSON in the error detail. */
export function conflictOf<T = Record<string, unknown>>(e: unknown): (T & { message?: string }) | null {
  const err = e as { status?: number; detail?: string }
  if (err?.status !== 409) return null
  try { return JSON.parse(err.detail ?? '') } catch { return { message: err.detail } as T & { message?: string } }
}
export const STATUS_LABEL: Record<PageStatus, string> = { draft: 'Draft', review: 'In review', approved: 'Approved' }
