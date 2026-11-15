import type { Building, Run } from '../data/types'
import { doorLabels } from './spots'

/**
 * An exit in words, as the exit chart names it: its door's label ("Exit Stair S1 (west)"), else the id. `short` drops the leading "Exit "
 * ("Stair S1 (west)") for a sentence that already says exit; "Exit from Lobby (L1)" keeps it, since "from Lobby" alone would not read.
 */
export function exitName(building: Building | null, id: string, short = false): string {
  const doorOf = new Map<string, string>()
  for (const f of building?.floors ?? []) for (const e of f.exits ?? []) doorOf.set(e.id, e.door ?? e.id)
  const label = (building && doorLabels(building).get(doorOf.get(id) ?? id)?.label) || id
  return short && label.startsWith('Exit ') && !label.startsWith('Exit from ') ? label.slice(5) : label
}

export interface BusiestExit {
  name: string
  /** people who left by it */
  n: number
  /** people who left by any exit (the run's exit events) */
  total: number
}

/** The exit most people left by in a run, counted from its `exit` events (ties go to the first by name); null when no one left. */
export function busiestExit(run: Run, building: Building | null): BusiestExit | null {
  const counts = new Map<string, number>()
  let total = 0
  for (const e of run.events) {
    if (e.type !== 'exit' || !e.exit) continue
    counts.set(e.exit, (counts.get(e.exit) ?? 0) + 1)
    total++
  }
  let best: { id: string; name: string; n: number } | null = null
  for (const [id, n] of counts) {
    const name = exitName(building, id, true)
    if (!best || n > best.n || (n === best.n && name < best.name)) best = { id, name, n }
  }
  return best ? { name: best.name, n: best.n, total } : null
}
