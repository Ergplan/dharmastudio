import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from '@tanstack/react-query'
import { api } from './client'
import type {
  Project, Models, ModelSelection, Volume, Canvas, Chapter, Character, CharacterRef, Page, Panel, Candidate, Silhouette, Job, Ledger, Gate,
  ExportRecord, ExportRequest, ExportEstimate, DirectorRequest, DirectorEstimate, ID,
  FontInfo, PresetsInfo, VolumeTypography, TypographySetting, PanelPalette,
} from './types'
import { useToasts } from '@/store/toasts'

export const qk = {
  project: ['project'] as const,
  models: ['models'] as const,
  volumes: ['volumes'] as const,
  canvases: ['canvases'] as const,
  chapters: ['chapters'] as const,
  chapter: (id: ID) => ['chapter', id] as const,
  characters: ['characters'] as const,
  pages: (chapterId: ID) => ['pages', chapterId] as const,
  page: (id: ID) => ['page', id] as const,
  render: (id: ID, canvas: string | null, lang: string) => ['render', id, canvas ?? '', lang] as const,
  gate: (id: ID) => ['gate', id] as const,
  silhouettes: ['silhouettes'] as const,
  exports: ['exports'] as const,
  jobs: ['jobs'] as const,
  job: (id: ID) => ['job', id] as const,
  ledger: ['ledger'] as const,
  fonts: ['fonts'] as const,
  presets: ['typography-presets'] as const,
  volumeType: (id: ID) => ['volume-typography', id] as const,
  palette: (id: ID) => ['palette', id] as const,
}

type QOpts<T> = Omit<UseQueryOptions<T>, 'queryKey' | 'queryFn'>

export const useProject = () => useQuery({ queryKey: qk.project, queryFn: () => api.get<Project>('/api/project') })
export const useModels = () => useQuery({ queryKey: qk.models, queryFn: () => api.get<Models>('/api/models') })
export const useVolumes = () => useQuery({ queryKey: qk.volumes, queryFn: () => api.get<Volume[]>('/api/volumes') })
export const useCanvases = () => useQuery({ queryKey: qk.canvases, queryFn: () => api.get<Canvas[]>('/api/canvases') })
export const useChapters = () => useQuery({ queryKey: qk.chapters, queryFn: () => api.get<Chapter[]>('/api/chapters') })
export const useChapter = (id: ID | null) => useQuery({ queryKey: qk.chapter(id ?? 0), queryFn: () => api.get<Chapter>(`/api/chapters/${id}`), enabled: !!id })
export const useCharacters = () => useQuery({ queryKey: qk.characters, queryFn: () => api.get<Character[]>('/api/characters') })
export const usePages = (chapterId: ID | null, opts?: QOpts<Page[]>) =>
  useQuery({ queryKey: qk.pages(chapterId ?? 0), queryFn: () => api.get<Page[]>(`/api/pages?chapter_id=${chapterId}`), enabled: !!chapterId, ...opts })
export const usePage = (id: ID | null) => useQuery({ queryKey: qk.page(id ?? 0), queryFn: () => api.get<Page>(`/api/pages/${id}`), enabled: !!id })
export const useRender = (id: ID | null, canvas: string | null, lang: 'en' | 'hi') =>
  useQuery({
    queryKey: qk.render(id ?? 0, canvas, lang),
    queryFn: () => api.get<string>(`/api/pages/${id}/render?lang=${lang}${canvas ? `&canvas=${canvas}` : ''}`),
    enabled: !!id,
    staleTime: 0,
  })
export const useGate = (id: ID | null) => useQuery({ queryKey: qk.gate(id ?? 0), queryFn: () => api.get<Gate>(`/api/pages/${id}/gate`), enabled: !!id })
export const useSilhouettes = () => useQuery({ queryKey: qk.silhouettes, queryFn: () => api.get<Silhouette[]>('/api/silhouettes') })
export const useExports = () => useQuery({ queryKey: qk.exports, queryFn: () => api.get<ExportRecord[]>('/api/exports') })
export const useFonts = () => useQuery({ queryKey: qk.fonts, queryFn: () => api.get<FontInfo[]>('/api/fonts'), staleTime: Infinity })
export const usePresets = () => useQuery({ queryKey: qk.presets, queryFn: () => api.get<PresetsInfo>('/api/typography/presets'), staleTime: Infinity })
export const useVolumeTypography = (id: ID | null) => useQuery({ queryKey: qk.volumeType(id ?? 0), queryFn: () => api.get<VolumeTypography>(`/api/volumes/${id}/typography`), enabled: !!id })
export const usePanelPalette = (id: ID | null, enabled = true) => useQuery({ queryKey: qk.palette(id ?? 0), queryFn: () => api.get<PanelPalette>(`/api/panels/${id}/palette`), enabled: !!id && enabled })
export const useSaveVolumeTypography = () => useApiMutation(({ id, ...body }: { id: ID } & TypographySetting) => api.put<VolumeTypography>(`/api/volumes/${id}/typography`, body), [['volume-typography'], qk.volumes, ['render'], ['pages'], ['page']])
export const useLedger = () => useQuery({ queryKey: qk.ledger, queryFn: () => api.get<Ledger>('/api/ledger') })
export const useActiveJobs = () => useQuery({ queryKey: qk.jobs, queryFn: () => api.get<Job[]>('/api/jobs?active=1'), refetchInterval: 2000 })
export const useJob = (id: ID | null) =>
  useQuery({
    queryKey: qk.job(id ?? 0),
    queryFn: () => api.get<Job>(`/api/jobs/${id}`),
    enabled: !!id,
    refetchInterval: (q) => { const s = q.state.data?.status; return s === 'done' || s === 'failed' || s === 'stopped' ? false : 1000 },
  })

