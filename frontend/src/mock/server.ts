// Mock API router for VITE_MOCK=1. Mirrors SPEC §4, §8, §9 against the in-memory fixtures.
import * as F from './fixtures'
import { renderPageHtml } from './render'
import { plate, portrait, silhouette } from './images'
import { presetPolygon, DEFAULT_EDGE } from '@/lib/shapes'
import type { Job, Panel, Page, Candidate, BatchProgress, DirectorRequest, ExportRequest, Character, CharacterRef, ShapeKind, Beat } from '@/api/types'

export class MockHttpError extends Error {
  constructor(public status: number, public detail: string) { super(detail) }
}

type Body = Record<string, unknown>

const delay = (ms: number) => new Promise(r => setTimeout(r, ms))
const nowIso = () => new Date().toISOString()

// ---------- helpers ----------
const pageById = (id: number) => F.pages.find(p => p.id === id)
const panelById = (id: number) => F.panels.find(p => p.id === id)
const panelsOfPage = (pageId: number) => F.panels.filter(p => p.page_id === pageId).sort((a, b) => a.n - b.n)
const charByForm = (form: string) => F.characters.find(c => c.form_key === form || c.form_key.split('/')[0] === form.split('/')[0])
const unlockedOnPage = (pageId: number) => {
  const names = new Set<string>()
  for (const p of panelsOfPage(pageId)) for (const f of p.characters) { const c = charByForm(f); if (c && !c.locked) names.add(c.name) }
  return [...names]
}
const gateMessage = (names: string[]) => `Cannot generate: unlocked character${names.length > 1 ? 's' : ''} on this page — ${names.join(', ')}. Lock them on the Characters screen first.`
const canvasForPage = (page: Page) => {
  if (page.canvas_override) return F.canvasByKey(page.canvas_override) ?? F.canvases[0]
  const ch = F.chapters.find(c => c.id === page.chapter_id)
  const vol = F.volumes.find(v => v.id === ch?.volume_id)
  return F.canvases.find(c => c.id === vol?.canvas_id) ?? F.canvases[0]
}
const pageOut = (p: Page) => ({ ...p, panels: panelsOfPage(p.id) })
const jobOut = (j: Job) => ({ ...j })

// ---------- job engine ----------
type Effect = (job: Job) => void
const effects = new Map<number, Effect>()
const tickers = new Map<number, () => void>()

function createJob(kind: Job['kind'], ref_id: number | null, label: string, opts: { duration?: number; cost?: number; effect?: Effect; log?: string; batch?: BatchProgress; tick?: (j: Job) => void }): Job {
  const job: Job = { id: F.newId(), kind, ref_id, status: 'queued', progress: opts.batch ?? 0, log: opts.log ?? `queued ${kind}`, cost_usd: 0, label, stop: false }
  F.jobs.unshift(job)
  const duration = opts.duration ?? 6000
  const started = Date.now() + 400
  if (opts.effect) effects.set(job.id, opts.effect)
  const timer = setInterval(() => {
    const t = Date.now()
    if (t < started) return
    if (job.status === 'queued') { job.status = 'running'; job.log += `\nrunning` }
    if (opts.tick) { opts.tick(job) } else {
      const p = Math.min(1, (t - started) / duration)
      job.progress = p
      job.cost_usd = +((opts.cost ?? 0) * p).toFixed(3)
    }
    const prog = typeof job.progress === 'number' ? job.progress : job.progress.done / Math.max(1, job.progress.total)
    if (prog >= 1 || job.status === 'stopped') {
      clearInterval(timer); tickers.delete(job.id)
      if (job.status !== 'stopped') { job.status = 'done'; job.log += `\ndone` }
      effects.get(job.id)?.(job); effects.delete(job.id)
      if (job.cost_usd > 0) F.ledger.push({ id: F.newId(), provider: kind === 'prefill' || kind === 'hindi' || kind === 'propose' ? 'anthropic' : 'openai', usd: job.cost_usd, ref: label })
    }
  }, 300)
  tickers.set(job.id, () => clearInterval(timer))
  return job
}

