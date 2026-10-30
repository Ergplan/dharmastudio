// Types mirroring SPEC §3 (data model), §4 (API) and §8 (models + journey).

export type ID = number

export type Provider = 'sunburst' | 'gemini-nb21' | 'gemini-pro'
export const PROVIDERS: { key: Provider; label: string; cost: string }[] = [
  { key: 'sunburst', label: 'Sunburst (OpenAI)', cost: '~$0.04 / image' },
  { key: 'gemini-nb21', label: 'Gemini NB 2.1', cost: '~$0.03 / image' },
  { key: 'gemini-pro', label: 'Gemini Pro', cost: '~$0.08 / image' },
]

export type Beat = 'calm' | 'tension' | 'action' | 'revelation' | 'hex'
export const BEATS: Beat[] = ['calm', 'tension', 'action', 'revelation', 'hex']

export type TextState = 'quiet' | 'rising' | 'peak' | 'ego' | 'knowledge' | 'voice'
export const STATES: TextState[] = ['quiet', 'rising', 'peak', 'ego', 'knowledge', 'voice']

export type Scale = 'EWS' | 'WS' | 'MWS' | 'MS' | 'MCU' | 'CU' | 'ECU'
export const SCALES: Scale[] = ['EWS', 'WS', 'MWS', 'MS', 'MCU', 'CU', 'ECU']

export type PageStatus = 'empty' | 'draft' | 'generating' | 'review' | 'approved'

export type ShapeKind = 'torn' | 'crisp' | 'fracture' | 'hex' | 'rect' | 'inset' | 'bleed' | 'custom'
export const SHAPE_KINDS: ShapeKind[] = ['torn', 'crisp', 'fracture', 'hex', 'rect', 'inset', 'bleed']

export type EdgeTreatment = 'torn' | 'crisp' | 'chipped' | 'feathered' | 'rim'
export const EDGES: EdgeTreatment[] = ['torn', 'crisp', 'chipped', 'feathered', 'rim']

export type JourneyStep = 'manuscript' | 'models' | 'characters' | 'canvas' | 'prefill' | 'pages'
export const JOURNEY_STEPS: JourneyStep[] = ['manuscript', 'models', 'characters', 'canvas', 'prefill', 'pages']

export interface Point { x: number; y: number }
export type PolygonMm = [number, number][]

export interface Focal { x: number; y: number; scale: number }

export interface Shape {
  kind: ShapeKind
  polygon_mm: PolygonMm
  edge: EdgeTreatment
  z: number
  focal: Focal
}

export interface Keys { openai: boolean; gemini: boolean; anthropic: boolean; topaz: boolean }

export interface Journey { step: JourneyStep; done: JourneyStep[] }

export interface Project {
  id: ID
  title: string
  author: string
  manuscript_pdf: string | null
  settings: Record<string, unknown> & { models?: ModelSelection }
  keys: Keys
  journey: Journey
}

export interface ModelChoice { id: string; label: string; provider: keyof Keys; note?: string }
export type Role = 'script_writer' | 'prompt_writer' | 'critic' | 'image'
export const ROLES: { key: Role; label: string; what: string }[] = [
  { key: 'script_writer', label: 'Script writer', what: 'prefill pages/panels from the chapter text; Hindi drafts' },
  { key: 'prompt_writer', label: 'Prompt writer', what: 'write and rewrite each panel’s SCENE line from text + feedback' },
  { key: 'critic', label: 'Critic', what: 'QA a candidate against the scene, the lock and the book (optional)' },
  { key: 'image', label: 'Image', what: 'paint the panel' },
]
export type ModelSelection = Record<Role, string>
export interface Models {
  providers: Keys
  roles: Record<Role, ModelChoice[]>
  selected: ModelSelection
}

export interface Volume {
  id: ID
  project_id: ID
  number: number
  title: string
  canvas_id: ID | null
  era_default: string
  suggested_canvas_keys?: string[]
}

