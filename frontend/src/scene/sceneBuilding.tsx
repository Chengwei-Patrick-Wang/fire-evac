import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'
import { useApp } from '../store/app'
import type { Building } from '../data/types'

/**
 * The building a pane draws when it is not the loaded one (the split view's right pane on another building). It is provided inside each
 * Canvas (a context from outside would not reach the scene), and every scene component reads its building through useSceneBuilding.
 */
const SceneBuildingContext = createContext<Building | null>(null)

export function SceneBuildingProvider({ building, children }: { building: Building | null; children: ReactNode }) {
  return <SceneBuildingContext.Provider value={building}>{children}</SceneBuildingContext.Provider>
}

/** The pane's own building, else the loaded building. */
export function useSceneBuilding(): Building | null {
  const own = useContext(SceneBuildingContext)
  const loaded = useApp((s) => s.building)
  return own ?? loaded
}
