import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useApiMutation, type JobResp } from '@/api/hooks'
import type { ID } from '@/api/types'

export type Age = 'treta' | 'dwapara' | 'kali'

export interface DChapter {
  id: ID; volume: number; studio_number: number; manuscript_number: number | null; kind: string; title: string; label: string
  age: Age; age_source: string; era: string; age_name: string; palette: string[]; has_text: boolean; from_book: boolean
  pages: number; review: number; approved: number
}
export type PageMode = 'painted' | 'shards'
export interface DBook { volume_id: ID; volume: number; book: string; title: string; range: [number, number] | null; chapters: DChapter[]; page_mode: PageMode }
export interface DChapters { books: DBook[]; has_book: boolean; guardrails_sha: string }
export interface CastKey { name: string; mentions: number; keys: { key: string; locked: boolean; character_id: ID }[] }
export interface DChapterDetail extends DChapter {
  manuscript: { label: string; setting: string; cast: unknown[]; eras: string[]; from_book: boolean; words: number; book_title: string }
  setting: string; paragraphs: string[]; cast: CastKey[]; no_manuscript: boolean
  pages_list: { id: ID; number: number; status: string; panels: number; mode: PageMode; mode_override: PageMode | null; painted_url: string | null }[]; next_page_number: number; passages: number
  volume_id: ID; volume_mode: PageMode
}

export interface BriefLine { text: string; kind: 'dialogue' | 'narration'; speaker: string | null; adapted_approved: boolean }
export interface Brief {
  chapter_id: ID; action: string; characters: string[]; setting: string; lines: BriefLine[]
  page_id: ID | null; page_number: number | null; age: Age | null; full_page: boolean; mode?: PageMode | null
}
export interface BriefCheck {
  ok: boolean; can_paint: boolean; errors: string[]; warnings: string[]
  lines: (BriefLine & { verbatim: boolean; status: string; closest: string; too_long?: boolean })[]
  characters: { key: string; exists: boolean; locked: boolean; name: string; character_id?: ID; has_reference?: boolean; suggestions: string[] }[]
  needs_reference: { key: string; name: string; character_id: ID; has_reference: boolean }[]
  no_manuscript: boolean; age: Age; age_source: string; age_name: string; palette: string[]; palette_text: string; manuscript: string; mode?: PageMode
}
export interface RunSettings { candidates: number; retries: number; budget_usd: number; run_critic: boolean; provider: string | null; text_model?: string | null; mode?: PageMode; repaint_only?: boolean }
export interface Estimate { panels: number; images: number; images_worst: number; usd: number; usd_worst: number; per_image: number; provider: string; dry_run: boolean; budget_usd: number; critic_live: boolean; planner_live: boolean; critic_model: string; planner_model: string; mode?: PageMode }

export interface PlanPanel { n: number; role: string; scale: string; beat: string; state: string; scene: string; characters: string[]; narration: string; dialogue: string; speaker: string | null }
export interface Check { check: string; ok: boolean; detail: string; skipped?: boolean }
export interface CriticResult { judged: boolean; scores: Record<string, number>; violations: { rule: string; detail: string }[]; fix_prompt: string; note?: string }
export interface Verdict { pass: boolean; judged: boolean; mean: number | null; min: number | null; failed_points: number[]; reasons: string[] }
export interface RunCandidate { panel: number; panel_id: ID; candidate_id: ID; path: string; url: string; attempt: number; checks: { checks: Check[]; ok: boolean }; critic: CriticResult; verdict: Verdict; dry_run: boolean; cost_usd: number; selected?: boolean
  mode?: PageMode; page_id?: ID; verification?: TextCheck; correction?: string }