function makeCandidates(panel: Panel, provider: string, n: number, feedback: string) {
  const out: Candidate[] = []
  for (let i = 0; i < n; i++) {
    const c: Candidate = {
      id: F.newId(), panel_id: panel.id, path: plate(`${panel.id}-${Date.now()}-${i}`, `p${Math.floor(panel.page_id)}.${panel.n} · new ${i + 1}`),
      provider, model: provider === 'sunburst' ? 'gpt-image-1.5' : provider === 'gemini-pro' ? 'gemini-2.5-pro-image' : 'gemini-2.1-nb',
      prompt_full: `COMIC_STYLE: An ancient Indian illuminated historical manuscript brought to life through photorealistic cinematic illustration.\nCAMERA: ${panel.scale}.\nSCENE: ${panel.scene}\nCHARACTERS: ${panel.characters.join(', ') || '—'}${feedback ? `\nFEEDBACK: ${feedback}` : ''}\nAVOID: plastic skin, neon colours, modern buildings, extra limbs, wrong number of heads, any text.`,
      feedback_used: feedback, cost_usd: provider === 'sunburst' ? 0.04 : provider === 'gemini-pro' ? 0.08 : 0.03, created_at: nowIso(), qa: null, rejected: false,
    }
    F.candidates.push(c); panel.candidates.push(c); out.push(c)
  }
  return out
}

const providerCost = (p: string) => (p === 'sunburst' ? 0.04 : p === 'gemini-pro' ? 0.08 : 0.03)

// Give the seeded "running" job a real life: it finishes in ~20 s and drops two candidates on panel 7.1, page 7 → review.
;(function seedRunningJob() {
  const j = F.jobs.find(x => x.status === 'running' && x.kind === 'panel')
  if (!j) return
  const start = Date.now(), from = typeof j.progress === 'number' ? j.progress : 0
  const timer = setInterval(() => {
    const p = Math.min(1, from + ((Date.now() - start) / 20000) * (1 - from))
    j.progress = p; j.cost_usd = +(0.08 * p).toFixed(3)
    if (p >= 1) {
      clearInterval(timer); j.status = 'done'; j.log += '\nsunburst: candidate 2/2 done\ndone'
      const pn = panelById(j.ref_id ?? 0); const pg = pn && pageById(pn.page_id)
      if (pn && pg) { const cs = makeCandidates(pn, 'sunburst', 2, ''); pn.selected_candidate_id = cs[0].id; pg.status = 'review' }
    }
  }, 500)
  tickers.set(j.id, () => clearInterval(timer))
})()

