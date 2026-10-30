import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import { useApiMutation, type JobResp } from './hooks'
import type { ID } from './types'

// ---------------------------------------------------------------------------------
// types (mirror backend/links.py, qr_api.py, motion.py, site_gen.py)
// ---------------------------------------------------------------------------------

export type LinkStatus = 'published' | 'draft' | 'broken'
export type TargetType = 'moment' | 'chapter' | 'page' | 'url'

export interface LinkRow {
  id: ID; code: string; short_url: string; target_type: TargetType; target_ref: string
  destination_override: string | null; enabled: boolean; notes: string; print_locked: boolean; scans_note: string
  status: LinkStatus; reasons: string[]; resolved: { kind: string; destination: string; label: string }
  where_printed: { page_id: ID; volume: number; chapter: number; page: number; qr_id: ID; x_mm: number; y_mm: number; w_mm: number }[]
  title: string; volume: number | null; page: number | null; page_id: ID | null; moment_id: ID | null; moment_status: string | null; qr_ids: ID[]
}

export interface QRStyle {
  colour: string; module: 'square' | 'rounded' | 'dots'; ec: 'L' | 'M' | 'Q' | 'H'; quiet: number
  emblem: 'none' | 'chakra' | 'lotus' | 'om' | 'upload'; emblem_scale: number; label: 'en' | 'hi' | 'none'; show_url: boolean; size_mm: number
}
export interface QRTest { ok: boolean; url: string; size_mm: number; dpis: Record<string, { ok: boolean; read: string | null; px: number[] }>; error?: string }
export interface QRRow {
  id: ID; name: string; link_id: ID; code: string | null; url: string; style: QRStyle; has_emblem_upload: boolean
  tested: boolean; test: QRTest | null; approved: boolean; width_mm: number; height_mm: number; link_locked: boolean
  placements: { id: ID; page_id: ID; x_mm: number; y_mm: number; w_mm: number }[]; preview_url: string; svg_url: string
}
export interface QROptions {
  modules: string[]; emblems: string[]; ec_levels: string[]; labels: Record<string, string>; min_mm: number; max_emblem_area: number
  colours: { id: string; hex: string; label: string }[]; defaults: QRStyle; decoder: boolean; test_dpis: number[]
}
export interface QRLive { url: string; width_mm: number; height_mm: number; png: string; style: QRStyle; test?: QRTest }
export interface PageQREl { id: ID; qr_id: ID; url: string; x_mm: number; y_mm: number; w_mm: number; h_mm: number; colour: string; tested: boolean; code: string }

export type ShotSource = 'kenburns' | 'seedance'
export interface Shot { panel_id?: ID; take_id?: ID; source: ShotSource; duration_s: number; move: string; focal?: { x: number; y: number }; thumb?: string | null }
export type MomentStatus = 'draft' | 'rendering' | 'review' | 'approved' | 'published'
export interface Moment {
  id: ID; page_id: ID; page: number; chapter: number; chapter_id: ID; volume: number; chapter_title: string
  link_id: ID | null; code: string | null; short_url: string | null; link_locked: boolean; qr_id: ID | null; qr_tested: boolean
  title_en: string; title_hi: string; shots: Shot[]; narration_en: string; narration_hi: string; voice: 'none' | 'elevenlabs'; voice_id: string
  music_path: string | null; music_url: string | null; status: MomentStatus
  outputs: Partial<Record<'en_16x9' | 'en_9x16' | 'hi_16x9' | 'hi_9x16' | 'poster' | 'poster_9x16', string>>
  render_meta: { variants?: Record<string, { duration: number; width: number; height: number; bytes: number }>; shot_seconds?: number[]; rendered_at?: string; size?: string }
  timing: { shots_s: number; available_s: number; scale: number; title_s: number; end_s: number; total_s: number }
  published_at: string | null
}
export interface MotionOptions {
  moves: { id: string; label: string }[]; camera_presets: { id: string; label: string; text: string }[]
  providers: { id: 'fal' | 'byteplus'; label: string; key: boolean }[]; resolutions: string[]; aspects: string[]; durations: number[]
  voice: { elevenlabs: boolean; default_voice_id: string }; total_s: number; title_s: number; end_s: number
}
export interface Take {
  id: ID; panel_id: ID | null; still_url: string | null; prompt: string
  params: { duration: number; resolution: string; aspect: string; seed: number | null; camera: string; estimate?: Estimate }
  provider: string; model: string; cost_usd: number; url: string | null; thumb: string | null; seed: number | null; dry_run: boolean
  status: 'queued' | 'running' | 'done' | 'failed'; job_id: ID | null; picked: boolean; notes: string; created_at: string
}
export interface Estimate { provider: string; usd: number; usd_if_live: number; per_second: number; dry_run: boolean; note: string }
export interface Health { ok: boolean; ffmpeg: { ok: boolean; version?: string; error?: string }; zxing: boolean; keys: Record<string, boolean> }
export interface SiteState {
  site_url: string; media_base: string | null; blob_token: boolean; revalidate_secret: boolean; manifest_url: string | null
  last: Record<string, unknown> | null; checklist: { id: string; label: string; detail: string }[]; preview_url: string | null
  published_moments: number; links: number; history: ({ id: ID; kind: string; ok: boolean; at: string } & Record<string, unknown>)[]
}