export interface Canvas {
  id: ID
  key: string
  name: string
  paper_texture: string
  ink: string
  gutter: string
  caption_style: Record<string, unknown>
  marginalia_style: Record<string, unknown>
  /** path of the preview image (relative to data/, or a URL); resolve with mediaUrl() */
  preview: string
  /** flat colour of the paper, for swatches (paper_texture is the texture image path) */
  swatch?: string
  description?: string
}

export interface Chapter {
  id: ID
  volume_id: ID
  number: number
  title: string
  text?: string
  pages_from: number | null
  pages_to: number | null
  page_count?: number
}

export interface CharacterRef {
  id: ID
  character_id: ID
  path: string
  provider: string
  prompt: string
  is_primary: boolean
  approved: boolean
}

export interface Character {
  id: ID
  project_id: ID
  name: string
  form_key: string
  look: string
  locked: boolean
  primary_ref_id: ID | null
  refs: CharacterRef[]
}

export interface Marginalia {
  silhouette_id: ID
  x_mm: number
  y_mm: number
  w_mm: number
  rotation: number
  tint: string
}

export interface Balance { image: number; parchment: number; ink: number }

export interface Page {
  id: ID
  chapter_id: ID
  number: number
  beat: Beat
  status: PageStatus
  canvas_override: string | null
  marginalia: Marginalia[]
  seed: number
  balance?: Balance
  thumb?: string
  artifact?: string | null
  panels?: Panel[]
}

export interface Panel {
  id: ID
  page_id: ID
  n: number
  kind: 'shard' | 'plate'
  shape: Shape
  image_group: string | null
  scene: string
  scale: Scale
  state: TextState
  characters: string[]
  caption_en: string
  caption_hi: string
  balloon_en: string
  balloon_hi: string
  speaker: string
  hi_is_draft: boolean
  selected_candidate_id: ID | null
  locked_shape: boolean
  candidates: Candidate[]
}

export interface Candidate {
  id: ID
  panel_id: ID
  path: string
  provider: string
  model: string
  prompt_full: string
  feedback_used: string
  cost_usd: number
  created_at: string
  qa: Record<string, unknown> | null
  rejected: boolean
}

export interface Silhouette {
  id: ID
  project_id: ID
  path: string
  tags: string[]
  source: 'generated' | 'uploaded'
  prompt: string
}

export type JobKind =
  | 'refs' | 'panel' | 'page' | 'prefill' | 'hindi' | 'silhouettes' | 'export' | 'propose' | 'manuscript' | 'batch'
export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'stopped'
export interface BatchProgress { page: number; panel: number; done: number; total: number; cost_so_far: number }
export interface Job {
  id: ID
  kind: JobKind
  ref_id: ID | null
  status: JobStatus
  /** 0..1 for simple jobs; page-by-page progress for a Director batch (SPEC §9). */
  progress: number | BatchProgress
  log: string
  cost_usd: number
  label?: string
  stop?: boolean
  result?: Record<string, unknown>
}

export interface DirectorRequest {
  chapter_id: ID
  pages: number[] | { next: number }
  candidates_per_panel: number
  provider: Provider
  prefill_text: boolean
  run_critic: boolean
  dry_run?: boolean
}
export interface DirectorEstimate { panels: number; images: number; usd: number; pages?: number[] }

export interface LedgerRow { id: ID; provider: string; usd: number; ref: string }
export interface Ledger { total: number; by_provider: Record<string, number>; rows: LedgerRow[] }

export interface Gate { ok: boolean; unlocked: string[] }

export interface ExportRequest {
  chapter_id?: ID
  volume_id?: ID
  lang: ('en' | 'hi')[]
  paper: 'screen' | 'print'
  upscale: boolean
  /** export the approved pages even when the scope has unapproved ones (the backend answers 409 otherwise) */
  allow_partial?: boolean
}
export interface ExportEstimate { usd: number; images: number; approved: number; total: number; unapproved: number }
export interface ExportRecord {
  id: ID
  job_id: ID
  created_at: string
  scope: string
  lang: string[]
  paper: string
  upscale: boolean
  files: { name: string; url: string; bytes: number }[]
  cost_usd: number
  status: JobStatus
}

export interface ApiError extends Error { status: number; detail: string }
