import { useEffect, type RefObject } from 'react'
import { create } from 'zustand'

const KEY = 'fes.a11y'
const mq = () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null)

type Saved = { contrast?: boolean; reduceMotion?: boolean }
const load = (): Saved => {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '{}') ?? {}
  } catch {
    return {}
  }
}
const save = (s: Saved) => {
  try {
    localStorage.setItem(KEY, JSON.stringify(s))
  } catch {
    /* ignore */
  }
}

const saved = load()
let userPickedMotion = typeof saved.reduceMotion === 'boolean'

type A11y = {
  contrast: boolean
  reduceMotion: boolean
  setContrast: (v: boolean) => void
  setReduceMotion: (v: boolean) => void
}

export const useA11y = create<A11y>((set, get) => ({
  contrast: !!saved.contrast,
  reduceMotion: typeof saved.reduceMotion === 'boolean' ? saved.reduceMotion : !!mq()?.matches,
  setContrast: (v) => {
    set({ contrast: v })
    save({ contrast: v, reduceMotion: userPickedMotion ? get().reduceMotion : undefined })
  },
  setReduceMotion: (v) => {
    userPickedMotion = true
    set({ reduceMotion: v })
    save({ contrast: get().contrast, reduceMotion: v })
  },
}))

const mirror = (s: A11y) => {
  if (typeof document === 'undefined') return
  const d = document.documentElement.dataset
  if (s.contrast) d.contrast = 'high'
  else delete d.contrast
  if (s.reduceMotion) d.motion = 'reduce'
  else delete d.motion
}
useA11y.subscribe(mirror)
mirror(useA11y.getState())
mq()?.addEventListener?.('change', (e) => {
  if (!userPickedMotion) useA11y.setState({ reduceMotion: e.matches })
})

const FOCUSABLE = 'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea, [tabindex]:not([tabindex="-1"])'

/** Focus the [data-close] button on open, keep Tab inside `ref`, and give focus back to the opener on close. */
export function useDialogFocus(ref: RefObject<HTMLElement | null>, active: boolean) {
  useEffect(() => {
    if (!active) return
    const opener = document.activeElement as HTMLElement | null
    const root = ref.current
    root?.querySelector<HTMLElement>('[data-close]')?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || !ref.current) return
      const els = [...ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement)
      if (!els.length) return
      const first = els[0]
      const last = els[els.length - 1]
      const cur = document.activeElement as HTMLElement | null
      if (!cur || !ref.current.contains(cur)) {
        e.preventDefault()
        first.focus()
      } else if (e.shiftKey && cur === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && cur === last) {
        e.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      if (opener && document.contains(opener)) opener.focus()
    }
  }, [active, ref])
}