// ---------------------------------------------------------------------------------
// queries
// ---------------------------------------------------------------------------------

export const mk = {
  links: ['links'] as const, qr: ['qr'] as const, qrOptions: ['qr-options'] as const, moments: ['moments'] as const,
  moment: (id: ID) => ['moment', id] as const, pageMoment: (id: ID) => ['page-moment', id] as const, pageQr: (id: ID) => ['page-qr', id] as const,
  takes: (panel: ID | null) => ['takes', panel ?? 0] as const, options: ['motion-options'] as const, health: ['motion-health'] as const, site: ['site'] as const,
}
const ALL_MOTION = [['links'], ['qr'], ['moments'], ['moment'], ['page-moment'], ['page-qr'], ['takes'], ['site'], ['render'], ['ledger']] as const

export const useLinks = () => useQuery({ queryKey: mk.links, queryFn: () => api.get<LinkRow[]>('/api/links') })
export const useQRs = () => useQuery({ queryKey: mk.qr, queryFn: () => api.get<QRRow[]>('/api/qr') })
export const useQROptions = () => useQuery({ queryKey: mk.qrOptions, queryFn: () => api.get<QROptions>('/api/qr/options'), staleTime: Infinity })
export const useMoments = () => useQuery({ queryKey: mk.moments, queryFn: () => api.get<Moment[]>('/api/moments') })
export const useMoment = (id: ID | null) => useQuery({ queryKey: mk.moment(id ?? 0), queryFn: () => api.get<Moment>(`/api/moments/${id}`), enabled: !!id })
export const usePageMoment = (pageId: ID | null) => useQuery({ queryKey: mk.pageMoment(pageId ?? 0), queryFn: () => api.get<Moment | null>(`/api/pages/${pageId}/moment`), enabled: !!pageId })
export const usePageQR = (pageId: ID | null) => useQuery({ queryKey: mk.pageQr(pageId ?? 0), queryFn: () => api.get<PageQREl[]>(`/api/pages/${pageId}/qr`), enabled: !!pageId })
export const useTakes = (panelId: ID | null) => useQuery({ queryKey: mk.takes(panelId), queryFn: () => api.get<Take[]>(`/api/seedance/takes${panelId ? `?panel_id=${panelId}` : ''}`), refetchInterval: (q) => (q.state.data ?? []).some(t => t.status === 'queued' || t.status === 'running') ? 1500 : false })
export const useMotionOptions = () => useQuery({ queryKey: mk.options, queryFn: () => api.get<MotionOptions>('/api/motion/options') })
export const useMotionHealth = () => useQuery({ queryKey: mk.health, queryFn: () => api.get<Health>('/api/motion/health'), staleTime: 60_000 })
export const useSite = () => useQuery({ queryKey: mk.site, queryFn: () => api.get<SiteState>('/api/site') })

// ---------------------------------------------------------------------------------
// mutations
// ---------------------------------------------------------------------------------

export const useCreateLink = () => useApiMutation((b: Partial<LinkRow>) => api.post<LinkRow>('/api/links', b), ALL_MOTION as unknown as unknown[][])
export const useSaveLink = () => useApiMutation(({ id, ...b }: { id: ID } & Partial<LinkRow>) => api.put<LinkRow>(`/api/links/${id}`, b), ALL_MOTION as unknown as unknown[][])
export const useDeleteLink = () => useApiMutation((id: ID) => api.del(`/api/links/${id}`), ALL_MOTION as unknown as unknown[][])
export const useLockLink = () => useApiMutation((id: ID) => api.post<LinkRow>(`/api/links/${id}/lock`), ALL_MOTION as unknown as unknown[][])
export const useCheckLink = () => useApiMutation((id: ID) => api.post<LinkRow>(`/api/links/${id}/check`), [mk.links])