/** Invalidate everything a finished job could have changed. */
export function useInvalidateAll() {
  const qc = useQueryClient()
  return () => { qc.invalidateQueries() }
}

function useErrToast() {
  const push = useToasts(s => s.push)
  return (e: unknown) => {
    const err = e as { status?: number; detail?: string; message?: string }
    push({ kind: err.status === 409 ? 'gate' : 'error', title: err.status === 409 ? 'Blocked' : `Error${err.status ? ` ${err.status}` : ''}`, message: err.detail ?? err.message ?? String(e) })
  }
}

/** Generic mutation helper: runs fn, invalidates keys, toasts errors. */
export function useApiMutation<TArgs, TRes>(fn: (a: TArgs) => Promise<TRes>, invalidate: (readonly unknown[])[] | 'all' = [], onOk?: (r: TRes, a: TArgs) => void) {
  const qc = useQueryClient()
  const toastErr = useErrToast()
  return useMutation({
    mutationFn: fn,
    onSuccess: (r, a) => {
      if (invalidate === 'all') qc.invalidateQueries()
      else for (const k of invalidate) qc.invalidateQueries({ queryKey: k })
      onOk?.(r, a)
    },
    onError: toastErr,
  })
}

export interface JobResp { job_id: ID; job: Job }

// --- concrete mutations used across screens ---
export const useSaveModels = () => useApiMutation((sel: ModelSelection) => api.put<Models>('/api/project/models', sel), [qk.models, qk.project])
export const useSaveVolume = () => useApiMutation(({ id, ...body }: { id: ID; canvas_id: ID | null }) => api.put<Volume>(`/api/volumes/${id}`, body), [qk.volumes, qk.project, ['render']])
export const useSaveCharacter = () => useApiMutation(({ id, ...body }: { id: ID; look?: string; locked?: boolean; name?: string }) => api.put<Character>(`/api/characters/${id}`, body), [qk.characters, ['gate'], qk.project])
export const useSaveRef = () => useApiMutation(({ cid, rid, ...body }: { cid: ID; rid: ID; is_primary?: boolean; approved?: boolean }) => api.put<CharacterRef>(`/api/characters/${cid}/refs/${rid}`, body), [qk.characters])
export const useSaveChapter = () => useApiMutation(({ id, ...body }: { id: ID; title?: string; pages_from?: number | null; pages_to?: number | null }) => api.put<Chapter>(`/api/chapters/${id}`, body), [qk.chapters])
export const useSavePage = () => useApiMutation(({ id, ...body }: { id: ID } & Partial<Pick<Page, 'beat' | 'status' | 'marginalia' | 'canvas_override' | 'typography_override'>>) => api.put<Page>(`/api/pages/${id}`, body), [['pages'], ['page'], ['render'], qk.exports])
export const useSavePanel = () => useApiMutation(({ id, ...body }: { id: ID } & Partial<Omit<Panel, 'id' | 'page_id' | 'candidates'>>) => api.put<Panel>(`/api/panels/${id}`, body), [['pages'], ['page'], ['render'], ['gate']])
export const useSelectCandidate = () => useApiMutation(({ id, candidate_id }: { id: ID; candidate_id: ID }) => api.post<Panel>(`/api/panels/${id}/select`, { candidate_id }), [['pages'], ['page'], ['render']])
export const useRejectCandidate = () => useApiMutation(({ id, cid, rejected }: { id: ID; cid: ID; rejected: boolean }) => api.put<Candidate>(`/api/panels/${id}/candidates/${cid}`, { rejected }), [['pages'], ['page']])
export const useRecut = () => useApiMutation((id: ID) => api.post<Page>(`/api/pages/${id}/recut`), [['pages'], ['page'], ['render']])
export const useExportEstimate = () => useApiMutation((req: ExportRequest) => api.post<ExportEstimate>('/api/export/estimate', req))
export const useDirectorEstimate = () => useApiMutation((req: DirectorRequest) => api.get<DirectorEstimate>(`/api/director/estimate?${new URLSearchParams({ chapter_id: String(req.chapter_id), pages: JSON.stringify(req.pages), candidates_per_panel: String(req.candidates_per_panel), provider: req.provider, prefill_text: String(req.prefill_text), run_critic: String(req.run_critic) })}`))
export const useStopJob = () => useApiMutation((id: ID) => api.post<Job>(`/api/jobs/${id}/stop`), [qk.jobs, ['job']])
