import type { Building, Door, Room, Vec2 } from '../data/types'

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

/** Anything a list can name: a batch `top[]` entry, a headline-pack weak spot. */
export interface SpotLike {
  id: string
  floor?: string
  kind?: string
  label?: string
  why?: string
}

/**
 * A weak spot in words, never as its raw id. Batch `top[]` entries carry no `label`, but each `why` starts with it
 * ("<label>: ..."); room ids read well, so a room may show its own.
 */
export function spotLabel(e: SpotLike): string {
  const label = typeof e.label === 'string' ? e.label.trim() : ''
  if (label) return label
  const why = typeof e.why === 'string' ? e.why : ''
  const at = why.indexOf(': ')
  const lead = at > 0 ? why.slice(0, at).trim() : ''
  if (lead) return lead
  if (e.kind === 'room') return `Room ${e.id}`
  const kind = e.kind ? e.kind.charAt(0).toUpperCase() + e.kind.slice(1) : 'Spot'
  return e.floor ? `${kind} on ${e.floor}` : kind
}

export interface DoorName {
  label: string
  floor: string
}

const mid = (d: Door): Vec2 => [(d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2]

const doorCache = new WeakMap<Building, Map<string, DoorName>>()

/**
 * Every door in words, by id, for pickers: exits and stair doors by name, a plain door by the rooms it joins (the rule of
 * fire/batch.py `door_label`, with D23's plain-door wording). Two doors never read the same on a floor. The id stays the key.
 */
export function doorLabels(building: Building): Map<string, DoorName> {
  let m = doorCache.get(building)
  if (!m) doorCache.set(building, (m = buildDoorLabels(building)))
  return m
}

function buildDoorLabels(building: Building): Map<string, DoorName> {
  const out = new Map<string, DoorName>()
  const nm = (r: Room) => r.name || r.id
  for (const f of building.floors) {
    const rows: { d: Door; label: string; plain?: [Room, Room] }[] = []
    for (const d of f.doors) {
      const rooms = f.rooms.filter((r) => d.connects.includes(r.id))
      const stair = rooms.find((r) => r.type === 'stair')
      if (d.connects.includes('outside')) {
        const name = (f.exits ?? []).find((e) => e.door === d.id)?.name ?? ''
        const first = rooms[0]
        const label =
          name && !name.includes(':') && name.length <= 30
            ? `Exit ${name}`
            : stair
              ? `Stair ${stair.group ?? stair.id} exit`
              : first
                ? `Exit from ${nm(first)} (${first.id})`
                : `Exit ${d.id}`
        rows.push({ d, label })
      } else if (stair) rows.push({ d, label: `Stair ${stair.group ?? stair.id} door` })
      else if (rooms.length < 2) rows.push({ d, label: rooms.length ? `Door from ${nm(rooms[0])}` : `Door ${d.id}` })
      else rows.push({ d, label: '', plain: [rooms[0], rooms[1]] })
    }
    // A plain door reads "Door between A and B"; room ids join the names when another door on the floor joins the same names (or the names are equal).
    const nameKey = ([a, b]: [Room, Room]) => [nm(a), nm(b)].sort().join('\0')
    const joins = new Map<string, number>()
    for (const r of rows) if (r.plain) joins.set(nameKey(r.plain), (joins.get(nameKey(r.plain)) ?? 0) + 1)
    for (const r of rows) {
      if (!r.plain) continue
      const [a, b] = r.plain
      const ids = nm(a) === nm(b) || (joins.get(nameKey(r.plain)) ?? 0) > 1
      r.label = ids ? `Door between ${nm(a)} (${a.id}) and ${nm(b)} (${b.id})` : `Door between ${nm(a)} and ${nm(b)}`
    }
    // Doors that still read the same (two doors between the same rooms, two into one stair) are numbered by position: x, then y.
    const same = new Map<string, Door[]>()
    for (const r of rows) same.set(r.label, [...(same.get(r.label) ?? []), r.d])
    for (const r of rows) {
      const twins = same.get(r.label) ?? []
      const k = twins.length > 1 ? [...twins].sort((p, q) => mid(p)[0] - mid(q)[0] || mid(p)[1] - mid(q)[1]).indexOf(r.d) + 1 : 0
      if (!out.has(r.d.id)) out.set(r.d.id, { label: k ? `${r.label}, ${k} of ${twins.length}` : r.label, floor: f.id })
    }
  }
  return out
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
