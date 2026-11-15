import type { BuildingSummary } from '../model/buildingIndex'
import { create } from 'zustand'
import type { Batch, Building, BuildingInfo, DemoRun, DoorState, Material, Run, Scenario, Vec2 } from '../data/types'
import type { Mode } from '../data/loader'
import { buildRunIndex } from '../replay/runIndex'
import type { RunIndex } from '../replay/runIndex'
import { useClock } from './clock'
import { ApiError, listDemoRuns, loadBatch, loadBuilding, loadDemoRun, pollRun, setMode as setLoaderMode, startBatch, startRun } from '../data/loader'
import { defaultFire, makeDraft, nearestPrecomputedRun, normalizeMix } from '../model/scenarioDraft'
import { spotPosition } from '../model/spots'
import type { HeadlinePack } from '../model/headlines'
import { DEFAULT_MATERIAL, materialName, materialPair } from '../model/fireSpread'
import { brainPair, claudeCrowdLimit, crowdOf, crowdTooBig, runLabel, runStatus, runWaitS } from '../model/brain'
import type { Brain } from '../model/brain'
import { floorsByLevel } from '../model/floors'
import type { ViewMode } from '../scene/geometry'

/** The floor gap a fresh page starts with: with opaque slabs, no gap would hide the lower floors. */
export const DEFAULT_EXPLODE = 0.6

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
  /**
   * The run this one is a variant of: a material variant (the precomputed wood run) has `material`, a crowd variant (the precomputed
   * Claude crowd) has `brain`. Neither has a door: `door` is '' and `state` a placeholder (the field stays for the run/v0 pairs).
   */
  whatIf?: { baselineKey: string; door: string; state: DoorState; material?: Material; brain?: Brain }
}

export type View = 'replay' | 'tracer'
export type ResultsTab = 'results' | 'risk' | 'report'
/** The floating card open over the viewer, if any (one at a time). */
export type Card = 'scenario' | 'layers' | 'visibility' | null
/** The two panes of the split view. */
export type Side = 'L' | 'R'

/** The run each pane of the split view shows: a side's own pick, else the left is the baseline of the active run and the right is the active run. */
export function splitKeys(s: Pick<AppState, 'runs' | 'runOrder' | 'activeRunKey' | 'splitLeft' | 'splitRight'>): { left: string | null; right: string | null } {
  const active = s.activeRunKey
  const right = s.splitRight && s.runs[s.splitRight] ? s.splitRight : active
  const base = active ? s.runs[active]?.whatIf?.baselineKey ?? s.runOrder.find((k) => k !== active) : undefined
  const derived = right === active ? base : active
  const left = s.splitLeft && s.runs[s.splitLeft] && s.splitLeft !== right ? s.splitLeft : derived
  return { left: left ?? null, right: right ?? null }
}

