import type { Batch, Run } from '../data/types'

export interface RunExposure {
  personSecondsInSmoke: number
  stairs: { floor: string; group: string; smokeAt: number | null }[]
}
export interface WhatIfEntry {
  id: string
  label: string
  why: string
  n: number
  dT90: number
  dT90Min?: number
  dT90Max?: number
  slower?: number
  faster?: number
  dTrapped?: number
  dDosed?: number
  dSmokeSeconds?: number
  /** the change in person-seconds in smoke, in percent of the paired baselines (D's `smokePct`; null when it cannot be computed) */
  smokePct?: number | null
}
export interface Headline {
  main: string
  secondary: string | null
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null

export function stairLabel(g: string): string {
  return /^S[A-Za-z0-9]$/.test(g) ? `Stair ${g[1]}` : `Stair ${g}`
}

export function readExposure(run: Run): RunExposure | null {
  const e = (run.metrics as unknown as { exposure?: unknown } | undefined)?.exposure
  if (!isObj(e) || !isNum(e.personSecondsInSmoke) || !Array.isArray(e.stairs)) return null
  return e as unknown as RunExposure
}

export function readWhatIf(batch: Batch | null | undefined): WhatIfEntry[] {
  const w = (batch as unknown as { whatIf?: unknown } | null | undefined)?.whatIf
  if (!Array.isArray(w)) return []
  return w.filter(
    (e): e is WhatIfEntry =>
      isObj(e) && typeof e.id === 'string' && typeof e.label === 'string' && typeof e.why === 'string' && isNum(e.n) && isNum(e.dT90),
  )
}

const sgn = (v: number, digits = 0) => `${v > 0 ? '+' : ''}${v.toFixed(digits)}`
const sgn0 = (v: number, digits = 1) => `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`
const sec = (v: number | null) => (v == null ? 'not reached' : `${v.toFixed(0)} s`)

/** A pair headline. When the two runs differ in how many people were trapped, that leads and `smoke` is the smoke line to show second. */
export interface PairHeadline extends Headline {
  smoke: string | null
}

const people = (n: number) => (n === 1 ? '1 person' : `${n} people`)

/** "33 people trapped instead of 0": what the variant (b) does to the number of people trapped against the base (a). */
function trappedClause(a: number, b: number): string {
  return `${b === 0 ? 'no one' : people(b)} trapped instead of ${a}`
}

/** What the variant does to the time until 90% are out, as a clause after the trapped one; nothing when it hardly moves. */
function t90Clause(a: number | null, b: number | null): string {
  if (b == null) return a == null ? '' : '; 90% never get out'
  if (a == null) return `; 90% out after ${b.toFixed(0)} s`
  const d = b - a
  return Math.abs(d) < 1 ? '' : `; 90% out ${Math.abs(d).toFixed(0)} s ${d > 0 ? 'later' : 'sooner'}`
}

/**
 * The headline of a variant (b) against its base (a): `label` and what changed. When the number of people trapped differs by at least one,
 * that leads ("Wood instead of drywall: 33 people trapped instead of 0; 90% never get out") and the smoke line comes second; when it is
 * equal the smoke leads, as before. Null when there is nothing to say: no exposure numbers and the same number trapped.
 */
export function pairHeadline(a: Run, b: Run, label: string): PairHeadline | null {
  const ma = a.metrics
  const mb = b.metrics
  const ea = readExposure(a)
  const eb = readExposure(b)
  let smoke: string | null = null
  if (ea && eb) {
    const d = eb.personSecondsInSmoke - ea.personSecondsInSmoke
    smoke =
      ea.personSecondsInSmoke > 0
        ? `${sgn((d / ea.personSecondsInSmoke) * 100)}% person-seconds in smoke`
        : `${sgn(d)} person-seconds in smoke`
    let best: { text: string; gain: number } | null = null
    for (const sa of ea.stairs) {
      const sb = eb.stairs.find((x) => x.floor === sa.floor && x.group === sa.group)
      if (!sb || !isNum(sb.smokeAt)) continue
      const name = `${stairLabel(sa.group)} on ${sa.floor}`
      if (!isNum(sa.smokeAt)) {
        if (!best || best.gain !== Infinity) best = { text: `${name} fills with smoke (clear in the baseline)`, gain: Infinity }
      } else {
        const gain = sa.smokeAt - sb.smokeAt
        if (gain > 0 && (!best || gain > best.gain)) best = { text: `${name} fills ${gain.toFixed(0)} s sooner`, gain }
      }
    }
    if (best) smoke += `, ${best.text}`
  }
  const dt = ma.t90 == null || mb.t90 == null ? '' : ` (${sgn(mb.t90 - ma.t90)} s)`
  const numbers = `t90 ${sec(ma.t90)} → ${sec(mb.t90)}${dt}, trapped ${ma.trapped} → ${mb.trapped}`
  if (isNum(ma.trapped) && isNum(mb.trapped) && Math.abs(mb.trapped - ma.trapped) >= 1) {
    return { main: `${label}: ${trappedClause(ma.trapped, mb.trapped)}${t90Clause(ma.t90, mb.t90)}`, secondary: smoke ? `${smoke} · ${numbers}` : numbers, smoke }
  }
  if (smoke === null) return null
  return { main: `${label}: ${smoke}`, secondary: numbers, smoke: null }
}

export function batchHeadline(batch: Batch | null | undefined): (Headline & { n: number }) | null {
  const list = readWhatIf(batch)
  if (!list.length || !batch) return null
  const e = list.find((x) => x.id === 'proppedStairs') ?? list[0]
  const secondary =
    `90% out ${sgn0(e.dT90)} s on average` +
    (isNum(e.slower) ? ` (slower in ${e.slower} of ${e.n} fires)` : '') +
    (isNum(e.dTrapped) ? `, trapped ${sgn0(e.dTrapped)} per fire` : '')
  // The relative change leads, as the Report tab says it ("+69% more time in smoke"): D's own percent, else person-seconds against the mean of the
  // batch's runs (only when the pairs are all of them). Never raw person-seconds and never the smoke dose: with no percent to give, the 90% out line leads.
  let pct: number | null = isNum(e.smokePct) ? e.smokePct : null
  if (pct === null && isNum(e.dSmokeSeconds)) {
    const runs = batch.runs as unknown as { smokeSeconds?: unknown }[]
    const vals = runs.map((r) => r.smokeSeconds)
    const mean = vals.length && vals.every(isNum) ? (vals as number[]).reduce((s, v) => s + v, 0) / vals.length : 0
    if (mean > 0 && e.n === runs.length) pct = (e.dSmokeSeconds / mean) * 100
  }
  if (pct === null) return { main: `${e.label}: 90% out ${sgn0(e.dT90)} s on average`, secondary, n: e.n }
  const rounded = Math.round(pct)
  return { main: `${e.label}: ${rounded > 0 ? `+${rounded}% more` : rounded < 0 ? `${-rounded}% less` : 'no change in'} time in smoke`, secondary, n: e.n }
}
