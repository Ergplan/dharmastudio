import type { ApiError } from './types'

export const MOCK = import.meta.env.VITE_MOCK === '1' || import.meta.env.VITE_MOCK === 'true'

/** Resolve a media path (`/media/...`, `data/...` or a data: URI) to something an <img> can load. */
export function mediaUrl(path: string | null | undefined): string {
  if (!path) return ''
  if (path.startsWith('data:') || path.startsWith('blob:') || path.startsWith('http')) return path
  if (path.startsWith('/')) return path
  return `/media/${path.replace(/^data\//, '')}`
}

function makeError(status: number, detail: string): ApiError {
  const e = new Error(detail) as ApiError
  e.status = status
  e.detail = detail
  return e
}

let mockRequest: ((m: string, u: string, b?: unknown) => Promise<unknown>) | null = null
let MockErr: (new (s: number, d: string) => Error & { status: number; detail: string }) | null = null
async function loadMock() {
  if (!mockRequest) {
    const m = await import('@/mock/server')
    mockRequest = m.mockRequest
    MockErr = m.MockHttpError
  }
}

export async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  if (MOCK) {
    await loadMock()
    try {
      return (await mockRequest!(method, url, body)) as T
    } catch (e) {
      if (MockErr && e instanceof MockErr) throw makeError(e.status, e.detail)
      throw e
    }
  }
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  const res = await fetch(url, {
    method,
    headers: isForm || body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  })
  const ct = res.headers.get('content-type') ?? ''
  const payload = ct.includes('application/json') ? await res.json().catch(() => null) : await res.text()
  if (!res.ok) {
    const detail = typeof payload === 'string' ? payload : (payload?.detail ?? payload?.message ?? res.statusText)
    throw makeError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return payload as T
}

export const api = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body),
  put: <T>(url: string, body?: unknown) => request<T>('PUT', url, body),
  del: <T>(url: string) => request<T>('DELETE', url),
}

/** URL of the page's render HTML — opened in a new tab as the standalone artifact. In mock mode we open a blob. */
export async function openRenderInNewTab(pageId: number, params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString()
  const url = `/api/pages/${pageId}/render${qs ? `?${qs}` : ''}`
  if (!MOCK) { window.open(url, '_blank', 'noopener'); return }
  const html = await api.get<string>(url)
  const blob = new Blob([html], { type: 'text/html' })
  window.open(URL.createObjectURL(blob), '_blank', 'noopener')
}
