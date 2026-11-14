import type { Building, DemoRun, Scenario } from '../data/types'
import { pointInPolygon } from '../scene/geometry'

export const FIRE_TYPES = ['kitchen', 'bedroom', 'battery', 'trash', 'liquid']

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

/** Mix normalized to sum 1; falls back to all typical. */
export function normalizeMix(mix: Scenario['occupants']['mix']) {
  const out: Scenario['occupants']['mix'] = {}
  let sum = 0
  for (const v of Object.values(mix)) sum += Math.max(0, v ?? 0)
  if (sum <= 0) return { typical: 1 }
  for (const [k, v] of Object.entries(mix)) out[k as keyof typeof out] = Math.max(0, v ?? 0) / sum
  return out
}
