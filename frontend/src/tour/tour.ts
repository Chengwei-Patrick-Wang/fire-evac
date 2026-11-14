import { useEffect } from 'react'
import { create } from 'zustand'
import { useApp } from '../store/app'
import { TOUR } from './scenes'

interface TourState {
  scene: number | null
  auto: boolean
  note: string | null
  startedAt: number
  go: (i: number, auto: boolean) => void
  start: () => void
  stop: () => void
}

let seq = 0
let timers: ReturnType<typeof setTimeout>[] = []
const clear = () => {
  timers.forEach(clearTimeout)
  timers = []
}

export const useTour = create<TourState>((set, get) => ({
  scene: null,
  auto: false,
  note: null,
  startedAt: 0,
  go: (i, auto) => {
    const n = TOUR.length
    if (i < 0 || i >= n) return
    const mine = ++seq
    clear()
    set({ scene: i, auto, note: null, startedAt: performance.now() })
    const after = (ms: number, fn: () => void) => {
      timers.push(setTimeout(() => { if (mine === seq) fn() }, ms))
    }
    const setNote = (note: string | null) => { if (mine === seq) set({ note }) }
    void TOUR[i]
      .enter({ after, setNote })
      .catch((e: unknown) => setNote(e instanceof Error ? e.message : String(e)))
      .then(() => {
        if (mine !== seq || !auto || i >= n - 1) return
        after(TOUR[i].seconds * 1000, () => get().go(i + 1, true))
      })
  },
  start: () => get().go(0, true),
  stop: () => {
    seq++
    clear()
    set({ scene: null, note: null })
  },
}))

/** Keys: 1-6 jump (manual pacing); while a scene is on, arrows and PageUp/Down step and Esc stops. Space belongs to Timeline. */
export function useTourKeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (useApp.getState().view !== 'replay' || e.ctrlKey || e.altKey || e.metaKey) return
      const el = e.target as HTMLElement | null
      const tag = el?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || el?.isContentEditable) return
      const t = useTour.getState()
      if (/^[1-6]$/.test(e.key)) return t.go(Number(e.key) - 1, false)
      if (t.scene === null) return
      if (e.key === 'ArrowRight' || e.key === 'PageDown') {
        e.preventDefault()
        t.go(Math.min(t.scene + 1, TOUR.length - 1), t.auto)
      } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
        e.preventDefault()
        t.go(Math.max(t.scene - 1, 0), t.auto)
      } else if (e.key === 'Escape') t.stop()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
