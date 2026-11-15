import type { DemoRun, Run } from '../data/types'
import { pairHeadline } from './exposure'
import { materialWords } from './fireSpread'
import type { MaterialPair } from './fireSpread'
import { CLAUDE_WORDS } from './brain'
import type { BrainPair } from './brain'

const people = (n: number) => (n === 1 ? '1 person' : `${n} people`)
// The index entries carry only a run's headline numbers (t90, trapped): that is all the verdict needs, so no run file is loaded for it.
const asRun = (e: DemoRun) => ({ metrics: e.metrics }) as unknown as Run

/**
 * One line on how a precomputed pair came out: pairHeadline's ("Wood instead of drywall: 33 people trapped instead of 0; 90% never get out"),
 * and when the two runs trap the same number, the time to get 90% out ("Claude crowd instead of rules: 90% out 1.9 s later, 1 person trapped
 * either way"). Null when an entry has no metrics.
 */
export function verdictLine(base: DemoRun, variant: DemoRun, label: string): string | null {
  const a = base.metrics
  const b = variant.metrics
  if (!a || !b) return null
  const head = pairHeadline(asRun(base), asRun(variant), label)
  if (head) return head.main
  const same = `${a.trapped === 0 ? 'no one' : people(a.trapped)} trapped either way`
  if (a.t90 == null && b.t90 == null) return `${label}: 90% never get out, ${same}`
  if (a.t90 == null || b.t90 == null) return null
  const d = b.t90 - a.t90
  return `${label}: ${Math.abs(d) < 1 ? 'the same time to get 90% out' : `90% out ${Math.abs(d).toFixed(1)} s ${d > 0 ? 'later' : 'sooner'}`}, ${same}`
}

/**
 * The verdict of the building's precomputed pair the run `key` belongs to (either of its two runs): wood against drywall, or rules against a Claude
 * crowd. Null for any other run, so a line is shown only for the fire it is about.
 */
export function pairVerdict(key: string | null | undefined, pairs: { material: MaterialPair | null; claude: BrainPair | null }): string | null {
  if (!key) return null
  const { material, claude } = pairs
  if (material && (key === material.wood.id || key === material.drywall.id)) return verdictLine(material.drywall, material.wood, materialWords('wood', 'drywall'))
  if (claude && (key === claude.claude.id || key === claude.rules.id)) return verdictLine(claude.rules, claude.claude, CLAUDE_WORDS)
  return null
}
