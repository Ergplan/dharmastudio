import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Check } from 'lucide-react'
import type { FontInfo, FontRole } from '@/api/types'
import { cx } from '@/components/ui'
import { scriptsFor } from './FontFaces'

/** A dropdown that shows every font in its own face, filtered to the language's script; role-suited fonts first. */
export function FontPicker({ fonts, value, role, lang, onChange, inherited }: {
  fonts: FontInfo[]; value: string | null | undefined; role: FontRole; lang: 'en' | 'hi'; onChange: (id: string | null) => void; inherited?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    window.addEventListener('mousedown', h); return () => window.removeEventListener('mousedown', h)
  }, [open])
  const ok = fonts.filter(f => scriptsFor(lang).includes(f.script))
  const suited = ok.filter(f => f.roles.includes(role))
  const others = ok.filter(f => !f.roles.includes(role))
  const cur = fonts.find(f => f.id === (value ?? inherited))
  const sample = (f: FontInfo) => (lang === 'hi' ? f.preview.devanagari : f.preview.latin)?.[role] ?? f.family
  const row = (f: FontInfo) => (
    <button key={f.id} type="button" onClick={() => { onChange(f.id); setOpen(false) }} title={f.note}
      className={cx('w-full text-left px-2.5 py-1.5 hover:bg-ink-700 flex items-center gap-2', f.id === cur?.id && 'bg-gold-500/10')}>
      <span className="w-4 shrink-0">{f.id === cur?.id && <Check size={12} className="text-gold-300" />}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-ink-100 text-[1.05rem] leading-snug truncate" style={{ fontFamily: `'${f.family}',serif`, fontWeight: role === 'title' || role === 'sfx' ? f.title_weight : f.text_weight }}>{lang === 'hi' ? sample(f) : f.family}</span>
        <span className="block text-2xs text-ink-500 truncate">{f.note}</span>
      </span>
    </button>
  )
  return (
    <div ref={ref} className="relative">
      <button type="button" className="input h-9 flex items-center gap-2 text-left" onClick={() => setOpen(o => !o)}>
        <span className="flex-1 truncate text-sm text-ink-100" style={{ fontFamily: cur ? `'${cur.family}',serif` : undefined }}>{cur ? (lang === 'hi' ? `${sample(cur)} · ${cur.family}` : cur.family) : '—'}</span>
        {value == null && inherited && <span className="chip">preset</span>}
        <ChevronDown size={13} className="text-ink-400 shrink-0" />
      </button>
      {open && (
        <div className="absolute z-30 left-0 right-0 mt-1 max-h-80 overflow-auto card shadow-xl shadow-black/60 py-1">
          {value != null && <button type="button" className="w-full text-left px-2.5 py-1.5 text-xs text-ink-300 hover:bg-ink-700" onClick={() => { onChange(null); setOpen(false) }}>Use the preset’s font</button>}
          <div className="label px-2.5 pt-1.5 pb-1">Suited to {role}</div>
          {suited.map(row)}
          {others.length > 0 && <div className="label px-2.5 pt-2 pb-1">Other {lang === 'hi' ? 'Devanagari' : 'Latin'} fonts</div>}
          {others.map(row)}
        </div>
      )}
    </div>
  )
}

export function ContrastBadge({ ratio }: { ratio: number }) {
  const tone = ratio >= 7 ? 'border-emerald-500/50 text-emerald-300 bg-emerald-500/10' : ratio >= 4.5 ? 'border-amber-500/50 text-amber-300 bg-amber-500/10' : 'border-red-500/50 text-red-300 bg-red-500/10'
  return <span className={cx('chip font-mono', tone)} title="WCAG contrast of text on box (AAA = 7:1)">{ratio.toFixed(1)}:1 {ratio >= 7 ? 'AAA' : ratio >= 4.5 ? 'AA' : 'low'}</span>
}
