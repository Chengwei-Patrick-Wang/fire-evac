import type { BuildingSummary } from '../model/buildingIndex'
import { create } from 'zustand'
import type { Batch, Building, BuildingInfo, DoorState, Run, Scenario, Vec2 } from '../data/types'
import type { Mode } from '../data/loader'
import { buildRunIndex } from '../replay/runIndex'
import type { RunIndex } from '../replay/runIndex'
import { useClock } from './clock'
import { ApiError, listDemoRuns, loadDemoRun, pollRun, setMode as setLoaderMode, startBatch, startRun } from '../data/loader'
import { nearestPrecomputedRun, normalizeMix } from '../model/scenarioDraft'
import { spotPosition } from '../model/spots'
import type { HeadlinePack } from '../model/headlines'
import { findPrecomputedVariant, makeVariant } from '../model/whatif'

/** Room labels start on only for small buildings (up to 40 rooms over all floors). */
export function labelsFor(building: Building): boolean {
  return building.floors.reduce((n, f) => n + f.rooms.length, 0) <= 40
}

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
export type ResultsTab = 'results' | 'risk' | 'report' | 'cred'
/** The floating card open over the viewer, if any (one at a time). */
export type Card = 'scenario' | 'layers' | null

/** Phones (900 px and under) start with the analytics sidebar collapsed, so it doesn't cover the 3D view. */
const phoneAtStart = () => typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(max-width: 900px)').matches

export interface Layers {
  rooms: boolean
  labels: boolean
  smoke: boolean
  fire: boolean
  heatmap: boolean
  queues: boolean
  risk: boolean
}

export interface Focus {
  floorId: string
  pos: Vec2
  nonce: number
}

