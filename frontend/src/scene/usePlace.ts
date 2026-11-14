import { useCallback } from 'react'
import { useApp } from '../store/app'
import type { BuildingFloor } from '../data/types'
import { floorPlace } from './geometry'
import type { Place } from './geometry'

/**
 * `place(floor)` gives where a floor sits now ({dx, y}), for the current view mode and floor gap; the hook re-renders its component
 * when the building, the mode or the gap changes. Code that runs every frame calls floorPlace with useApp.getState() instead.
 */
export function usePlace(): (f: BuildingFloor) => Place {
  const building = useApp((s) => s.building)
  const viewMode = useApp((s) => s.viewMode)
  const explode = useApp((s) => s.explode)
  return useCallback((f: BuildingFloor) => floorPlace(building, f, viewMode, explode), [building, viewMode, explode])
}
