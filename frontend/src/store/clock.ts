import { useEffect, useState } from 'react'
import { create } from 'zustand'

/** Playback speeds the timeline and the Simulation menu offer. */
export const SPEEDS = [0.25, 0.5, 1, 2, 4, 10]

interface ClockState {
  t: number
  playing: boolean
  speed: number
  duration: number
  seek: (t: number) => void
  toggle: () => void
  setSpeed: (s: number) => void
  setDuration: (d: number) => void
}

export const useClock = create<ClockState>((set, get) => ({
  t: 0,
  playing: false,
  speed: 1,
  duration: 0,
  seek: (t) => set({ t: Math.min(Math.max(0, t), get().duration) }),
  toggle: () =>
    set((s) => (s.playing ? { playing: false } : { playing: true, t: s.t >= s.duration ? 0 : s.t })),
  setSpeed: (speed) => set({ speed }),
  setDuration: (duration) => set((s) => ({ duration, t: Math.min(s.t, duration) })),
}))

/** t for React renderers: re-renders at most every `ms`. */
export function useThrottledT(ms: number): number {
  const [t, setT] = useState(() => useClock.getState().t)
  useEffect(() => {
    const id = setInterval(() => {
      const cur = useClock.getState().t
      setT((p) => (p === cur ? p : cur))
    }, ms)
    return () => clearInterval(id)
  }, [ms])
  return t
}
