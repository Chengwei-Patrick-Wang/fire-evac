export interface Rng {
  min: number | null
  median: number | null
  max: number | null
  missing: number
}
export interface SeedRange {
  seeds: number[]
  [k: string]: unknown
}
export interface Stability {
  seeds?: number[]
  top3?: string[]
  heldIn: number
  n: number
  stable?: boolean
  why: string
}
export interface Span3 {
  min: number
  median: number
  max: number
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null
const numOrNull = (v: unknown) => v === null || isNum(v)

export type SeedKey = 't50' | 't90' | 't100' | 'evacuated' | 'trapped'
export type SeedRangeMap = { seeds: number[] } & Partial<Record<SeedKey, Rng>>

export function readSeedRange(run: unknown): SeedRangeMap | null {
  const sr = (run as { metrics?: { seedRange?: unknown } } | null | undefined)?.metrics?.seedRange
  if (!isObj(sr) || !Array.isArray(sr.seeds)) return null
  const seeds = sr.seeds.filter(isNum)
  if (seeds.length < 2) return null
  const out: SeedRangeMap = { seeds }
  let any = false
  for (const k of ['t50', 't90', 't100', 'evacuated', 'trapped'] as SeedKey[]) {
    const v = sr[k]
    if (isObj(v) && numOrNull(v.min) && numOrNull(v.median) && numOrNull(v.max) && isNum(v.missing)) {
      out[k] = v as unknown as Rng
      any = true
    }
  }
  return any ? out : null
}

export function readStability(batch: unknown): Stability | null {
  const s = (batch as { stability?: unknown } | null | undefined)?.stability
  if (!isObj(s) || !isNum(s.heldIn) || !isNum(s.n) || typeof s.why !== 'string') return null
  return s as unknown as Stability
}

function span3(v: unknown): Span3 | null {
  return isObj(v) && isNum(v.min) && isNum(v.median) && isNum(v.max) ? { min: v.min, median: v.median, max: v.max } : null
}

export function roomRange(batch: unknown, id: string, key = 'riskT90Range'): Span3 | null {
  const rooms = (batch as { rooms?: unknown } | null | undefined)?.rooms
  if (!Array.isArray(rooms)) return null
  const r = rooms.find((x) => isObj(x) && x.id === id)
  return isObj(r) ? span3(r[key]) : null
}

export function doorRange(batch: unknown, id: string, floor: string): Span3 | null {
  const doors = (batch as { doors?: unknown } | null | undefined)?.doors
  if (!Array.isArray(doors)) return null
  const d = doors.find((x) => isObj(x) && x.id === id && (x.floor === floor || x.floor === undefined))
  return isObj(d) ? span3(d.scoreRange) : null
}

export function span(r: { min: number; max: number }, unit = ' s', digits = 0): string {
  const a = r.min.toFixed(digits)
  const b = r.max.toFixed(digits)
  return a === b ? `${a}${unit}` : `${a}–${b}${unit}`
}

export function seedBadge(kind: string, inTop3: unknown, n: unknown): { text: string; stable: boolean } | null {
  if (!isNum(inTop3) || !isNum(n)) return null
  return { text: `${kind === 'room' ? 'worst room' : 'top 3'} in ${inTop3} of ${n} seeds`, stable: inTop3 === n }
}

// Text for one seed-range row: "117–130 s", with a missing note.
export function rangeCell(r: Rng | undefined, unit: string): string | null {
  if (!r) return null
  if (r.min == null || r.max == null) return 'not reached in any seed'
  return span({ min: r.min, max: r.max }, unit) + (r.missing > 0 ? `, not reached in ${r.missing}` : '')
}

export function t90Phrase(run: unknown): string | null {
  const sr = readSeedRange(run)
  const r = sr?.t90
  if (!sr || !r || r.min == null || r.max == null) return null
  return `t90 ${span({ min: r.min, max: r.max })} over ${sr.seeds.length} seeds`
}