export const useCreateQR = () => useApiMutation((b: { link_id?: ID; target_type?: string; target_ref?: string; code?: string; name?: string; style?: Partial<QRStyle> }) => api.post<QRRow>('/api/qr', b), ALL_MOTION as unknown as unknown[][])
export const useSaveQR = () => useApiMutation(({ id, ...b }: { id: ID; style?: Partial<QRStyle>; name?: string; link_id?: ID }) => api.put<QRRow>(`/api/qr/${id}`, b), ALL_MOTION as unknown as unknown[][])
export const useDeleteQR = () => useApiMutation((id: ID) => api.del(`/api/qr/${id}`), ALL_MOTION as unknown as unknown[][])
export const useTestQR = () => useApiMutation((id: ID) => api.post<QRRow>(`/api/qr/${id}/test`), ALL_MOTION as unknown as unknown[][])
export const useApproveQR = () => useApiMutation((id: ID) => api.post<QRRow>(`/api/qr/${id}/approve`), ALL_MOTION as unknown as unknown[][])
export const usePlaceQR = () => useApiMutation(({ id, ...b }: { id: ID; page_id: ID; x_mm?: number; y_mm?: number; w_mm?: number }) => api.post(`/api/qr/${id}/place`, b), ALL_MOTION as unknown as unknown[][])
export const useMovePageQR = () => useApiMutation(({ id, ...b }: { id: ID; x_mm?: number; y_mm?: number; w_mm?: number }) => api.put(`/api/page-qr/${id}`, b), [['page-qr'], ['render'], ['qr']])
export const useRemovePageQR = () => useApiMutation((id: ID) => api.del(`/api/page-qr/${id}`), [['page-qr'], ['render'], ['qr'], ['links']])
export const useQRLive = () => useApiMutation((b: { link_id?: ID; code?: string; style: Partial<QRStyle>; test?: boolean; dpi?: number }) => api.post<QRLive>('/api/qr/render', b))
export async function uploadEmblem(id: ID, file: File) { const fd = new FormData(); fd.append('file', file); return api.post<QRRow>(`/api/qr/${id}/emblem`, fd) }

export const useCreateMoment = () => useApiMutation((b: { page_id: ID; code?: string; title_en?: string; title_hi?: string }) => api.post<Moment>('/api/moments', b), ALL_MOTION as unknown as unknown[][])
export const useSaveMoment = () => useApiMutation(({ id, ...b }: { id: ID } & Partial<Moment>) => api.put<Moment>(`/api/moments/${id}`, b), ALL_MOTION as unknown as unknown[][])
export const useRenderMoment = () => useApiMutation(({ id, ...b }: { id: ID; size?: string; variants?: string[] }) => api.post<JobResp>(`/api/moments/${id}/render`, b), ALL_MOTION as unknown as unknown[][])
export const useApproveMoment = () => useApiMutation((id: ID) => api.post<Moment>(`/api/moments/${id}/approve`), ALL_MOTION as unknown as unknown[][])
export const usePublishMoment = () => useApiMutation(({ id, deploy }: { id: ID; deploy: boolean }) => api.post<{ moment: Moment } & JobResp>(`/api/moments/${id}/publish`, { deploy }), ALL_MOTION as unknown as unknown[][])
export const useUnpublishMoment = () => useApiMutation((id: ID) => api.post<Moment>(`/api/moments/${id}/unpublish`), ALL_MOTION as unknown as unknown[][])
export const useMomentQR = () => useApiMutation(({ id, ...b }: { id: ID; style?: Partial<QRStyle>; place?: boolean; test?: boolean }) => api.post<{ moment: Moment; qr: QRRow }>(`/api/moments/${id}/qr`, b), ALL_MOTION as unknown as unknown[][])
export async function uploadMusic(id: ID, file: File) { const fd = new FormData(); fd.append('file', file); return api.post<Moment>(`/api/moments/${id}/music`, fd) }

export const useCreateTake = () => useApiMutation((b: Record<string, unknown>) => api.post<{ take: Take } & JobResp>('/api/seedance/takes', b), [['takes'], ['ledger']])
export const useSendTake = () => useApiMutation(({ id, moment_id }: { id: ID; moment_id: ID }) => api.post<{ moment: Moment; take: Take }>(`/api/seedance/takes/${id}/send`, { moment_id }), ALL_MOTION as unknown as unknown[][])
export const useMotionPrompt = () => useApiMutation((b: { panel_id?: ID | null; scene?: string; camera: string }) => api.post<{ prompt: string; source: string }>('/api/seedance/prompt', b))
export async function uploadStill(file: File) { const fd = new FormData(); fd.append('file', file); return api.post<{ still_path: string; url: string }>('/api/seedance/upload', fd) }
export const fetchEstimate = (provider: string, duration: number, resolution: string) => api.get<Estimate>(`/api/seedance/estimate?provider=${provider}&duration=${duration}&resolution=${resolution}`)

export const useSiteSettings = () => useApiMutation((b: { site_url?: string; media_base?: string }) => api.put('/api/site/settings', b), [mk.site])
export const useSitePreview = () => useApiMutation(() => api.post<{ url: string; moments: number; pages: number }>('/api/site/preview'), [mk.site])
export const useSitePublish = () => useApiMutation(() => api.post<JobResp>('/api/site/publish'), [mk.site])
export const useSiteExport = () => useApiMutation(() => api.post<{ url: string; bytes: number }>('/api/site/export'), [mk.site])
export const useSiteSecret = () => useApiMutation(() => api.post<{ secret: string; note: string }>('/api/site/secret'), [mk.site])
