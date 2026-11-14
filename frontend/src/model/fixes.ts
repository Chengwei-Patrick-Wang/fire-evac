import type { Building } from '../data/types'
import { spotLabel, spotPosition } from './spots'
import type { SpotLike } from './spots'

export interface Fix {
  id: string
  kind?: string
  label: string
  why: string
  door?: string
  floor?: string
  width?: number
  doors?: Record<string, string>
  sprinklers?: boolean
  derivedFrom?: string
  n: number
  dT90: number
  dT90Min?: number
  dT90Max?: number
  slower?: number
  faster?: number
  dTrapped?: number
  dDosed?: number
  dSmokeSeconds?: number
  smokePct?: number | null
  helps?: boolean
  /** D22 data only: gains and a cost. Absent on older batches and packs, so the verdict is derived then. */
  tradeoff?: boolean
  /** D22 data only: the costs as phrases ("1.3 more trapped per fire"). */
  costs?: string[]
}

export type Verdict = 'helps' | 'tradeoff' | 'nogain'

/** D22's rule (fire/fixes.py VERDICT): a measure is a gain, or a cost, only from these limits on (t90 in s, trapped per fire, smoke in %). */
export const VERDICT = { t90: 1, trapped: 0.05, smokePct: 5 }

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null

export function readFixes(src: unknown): Fix[] {
  const f = (src as { fixes?: unknown } | null | undefined)?.fixes
  if (!Array.isArray(f)) return []
  return f.filter(
    (e): e is Fix => isObj(e) && typeof e.id === 'string' && typeof e.label === 'string' && typeof e.why === 'string' && isNum(e.n) && isNum(e.dT90),
  )
}

export function readSkipped(src: unknown): { id: string; reason: string }[] {
  const f = (src as { fixesSkipped?: unknown } | null | undefined)?.fixesSkipped
  if (!Array.isArray(f)) return []
  return f.filter((e): e is { id: string; reason: string } => isObj(e) && typeof e.id === 'string' && typeof e.reason === 'string')
}

export function fixDoor(fix: Fix): string | null {
  if (typeof fix.door === 'string') return fix.door
  for (const p of ['widen-', 'keepClear-']) if (fix.id.startsWith(p) && fix.id.length > p.length) return fix.id.slice(p.length)
  if (isObj(fix.doors)) {
    const k = Object.keys(fix.doors)[0]
    if (k) return k
  }
  return null
}

/** Where a fix points: the weak spot it names (`label` set when ranked in `top`) or just a place to show on its floor. The id is for clicks, never for display. */
export function fixTarget(
  fix: Fix,
  top: (SpotLike & { floor: string })[],
  building: Building | null,
): { id: string; floor: string; rank: number | null; label: string | null } | null {
  const id = fixDoor(fix)
  if (!id) return null
  const i = top.findIndex((t) => t.id === id)
  if (i >= 0) return { id, floor: top[i].floor, rank: i + 1, label: spotLabel(top[i]) }
  const p = building ? spotPosition(building, { id, floor: fix.floor }) : null
  return p ? { id, floor: p.floorId, rank: null, label: null } : null
}

const sg = (v: number) => `${v > 0 ? '+' : ''}${Math.round(v)}`
const sg1 = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(1)}`

interface Measure {
  kind: 'gain' | 'cost' | null
  text: string
}

/** t90, smoke and trapped, in the line's order: each a gain, a cost or neither by D22's rule, and written signed. */
function measures(fix: Fix): Measure[] {
  const out: Measure[] = []
  const by = (v: number, limit: number): Measure['kind'] => (v <= -limit ? 'gain' : v >= limit ? 'cost' : null)
  if (isNum(fix.dT90)) out.push({ kind: by(fix.dT90, VERDICT.t90), text: `${sg(fix.dT90)} s t90` })
  if (isNum(fix.smokePct)) out.push({ kind: by(fix.smokePct, VERDICT.smokePct), text: `${sg(fix.smokePct)}% smoke exposure` })
  else if (isNum(fix.dSmokeSeconds))
    out.push({ kind: fix.dSmokeSeconds < 0 ? 'gain' : fix.dSmokeSeconds > 0 ? 'cost' : null, text: `${sg(fix.dSmokeSeconds)} person-seconds in smoke` })
  if (isNum(fix.dTrapped)) out.push({ kind: by(fix.dTrapped, VERDICT.trapped), text: `${sg1(fix.dTrapped)} trapped per fire` })
  return out
}

/** One rule for the badge, the line and the tour. D22 batches say it themselves (`tradeoff`); older ones are judged on their numbers. */
export function fixVerdict(fix: Fix): Verdict {
  if (fix.n === 0) return 'nogain'
  if (typeof fix.tradeoff === 'boolean') return fix.tradeoff ? 'tradeoff' : fix.helps ? 'helps' : 'nogain'
  const m = measures(fix)
  if (!m.some((x) => x.kind === 'gain')) return 'nogain'
  return m.some((x) => x.kind === 'cost') ? 'tradeoff' : 'helps'
}

/** What a fix costs, signed ("+1.3 trapped per fire"). A D22 trade-off whose numbers show none falls back to D's own phrases. */
export function fixCosts(fix: Fix): string[] {
  const c = measures(fix)
    .filter((x) => x.kind === 'cost')
    .map((x) => x.text)
  if (c.length || fix.tradeoff !== true) return c
  return Array.isArray(fix.costs) ? fix.costs.filter((s): s is string => typeof s === 'string' && s !== '') : []
}

const SKIPPED_WORD = new Map([
  ['widen', 'Widen'],
  ['keepClear', 'Keep clear'],
  ['sprinklers', 'Sprinklers'],
  ['selfClosers', 'Self-closers'],
])

/** A fix that was not measured, as "<kind word>: <reason>": the id (which may hold a door id) never shows. */
export function skippedLine(s: { id: string; reason: string }): string {
  const word = SKIPPED_WORD.get(s.id.split('-')[0])
  return word ? `${word}: ${s.reason}` : s.reason
}

export function fixLine(fix: Fix): string {
  if (fix.n === 0) return `${fix.label}: no matched fires`
  if (fixVerdict(fix) === 'tradeoff') {
    // Its gains, then what it costs; a measure that is neither is left out.
    const gains = measures(fix)
      .filter((x) => x.kind === 'gain')
      .map((x) => x.text)
    const costs = fixCosts(fix)
    if (gains.length && costs.length) return `${fix.label}: ${gains.join(', ')} across ${fix.n} fires; but ${costs.join(', ')}`
  }
  let s = `${fix.label}: ${sg(fix.dT90)} s t90`
  if (isNum(fix.smokePct)) s += `, ${sg(fix.smokePct)}% smoke exposure`
  else if (isNum(fix.dSmokeSeconds)) s += `, ${sg(fix.dSmokeSeconds)} person-seconds in smoke`
  s += ` across ${fix.n} fires`
  if (isNum(fix.dTrapped) && Math.abs(fix.dTrapped) >= 0.05) s += `; ${sg1(fix.dTrapped)} trapped per fire`
  return s
}
