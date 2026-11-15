import type { Run } from '../data/types'

export interface Compare {
  dT90: number | null
  dT100: number | null
  dTrapped: number
  t90: [number | null, number | null]
}

/** Differences b − a; a delta is null when either side never reached the mark. */
export function compareRuns(a: Run, b: Run): Compare {
  const d = (x: number | null, y: number | null) => (x == null || y == null ? null : y - x)
  return {
    dT90: d(a.metrics.t90, b.metrics.t90),
    dT100: d(a.metrics.t100, b.metrics.t100),
    dTrapped: b.metrics.trapped - a.metrics.trapped,
    t90: [a.metrics.t90, b.metrics.t90],
  }
}
