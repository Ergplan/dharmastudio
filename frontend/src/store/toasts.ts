import { create } from 'zustand'

export interface Toast { id: number; kind: 'error' | 'gate' | 'info' | 'ok'; title: string; message: string }

let seq = 1
export const useToasts = create<{ toasts: Toast[]; push: (t: Omit<Toast, 'id'>) => void; dismiss: (id: number) => void }>((set) => ({
  toasts: [],
  push: (t) => {
    const id = seq++
    set(s => ({ toasts: [...s.toasts, { ...t, id }] }))
    setTimeout(() => set(s => ({ toasts: s.toasts.filter(x => x.id !== id) })), t.kind === 'gate' ? 9000 : 6000)
  },
  dismiss: (id) => set(s => ({ toasts: s.toasts.filter(x => x.id !== id) })),
}))

export const toast = (kind: Toast['kind'], title: string, message = '') => useToasts.getState().push({ kind, title, message })
