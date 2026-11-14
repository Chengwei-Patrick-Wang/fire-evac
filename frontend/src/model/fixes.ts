import type { Building } from '../data/types'
import { spotPosition } from './spots'

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
}

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

export function fixTarget(
  fix: Fix,
  top: { id: string; floor: string }[],
  building: Building | null,
): { id: string; floor: string; rank: number | null } | null {
  const id = fixDoor(fix)
  if (!id) return null
  const i = top.findIndex((t) => t.id === id)
  if (i >= 0) return { id, floor: top[i].floor, rank: i + 1 }
  const p = building ? spotPosition(building, { id, floor: fix.floor }) : null
  return p ? { id, floor: p.floorId, rank: null } : null
}

const sg = (v: number) => `${v > 0 ? '+' : ''}${Math.round(v)}`
const sg1 = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(1)}`

export function fixLine(fix: Fix): string {
  if (fix.n === 0) return `${fix.label}: no matched fires`
  let s = `${fix.label}: ${sg(fix.dT90)} s t90`
  if (isNum(fix.smokePct)) s += `, ${sg(fix.smokePct)}% smoke exposure`
  else if (isNum(fix.dSmokeSeconds)) s += `, ${sg(fix.dSmokeSeconds)} person-seconds in smoke`
  s += ` across ${fix.n} fires`
  if (isNum(fix.dTrapped) && Math.abs(fix.dTrapped) >= 0.05) s += `; ${sg1(fix.dTrapped)} trapped per fire`
  return s
}