// ---------- router ----------
export async function mockRequest(method: string, url: string, body?: unknown): Promise<unknown> {
  await delay(60 + Math.random() * 90)
  const u = new URL(url, 'http://mock')
  const path = u.pathname.replace(/^\/api/, '')
  const q = u.searchParams
  const seg = path.split('/').filter(Boolean)
  const b = (body ?? {}) as Body
  const num = (s: string) => Number(s)
  const M = (m: string, pattern: string) => {
    if (method !== m) return null
    const ps = pattern.split('/').filter(Boolean)
    if (ps.length !== seg.length) return null
    const params: Record<string, string> = {}
    for (let i = 0; i < ps.length; i++) {
      if (ps[i].startsWith(':')) params[ps[i].slice(1)] = seg[i]
      else if (ps[i] !== seg[i]) return null
    }
    return params
  }
  let p: Record<string, string> | null

  // ----- project / models / journey -----
  if (M('GET', '/project')) return { ...F.project, settings: { ...F.project.settings, models: F.models.selected } }
  if (M('GET', '/models')) return F.models
  if (M('PUT', '/project/models')) { Object.assign(F.models.selected, b); markDone('models'); return F.models }
  if (M('POST', '/project/manuscript')) {
    const fd = body as FormData
    const file = fd.get('file') as File | null
    const job = createJob('manuscript', 1, `Manuscript · ${file?.name ?? 'upload'}`, { duration: 2500, log: `received ${file?.name ?? 'file'} (${file ? Math.round(file.size / 1024) : 0} KB)\nextracting text…\ndetecting chapters…`, effect: () => { F.project.manuscript_pdf = `data/manuscript/${file?.name ?? 'manuscript.pdf'}`; markDone('manuscript') } })
    return { job_id: job.id, job }
  }
  if (M('POST', '/project/journey/reset')) { F.project.journey = { step: 'manuscript', done: [] }; return F.project.journey }
  if (M('GET', '/volumes')) return F.volumes
  if ((p = M('PUT', '/volumes/:id'))) { const v = F.volumes.find(x => x.id === num(p!.id)); if (!v) throw new MockHttpError(404, 'volume not found'); Object.assign(v, b); markDone('canvas'); return v }
  if (M('GET', '/canvases')) return F.canvases

  // ----- characters -----
  if (M('GET', '/characters')) return F.characters
  if (M('POST', '/characters')) {
    const c: Character = { id: F.newId(), project_id: 1, name: String(b.name ?? 'New character'), form_key: String(b.form_key ?? String(b.name ?? 'new').toLowerCase()), look: String(b.look ?? ''), locked: false, primary_ref_id: null, refs: [] }
    F.characters.push(c); return c
  }
  if (M('POST', '/characters/propose')) {
    const job = createJob('propose', 1, 'Propose cast from manuscript', { duration: 4000, cost: 0.12, effect: () => {
      for (const [name, form, look] of [['Agastya', 'agastya', 'The sage of the forest: white beard to the chest, bare chest, deerskin, eyes that have already seen the hour he prepares for.'], ['Ashwasena', 'ashwasena', 'Naga child in smoke; dark-scaled arrowhead with red eyes; red smoke trail.']] as const) {
        if (!F.characters.some(c => c.form_key === form)) F.characters.push({ id: F.newId(), project_id: 1, name, form_key: form, look, locked: false, primary_ref_id: null, refs: [] })
      }
    } })
    return { job_id: job.id, job }
  }
  if ((p = M('PUT', '/characters/:id'))) {
    const c = F.characters.find(x => x.id === num(p!.id)); if (!c) throw new MockHttpError(404, 'character not found')
    if (b.locked === true) {
      const prim = c.refs.find(r => r.id === c.primary_ref_id)
      if (!prim || !prim.approved) throw new MockHttpError(409, `${c.name} cannot be locked: it needs an approved primary reference image.`)
    }
    if (typeof b.look === 'string') c.look = b.look
    if (typeof b.locked === 'boolean') c.locked = b.locked
    if (typeof b.name === 'string') c.name = b.name
    if (F.characters.every(x => x.locked || !F.panels.some(pn => pn.page_id <= 10 && pn.characters.some(f => charByForm(f)?.id === x.id)))) markDone('characters')
    return c
  }
  if ((p = M('POST', '/characters/:id/refs/generate'))) {
    const c = F.characters.find(x => x.id === num(p!.id)); if (!c) throw new MockHttpError(404, 'character not found')
    const n = Number(b.n ?? 2), provider = String(b.provider ?? 'sunburst')
    const job = createJob('refs', c.id, `${c.name} · ${n} reference candidates (${provider})`, { duration: 1200 * n, cost: providerCost(provider) * n, effect: () => {
      for (let i = 0; i < n; i++) {
        const r: CharacterRef = { id: F.newId(), character_id: c.id, path: portrait(`${c.form_key}-${Date.now()}-${i}`, c.name), provider, prompt: `Character reference sheet, ${c.name}. ${c.look.slice(0, 200)}`, is_primary: false, approved: false }
        c.refs.push(r)
      }
    } })
    return { job_id: job.id, job }
  }
  if ((p = M('POST', '/characters/:id/refs/upload'))) {
    const c = F.characters.find(x => x.id === num(p!.id)); if (!c) throw new MockHttpError(404, 'character not found')
    const fd = body as FormData
    const files = fd.getAll('files').concat(fd.getAll('file')) as File[]
    const added: CharacterRef[] = []
    for (const f of files) {
      const r: CharacterRef = { id: F.newId(), character_id: c.id, path: URL.createObjectURL(f), provider: 'upload', prompt: f.name, is_primary: false, approved: false }
      c.refs.push(r); added.push(r)
    }
    return added
  }
  if ((p = M('PUT', '/characters/:id/refs/:rid'))) {
    const c = F.characters.find(x => x.id === num(p!.id)); if (!c) throw new MockHttpError(404, 'character not found')
    const r = c.refs.find(x => x.id === num(p!.rid)); if (!r) throw new MockHttpError(404, 'ref not found')
    if (b.is_primary === true) { c.refs.forEach(x => (x.is_primary = false)); r.is_primary = true; c.primary_ref_id = r.id }
    if (b.is_primary === false && r.is_primary) { r.is_primary = false; c.primary_ref_id = null }
    if (typeof b.approved === 'boolean') { r.approved = b.approved; if (!r.approved && r.is_primary && c.locked) c.locked = false }
    return r
  }
  if ((p = M('DELETE', '/characters/:id/refs/:rid'))) {
    const c = F.characters.find(x => x.id === num(p!.id)); if (!c) throw new MockHttpError(404, 'character not found')
    c.refs = c.refs.filter(x => x.id !== num(p!.rid)); if (c.primary_ref_id === num(p!.rid)) { c.primary_ref_id = null; c.locked = false }
    return { ok: true }
  }

  // ----- chapters -----
  if (M('GET', '/chapters')) return F.chapters.map(c => ({ ...c, text: undefined, page_count: F.pages.filter(pg => pg.chapter_id === c.id).length }))
  if ((p = M('GET', '/chapters/:id'))) { const c = F.chapters.find(x => x.id === num(p!.id)); if (!c) throw new MockHttpError(404, 'chapter not found'); return c }
  if ((p = M('PUT', '/chapters/:id'))) { const c = F.chapters.find(x => x.id === num(p!.id)); if (!c) throw new MockHttpError(404, 'chapter not found'); Object.assign(c, b); return c }
  if ((p = M('POST', '/chapters/:id/prefill'))) {
    const c = F.chapters.find(x => x.id === num(p!.id)); if (!c) throw new MockHttpError(404, 'chapter not found')
    const job = createJob('prefill', c.id, `Prefill chapter ${c.number} (${F.models.selected.script_writer})`, { duration: 5000, cost: 0.18, log: 'reading chapter text\nbreaking into pages…', effect: () => {
      if (F.pages.some(pg => pg.chapter_id === c.id)) { markDone('prefill'); return }
      const base = F.pages.length
      for (let i = 0; i < 3; i++) {
        const pg: Page = { id: F.newId(), chapter_id: c.id, number: i + 1, beat: 'calm', status: 'draft', canvas_override: null, marginalia: [], seed: base + i, balance: { image: 0.68, parchment: 0.22, ink: 0.1 }, artifact: null }
        F.pages.push(pg)
        const boxes = [{ x0: 6, y0: 20, x1: 164, y1: 130 }, { x0: 6, y0: 134, x1: 84, y1: 246 }, { x0: 88, y0: 134, x1: 164, y1: 246 }]
        boxes.forEach((bx, k) => {
          const kind: ShapeKind = 'torn'
          F.panels.push({ id: F.newId(), page_id: pg.id, n: k + 1, kind: 'shard', shape: { kind, polygon_mm: presetPolygon(kind, bx, k + 1), edge: 'torn', z: k, focal: { x: 0.5, y: 0.5, scale: 1 } }, image_group: null, scene: `(prefilled) ${c.title}, beat ${k + 1}.`, scale: 'WS', state: 'quiet', characters: [], caption_en: `(prefilled from chapter ${c.number}, paragraph ${k + 1})`, caption_hi: '', balloon_en: '', balloon_hi: '', speaker: '', hi_is_draft: false, selected_candidate_id: null, locked_shape: false, candidates: [] })
        })
      }
      markDone('prefill')
    } })
    return { job_id: job.id, job }
  }
  if ((p = M('POST', '/chapters/:id/hindi'))) {
    const c = F.chapters.find(x => x.id === num(p!.id)); if (!c) throw new MockHttpError(404, 'chapter not found')
    const job = createJob('hindi', c.id, `Draft Hindi · chapter ${c.number}`, { duration: 3500, cost: 0.09, effect: () => {
      for (const pg of F.pages.filter(x => x.chapter_id === c.id)) for (const pn of panelsOfPage(pg.id)) {
        if (pn.caption_en && !pn.caption_hi) { pn.caption_hi = '(हिंदी प्रारूप) ' + pn.caption_en.slice(0, 48) + '…'; pn.hi_is_draft = true }
        if (pn.balloon_en && !pn.balloon_hi) { pn.balloon_hi = '(हिंदी प्रारूप) ' + pn.balloon_en.slice(0, 40) + '…'; pn.hi_is_draft = true }
      }
    } })
    return { job_id: job.id, job }
  }

  // ----- pages -----
  if (M('GET', '/pages')) {
    const cid = q.get('chapter_id')
    return F.pages.filter(pg => !cid || pg.chapter_id === Number(cid)).sort((a, b2) => a.number - b2.number).map(pageOut)
  }
  if ((p = M('GET', '/pages/:id'))) { const pg = pageById(num(p!.id)); if (!pg) throw new MockHttpError(404, 'page not found'); return pageOut(pg) }
  if ((p = M('PUT', '/pages/:id'))) {
    const pg = pageById(num(p!.id)); if (!pg) throw new MockHttpError(404, 'page not found')
    if (b.status && !['empty', 'draft', 'generating', 'review', 'approved'].includes(String(b.status))) throw new MockHttpError(422, 'bad status')
    if (b.status === 'approved') pg.artifact = `data/artifacts/ch${pg.chapter_id}/page_${String(pg.number).padStart(3, '0')}.html`
    if (b.status && b.status !== 'approved' && pg.status === 'approved') pg.artifact = null
    for (const k of ['beat', 'status', 'marginalia', 'canvas_override'] as const) if (k in b) (pg as unknown as Record<string, unknown>)[k] = b[k]
    return pageOut(pg)
  }
  if ((p = M('GET', '/pages/:id/render'))) {
    const pg = pageById(num(p!.id)); if (!pg) throw new MockHttpError(404, 'page not found')
    const canvas = q.get('canvas') ? F.canvasByKey(q.get('canvas')!) ?? canvasForPage(pg) : canvasForPage(pg)
    const lang = (q.get('lang') === 'hi' ? 'hi' : 'en') as 'en' | 'hi'
    const ch = F.chapters.find(c => c.id === pg.chapter_id)
    return renderPageHtml(pg, panelsOfPage(pg.id), canvas, F.silhouettes, lang, ch?.title.split('/').pop()?.trim().toUpperCase())
  }
  if ((p = M('GET', '/pages/:id/gate'))) { const names = unlockedOnPage(num(p!.id)); return { ok: names.length === 0, unlocked: names } }
  if ((p = M('POST', '/pages/:id/recut'))) {
    const pg = pageById(num(p!.id)); if (!pg) throw new MockHttpError(404, 'page not found')
    if (pg.status === 'approved') throw new MockHttpError(409, 'Page is approved and frozen. Un-approve it before re-cutting.')
    const kinds: Record<Beat, ShapeKind> = { calm: 'torn', tension: 'crisp', action: 'fracture', revelation: 'torn', hex: 'hex' }
    for (const pn of panelsOfPage(pg.id)) {
      if (pn.locked_shape || pn.kind === 'plate') continue
      const bb = pn.shape.polygon_mm.reduce((a, [x, y]) => ({ x0: Math.min(a.x0, x), y0: Math.min(a.y0, y), x1: Math.max(a.x1, x), y1: Math.max(a.y1, y) }), { x0: 1e9, y0: 1e9, x1: -1e9, y1: -1e9 })
      const kind = kinds[pg.beat]
      pn.shape = { ...pn.shape, kind, edge: DEFAULT_EDGE[kind], polygon_mm: presetPolygon(kind, bb, Math.floor(Math.random() * 1e6)) }
    }
    return pageOut(pg)
  }
  if ((p = M('POST', '/pages/:id/generate-all'))) {
    const pg = pageById(num(p!.id)); if (!pg) throw new MockHttpError(404, 'page not found')
    if (pg.status === 'approved') throw new MockHttpError(409, 'Page is approved and frozen. Un-approve it before regenerating.')
    const names = unlockedOnPage(pg.id); if (names.length) throw new MockHttpError(409, gateMessage(names))
    const provider = String(b.provider ?? F.models.selected.image), n = Number(b.n ?? 2)
    const pns = panelsOfPage(pg.id)
    pg.status = 'generating'
    const job = createJob('page', pg.id, `Page ${pg.number} · ${pns.length} panels × ${n}`, { duration: 1500 * pns.length * n, cost: providerCost(provider) * n * pns.length, effect: () => { for (const pn of pns) { const cs = makeCandidates(pn, provider, n, ''); if (!pn.selected_candidate_id) pn.selected_candidate_id = cs[0].id } pg.status = 'review' } })
    return { job_id: job.id, job }
  }

  // ----- panels -----
  if ((p = M('PUT', '/panels/:id'))) {
    const pn = panelById(num(p!.id)); if (!pn) throw new MockHttpError(404, 'panel not found')
    const pg = pageById(pn.page_id)!
    if (pg.status === 'approved' && ('shape' in b)) throw new MockHttpError(409, 'Page is approved and frozen. Un-approve it before editing shards.')
    for (const k of ['caption_en', 'caption_hi', 'balloon_en', 'balloon_hi', 'speaker', 'state', 'scale', 'characters', 'scene', 'shape', 'locked_shape', 'image_group', 'hi_is_draft'] as const) if (k in b) (pn as unknown as Record<string, unknown>)[k] = b[k]
    if ('caption_hi' in b) pn.hi_is_draft = false
    return pn
  }
  if ((p = M('POST', '/panels/:id/generate'))) {
    const pn = panelById(num(p!.id)); if (!pn) throw new MockHttpError(404, 'panel not found')
    const pg = pageById(pn.page_id)!
    if (pg.status === 'approved') throw new MockHttpError(409, 'Page is approved and frozen. Un-approve it before regenerating.')
    const names = unlockedOnPage(pg.id); if (names.length) throw new MockHttpError(409, gateMessage(names))
    const provider = String(b.provider ?? 'sunburst'), n = Number(b.n ?? 2), feedback = String(b.feedback ?? '')
    const prevStatus = pg.status
    pg.status = 'generating'
    const job = createJob('panel', pn.id, `Panel ${pg.number}.${pn.n} · ${n} candidates (${provider})`, { duration: 1800 * n, cost: providerCost(provider) * n, log: `${provider}: prompt assembled (${pn.characters.length} refs attached)`, effect: () => { makeCandidates(pn, provider, n, feedback); pg.status = prevStatus === 'empty' || prevStatus === 'draft' ? 'review' : prevStatus === 'generating' ? 'review' : prevStatus } })
    return { job_id: job.id, job }
  }
  if ((p = M('POST', '/panels/:id/select'))) {
    const pn = panelById(num(p!.id)); if (!pn) throw new MockHttpError(404, 'panel not found')
    const pg = pageById(pn.page_id)!
    if (pg.status === 'approved') throw new MockHttpError(409, 'Page is approved and frozen. Un-approve it before changing the selection.')
    pn.selected_candidate_id = Number(b.candidate_id)
    if (pg.status === 'empty' || pg.status === 'draft') pg.status = 'review'
    return pn
  }
  if ((p = M('PUT', '/panels/:id/candidates/:cid'))) {
    const pn = panelById(num(p!.id)); if (!pn) throw new MockHttpError(404, 'panel not found')
    const c = pn.candidates.find(x => x.id === num(p!.cid)); if (!c) throw new MockHttpError(404, 'candidate not found')
    if (typeof b.rejected === 'boolean') c.rejected = b.rejected
    return c
  }
  if ((p = M('POST', '/panels/:id/rewrite'))) {
    const pn = panelById(num(p!.id)); if (!pn) throw new MockHttpError(404, 'panel not found')
    await delay(900)
    const fb = String(b.feedback ?? '').trim()
    return { scene: `${pn.scene.replace(/\.$/, '')}; ${fb ? fb.replace(/\.$/, '') : 'held a beat longer'}. Eyes open, level gaze; figures at true human scale; no giants.` }
  }

  // ----- director (SPEC §9) -----
  if (M('GET', '/director/estimate') || M('POST', '/director/estimate')) {
    const req = (method === 'GET' ? Object.fromEntries(q.entries()) : b) as unknown as DirectorRequest & { pages: unknown }
    const chapterId = Number(req.chapter_id ?? 1)
    const pgs = resolvePages(chapterId, req.pages)
    let panelsCount = 0
    for (const pg of pgs) { const pns = panelsOfPage(pg.id).filter(x => !x.selected_candidate_id); panelsCount += pns.length || ((req.prefill_text === true || String(req.prefill_text) === 'true') && panelsOfPage(pg.id).length === 0 ? 3 : 0) }
    const n = Number(req.candidates_per_panel ?? 2)
    const images = panelsCount * n
    const critic = req.run_critic === true || String(req.run_critic) === 'true'
    return { panels: panelsCount, images, usd: +(images * providerCost(String(req.provider ?? 'sunburst')) + (critic ? images * 0.004 : 0)).toFixed(2), pages: pgs.map(x => x.number) }
  }
  if (M('POST', '/director/batch')) {
    const req = b as unknown as DirectorRequest
    const pgs = resolvePages(Number(req.chapter_id ?? 1), req.pages)
    if (!pgs.length) throw new MockHttpError(422, 'No pages selected for the batch.')
    const n = Number(req.candidates_per_panel ?? 2)
    const plan: { page: Page; panel: Panel }[] = []
    for (const pg of pgs) { if (pg.status === 'approved') continue; for (const pn of panelsOfPage(pg.id)) if (!pn.selected_candidate_id) plan.push({ page: pg, panel: pn }) }
    const total = plan.length
    let idx = 0, lastTick = 0
    const prog: BatchProgress = { page: pgs[0].number, panel: 0, done: 0, total, cost_so_far: 0 }
    const skipped = new Set<number>()
    const job = createJob('batch', Number(req.chapter_id ?? 1), `Director · pages ${pgs.map(x => x.number).join(', ')} · ${n}/panel`, {
      batch: prog, log: `batch: ${pgs.length} pages, ${total} panels, ${total * n} images planned`,
      tick: (j) => {
        const t = Date.now(); if (t - lastTick < 1100) return; lastTick = t
        if (j.stop) { j.status = 'stopped'; j.log += `\nstopped by author after ${idx}/${total}`; return }
        if (idx >= total) { j.progress = { ...prog, done: total }; return }
        const { page, panel } = plan[idx]
        const names = unlockedOnPage(page.id)
        if (names.length) { if (!skipped.has(page.id)) { skipped.add(page.id); j.log += `\npage ${page.number}: skipped — unlocked ${names.join(', ')}` } }
        else {
          if (page.status !== 'generating') page.status = 'generating'
          const cs = makeCandidates(panel, String(req.provider), n, '')
          if (req.run_critic) { cs[0].qa = { score: +(0.7 + Math.random() * 0.25).toFixed(2), notes: 'critic: scene matched; lock honoured' }; panel.selected_candidate_id = cs[0].id }
          prog.cost_so_far = +(prog.cost_so_far + n * providerCost(String(req.provider))).toFixed(2)
          j.log += `\npage ${page.number} panel ${panel.n}: ${n} candidates (${req.provider})`
        }
        idx++
        prog.page = page.number; prog.panel = panel.n; prog.done = idx
        j.progress = { ...prog }; j.cost_usd = prog.cost_so_far
        const finishedPage = idx >= total || plan[idx].page.id !== page.id
        if (finishedPage && !skipped.has(page.id)) { page.status = 'review'; j.log += `\npage ${page.number} → review` }
      },
      effect: (j) => { for (const pg of pgs) if (pg.status === 'generating') pg.status = j.status === 'stopped' ? 'draft' : 'review' },
    })
    if (total === 0) { job.progress = { ...prog, total: 0, done: 0 }; job.status = 'done'; job.log += '\nnothing to do: all panels already have a selected candidate'; tickers.get(job.id)?.(); }
    return { job_id: job.id, job }
  }

  // ----- silhouettes -----
  if (M('GET', '/silhouettes')) return F.silhouettes
  if (M('POST', '/silhouettes/generate')) {
    const n = Number(b.n ?? 2), prompt = String(b.prompt ?? ''), tags = (Array.isArray(b.tags) ? b.tags : String(b.tags ?? '').split(',').map(s => s.trim()).filter(Boolean)) as string[]
    const job = createJob('silhouettes', null, `Silhouettes · ${n} (${tags.join(', ') || prompt.slice(0, 24)})`, { duration: 1500 * n, cost: 0.04 * n, effect: () => {
      const kinds = ['figure', 'compass', 'bow', 'mace', 'lotus', 'temple', 'map', 'chariot']
      for (let i = 0; i < n; i++) F.silhouettes.push({ id: F.newId(), project_id: 1, path: silhouette(`gen-${Date.now()}-${i}`, kinds.find(k => tags.includes(k) || prompt.toLowerCase().includes(k)) ?? kinds[i % kinds.length]), tags: tags.length ? tags : ['generated'], source: 'generated', prompt })
    } })
    return { job_id: job.id, job }
  }
  if (M('POST', '/silhouettes/upload')) {
    const fd = body as FormData
    const files = fd.getAll('files').concat(fd.getAll('file')) as File[]
    const tags = String(fd.get('tags') ?? '').split(',').map(s => s.trim()).filter(Boolean)
    const out = files.map(f => { const s = { id: F.newId(), project_id: 1, path: URL.createObjectURL(f), tags: tags.length ? tags : ['uploaded'], source: 'uploaded' as const, prompt: '' }; F.silhouettes.push(s); return s })
    return out
  }
  if ((p = M('DELETE', '/silhouettes/:id'))) { const i = F.silhouettes.findIndex(s => s.id === num(p!.id)); if (i >= 0) F.silhouettes.splice(i, 1); return { ok: true } }

  // ----- export -----
  if (M('POST', '/export/estimate') || M('GET', '/export/estimate')) {
    const req = (method === 'GET' ? Object.fromEntries(q.entries()) : b) as unknown as ExportRequest
    const pgs = exportPages(req)
    const approved = pgs.filter(x => x.status === 'approved')
    const images = approved.reduce((s, pg) => s + panelsOfPage(pg.id).filter(x => x.selected_candidate_id).length, 0)
    const upscale = String(req.upscale) === 'true' || req.upscale === true
    return { usd: +(upscale ? images * 0.05 : 0).toFixed(2), images, approved: approved.length, total: pgs.length, unapproved: pgs.length - approved.length }
  }
  if (M('POST', '/export')) {
    const req = b as unknown as ExportRequest
    const pgs = exportPages(req)
    const approved = pgs.filter(x => x.status === 'approved')
    if (!approved.length) throw new MockHttpError(409, 'Nothing to export: no approved pages in the selected scope.')
    if (approved.length < pgs.length && !req.allow_partial) throw new MockHttpError(409, `Unapproved pages: ${pgs.filter(x => x.status !== 'approved').map(x => x.number).join(', ')}. Pass allow_partial to export the approved ones.`)
    if (req.upscale && !F.project.keys.topaz) throw new MockHttpError(409, 'Topaz upscale requested but TOPAZ key is missing in .env.')
    const scope = req.chapter_id ? `Chapter ${F.chapters.find(c => c.id === req.chapter_id)?.number ?? req.chapter_id}` : `Volume ${F.volumes.find(v => v.id === req.volume_id)?.number ?? req.volume_id}`
    const rec = { id: F.newId(), job_id: 0, created_at: nowIso(), scope, lang: req.lang, paper: req.paper, upscale: req.upscale, files: [] as { name: string; url: string; bytes: number }[], cost_usd: 0, status: 'running' as Job['status'] }
    const job = createJob('export', rec.id, `Export ${scope} · ${req.lang.map(l => l.toUpperCase()).join('+')} · ${req.paper}${req.upscale ? ' · Topaz' : ''}`, { duration: 2500 + 900 * req.lang.length, cost: req.upscale ? approved.length * 0.2 : 0, log: `${approved.length}/${pgs.length} pages approved — exporting approved only\n${req.upscale ? 'topaz: upscaling plates…' : 'no upscale'}`, effect: (j) => {
      rec.status = 'done'; rec.cost_usd = j.cost_usd
      for (const l of req.lang) rec.files.push({ name: `cycle_of_dharma_${scope.toLowerCase().replace(' ', '')}_${l.toUpperCase()}_${req.paper}.pdf`, url: `/media/exports/${scope.toLowerCase().replace(' ', '')}_${l}_${req.paper}_${rec.id}.pdf`, bytes: Math.round(approved.length * 1.9e6 * (req.paper === 'print' ? 2.4 : 1)) })
    } })
    rec.job_id = job.id
    F.exportsList.unshift(rec)
    return { job_id: job.id, job, export: rec }
  }
  if (M('GET', '/exports')) return F.exportsList

  // ----- jobs / ledger -----
  if (M('GET', '/jobs')) {
    const active = q.has('active')
    return F.jobs.filter(j => !active || j.status === 'queued' || j.status === 'running' || (j.status === 'done' && Date.now() - lastSeen(j) < 4000)).map(jobOut)
  }
  if ((p = M('GET', '/jobs/:id'))) { const j = F.jobs.find(x => x.id === num(p!.id)); if (!j) throw new MockHttpError(404, 'job not found'); return jobOut(j) }
  if ((p = M('POST', '/jobs/:id/stop'))) { const j = F.jobs.find(x => x.id === num(p!.id)); if (!j) throw new MockHttpError(404, 'job not found'); j.stop = true; if (j.kind !== 'batch') { j.status = 'stopped'; tickers.get(j.id)?.(); } return jobOut(j) }
  if (M('GET', '/ledger')) {
    const by: Record<string, number> = {}
    for (const r of F.ledger) by[r.provider] = +((by[r.provider] ?? 0) + r.usd).toFixed(3)
    return { total: +F.ledger.reduce((s, r) => s + r.usd, 0).toFixed(2), by_provider: by, rows: F.ledger }
  }

  throw new MockHttpError(404, `mock: no route for ${method} ${path}`)
}

