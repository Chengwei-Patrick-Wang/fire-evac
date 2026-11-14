import { create } from 'zustand'
import type { Batch, Building, BuildingInfo, DoorState, Run, Scenario } from '../data/types'
import type { Mode } from '../data/loader'
import { buildRunIndex } from '../replay/runIndex'
import type { RunIndex } from '../replay/runIndex'
import { useClock } from './clock'
import { ApiError, listDemoRuns, loadDemoRun, pollRun, setMode as setLoaderMode, startRun } from '../data/loader'
import { nearestPrecomputedRun, normalizeMix } from '../model/scenarioDraft'

export interface LoadedRun {
  key: string
  label: string
  run: Run
  index: RunIndex
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
  compareKeys: string[]
  notice: string | null
  batch: Batch | null
  explode: number
  visibleFloors: string[] | null
  layers: Layers
  topView: number
  draft: Scenario | null
  placing: boolean
  running: string | null
  runError: string | null
  runNote: string | null
  setDraft: (d: Scenario | null) => void
  patchDraft: (p: Partial<Scenario>) => void
  setPlacing: (b: boolean) => void
  runScenario: (s: Scenario) => Promise<void>
  setMode: (m: Mode) => void
  setView: (v: View) => void
  setLoading: (s: string | null) => void
  setBuildings: (b: BuildingInfo[]) => void
  setBuilding: (b: Building) => void
  setNotice: (s: string | null) => void
  addRun: (r: Omit<LoadedRun, 'index'>) => void
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
  compareKeys: [],
  notice: null,
  batch: null,
  explode: 0,
  visibleFloors: null,
  layers: { rooms: true, labels: true, smoke: true, fire: true, heatmap: false, queues: true, risk: false },
  topView: 0,
  draft: null,
  placing: true,
  running: null,
  runError: null,
  runNote: null,
  setDraft: (draft) => set({ draft }),
  patchDraft: (p) => set((s) => (s.draft ? { draft: { ...s.draft, ...p } } : {})),
  setPlacing: (placing) => set({ placing }),
  runScenario: async (scenario) => {
    const st = useApp.getState()
    const b = st.building
    if (!b || st.running) return
    set({ running: 'Running…', runError: null, runNote: null })
    const sc: Scenario = { ...scenario, buildingId: b.id, occupants: { ...scenario.occupants, mix: normalizeMix(scenario.occupants.mix) } }
    const loadNearest = async () => {
      const entries = await listDemoRuns(b.id)
      const hit = nearestPrecomputedRun(entries, sc.fire)
      if (!hit) throw new ApiError('No precomputed run for this building')
      const { entry, distance } = hit
      if (!useApp.getState().runs[entry.id]) {
        const run = await loadDemoRun(entry)
        useApp.getState().addRun({ key: entry.id, label: entry.label, run, doors: entry.doors ?? {} })
      } else useApp.getState().switchRun(entry.id)
      const here = sc.fire.x !== undefined ? `, ${distance.toFixed(1)} m from your click` : ''
      set({ runNote: `Static mode: nearest precomputed run, fire in ${entry.fire.room}${here}` })
    }
    try {
      if (useApp.getState().mode === 'live') {
        try {
          const id = 'ui-' + Date.now().toString(36)
          sc.id = id
          const runId = await startRun(sc)
          const run = await pollRun(runId, (el) => set({ running: `Running… ${el} s` }))
          useApp.getState().addRun({ key: id, label: `Your run ${id.slice(3, 7)}`, run, doors: sc.doors ?? {}, scenario: sc })
          return
        } catch (e) {
          const unreachable = e instanceof ApiError && /Could not reach|Timed out/.test(e.message)
          if (!unreachable) throw e
          setLoaderMode('static')
          set({ mode: 'static', notice: 'Backend unreachable: precomputed runs only' })
        }
      }
      await loadNearest()
    } catch (e) {
      set({ runError: e instanceof Error ? e.message : String(e) })
    } finally {
      set({ running: null })
    }
  },
  setMode: (mode) => set({ mode }),
  setView: (view) => set({ view }),
  setLoading: (loading) => set({ loading }),
  setBuildings: (buildings) => set({ buildings }),
  // A different building invalidates the loaded runs.
  setBuilding: (building) => set({ building, draft: null, runNote: null, runError: null, visibleFloors: null, runs: {}, runOrder: [], activeRunKey: null, compareKeys: [] }),
  setNotice: (notice) => set({ notice }),
  addRun: (r) =>
    set((s) => {
      const index = buildRunIndex(r.run)
      r.run.frames = [] // free the parsed frames; the typed arrays hold them now
      useClock.setState({ duration: index.duration, t: 0, playing: false })
      return {
        runs: { ...s.runs, [r.key]: { ...r, index } },
        runOrder: s.runOrder.includes(r.key) ? s.runOrder : [...s.runOrder, r.key],
        activeRunKey: r.key,
        compareKeys: s.compareKeys.includes(r.key) ? s.compareKeys : [...s.compareKeys, r.key],
      }
    }),
  switchRun: (key) =>
    set((s) => {
      const lr = s.runs[key]
      if (!lr) return {}
      useClock.getState().setDuration(lr.index.duration)
      return { activeRunKey: key }
    }),
}))

if (import.meta.env.DEV) (window as unknown as { __app: typeof useApp }).__app = useApp
