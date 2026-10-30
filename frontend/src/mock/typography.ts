// Mock typography: the catalog/presets exported from engine/typography.py (scripts/export_typography.py) and the same
// merge/resolve rules as the engine.
import data from './typography.json'
import type { FontInfo, PresetsInfo, ResolvedTypography, TypographySetting, FontKey, SizeStep } from '@/api/types'
import { FONT_KEYS } from '@/api/types'

export const fonts = data.fonts as unknown as FontInfo[]
export const presets = data.presets as unknown as PresetsInfo

export function merge(volume?: TypographySetting | null, override?: TypographySetting | null): TypographySetting {
  let eff: TypographySetting = { ...presets.default }
  for (const layer of [volume ?? {}, override ?? {}]) {
    const clean = Object.fromEntries(Object.entries(layer).filter(([, v]) => v != null && v !== '')) as TypographySetting
    if (clean.preset) for (const k of FONT_KEYS) delete eff[k.key]
    eff = { ...eff, ...clean }
  }
  return eff
}

export function resolve(volume?: TypographySetting | null, override?: TypographySetting | null): ResolvedTypography {
  const eff = merge(volume, override)
  const p = presets.presets.find(x => x.id === eff.preset) ?? presets.presets[0]
  const out = {} as Record<FontKey, { id: string; family: string }>
  for (const { key } of FONT_KEYS) {
    const f = fonts.find(x => x.id === (eff[key] ?? p.fonts[key])) ?? fonts.find(x => x.id === p.fonts[key])!
    out[key] = { id: f.id, family: f.family }
  }
  const size = (eff.size ?? 'L') as SizeStep
  const title = (eff.title_size ?? size) as SizeStep
  return { preset: eff.preset ?? null, size, title_size: title, line_height: eff.line_height ?? 1.32, colour_mode: eff.colour_mode ?? 'smart', colours: eff.colours ?? {}, fonts: out, scale: { size: presets.sizes[size], title_size: presets.sizes[title] } }
}

export function fontFaceCss(families: string[]): string {
  return fonts.filter(f => families.includes(f.family)).flatMap(f => f.faces.map(x => `@font-face{font-family:'${f.family}';src:url('${x.url}') format('truetype');font-weight:${x.weight};font-style:${x.style}}`)).join('\n')
}