interface AppState {
  summaries: Record<string, BuildingSummary>
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
  headlines: HeadlinePack | null
  explode: number
  reveal: number
  visibleFloors: string[] | null
  layers: Layers
  topView: number
  split: boolean
  draft: Scenario | null
  placing: boolean
  running: string | null
  runError: string | null
  runNote: string | null
  /** True when runNote explains a precomputed run shown because the live run failed (the panel then shows it as a warning). */
  runFallback: boolean
  riskMetric: 'riskT90' | 'riskTrapped'
  crowding: boolean
  lens: boolean[]
  trails: boolean
  agentColor: 'status' | 'profile'
  follow: number | null
  pickAgent: boolean
  setFollow: (i: number | null) => void
  selectedRoom: string | null
  focus: Focus | null
  batchRunning: string | null
  batchError: string | null
  fromTracer: string | null
  pendingCam: number[] | null
  report: { key: string; md: string } | null
  printView: boolean
  setPrintView: (b: boolean) => void
  share: boolean
  setShare: (b: boolean) => void
  about: boolean
  setAbout: (b: boolean) => void
  resultsTab: ResultsTab
  setResultsTab: (t: ResultsTab) => void
  /** The top navigation (menus and toolbar) is a drawer: collapsed by default. */
  navOpen: boolean
  setNavOpen: (b: boolean) => void
  /** The analytics sidebar: open by default, collapsed on phones. */
  sidebarOpen: boolean
  setSidebarOpen: (b: boolean) => void
  card: Card
  setCard: (c: Card) => void
  activeSpot: string | null
  fitView: number
  autoRotate: boolean
  flyTo: (floorId: string, pos: Vec2) => void
  goToSpot: (id: string, floor: string) => boolean
  runBatch: () => Promise<void>
  setDraft: (d: Scenario | null) => void
  patchDraft: (p: Partial<Scenario>) => void
  setPlacing: (b: boolean) => void
  runScenario: (s: Scenario) => Promise<void>
  runWhatIf: (door: string, state: DoorState, sprinklers: boolean) => Promise<void>
  whatIfBusy: string | null
  whatIfError: string | null
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
  summaries: {},
  building: null,
  runs: {},
  runOrder: [],
  activeRunKey: null,
  compareKeys: [],
  notice: null,
  batch: null,
  headlines: null,
  explode: 0,
  reveal: 0,
  visibleFloors: null,
  layers: { rooms: true, labels: true, smoke: true, fire: true, heatmap: false, queues: true, risk: false },
  topView: 0,
  split: false,
  draft: null,
  placing: true,
  running: null,
  runError: null,
  whatIfBusy: null,
  whatIfError: null,
  runNote: null,
  runFallback: false,
  fromTracer: null,
  riskMetric: 'riskT90',
  crowding: false,
  lens: [true, true, true, true, true, true],
  trails: false,
  agentColor: 'status',
  follow: null,
  pickAgent: false,
  setFollow: (follow) => set({ follow, pickAgent: false }),
  selectedRoom: null,
  focus: null,
  batchRunning: null,
  batchError: null,
  pendingCam: null,
  report: null,
  printView: false,
  setPrintView: (printView) => set({ printView }),
  share: false,
  setShare: (share) => set({ share }),
  about: false,
  setAbout: (about) => set({ about }),
  resultsTab: 'results',
  setResultsTab: (resultsTab) => set({ resultsTab }),
  navOpen: false,
  setNavOpen: (navOpen) => set({ navOpen }),
  sidebarOpen: !phoneAtStart(),
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  card: null,
  setCard: (card) => set({ card }),
  activeSpot: null,
  fitView: 0,
  autoRotate: false,
  flyTo: (floorId, pos) => set((s) => ({ visibleFloors: [floorId], focus: { floorId, pos, nonce: (s.focus?.nonce ?? 0) + 1 } })),
  goToSpot: (id, floor) => {
    const b = useApp.getState().building
    const p = b ? spotPosition(b, { id, floor }) : null
    if (!p) {
      console.warn(`spot ${id} not found in ${b?.id ?? 'no building'}`)
      set({ notice: `Unknown spot ${id}` })
      return false
    }
    set({ notice: null, activeSpot: id })
    useApp.getState().flyTo(p.floorId, p.pos)
    return true
  },
  runBatch: async () => {
    const st = useApp.getState()
    const b = st.building
    if (!b || !st.draft || st.batchRunning) return
    set({ batchRunning: 'Running batch…', batchError: null })
    try {
      const base: Scenario = { ...st.draft, buildingId: b.id, occupants: { ...st.draft.occupants, mix: normalizeMix(st.draft.occupants.mix) } }
      const batch = await startBatch(base, (el) => set({ batchRunning: `Running batch… ${el} s` }))
      if (batch.buildingId !== b.id) throw new ApiError(`Batch is for building ${batch.buildingId}, not ${b.id}`)
      set({ batch })
    } catch (e) {
      set({ batchError: e instanceof Error ? e.message : String(e) })
    } finally {
      set({ batchRunning: null })
    }
  },
  setDraft: (draft) => set({ draft }),
  patchDraft: (p) => set((s) => (s.draft ? { draft: { ...s.draft, ...p } } : {})),
  setPlacing: (placing) => set({ placing }),
  runScenario: async (scenario) => {
    const st = useApp.getState()
    const b = st.building
    if (!b || st.running) return
    set({ running: 'Running…', runError: null, runNote: null, runFallback: false })
    const sc: Scenario = { ...scenario, buildingId: b.id, occupants: { ...scenario.occupants, mix: normalizeMix(scenario.occupants.mix) } }
    // The precomputed run nearest this fire (static mode's rule), loaded, made active and explained in runNote. False when the building
    // has none, or when it is no longer the loaded building (a late fallback must not add its run to another one).
    const showNearest = async (afterLiveFailure: boolean): Promise<boolean> => {
      const hit = nearestPrecomputedRun(await listDemoRuns(b.id), sc.fire)
      if (!hit || useApp.getState().building?.id !== b.id) return false
      const { entry, distance } = hit
      if (!useApp.getState().runs[entry.id]) {
        const run = await loadDemoRun(entry)
        if (useApp.getState().building?.id !== b.id) return false
        useApp.getState().addRun({ key: entry.id, label: entry.label, run, doors: entry.doors ?? {} })
      } else useApp.getState().switchRun(entry.id)
      const here = sc.fire.x !== undefined ? `, ${distance.toFixed(1)} m from your click` : ''
      set({
        runFallback: afterLiveFailure,
        runNote: afterLiveFailure
          ? `Live run unavailable: showing the nearest precomputed fire (room ${entry.fire.room}).`
          : `Static mode: nearest precomputed run, fire in ${entry.fire.room}${here}`,
      })
      return true
    }
    // Set when the live run failed, and whether the backend could not be reached at all (which also ends live mode).
    let failure: Error | null = null
    let unreachable = false
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
          // Spec §8 beat 3: the judge's fire "runs live, or loads the nearest precomputed run". Whatever went wrong (no backend, an HTTP
          // error, a run that failed, one that outlasted pollRun's wait), the screen gets the precomputed run below.
          failure = e instanceof Error ? e : new Error(String(e))
          unreachable = e instanceof ApiError && /Could not reach|Timed out/.test(e.message)
          console.warn(`live run failed, showing the nearest precomputed run instead: ${failure.message}`)
          if (unreachable) {
            setLoaderMode('static')
            set({ mode: 'static', notice: 'Backend unreachable: precomputed runs only' })
          }
          set({ running: 'Loading precomputed run…' })
        }
      }
      // With no precomputed run for this building the error is today's: the live failure itself, or after a connection failure "No precomputed run".
      if (!(await showNearest(failure !== null))) throw failure && !unreachable ? failure : new ApiError('No precomputed run for this building')
    } catch (e) {
      set({ runError: e instanceof Error ? e.message : String(e) })
    } finally {
      set({ running: null })
    }
  },
  runWhatIf: async (door, state, sprinklers) => {
    const st = useApp.getState()
    const b = st.building
    const active = st.activeRunKey ? st.runs[st.activeRunKey] : null
    if (!b || !active || st.whatIfBusy) return
    const base = active.whatIf ? st.runs[active.whatIf.baselineKey] ?? active : active
    set({ whatIfBusy: 'Running…', whatIfError: null })
    try {
      if (useApp.getState().mode === 'live') {
        try {
          const f = base.run.fire
          const room = st.draft?.fire.room
          const baseSc: Scenario = base.scenario ?? {
            ...(st.draft ?? makeDraftFallback(b.id)),
            id: base.key,
            seed: base.run.seed,
            fire: { ...(st.draft?.fire ?? { type: 'kitchen', start: 0 }), floor: f.floor, x: f.x, y: f.y, room: st.draft?.fire.room ?? room },
            doors: base.doors,
          }
          const sc = makeVariant({ ...baseSc, buildingId: b.id, occupants: { ...baseSc.occupants, mix: normalizeMix(baseSc.occupants.mix) } }, door, state, sprinklers)
          const runId = await startRun(sc)
          const run = await pollRun(runId, (el) => set({ whatIfBusy: `Running… ${el} s` }))
          const key = sc.id as string
          const prev = useClock.getState().t
          useApp.getState().addRun({ key, label: `What-if: ${door} ${state}${sprinklers ? ' +sprinklers' : ''}`, run, doors: sc.doors ?? {}, scenario: sc, whatIf: { baselineKey: base.key, door, state } })
          useClock.getState().seek(prev)
          return
        } catch (e) {
          const unreachable = e instanceof ApiError && /Could not reach|Timed out/.test(e.message)
          if (!unreachable) throw e
          setLoaderMode('static')
          set({ mode: 'static', notice: 'Backend unreachable: precomputed runs only' })
        }
      }
      const entries = await listDemoRuns(b.id)
      const hit = findPrecomputedVariant(entries, { buildingId: b.id, room: entries.find((e) => e.id === base.key)?.fire.room ?? st.draft?.fire.room, doors: base.doors })
      if (!hit) throw new ApiError('No precomputed what-if for this fire')
      const { entry } = hit
      if (useApp.getState().runs[entry.id]) useApp.getState().switchRun(entry.id)
      else {
        const prev = useClock.getState().t
        const run = await loadDemoRun(entry)
        useApp.getState().addRun({ key: entry.id, label: entry.label, run, doors: entry.doors ?? {}, whatIf: { baselineKey: base.key, door: hit.door, state: hit.state } })
        useClock.getState().seek(prev)
      }
    } catch (e) {
      set({ whatIfError: e instanceof Error ? e.message : String(e) })
    } finally {
      set({ whatIfBusy: null })
    }
  },
  setMode: (mode) => set({ mode }),
  setView: (view) => set({ view }),
  setLoading: (loading) => set({ loading }),
  setBuildings: (buildings) => set({ buildings }),
  // A different building invalidates the loaded runs.
  setBuilding: (building) => set((s) => ({ reveal: s.reveal + 1, building, headlines: null, layers: { ...s.layers, labels: labelsFor(building) }, draft: null, fromTracer: null, runNote: null, runFallback: false, runError: null, visibleFloors: null, focus: null, follow: null, pickAgent: false, selectedRoom: null, activeSpot: null, runs: {}, runOrder: [], activeRunKey: null, compareKeys: [] })),
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

function makeDraftFallback(buildingId: string): Scenario {
  return { version: 'scenario/v0', buildingId, seed: 1, occupants: { total: 160, mix: { typical: 1 } }, fire: { type: 'kitchen', start: 0 }, sprinklers: false, doors: {}, alarmTime: 30, maxTime: 400 }
}

if (import.meta.env.DEV) (window as unknown as { __app: typeof useApp }).__app = useApp
