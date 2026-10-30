import { NextResponse, type NextRequest } from 'next/server'
import { CODE_RE, type Manifest } from '@/lib/manifest'

/**
 * Short links. Printed QRs point at /v/{code}; people also type /{code}.
 * - a destination override (e.g. YouTube) answers with a 302 from the manifest
 * - /{code} -> /v/{code}
 * Everything else (watch / coming-soon / chapter pages) is rendered by app/v/[code].
 */

const RESERVED = new Set(['v', 'api', 'media', 'moments', 'fonts', 'textures', 'index', 'robots', 'sitemap', 'manifest', 'favicon', '_next'])
let cache: { at: number; links: Map<string, string> } | null = null

async function overrides(): Promise<Map<string, string>> {
  if (cache && Date.now() - cache.at < 60_000) return cache.links
  const links = new Map<string, string>()
  const url = process.env.MANIFEST_URL
  if (url) {
    try {
      const res = await fetch(url, { cache: 'no-store' })
      if (res.ok) {
        const m = (await res.json()) as Manifest
        for (const l of m.links ?? []) if (l.kind === 'redirect' && l.destination) links.set(l.code, l.destination)
      }
    } catch { /* offline: no overrides */ }
  }
  cache = { at: Date.now(), links }
  return links
}

export async function proxy(req: NextRequest) {
  const parts = req.nextUrl.pathname.split('/').filter(Boolean)
  let code: string | null = null
  if (parts.length === 2 && parts[0] === 'v') code = parts[1]
  else if (parts.length === 1 && !RESERVED.has(parts[0])) code = parts[0]
  if (!code || !CODE_RE.test(code)) return NextResponse.next()
  const dest = (await overrides()).get(code)
  if (dest) return NextResponse.redirect(dest, 302)
  if (parts.length === 1) return NextResponse.redirect(new URL(`/v/${code}`, req.url), 302)
  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!_next/|api/|textures/|fonts/|favicon|.*\\..*).*)'],
}
