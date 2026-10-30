import { revalidatePath, revalidateTag } from 'next/cache'
import { NextResponse, type NextRequest } from 'next/server'

/** Called by Dharma Studio after it publishes manifest.json: expire the manifest now (REVALIDATE_SECRET). */
export async function POST(req: NextRequest) {
  const expected = process.env.REVALIDATE_SECRET
  let secret = req.headers.get('x-revalidate-secret')
  if (!secret) {
    try { secret = ((await req.json()) as { secret?: string }).secret ?? null } catch { secret = null }
  }
  if (!expected || secret !== expected) return NextResponse.json({ ok: false, error: 'unauthorised' }, { status: 401 })
  revalidateTag('manifest', { expire: 0 })
  revalidatePath('/', 'layout')
  return NextResponse.json({ ok: true, at: new Date().toISOString() })
}
