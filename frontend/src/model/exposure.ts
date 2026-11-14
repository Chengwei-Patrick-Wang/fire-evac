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

export function pairHeadline(a: Run, b: Run, label: string): Headline | null {
  const ea = readExposure(a)
  const eb = readExposure(b)
  if (!ea || !eb) return null
  const d = eb.personSecondsInSmoke - ea.personSecondsInSmoke
  let main =
    ea.personSecondsInSmoke > 0
      ? `${label}: ${sgn((d / ea.personSecondsInSmoke) * 100)}% person-seconds in smoke`
      : `${label}: ${sgn(d)} person-seconds in smoke`
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
  if (best) main += `, ${best.text}`
  const ma = a.metrics
  const mb = b.metrics
  const dt = ma.t90 == null || mb.t90 == null ? '' : ` (${sgn(mb.t90 - ma.t90)} s)`
  return { main, secondary: `t90 ${sec(ma.t90)} → ${sec(mb.t90)}${dt}, trapped ${ma.trapped} → ${mb.trapped}` }
}

export function batchHeadline(batch: Batch | null | undefined): (Headline & { n: number }) | null {
  const list = readWhatIf(batch)
  if (!list.length || !batch) return null
  const e = list.find((x) => x.id === 'proppedStairs') ?? list[0]
  const secondary =
    `90% out ${sgn0(e.dT90)} s on average` +
    (isNum(e.slower) ? ` (slower in ${e.slower} of ${e.n} fires)` : '') +
    (isNum(e.dTrapped) ? `, trapped ${sgn0(e.dTrapped)} per fire` : '')
  if (!isNum(e.dSmokeSeconds)) return { main: `${e.label}: 90% out ${sgn0(e.dT90)} s on average`, secondary, n: e.n }
  const runs = batch.runs as unknown as { smokeSeconds?: unknown }[]
  const vals = runs.map((r) => r.smokeSeconds)
  const mean = vals.length && vals.every(isNum) ? (vals as number[]).reduce((s, v) => s + v, 0) / vals.length : 0
  let main =
    mean > 0 && e.n === runs.length
      ? `${e.label}: ${sgn((e.dSmokeSeconds / mean) * 100)}% person-seconds in smoke`
      : `${e.label}: ${sgn(e.dSmokeSeconds)} person-seconds in smoke per fire`
  if (isNum(e.dDosed) && Math.abs(e.dDosed) >= 0.05) main += `, ${sgn(e.dDosed, 1)} people at an illustrative smoke dose of 1`
  return { main, secondary, n: e.n }
}
