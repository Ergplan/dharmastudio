import { useMemo } from 'react'
import { useFonts } from '@/api/hooks'
import type { FontInfo } from '@/api/types'

/** @font-face for every catalog face, served by /api/fonts/{file}. Browsers only download a face when text uses it. */
export function FontFaces() {
  const { data: fonts } = useFonts()
  const css = useMemo(() => (fonts ?? []).flatMap(f => f.faces.map(x => `@font-face{font-family:'${f.family}';src:url('${x.url}') format('truetype');font-weight:${x.weight};font-style:${x.style};font-display:swap}`)).join('\n'), [fonts])
  return css ? <style data-fonts>{css}</style> : null
}

export const fontStack = (f: FontInfo | undefined, fallback = 'serif') => f ? `'${f.family}',${fallback}` : fallback
export const scriptsFor = (lang: 'en' | 'hi') => lang === 'hi' ? ['devanagari', 'both'] : ['latin', 'both']
