import type { Building, BuildingFloor } from '../data/types'

/** Floors from the lowest level up. */
export function floorsByLevel(b: Building): BuildingFloor[] {
  return [...b.floors].sort((a, c) => a.level - c.level)
}

/** "Floor 1", "Floor 2"... by level (the lowest floor is Floor 1), never the raw id. */
export function floorName(b: Building, id: string): string {
  const i = floorsByLevel(b).findIndex((f) => f.id === id)
  return i < 0 ? 'Floor' : `Floor ${i + 1}`
}