/** Painted-page mode: one lettered box (in reading order) and the proofreader's verdict on it. */
export interface PaintedBox { index: number; panel: number; box: number; kind: 'narration' | 'speech'; speaker: string | null; text: string }
export interface TextCheck {
  judged: boolean; pass: boolean; model: string | null; transcription: string[]; extra: string[]; note?: string
  boxes: (PaintedBox & { found: string; match: boolean | null; model_match?: boolean | null })[]
  header?: { text: string; found: string; match: boolean } | null
}
export interface PaintedSpec { header: string | null; looks: string[]; references: string[]; panels: { n: number; shot: string; scene: string; characters: string[]; boxes: { kind: string; text: string; speaker: string | null }[] }[] }
export interface PaintedCandidate { id: number; path: string; url: string; provider: string; model: string; attempt: number; run_id: ID; dry_run: boolean; cost_usd: number; correction?: string; verification?: TextCheck; verdict?: { pass: boolean; judged: boolean; reasons: string[] }; created_at: string }
export interface PaintedState { page_id: ID; page_number: number; mode: PageMode; mode_override: PageMode | null; status: string; spec: PaintedSpec | null; boxes: PaintedBox[]; selected_id: number | null; candidates: PaintedCandidate[] }
export interface PaintedStyle { house_style: string; typography: string; pacing: string; safe_area: string; max_box_words: number; size: [number, number]; text_model_default: string; text_model_fallback: string }
export interface RunPrompt { panel: number; panel_id: ID; attempt: number; prompt: string; chars: number; lint: string[]; sections: string[]; references: string[] }
export interface Run {
  id: ID; kind: string; parent_id: ID | null; status: string; chapter_id: ID; page_id: ID | null; page_number: number | null; job_id: ID | null
  manuscript: { label?: string; number?: number; title?: string; book?: string }; cost_usd: number; estimate: Partial<Estimate>; settings: Partial<RunSettings>
  flags: { panel?: number; panel_id?: ID; candidate_id?: ID | null; reasons?: string[]; page?: number; run_id?: ID; flags?: number }[]
  brief: Partial<Brief>; created_at: string
  check?: BriefCheck; plan?: { page_beat: string; panels: PlanPanel[]; source: string; attempts?: number }; prompts?: RunPrompt[]; candidates?: RunCandidate[]
  steps?: { t: string; step: string; msg: string }[]; children?: Run[]; panels?: number; candidates_n?: number
}

export interface Guardrails {
  sha256: string; raw: string; preamble: Record<string, string>
  sections: { number: number; title: string; text: string; bullets: string[] }[]
  ages: Record<Age, { key: Age; name: string; subtitle: string; palette: string[]; palette_text: string; visual_language: string; directives: Record<string, string[]>; general: string[] }>
  characters: Record<string, { age: string; text: string }[]>; ravana_heads: Record<string, string>
  page_architecture: { min_panels: number; max_panels: number; hierarchy: string[]; full_page_for: string[] }
  typography: { series_title: string; author_credit: string; rules: string[] }; negatives: string[]; quality_test: string[]; final_command: string
}

export interface CoverState {
  volume_id: ID; volume: number; title: string; range: [number, number] | null
  text: { title: string; volume_line: string; author: string; publisher: string }
  prompt: string; prompt_source: string; facts: { principal?: string[]; key_images?: { chapter: string; image: string }[]; chapters?: string }
  art_path: string | null; art_url: string | null; art_candidates: { path: string; url: string; provider: string; dry_run: boolean }[]
  reference_path: string | null; reference_url: string | null; publisher: string
  exports: { png?: string; pdf?: string; svg?: string; thumb?: string; size_px?: [number, number]; ppi?: number; mm?: [number, number]; art?: string; at?: string }
  svg: string
}

const B = '/api/art-director'
export const dk = { chapters: ['ad-chapters'] as const, chapter: (id: ID) => ['ad-chapter', id] as const, guard: ['ad-guardrails'] as const, runs: (c: ID | null, p: ID | null) => ['ad-runs', c, p] as const, run: (id: ID) => ['ad-run', id] as const, covers: ['ad-covers'] as const }

export const useDChapters = () => useQuery({ queryKey: dk.chapters, queryFn: () => api.get<DChapters>(`${B}/chapters`) })
export const useDChapter = (id: ID | null) => useQuery({ queryKey: dk.chapter(id ?? 0), queryFn: () => api.get<DChapterDetail>(`${B}/chapters/${id}`), enabled: !!id })
export const useGuardrails = () => useQuery({ queryKey: dk.guard, queryFn: () => api.get<Guardrails>(`${B}/guardrails`), staleTime: Infinity })
export const useRuns = (chapterId: ID | null, pageId: ID | null = null) => useQuery({
  queryKey: dk.runs(chapterId, pageId), enabled: !!chapterId || !!pageId, refetchInterval: 3000,
  queryFn: () => api.get<Run[]>(`${B}/runs?${new URLSearchParams({ ...(chapterId ? { chapter_id: String(chapterId) } : {}), ...(pageId ? { page_id: String(pageId) } : {}) })}`),
})
export const useRun = (id: ID | null) => useQuery({
  queryKey: dk.run(id ?? 0), enabled: !!id, queryFn: () => api.get<Run>(`${B}/runs/${id}`),
  refetchInterval: (q) => { const s = q.state.data?.status; return s === 'queued' || s === 'running' ? 1200 : false },
})
export const usePaintedStyle = () => useQuery({ queryKey: ['ad-painted-style'], queryFn: () => api.get<PaintedStyle>(`${B}/painted/style`), staleTime: Infinity })
export const usePainted = (pageId: ID | null, live = false) => useQuery({ queryKey: ['ad-painted', pageId ?? 0], enabled: !!pageId, queryFn: () => api.get<PaintedState>(`${B}/pages/${pageId}/painted`), refetchInterval: live ? 1500 : false })
const MODE_KEYS = [['ad-chapter'], ['ad-chapters'], ['ad-painted'], ['pages'], ['page'], ['render']]
export const useSetVolumeMode = () => useApiMutation((a: { vid: ID; mode: PageMode | null }) => api.put<{ page_mode: PageMode }>(`${B}/volumes/${a.vid}/mode`, { mode: a.mode }), MODE_KEYS)
export const useSetPageMode = () => useApiMutation((a: { pid: ID; mode: PageMode | null }) => api.put<PaintedState>(`${B}/pages/${a.pid}/mode`, { mode: a.mode }), MODE_KEYS)
export const useSelectPainting = () => useApiMutation((a: { pid: ID; candidate_id: number }) => api.post<PaintedState>(`${B}/pages/${a.pid}/painted/select`, { candidate_id: a.candidate_id }), [['ad-painted'], ['pages'], ['page'], ['render']])
export const useReverify = () => useApiMutation((a: { pid: ID; candidate_id: number; text_model?: string | null }) => api.post<PaintedState>(`${B}/pages/${a.pid}/painted/verify`, a), [['ad-painted']])
export const useEditBoxes = (onOk: (r: JobResp & { run: Run }) => void) => useApiMutation((a: { pid: ID; boxes: { panel: number; box: number; text: string }[]; settings?: Partial<RunSettings> }) =>
  api.post<JobResp & { run: Run }>(`${B}/pages/${a.pid}/painted/boxes`, { boxes: a.boxes, settings: a.settings ?? {} }), [['ad-runs'], ['jobs'], ['ad-painted']], onOk)