const doneAt = new Map<number, number>()
function lastSeen(j: Job) { if (!doneAt.has(j.id)) doneAt.set(j.id, Date.now()); return doneAt.get(j.id)! }

function markDone(step: Project_Step) {
  const j = F.project.journey
  if (!j.done.includes(step)) j.done.push(step)
  const order = ['manuscript', 'models', 'characters', 'canvas', 'prefill', 'pages'] as const
  j.step = order.find(s => !j.done.includes(s)) ?? 'pages'
}
type Project_Step = 'manuscript' | 'models' | 'characters' | 'canvas' | 'prefill' | 'pages'

function resolvePages(chapterId: number, sel: unknown): Page[] {
  const all = F.pages.filter(pg => pg.chapter_id === chapterId).sort((a, b) => a.number - b.number)
  if (typeof sel === 'string') { const str = sel; try { sel = JSON.parse(str) } catch { sel = str.split(',').map(Number) } }
  if (Array.isArray(sel)) { const set = new Set(sel.map(Number)); return all.filter(pg => set.has(pg.number)) }
  if (sel && typeof sel === 'object' && 'next' in (sel as object)) { const n = Number((sel as { next: number }).next); return all.filter(pg => pg.status === 'empty' || pg.status === 'draft').slice(0, n) }
  return all
}
function exportPages(req: ExportRequest): Page[] {
  if (req.chapter_id) return F.pages.filter(pg => pg.chapter_id === Number(req.chapter_id))
  const chs = F.chapters.filter(c => c.volume_id === Number(req.volume_id)).map(c => c.id)
  return F.pages.filter(pg => chs.includes(pg.chapter_id))
}
