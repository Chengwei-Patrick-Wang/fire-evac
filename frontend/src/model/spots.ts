import type { Building, Vec2 } from '../data/types'

export function centroidOf(poly: Vec2[]): Vec2 {
  const n = poly.length || 1
  return [poly.reduce((s, p) => s + p[0], 0) / n, poly.reduce((s, p) => s + p[1], 0) / n]
}

/** Looks the id up (doors, stairs, exits, rooms) rather than trusting `kind`. */
export function spotPosition(building: Building, spot: { id: string; floor?: string }): { floorId: string; pos: Vec2 } | null {
  const floors = [...building.floors].sort((a, b) => (a.id === spot.floor ? -1 : b.id === spot.floor ? 1 : 0))
  for (const f of floors) {
    const d = f.doors.find((x) => x.id === spot.id)
    if (d) return { floorId: f.id, pos: d.rect && d.rect.length >= 3 ? centroidOf(d.rect) : [(d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2] }
  }
  for (const f of floors) {
    const s = f.stairs.find((x) => x.id === spot.id)
    if (s) return { floorId: f.id, pos: centroidOf(s.polygon) }
  }
  for (const f of floors) {
    const e = f.exits.find((x) => x.id === spot.id)
    if (e) return { floorId: f.id, pos: centroidOf(e.polygon) }
  }
  for (const f of floors) {
    const r = f.rooms.find((x) => x.id === spot.id)
    if (r) return { floorId: f.id, pos: centroidOf(r.polygon) }
  }
  return null
}

const RAMP: [number, number, number][] = [
  [0x22, 0xc5, 0x5e],
  [0xea, 0xb3, 0x08],
  [0xef, 0x44, 0x44],
]
/** Green → yellow → red, v in 0..1. */
export function rampColor(v: number): string {
  const x = Math.min(1, Math.max(0, Number.isFinite(v) ? v : 0)) * 2
  const i = Math.min(1, Math.floor(x))
  const w = x - i
  const c = [0, 1, 2].map((k) => Math.round(RAMP[i][k] + (RAMP[i + 1][k] - RAMP[i][k]) * w))
  return `rgb(${c[0]},${c[1]},${c[2]})`
}

export const NEVER_COLOR = '#7f1d1d'
export const NODATA_COLOR = '#475569'

import type { Batch } from '../data/types'

export type RiskMetric = 'riskT90' | 'riskTrapped'

/** Min and max of the metric over rooms that have data (n > 0, non-null). */
export function riskRange(batch: Batch, metric: RiskMetric): { min: number; max: number } | null {
  let min = Infinity
  let max = -Infinity
  for (const r of batch.rooms) {
    const v = r[metric]
    if (r.n > 0 && v !== null && Number.isFinite(v)) {
      min = Math.min(min, v)
      max = Math.max(max, v)
    }
  }
  return min <= max ? { min, max } : null
}

export function roomRiskColor(r: Batch['rooms'][number] | undefined, metric: RiskMetric, range: { min: number; max: number } | null): string {
  if (!r || r.n === 0) return NODATA_COLOR
  const v = r[metric]
  if (v === null || !Number.isFinite(v)) return NEVER_COLOR
  if (!range) return NODATA_COLOR
  return rampColor(range.max > range.min ? (v - range.min) / (range.max - range.min) : 0.5)
}

/** Stairs take the max score of the doors that connect to the stair room. */
export function stairScore(building: Building, batch: Batch, stairRoom: string): number {
  let m = 0
  for (const f of building.floors)
    for (const d of f.doors) if (d.connects.includes(stairRoom)) m = Math.max(m, batch.doors.find((x) => x.id === d.id)?.score ?? 0)
  return m
}
