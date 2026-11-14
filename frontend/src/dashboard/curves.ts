import type { Run } from '../data/types'

/** Percent of agents that have exited (type "exit", not "stair") at each time. */
export function evacCurve(run: Run, times: number[]): number[] {
  const n = run.metrics.agents || run.agents.length
  const ts = run.events.filter((e) => e.type === 'exit').map((e) => e.t).sort((a, b) => a - b)
  const out: number[] = []
  let c = 0
  for (const t of times) {
    while (c < ts.length && ts[c] <= t) c++
    out.push(n > 0 ? (c / n) * 100 : 0)
  }
  return out
}

export const RUN_COLORS = ['#38bdf8', '#f97316', '#a78bfa', '#22c55e', '#f43f5e', '#eab308']
export const PROFILE_HEX = ['#38bdf8', '#a78bfa', '#facc15', '#f472b6', '#fb7185', '#34d399']
export const PROFILE_LABELS = ['typical', 'older', 'visitor', 'cane', 'walker', 'wheelchair']
