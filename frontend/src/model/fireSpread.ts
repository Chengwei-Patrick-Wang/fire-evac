import type { DemoRun, FireRoom, Material, Run } from '../data/types'

export type { Material }

/**
 * The building materials the scenario card offers. They set how fast the fire jumps from room to room (fire/spread.py): illustrative
 * speeds that rank the materials, never engineering values.
 */
export const MATERIALS: { id: Material; label: string }[] = [
  { id: 'concrete', label: 'Concrete' },
  { id: 'drywall', label: 'Drywall' },
  { id: 'wood', label: 'Wood' },
]
/** What a scenario without `fire.material` spreads at. */
export const DEFAULT_MATERIAL: Material = 'drywall'

const isMaterial = (v: unknown): v is Material => MATERIALS.some((m) => m.id === v)

/** The material a run was made at: its `fire.material`, else drywall (what a run from before the material setting spread at). */
export function runMaterial(run: Run): Material {
  const m: unknown = run.fire.material
  return isMaterial(m) ? m : DEFAULT_MATERIAL
}

/** "Wood", "Drywall" or "Concrete". */
export function materialName(m: Material): string {
  return MATERIALS.find((x) => x.id === m)?.label ?? m
}

/** "Wood instead of drywall": a material what-if in words (the headline of the material pair and the tour's caption). */
export function materialWords(to: Material, from: Material = DEFAULT_MATERIAL): string {
  return `${materialName(to)} instead of ${materialName(from).toLowerCase()}`
}

export interface Spread {
  /** the rooms that catch fire, sorted by `ignite` (the first is the ignition room) */
  rooms: FireRoom[]
  /** null when the run does not name one of the three materials */
  material: Material | null
}

const isRoom = (e: unknown): e is FireRoom => {
  const r = e as Partial<FireRoom> | null
  return !!r && typeof r.room === 'string' && typeof r.floor === 'string' && typeof r.ignite === 'number' && Number.isFinite(r.ignite) && r.ignite >= 0
}

/**
 * The room-to-room spread a run carries in `fire.rooms`, or null when it has none (a run made before the spread model, an older
 * backend). Entries that are not {room, floor, ignite ≥ 0} are dropped; nothing is ever filled in for a room the run does not list.
 */
export function readSpread(run: Run | null | undefined): Spread | null {
  const raw = (run?.fire as { rooms?: unknown } | undefined)?.rooms
  if (!Array.isArray(raw)) return null
  const rooms = raw.filter(isRoom).map((e) => ({ room: e.room, floor: e.floor, ignite: e.ignite }))
  if (rooms.length === 0) return null
  rooms.sort((a, b) => a.ignite - b.ignite)
  const material: unknown = run?.fire.material
  return { rooms, material: isMaterial(material) ? material : null }
}

/** The rooms on fire at time t (s): those with `ignite <= t`. */
export function burningAt(spread: Spread, t: number): FireRoom[] {
  return spread.rooms.filter((r) => r.ignite <= t)
}

/** A burning room goes from orange to red over this many seconds after it ignites. */
export const TINT_SECONDS = 60
const FROM: [number, number, number] = [0xf9, 0x73, 0x16] // #F97316
const TO: [number, number, number] = [0xdc, 0x26, 0x26] // #DC2626

export interface Tint {
  /** progress from ignition, 0 to 1 */
  k: number
  /** sRGB, 0 to 255 */
  r: number
  g: number
  b: number
  opacity: number
}

/**
 * How a burning room is painted `t - ignite` seconds after it ignites: #F97316 turning to #DC2626 over the first 60 s, and an
 * opacity of min(0.85, (0.35 + 0.25 k) × (0.5 + 0.5 × glow)). The glow is the visibility setting (0 to 2), a picture setting only.
 */
export function spreadTint(ignite: number, t: number, glow: number): Tint {
  const k = Math.min(1, Math.max(0, (t - ignite) / TINT_SECONDS))
  return {
    k,
    r: FROM[0] + (TO[0] - FROM[0]) * k,
    g: FROM[1] + (TO[1] - FROM[1]) * k,
    b: FROM[2] + (TO[2] - FROM[2]) * k,
    opacity: Math.min(0.85, (0.35 + 0.25 * k) * (0.5 + 0.5 * glow)),
  }
}

export interface MaterialPair {
  wood: DemoRun
  drywall: DemoRun
}

/**
 * The drywall run to set a material run against: the same building and fire room with `material: 'drywall'` (a material run or a
 * baseline). Failing that, that fire's own baseline (`whatIf: null`), as long as it isn't of the same material.
 */
export function materialPartner(entries: DemoRun[], run: DemoRun): DemoRun | null {
  const same = entries.filter((e) => e.id !== run.id && e.buildingId === run.buildingId && e.fire.floor === run.fire.floor && e.fire.room === run.fire.room)
  return (
    same.find((e) => e.material === 'drywall' && (e.whatIf === 'material' || e.whatIf === null)) ??
    same.find((e) => e.whatIf === null && e.material !== run.material) ??
    null
  )
}

/**
 * The precomputed wood-against-drywall pair of a building: the wood run is an entry with `whatIf: 'material'` and `material: 'wood'`.
 * Null when the building has no wood entry or no drywall partner for it (today's index has neither).
 */
export function materialPair(entries: DemoRun[], buildingId: string): MaterialPair | null {
  for (const wood of entries) {
    if (wood.buildingId !== buildingId || wood.whatIf !== 'material' || wood.material !== 'wood') continue
    const drywall = materialPartner(entries, wood)
    if (drywall) return { wood, drywall }
  }
  return null
}
