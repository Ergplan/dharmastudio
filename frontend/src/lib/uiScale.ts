// The app's text size: scales the root font-size (Tailwind sizes are rem-based). Stored per browser.
import { create } from 'zustand'

export const UI_STEPS = [0.9, 1, 1.1, 1.2, 1.32] as const
export const UI_DEFAULT = 2 // one step larger than the original dense UI (16 px root -> 17.6 px)
const KEY = 'dharma.uiScale'

function load(): number {
  try { const v = Number(localStorage.getItem(KEY)); if (Number.isInteger(v) && v >= 0 && v < UI_STEPS.length) return v } catch { /* storage blocked */ }
  return UI_DEFAULT
}
function apply(i: number) { document.documentElement.style.fontSize = `${16 * UI_STEPS[i]}px` }

export const useUiScale = create<{ step: number; set: (i: number) => void }>((set) => ({
  step: load(),
  set: (i) => {
    const s = Math.max(0, Math.min(UI_STEPS.length - 1, i))
    try { localStorage.setItem(KEY, String(s)) } catch { /* storage blocked */ }
    apply(s); set({ step: s })
  },
}))
apply(load())