export const useCovers = () => useQuery({ queryKey: dk.covers, queryFn: () => api.get<CoverState[]>(`${B}/covers`) })

export const checkBrief = (b: Brief) => api.post<BriefCheck>(`${B}/brief/check`, b)
export const estimateRun = (b: Brief, s: RunSettings) => api.post<Estimate>(`${B}/estimate`, { brief: b, settings: s })
export const useDirect = (onOk: (r: JobResp & { run: Run }) => void) => useApiMutation((a: { brief: Brief; settings: RunSettings }) => api.post<JobResp & { run: Run }>(`${B}/direct`, a), [['ad-runs'], ['jobs'], ['ad-chapters']], onOk)
export const useDirectChapter = (onOk: (r: JobResp & { run: Run }) => void) => useApiMutation((a: { chapter_id: ID; next: number; settings: RunSettings }) => api.post<JobResp & { run: Run }>(`${B}/direct-chapter`, a), [['ad-runs'], ['jobs']], onOk)
export const useStopRun = () => useApiMutation((id: ID) => api.post<Run>(`${B}/runs/${id}/stop`), [['ad-runs'], ['ad-run'], ['jobs']])

export const useComposeCover = () => useApiMutation((vid: ID) => api.post<CoverState>(`${B}/covers/${vid}/compose`), [dk.covers])
export const usePaintCover = (onOk: (r: JobResp) => void) => useApiMutation((a: { vid: ID; n: number; provider?: string | null }) => api.post<JobResp>(`${B}/covers/${a.vid}/paint`, { n: a.n, provider: a.provider }), [['jobs']], onOk)
export const useSaveCover = () => useApiMutation((a: { vid: ID; publisher?: string; art_path?: string }) => api.put<CoverState>(`${B}/covers/${a.vid}`, { publisher: a.publisher, art_path: a.art_path }), [dk.covers])
export const useTypesetCover = () => useApiMutation((a: { vid: ID; art: string }) => api.post<CoverState>(`${B}/covers/${a.vid}/typeset`, { art: a.art }), [dk.covers])
export const useUploadCoverRef = () => useApiMutation((a: { vid: ID; file: File }) => { const fd = new FormData(); fd.append('file', a.file); return api.post<CoverState>(`${B}/covers/${a.vid}/reference`, fd) }, [dk.covers])

/** Approximate swatches for the master prompt's palette words (display only). */
export const SWATCH: Record<string, string> = {
  'ember orange': '#d8622a', 'molten gold': '#e5a823', 'charcoal black': '#1d1b1a', 'weathered bronze': '#8a6a3c', 'smoky crimson': '#8e2c2a',
  'dusty bronze': '#9c7a4f', 'muted gold': '#b89a52', 'storm grey': '#5c6168', 'indigo': '#34407a', 'dried blood-red': '#6e1f1c', 'warm dawn light': '#f0c98f',
  'deep midnight blue': '#0f1a36', 'cold steel': '#7d8a96', 'restrained cyan': '#4a9aa6', 'muted amber': '#c08a3e', 'crimson': '#b3261e',
}
export const AGE_TONE: Record<Age, string> = { treta: 'border-orange-500/50 text-orange-200 bg-orange-500/10', dwapara: 'border-indigo-400/50 text-indigo-200 bg-indigo-500/10', kali: 'border-cyan-400/50 text-cyan-200 bg-cyan-500/10' }
