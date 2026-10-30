/**
 * The site's content: manifest.json published by Dharma Studio to Vercel Blob (schema: ./manifest.schema.json).
 * MANIFEST_URL points at it; pages are statically generated from it with ISR and refreshed by /api/revalidate.
 */

export type LinkKind = 'moment' | 'chapter' | 'redirect' | 'coming_soon'

export interface Verse { id: string; source?: string; lines: string[]; iast?: string; meaning: string }
export interface Media { en_16x9: string; en_9x16: string; hi_16x9: string; hi_9x16: string; poster: string; poster_9x16?: string }
export interface MomentEntry {
  code: string; title_en: string; title_hi: string; volume: number; chapter: number; chapter_title?: string; page: number
  caption_en: string; caption_hi: string; verse: Verse | null; media: Media; duration_s: number; published_at?: string | null
}
export interface LinkEntry {
  code: string; kind: LinkKind; destination?: string | null; moment?: string | null
  chapter?: { volume: number; number: number; title: string } | null; moments?: string[]
}
export interface Manifest {
  version: 1; generated_at: string; site_url: string; media_base?: string | null
  book: { title: string; title_hi?: string; author: string; books: { number: number; title: string; title_hi?: string; moments?: number }[] }
  links: LinkEntry[]; moments: MomentEntry[]
}

export const SITE_URL = (process.env.SITE_URL || 'https://cycleofdharma.world').replace(/\/$/, '')
export const CODE_RE = /^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$/
export const BOOK_HI = 'द साइकिल ऑफ़ धर्म'

const EMPTY: Manifest = {
  version: 1, generated_at: '', site_url: SITE_URL,
  book: { title: 'The Cycle of Dharma', title_hi: BOOK_HI, author: 'Rachit Agarwal', books: [1, 2, 3].map(n => ({ number: n, title: `Book ${n}` })) },
  links: [], moments: [],
}

/** The manifest (ISR: cached 5 min, tag 'manifest' — /api/revalidate expires it at once). Empty when unset/unreachable. */
export async function getManifest(): Promise<Manifest> {
  const url = process.env.MANIFEST_URL
  if (!url) return EMPTY
  try {
    const res = await fetch(url, { next: { revalidate: 300, tags: ['manifest'] } })
    if (!res.ok) return EMPTY
    const m = (await res.json()) as Manifest
    return m && m.version === 1 ? m : EMPTY
  } catch {
    return EMPTY
  }
}

export function findLink(m: Manifest, code: string): LinkEntry | undefined {
  return m.links.find(l => l.code === code)
}

export function findMoment(m: Manifest, code: string): MomentEntry | undefined {
  return m.moments.find(x => x.code === code)
}
