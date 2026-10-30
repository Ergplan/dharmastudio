'use client'

import { useEffect, useState } from 'react'

export type Lang = 'en' | 'hi'
const KEY = 'cod-lang'

/** EN | हिंदी — sets <html data-lang> (CSS shows .only-en / .only-hi) and tells the player. Remembered per browser. */
export function useLang(): [Lang, (l: Lang) => void] {
  const [lang, setLang] = useState<Lang>('en')
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get('lang')
    let s: string | null = null
    try { s = localStorage.getItem(KEY) } catch { /* private mode */ }
    const l = (q === 'hi' || q === 'en' ? q : s === 'hi' || s === 'en' ? s : navigator.language?.startsWith('hi') ? 'hi' : 'en') as Lang
    apply(l)
    setLang(l)
    const h = (e: Event) => setLang((e as CustomEvent<Lang>).detail)
    window.addEventListener('cod-lang', h)
    return () => window.removeEventListener('cod-lang', h)
  }, [])
  const set = (l: Lang) => { apply(l); try { localStorage.setItem(KEY, l) } catch { /* ignore */ } window.dispatchEvent(new CustomEvent('cod-lang', { detail: l })) }
  return [lang, set]
}

function apply(l: Lang) {
  document.documentElement.dataset.lang = l
  document.documentElement.lang = l
}

export default function LangSwitch() {
  const [lang, set] = useLang()
  return (
    <div className="langs" role="group" aria-label="Language">
      <button aria-pressed={lang === 'en'} onClick={() => set('en')}>EN</button>
      <button aria-pressed={lang === 'hi'} className="hi" onClick={() => set('hi')}>हिंदी</button>
    </div>
  )
}
