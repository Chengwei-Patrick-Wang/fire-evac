import { create } from 'zustand'
import type { Building, BuildingInfo, DoorState, Run, Scenario } from '../data/types'
import type { Mode } from '../data/loader'

export interface LoadedRun {
  key: string
  label: string
  run: Run
  doors: Record<string, DoorState>
  scenario?: Scenario
  whatIf?: { baselineKey: string; door: string; state: DoorState }
}

export type View = 'replay' | 'tracer'

export interface Layers {
  rooms: boolean
  labels: boolean
  smoke: boolean
  fire: boolean
  heatmap: boolean
  queues: boolean
  risk: boolean
}

interface AppState {
  mode: Mode
  view: View
  loading: string | null
  buildings: BuildingInfo[]
  building: Building | null
  runs: Record<string, LoadedRun>
  runOrder: string[]
  activeRunKey: string | null
  notice: string | null
  explode: number
  visibleFloors: string[] | null
  layers: Layers
  topView: number
  setMode: (m: Mode) => void
  setView: (v: View) => void
  setLoading: (s: string | null) => void
  setBuildings: (b: BuildingInfo[]) => void
  setBuilding: (b: Building) => void
  setNotice: (s: string | null) => void
  addRun: (r: LoadedRun) => void
  switchRun: (key: string) => void
}

export const useApp = create<AppState>((set) => ({
  mode: 'static',
  view: 'replay',
  loading: null,
  buildings: [],
  building: null,
  runs: {},
  runOrder: [],
  activeRunKey: null,
  notice: null,
  explode: 0,
  visibleFloors: null,
  layers: { rooms: true, labels: true, smoke: true, fire: true, heatmap: false, queues: true, risk: false },
  topView: 0,
  setMode: (mode) => set({ mode }),
  setView: (view) => set({ view }),
  setLoading: (loading) => set({ loading }),
  setBuildings: (buildings) => set({ buildings }),
  // A different building invalidates the loaded runs.
  setBuilding: (building) => set({ building, visibleFloors: null, runs: {}, runOrder: [], activeRunKey: null }),
  setNotice: (notice) => set({ notice }),
  addRun: (r) =>
    set((s) => ({
      runs: { ...s.runs, [r.key]: r },
      runOrder: s.runOrder.includes(r.key) ? s.runOrder : [...s.runOrder, r.key],
      activeRunKey: r.key,
    })),
  switchRun: (key) => set((s) => (s.runs[key] ? { activeRunKey: key } : {})),
}))

if (import.meta.env.DEV) (window as unknown as { __app: typeof useApp }).__app = useApp
