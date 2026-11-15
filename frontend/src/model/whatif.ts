import type { Building, DemoRun, Door, DoorState, Run, Scenario } from '../data/types'

function doorMid(d: Door): [number, number] {
  return [(d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2]
}

/** Doors that lead into a stair room (not the exterior "outside" doors). */
export function stairDoors(building: Building): { floor: string; door: Door }[] {
  const out: { floor: string; door: Door }[] = []
  for (const f of building.floors) {
    const stairRooms = new Set(f.rooms.filter((r) => r.type === 'stair').map((r) => r.id))
    for (const s of f.stairs) stairRooms.add(s.room)
    for (const d of f.doors) {
      if (d.connects.some((c) => c !== 'outside' && stairRooms.has(c))) out.push({ floor: f.id, door: d })
    }
  }
  return out
}

/** Stair door on the fire floor nearest the fire point (falls back to any floor). */
export function defaultWhatIfDoor(building: Building, fire: { floor?: string; x?: number; y?: number }): string | null {
  const all = stairDoors(building)
  if (!all.length) return null
  const pool = all.filter((d) => d.floor === fire.floor)
  const list = pool.length ? pool : all
  const fx = fire.x ?? 0
  const fy = fire.y ?? 0
  let best = list[0]
  let bd = Infinity
  for (const c of list) {
    const m = doorMid(c.door)
    const d = Math.hypot(m[0] - fx, m[1] - fy)
    if (d < bd) {
      bd = d
      best = c
    }
  }
  return best.door.id
}

export function makeVariant(base: Scenario, doorId: string, state: DoorState = 'propped', sprinklers = false): Scenario {
  const v = JSON.parse(JSON.stringify(base)) as Scenario
  v.id = `${base.id ?? 'run'}-${state}-${doorId}${sprinklers ? '-sprinklers' : ''}`
  v.doors = { ...(base.doors ?? {}), [doorId]: state }
  if (sprinklers) v.sprinklers = true
  return v
}

export interface Compare {
  dT90: number | null
  dT100: number | null
  dTrapped: number
  t90: [number | null, number | null]
}

/** Differences b − a; a delta is null when either side never reached the mark. */
export function compareRuns(a: Run, b: Run): Compare {
  const d = (x: number | null, y: number | null) => (x == null || y == null ? null : y - x)
  return {
    dT90: d(a.metrics.t90, b.metrics.t90),
    dT100: d(a.metrics.t100, b.metrics.t100),
    dTrapped: b.metrics.trapped - a.metrics.trapped,
    t90: [a.metrics.t90, b.metrics.t90],
  }
}

/**
 * Precomputed door what-if for the same building and fire room; `door` is the key whose state differs. Only `whatIf: 'propped'`
 * entries count: a material entry (the wood run) is the same fire at another material, never a door what-if.
 */
export function findPrecomputedVariant(
  entries: DemoRun[],
  baseline: { buildingId: string; room?: string; doors: Record<string, DoorState> },
): { entry: DemoRun; door: string; state: DoorState } | null {
  for (const e of entries) {
    if (e.whatIf !== 'propped' || e.buildingId !== baseline.buildingId) continue
    if (baseline.room && e.fire.room !== baseline.room) continue
    const keys = new Set([...Object.keys(e.doors), ...Object.keys(baseline.doors)])
    for (const k of keys) {
      const s = e.doors[k]
      if (s !== undefined && s !== baseline.doors[k]) return { entry: e, door: k, state: s }
    }
    return { entry: e, door: '?', state: 'propped' }
  }
  return null
}