/** The scenario a side edits: the left is the loaded building's, the right has its own once it is edited (until then it starts from the left's). */
export function sideDraft(s: Pick<AppState, 'draft' | 'rightDraft'>, side: Side | null | undefined): Scenario | null {
  return side === 'R' ? s.rightDraft ?? s.draft : s.draft
}

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
  /** The floors every layer draws (null: all). Written only by setViewMode and flyTo. */
  visibleFloors: string[] | null
  /** Stacked (all floors, a gap apart), single (one floor alone), side (all in a row on the ground) or ghost (all, one solid). */
  viewMode: ViewMode
  /** The floor that single and ghost centre on; null in stacked and side. */
  focusFloor: string | null
  /** Switches the floor view. Single and ghost take `floor`, else the current focus floor, else the run's fire floor, else the lowest. Clears the camera focus; `fit` (default true) also re-frames the camera. */
  setViewMode: (mode: ViewMode, floor?: string, fit?: boolean) => void
  /** How big and bright the fire is drawn, 0 to 2 (a picture setting; the simulation never changes). */
  fireGlow: number
  /** How dense the smoke is drawn, 0 to 1.5. */
  smokeOpacity: number
  layers: Layers
  topView: number
  split: boolean
  /** The split view's own pick of what each pane shows (null: derived from the active run, see splitKeys). */
  splitLeft: string | null
  splitRight: string | null
  /** The building the right pane draws when it is not the loaded one. Its run is kept out of `runOrder`, so the analytics stay on the loaded building. */
  rightBuilding: Building | null
  /** The right side's scenario (null until edited: it starts from the left's) and building material; the left side's are `draft` and `material`. */
  rightDraft: Scenario | null
  rightMaterial: Material
  setRightMaterial: (m: Material) => void
  patchRightDraft: (p: Partial<Scenario>) => void
  /** The pane the Fire and scenario card edits while the view is split (null: the left). */
  editSide: Side | null
  editSideOpen: (side: Side) => void
  /** Puts the right pane on another building, with that building's first precomputed run (the loaded building's id puts it back on it). */
  setRightBuilding: (id: string) => Promise<void>
  /** Shows one precomputed run on a side (loading it first). */
  pickSideRun: (side: Side, entry: DemoRun) => Promise<void>
  /** Runs a side's scenario: live runs it on the side's building, static shows the nearest precomputed run of it. */
  runSide: (side: Side) => Promise<void>
  /** Adds a run kept out of the loaded building's run list and shows it on a side; `building` (the right side's) is set with it. */
  addSideRun: (r: Omit<LoadedRun, 'index'>, side: Side, building?: Building) => void
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
  /** People are coloured by what they are doing (status) or by their mobility profile (type). */
  colorBy: 'status' | 'type'
  selectedRoom: string | null
  focus: Focus | null
  batchRunning: string | null
  batchError: string | null
  fromTracer: string | null
  pendingCam: number[] | null
  report: { key: string; md: string } | null
  printView: boolean
  setPrintView: (b: boolean) => void
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
  /** The sidebar grown toward the middle of the screen (desktop; a phone's sidebar is an overlay at full width anyway). Kept for the page's life only. */
  sidebarWide: boolean
  setSidebarWide: (b: boolean) => void
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
  runScenario: (s: Scenario, opts?: { side?: Side; building?: Building }) => Promise<void>
  /** Set while a comparison's two precomputed runs load (showMaterialPair, showBrainPair), and the error when they do not. */
  pairBusy: string | null
  pairError: string | null
  /** The building material the next live run spreads fire at (illustrative); kept across buildings. */
  material: Material
  setMaterial: (m: Material) => void
  /** Loads the precomputed wood and drywall runs of the loaded building and shows them side by side, at the clock time they were at. */
  showMaterialPair: () => Promise<void>
  /** The same for the precomputed rules run and Claude crowd run of the loaded building. */
  showBrainPair: () => Promise<void>
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
  explode: DEFAULT_EXPLODE,
  reveal: 0,
  visibleFloors: null,
  viewMode: 'stacked',
  focusFloor: null,
  setViewMode: (mode, floor, fit = true) =>
    set((s) => {
      const ids = s.building ? floorsByLevel(s.building).map((f) => f.id) : []
      const fireFloor = s.activeRunKey ? s.runs[s.activeRunKey]?.run.fire.floor : undefined
      const known = (id: string | null | undefined): id is string => !!id && ids.includes(id)
      const pick = [floor, s.focusFloor, fireFloor, ids[0]].find(known) ?? null
      const needsFloor = mode === 'single' || mode === 'ghost'
      // Single and ghost centre on a floor; with none to pick (no building yet) they fall back to stacked.
      const m: ViewMode = needsFloor && pick === null ? 'stacked' : mode
      const focusFloor = needsFloor ? pick : null
      return {
        viewMode: m,
        focusFloor: m === 'stacked' ? null : focusFloor,
        visibleFloors: m === 'single' && focusFloor ? [focusFloor] : null,
        focus: null,
        ...(fit ? { fitView: s.fitView + 1 } : {}),
      }
    }),
  fireGlow: 1,
  smokeOpacity: 1,
  layers: { rooms: false, labels: true, smoke: true, fire: true, heatmap: false, queues: true, risk: false },
  topView: 0,
  split: false,
  splitLeft: null,
  splitRight: null,
  rightBuilding: null,
  rightDraft: null,
  rightMaterial: DEFAULT_MATERIAL,
  setRightMaterial: (rightMaterial) => set({ rightMaterial }),
  patchRightDraft: (p) =>
    set((s) => {
      const d = s.rightDraft ?? s.draft
      return d ? { rightDraft: { ...(s.rightDraft ? d : (JSON.parse(JSON.stringify(d)) as Scenario)), ...p } } : {}
    }),
  editSide: null,
  editSideOpen: (editSide) => set({ editSide, card: 'scenario', placing: false }),
  draft: null,
  placing: false,
  running: null,
  runError: null,
  pairBusy: null,
  pairError: null,
  material: DEFAULT_MATERIAL,
  setMaterial: (material) => set({ material }),
  runNote: null,
  runFallback: false,
  fromTracer: null,
  // People trapped: it paints the worst fires red where the time to get 90% out spans a narrow range (and one outlier) and reads green.
  riskMetric: 'riskTrapped',
  crowding: false,
  lens: [true, true, true, true, true, true],
  trails: false,
  colorBy: 'status',
  selectedRoom: null,
  focus: null,
  batchRunning: null,
  batchError: null,
  pendingCam: null,
  report: null,
  printView: false,
  setPrintView: (printView) => set({ printView }),
  about: false,
  setAbout: (about) => set({ about }),
  resultsTab: 'results',
  setResultsTab: (resultsTab) => set({ resultsTab }),
  navOpen: false,
  setNavOpen: (navOpen) => set({ navOpen }),
  sidebarOpen: !phoneAtStart(),
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  sidebarWide: false,
  setSidebarWide: (sidebarWide) => set({ sidebarWide }),
  card: null,
  setCard: (card) => set({ card }),
  activeSpot: null,
  fitView: 0,
  autoRotate: false,
  flyTo: (floorId, pos) => set((s) => ({ viewMode: 'single', focusFloor: floorId, visibleFloors: [floorId], focus: { floorId, pos, nonce: (s.focus?.nonce ?? 0) + 1 } })),
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
  // A draft with no fire yet starts in placing mode: the first click on a room puts the fire there (the scenario card and the new-building card both say so).
  setDraft: (draft) => set(draft && !draft.fire.floor ? { draft, placing: true } : { draft }),
  patchDraft: (p) => set((s) => (s.draft ? { draft: { ...s.draft, ...p } } : {})),
  setPlacing: (placing) => set({ placing }),
  runScenario: async (scenario, opts) => {
    const st = useApp.getState()
    const side = opts?.side
    // The right pane can be on another building: its run is made on that one and kept out of the loaded building's runs. (`opts.building` is a
    // building the right pane is about to move to, with no saved run: it moves there when this first run lands.)
    const other = side === 'R' ? opts?.building ?? st.rightBuilding : null
    const adopting = !!opts?.building
    const b = other ?? st.building
    if (!b || st.running) return
    // Who decides for the crowd rides in the scenario's `brain`. Only a live run asks Claude: static mode shows a precomputed run of the rules.
    const brain = crowdOf(scenario.brain)
    const live = st.mode === 'live'
    const total = scenario.occupants.total
    // Everyone asks Claude holds up to 200 people. Refused here, before anything is sent (the Run buttons are off for it too).
    if (crowdTooBig(scenario, live)) {
      set({ runError: claudeCrowdLimit(total), runNote: null, runFallback: false })
      return
    }
    set({ running: live ? runStatus(brain, total) : 'Running…', runError: null, runNote: null, runFallback: false })
    // The material setting rides in the scenario's fire (illustrative spread speed); only the live backend reads it. Each side has its own.
    const material = side === 'R' ? st.rightMaterial : st.material
    const sc: Scenario = { ...scenario, buildingId: b.id, occupants: { ...scenario.occupants, mix: normalizeMix(scenario.occupants.mix) }, fire: { ...scenario.fire, material } }
    const before = splitKeys(st)
    /** The side's building is still the one this run was made for (a late answer must not land on another building). */
    const here = () => (adopting ? useApp.getState().building?.id === st.building?.id : other ? useApp.getState().rightBuilding?.id === b.id : useApp.getState().building?.id === b.id)
    /** Adds a run, or shows the one already loaded; on a side, that pane shows it and the other keeps what it showed. */
    const put = (r: Omit<LoadedRun, 'index'>) => {
      const app = useApp.getState()
      if (app.runs[r.key]) {
        if (!other) app.switchRun(r.key)
      } else if (other) app.addSideRun(r, 'R', adopting ? other : undefined)
      else app.addRun(r)
      if (side === 'L') useApp.setState({ splitLeft: r.key, splitRight: before.right })
      else if (side === 'R') useApp.setState({ splitRight: r.key, splitLeft: before.left })
    }
    // The precomputed run nearest this fire (static mode's rule), loaded, made active and explained in runNote. False when the building
    // has none, or when it is no longer the loaded building (a late fallback must not add its run to another one).
    const showNearest = async (afterLiveFailure: boolean): Promise<boolean> => {
      const hit = nearestPrecomputedRun(await listDemoRuns(b.id), sc.fire)
      if (!hit || !here()) return false
      const { entry, distance } = hit
      if (!useApp.getState().runs[entry.id]) {
        const run = await loadDemoRun(entry)
        if (!here()) return false
        put({ key: entry.id, label: entry.label, run, doors: entry.doors ?? {} })
      } else put({ key: entry.id, label: entry.label, run: useApp.getState().runs[entry.id].run, doors: entry.doors ?? {} })
      const place = sc.fire.x !== undefined ? `, ${distance.toFixed(1)} m from your click` : ''
      // Precomputed runs of the rules are what is shown: say so when the scenario asked for Claude.
      const crowd = brain === 'rules' ? '' : ' That run uses the rules crowd, not Claude.'
      set({
        runFallback: afterLiveFailure,
        runNote: afterLiveFailure
          ? `Live run unavailable: showing the nearest precomputed fire (room ${entry.fire.room}).${crowd}`
          : `Static mode: nearest precomputed run, fire in ${entry.fire.room}${place}${crowd}`,
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
          // A Claude crowd waits on a model for its decisions, so it is waited for longer (fifteen minutes against three).
          const run = await pollRun(runId, (el) => set({ running: runStatus(brain, total, el) }), runWaitS(brain))
          if (!here()) return
          const how = material === DEFAULT_MATERIAL ? '' : ` · ${materialName(material)}`
          const on = other ? ` · ${b.name}` : ''
          const lr: Omit<LoadedRun, 'index'> = { key: id, label: runLabel(`Your run ${id.slice(3, 7)}${on}${how}`, brain), run, doors: sc.doors ?? {}, scenario: sc }
          if (other) useApp.getState().addSideRun(lr, 'R', adopting ? other : undefined)
          else {
            useApp.getState().addRun(lr)
            if (side === 'L') useApp.setState({ splitLeft: id, splitRight: before.right })
            else if (side === 'R') useApp.setState({ splitRight: id, splitLeft: before.left })
          }
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
  runSide: async (side) => {
    const st = useApp.getState()
    const d = sideDraft(st, side)
    if (d) await st.runScenario(d, { side })
  },
  addSideRun: (r, side, building) =>
    set((s) => {
      const index = buildRunIndex(r.run)
      r.run.frames = [] // free the parsed frames; the typed arrays hold them now
      return { runs: { ...s.runs, [r.key]: { ...r, index } }, ...(side === 'R' ? { splitRight: r.key, ...(building ? { rightBuilding: building } : {}) } : { splitLeft: r.key }) }
    }),
  pickSideRun: async (side, entry) => {
    const st = useApp.getState()
    const other = side === 'R' ? st.rightBuilding : null
    const b = other ?? st.building
    if (!b || entry.buildingId !== b.id) return
    const before = splitKeys(st)
    const prevT = useClock.getState().t
    const prevActive = st.activeRunKey
    const here = () => (other ? useApp.getState().rightBuilding?.id === b.id : useApp.getState().building?.id === b.id)
    try {
      if (!useApp.getState().runs[entry.id]) {
        const run = await loadDemoRun(entry)
        if (!here()) return
        const lr = { key: entry.id, label: runLabel(entry.label, entry.brain), run, doors: entry.doors ?? {} }
        if (other) useApp.getState().addSideRun(lr, 'R')
        else useApp.getState().addRun(lr)
      }
      if (side === 'R') {
        useApp.setState({ splitRight: entry.id, splitLeft: before.left })
        if (!other) useApp.getState().switchRun(entry.id)
      } else {
        useApp.setState({ splitLeft: entry.id, splitRight: before.right, activeRunKey: prevActive ?? entry.id })
      }
      useClock.getState().seek(prevT)
    } catch (e) {
      useApp.setState({ runError: e instanceof Error ? e.message : String(e) })
    }
  },
  setRightBuilding: async (id) => {
    const st = useApp.getState()
    const left = st.building
    if (!left || st.pairBusy) return
    useApp.setState({ pairBusy: 'Loading building…', pairError: null })
    try {
      const before = splitKeys(st)
      if (id === left.id) {
        // Back on the loaded building: a precomputed run of it other than the left one.
        const entries = (await listDemoRuns(left.id)).filter((e) => e.whatIf !== 'propped' && e.id !== before.left)
        const entry = entries.find((e) => e.whatIf === null) ?? entries[0]
        if (!entry) throw new ApiError('No other precomputed run for this building')
        useApp.setState({ rightBuilding: null, rightDraft: null })
        await useApp.getState().pickSideRun('R', entry)
        return
      }
      const b = await loadBuilding(id)
      const entries = (await listDemoRuns(id)).filter((e) => e.whatIf !== 'propped')
      const entry = entries.find((e) => e.whatIf === null) ?? entries[0]
      if (!entry) {
        // No saved run for this building: static mode has nothing to show, live mode makes the first run now, from the building's own fire
        // (or the default one), and the right pane moves to the building when it lands.
        if (st.mode !== 'live') throw new ApiError(`${b.name} has no saved run yet. Live mode can run one.`)
        const batch = await loadBatch(id).catch(() => null)
        const draft = makeDraft(b, batch && batch.buildingId === id ? batch.base : null)
        if (!draft.fire.floor) draft.fire = defaultFire(b) ?? draft.fire
        useApp.setState({ rightDraft: draft, splitLeft: before.left, pairBusy: null })
        await useApp.getState().runScenario(draft, { side: 'R', building: b })
        return
      }
      const [run, batch] = await Promise.all([useApp.getState().runs[entry.id] ? null : loadDemoRun(entry), loadBatch(id).catch(() => null)])
      if (useApp.getState().building?.id !== left.id) return
      useApp.setState({ rightBuilding: b, rightDraft: makeDraft(b, batch && batch.buildingId === id ? batch.base : null) })
      if (run) useApp.getState().addSideRun({ key: entry.id, label: runLabel(entry.label, entry.brain), run, doors: entry.doors ?? {} }, 'R')
      else useApp.setState({ splitRight: entry.id })
      useApp.setState({ splitLeft: before.left })
    } catch (e) {
      useApp.setState({ pairError: e instanceof Error ? e.message : String(e) })
    } finally {
      useApp.setState({ pairBusy: null })
    }
  },
  showMaterialPair: () =>
    showPair('No precomputed wood and drywall pair for this building', (entries, id) => {
      const pair = materialPair(entries, id)
      return pair && { base: pair.drywall, variant: pair.wood, whatIf: { baselineKey: pair.drywall.id, door: '', state: 'propped', material: 'wood' } }
    }),
  showBrainPair: () =>
    showPair('No precomputed rules and Claude crowd pair for this building', (entries, id) => {
      const pair = brainPair(entries, id)
      return pair && { base: pair.rules, variant: pair.claude, whatIf: { baselineKey: pair.rules.id, door: '', state: 'propped', brain: 'llm' } }
    }),
  setMode: (mode) => set({ mode }),
  setView: (view) => set({ view }),
  setLoading: (loading) => set({ loading }),
  setBuildings: (buildings) => set({ buildings }),
  // A different building invalidates the loaded runs.
  setBuilding: (building) => set((s) => ({ reveal: s.reveal + 1, building, headlines: null, layers: { ...s.layers, labels: labelsFor(building) }, draft: null, placing: false, fromTracer: null, runNote: null, runFallback: false, runError: null, split: false, viewMode: 'stacked', focusFloor: null, visibleFloors: null, focus: null, selectedRoom: null, activeSpot: null, runs: {}, runOrder: [], activeRunKey: null, compareKeys: [], splitLeft: null, splitRight: null, rightBuilding: null, rightDraft: null, editSide: null })),
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

/**
 * Loads the two precomputed runs of a pair (a baseline and its variant: the same fire with another material, or another crowd) and shows
 * them side by side, at the clock time the page was at. `pick` finds the pair in the building's demo entries; null when it has none.
 */
async function showPair(
  missing: string,
  pick: (entries: DemoRun[], buildingId: string) => { base: DemoRun; variant: DemoRun; whatIf: NonNullable<LoadedRun['whatIf']> } | null,
): Promise<void> {
  const st = useApp.getState()
  const b = st.building
  if (!b || st.pairBusy) return
  useApp.setState({ pairBusy: 'Loading precomputed pair…', pairError: null })
  // Loads (once) and shows one precomputed run; false when another building was loaded meanwhile.
  const show = async (entry: DemoRun, whatIf?: LoadedRun['whatIf']): Promise<boolean> => {
    if (useApp.getState().runs[entry.id]) {
      if (whatIf && !useApp.getState().runs[entry.id].whatIf) useApp.setState((s) => ({ runs: { ...s.runs, [entry.id]: { ...s.runs[entry.id], whatIf } } }))
      useApp.getState().switchRun(entry.id)
      return true
    }
    const run = await loadDemoRun(entry)
    if (useApp.getState().building?.id !== b.id) return false
    useApp.getState().addRun({ key: entry.id, label: runLabel(entry.label, entry.brain), run, doors: entry.doors ?? {}, ...(whatIf ? { whatIf } : {}) })
    return true
  }
  try {
    const pair = pick(await listDemoRuns(b.id), b.id)
    if (!pair) throw new ApiError(missing)
    const prev = useClock.getState().t
    if (!(await show(pair.base)) || !(await show(pair.variant, pair.whatIf))) return
    const runs = useApp.getState().runs
    // Both panes share one clock, as long as the longer run: keep the time the page was at.
    useClock.setState({ duration: Math.max(runs[pair.base.id].index.duration, runs[pair.variant.id].index.duration) })
    useClock.getState().seek(prev)
    useApp.setState({ split: true, compareKeys: [pair.base.id, pair.variant.id], splitLeft: null, splitRight: null, rightBuilding: null, rightDraft: null })
  } catch (e) {
    useApp.setState({ pairError: e instanceof Error ? e.message : String(e) })
  } finally {
    useApp.setState({ pairBusy: null })
  }
}

if (import.meta.env.DEV) (window as unknown as { __app: typeof useApp }).__app = useApp
