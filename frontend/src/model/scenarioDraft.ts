import type { Building, DemoRun, Scenario, Vec2 } from '../data/types'
import { pointInPolygon } from '../scene/geometry'

export function makeDraft(building: Building, base?: Scenario | null): Scenario {
  const d: Scenario = base
    ? (JSON.parse(JSON.stringify(base)) as Scenario)
    : {
        version: 'scenario/v0',
        seed: 1,
        occupants: { total: 160, mix: { typical: 0.85, older: 0.1, visitor: 0.05 } },
        fire: { type: 'kitchen', start: 0 },
        sprinklers: false,
        doors: {},
        alarmTime: 30,
        maxTime: 400,
      }
  d.buildingId = building.id
  d.doors ??= {}
  return d
}

/** What a Run button says while the scenario has no fire yet (the backend refuses a run with no fire floor and room). */
export const PLACE_FIRE_FIRST = 'Click a room to place the fire first'

/** True once the scenario's fire sits in a room: a click on a room, or the room list, writes the fire's floor, room and spot. */
export const firePlaced = (s: Pick<Scenario, 'fire'> | null | undefined): boolean => !!s?.fire.floor && !!s.fire.room

/** The room containing floor-local point (x, y), or null for stairs, outside or no room. */
export function roomAt(building: Building, floorId: string, x: number, y: number) {
  const floor = building.floors.find((f) => f.id === floorId)
  if (!floor) return null
  const stairRooms = new Set(floor.stairs.map((s) => s.room))
  for (const r of floor.rooms) {
    if (stairRooms.has(r.id) || r.type === 'stair') continue
    if (pointInPolygon([x, y], r.polygon)) return r
  }
  return null
}

export function nearestPrecomputedRun(
  entries: DemoRun[],
  fire: { floor?: string; x?: number; y?: number },
): { entry: DemoRun; distance: number } | null {
  let best: { entry: DemoRun; distance: number; sameFloor: boolean } | null = null
  const fx = fire.x ?? 0
  const fy = fire.y ?? 0
  for (const e of entries) {
    if (e.whatIf !== null) continue
    const distance = Math.hypot(e.fire.x - fx, e.fire.y - fy)
    const sameFloor = !fire.floor || e.fire.floor === fire.floor
    if (!best || (sameFloor && !best.sameFloor) || (sameFloor === best.sameFloor && distance < best.distance)) {
      best = { entry: e, distance, sameFloor }
    }
  }
  return best && { entry: best.entry, distance: best.distance }
}

/** A profile's share as the whole percent the scenario card shows (the scenario keeps fractions from 0 to 1). */
export const toPercent = (share: number | undefined): number => Math.round(Math.max(0, share ?? 0) * 100)
/** The share (0 to 1) of a percent typed into the card: a whole percent, from 0 to 100. */
export const fromPercent = (percent: number): number => Math.min(100, Math.max(0, Math.round(percent))) / 100

/** Mix normalized to sum 1; falls back to all typical. */
export function normalizeMix(mix: Scenario['occupants']['mix']) {
  const out: Scenario['occupants']['mix'] = {}
  let sum = 0
  for (const v of Object.values(mix)) sum += Math.max(0, v ?? 0)
  if (sum <= 0) return { typical: 1 }
  for (const [k, v] of Object.entries(mix)) out[k as keyof typeof out] = Math.max(0, v ?? 0) / sum
  return out
}

function shoelace(p: Vec2[]) {
  let a = 0
  for (let i = 0; i < p.length; i++) {
    const [x1, y1] = p[i]
    const [x2, y2] = p[(i + 1) % p.length]
    a += x1 * y2 - x2 * y1
  }
  return Math.abs(a) / 2
}

export function insidePoint(poly: Vec2[]): Vec2 | null {
  if (poly.length < 3) return null
  const n = poly.length
  const avg: Vec2 = [poly.reduce((s, p) => s + p[0], 0) / n, poly.reduce((s, p) => s + p[1], 0) / n]
  if (pointInPolygon(avg, poly)) return avg
  for (let i = 1; i < n - 1; i++) {
    const c: Vec2 = [(poly[0][0] + poly[i][0] + poly[i + 1][0]) / 3, (poly[0][1] + poly[i][1] + poly[i + 1][1]) / 3]
    if (pointInPolygon(c, poly)) return c
  }
  return null
}

/** Default fire spot, following B6's make_scenario rule; null when the building has no usable room. */
export function defaultFire(building: Building): Scenario['fire'] | null {
  if (building.floors.length === 0) return null
  const floor = building.floors.reduce((a, b) => (b.level < a.level ? b : a))
  const stairRooms = new Set(floor.stairs.map((s) => s.room))
  const nonStair = floor.rooms.filter((r) => r.type !== 'stair' && !stairRooms.has(r.id))
  let pool = nonStair.filter((r) => !['corridor', 'lobby'].includes(r.type))
  if (pool.length === 0) pool = nonStair
  const ranked = pool
    .map((r) => ({ r, a: shoelace(r.polygon) }))
    .sort((p, q) => q.a - p.a)
  for (const { r } of ranked) {
    const pt = insidePoint(r.polygon)
    if (!pt) continue
    const type = r.type === 'kitchen' || r.type === 'bedroom' ? r.type : 'trash'
    return { floor: floor.id, room: r.id, x: pt[0], y: pt[1], type, start: 0 }
  }
  return null
}
