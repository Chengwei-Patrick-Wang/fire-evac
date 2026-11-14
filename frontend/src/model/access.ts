import type { Building, Run } from '../data/types'
import { PROFILE_NAMES } from '../replay/runIndex'
import { centroidOf } from './spots'

export interface ProfileRow {
  name: string
  agents: number
  evacuated: number | null
  trapped: number | null
  t50: number | null
  t90: number | null
  t100: number | null
}
export interface Assist {
  waiting: number
  meanWait: number | null
  maxWait: number | null
  personSeconds: number | null
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const numOrNull = (v: unknown) => (isNum(v) ? v : null)
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null
const KNOWN: readonly string[] = PROFILE_NAMES

export function readAccess(run: Run): { rows: ProfileRow[]; assist: Assist | null } | null {
  try {
    const m = run.metrics as unknown as { profiles?: unknown; assist?: unknown }
    const rows: ProfileRow[] = []
    if (isObj(m.profiles)) {
      const p = m.profiles
      const names = [...KNOWN, ...Object.keys(p).filter((k) => !KNOWN.includes(k))]
      for (const name of names) {
        const e = p[name]
        if (!isObj(e) || !isNum(e.agents) || e.agents <= 0) continue
        rows.push({
          name,
          agents: e.agents,
          evacuated: numOrNull(e.evacuated),
          trapped: numOrNull(e.trapped),
          t50: numOrNull(e.t50),
          t90: numOrNull(e.t90),
          t100: numOrNull(e.t100),
        })
      }
    }
    let assist: Assist | null = null
    if (isObj(m.assist) && isNum(m.assist.waiting) && m.assist.waiting > 0) {
      assist = {
        waiting: m.assist.waiting,
        meanWait: numOrNull(m.assist.meanWait),
        maxWait: numOrNull(m.assist.maxWait),
        personSeconds: numOrNull(m.assist.personSeconds),
      }
    }
    if (rows.length < 2 && !assist) return null
    return { rows, assist }
  } catch {
    return null
  }
}

export function fmtDuration(s: number): string {
  return s < 90 ? `${Math.round(s)} s` : `${(s / 60).toFixed(1)} min`
}

export function stairLabel(g: string): string {
  return /^S[A-Za-z0-9]$/.test(g) ? `Stair ${g[1]}` : `Stair ${g}`
}

const WHO: Record<string, string> = {
  wheelchair: 'wheelchair users',
  walker: 'people with walkers',
  cane: 'people with canes',
  older: 'older occupants',
  visitor: 'visitors',
  typical: 'occupants',
}

interface Group {
  profile: string
  floor: string
  sum: number
  n: number
  x?: number
  y?: number
}

export function waitLine(run: Run, building: Building | null): string | null {
  try {
    const profOf = new Map<number, string>()
    for (const a of run.agents) profOf.set(a.idx, a.profile)
    const groups = new Map<string, Group>()
    for (const e of run.events) {
      if (e.type !== 'wait' || !isNum(e.until) || e.idx == null) continue
      const profile = profOf.get(e.idx) ?? 'typical'
      const floor = e.floor ?? ''
      const key = `${profile}|${floor}`
      let g = groups.get(key)
      if (!g) {
        g = { profile, floor, sum: 0, n: 0 }
        if (isNum(e.x) && isNum(e.y)) {
          g.x = e.x
          g.y = e.y
        }
        groups.set(key, g)
      }
      g.sum += e.until - e.t
      g.n++
    }
    let best: Group | null = null
    let bestMean = -Infinity
    for (const g of groups.values()) {
      const mean = g.sum / g.n
      if (mean > bestMean) {
        best = g
        bestMean = mean
      }
    }
    if (best) {
      let at = ''
      const fl = building?.floors.find((f) => f.id === best.floor)
      if (fl && best.x != null && best.y != null && fl.stairs.length) {
        let bd = Infinity
        let bg = ''
        for (const s of fl.stairs) {
          const c = centroidOf(s.polygon)
          const d = Math.hypot(c[0] - best.x, c[1] - best.y)
          if (d < bd) {
            bd = d
            bg = s.group
          }
        }
        if (bg) at = ` at ${stairLabel(bg)}`
      }
      return `${best.floor} has no step-free way out in this model: ${WHO[best.profile] ?? best.profile} there waited ${fmtDuration(bestMean)} on average for help${at}.`
    }
    const m = run.metrics as unknown as { assist?: unknown }
    if (isObj(m.assist) && isNum(m.assist.waiting) && m.assist.waiting > 0) {
      const mw = isNum(m.assist.meanWait) ? `, ${fmtDuration(m.assist.meanWait)} on average` : ''
      return `${m.assist.waiting} people waited for help at the stairs${mw}.`
    }
    return null
  } catch {
    return null
  }
}
