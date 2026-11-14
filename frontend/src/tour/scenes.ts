import { labelsFor, useApp } from '../store/app'
import { useClock } from '../store/clock'
import { listDemoRuns, loadDemoRun } from '../data/loader'
import { compareRuns, findPrecomputedVariant } from '../model/whatif'
import { spotPosition } from '../model/spots'
import { batchHeadline, pairHeadline } from '../model/exposure'
import { fixLine } from '../model/fixes'
import { seedBadge } from '../model/ranges'

export interface TourCtx {
  after: (ms: number, fn: () => void) => void
  setNote: (s: string | null) => void
}
export interface TourScene {
  title: string
  seconds: number
  caption: () => string
  enter: (ctx: TourCtx) => Promise<void>
}

const DEFAULT_LAYERS = { rooms: true, labels: true, smoke: true, fire: true, heatmap: false, queues: true, risk: false }

/** Same starting picture for every scene, so a key pressed twice shows the same thing. */
export function resetStage() {
  const b = useApp.getState().building
  useApp.setState({
    view: 'replay',
    split: false,
    visibleFloors: null,
    focus: null,
    selectedRoom: null,
    activeSpot: null,
    explode: 0,
    autoRotate: false,
    trails: false,
    follow: null,
    pickAgent: false,
    crowding: false,
    riskMetric: 'riskT90',
    resultsTab: 'results',
    lens: [true, true, true, true, true, true],
    layers: { ...DEFAULT_LAYERS, labels: b ? labelsFor(b) : DEFAULT_LAYERS.labels },
  })
  useClock.setState({ playing: false })
}

const roomOf: Record<string, string> = {}

/** Loads (once) and shows the first baseline demo run. Only static index files are read, even in live mode. */
export async function baseline(): Promise<string | null> {
  const b = useApp.getState().building
  if (!b) return null
  const entry = (await listDemoRuns(b.id)).find((r) => r.whatIf === null)
  if (!entry) return null
  if (!useApp.getState().runs[entry.id]) {
    const run = await loadDemoRun(entry)
    useApp.getState().addRun({ key: entry.id, label: entry.label, run, doors: entry.doors ?? {} })
  }
  roomOf[entry.id] = entry.fire.room
  useApp.getState().switchRun(entry.id)
  useApp.setState({ compareKeys: [entry.id] })
  return entry.id
}

/** Adds and shows the precomputed what-if for the baseline's fire room, or returns null. */
export async function variant(baseKey: string): Promise<string | null> {
  const st = useApp.getState()
  const b = st.building
  const base = st.runs[baseKey]
  if (!b || !base) return null
  const entries = await listDemoRuns(b.id)
  const hit = findPrecomputedVariant(entries, { buildingId: b.id, room: roomOf[baseKey], doors: base.doors })
  if (!hit) return null
  const { entry } = hit
  if (!useApp.getState().runs[entry.id]) {
    const run = await loadDemoRun(entry)
    useApp.getState().addRun({ key: entry.id, label: entry.label, run, doors: entry.doors ?? {}, whatIf: { baselineKey: baseKey, door: hit.door, state: hit.state } })
  }
  useApp.getState().switchRun(entry.id)
  useApp.setState({ compareKeys: [baseKey, entry.id] })
  return entry.id
}

/** A run plays in about 35 s. */
export function tourSpeed(duration: number): number {
  return [2, 5, 10].find((s) => s >= duration / 35) ?? 10
}

function play(key: string) {
  const d = useApp.getState().runs[key]?.index.duration ?? 0
  const c = useClock.getState()
  c.seek(0)
  c.setSpeed(tourSpeed(d))
  useClock.setState({ playing: true })
}

const fit = () => useApp.setState((s) => ({ fitView: s.fitView + 1 }))
const sgn = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(0)} s`
const sec = (v: number | null) => (v == null ? 'not reached' : `${v.toFixed(0)} s`)

function variantCaption(): string {
  const st = useApp.getState()
  if (st.headlines?.headline) return st.headlines.headline
  const [a, b] = st.compareKeys.map((k) => st.runs[k])
  if (!a || !b || !b.whatIf) {
    const bh = batchHeadline(st.batch)
    return bh ? `${bh.main} (mean of ${bh.n} fires)` : ''
  }
  const h = pairHeadline(a.run, b.run, `Stair door ${b.whatIf.door} propped open`)
  if (h) return h.secondary ? `${h.main} · ${h.secondary}` : h.main
  const c = compareRuns(a.run, b.run)
  return `Stair door ${b.whatIf.door} propped open: t90 ${sec(c.t90[0])} → ${sec(c.t90[1])}${c.dT90 != null ? ` (${sgn(c.dT90)})` : ''}, trapped ${a.run.metrics.trapped} → ${b.run.metrics.trapped}`
}

export const TOUR: TourScene[] = [
  {
    title: 'Hook',
    seconds: 15,
    caption: () => 'Where would people get stuck if this building caught fire?',
    enter: async ({ after }) => {
      resetStage()
      await baseline()
      useClock.getState().seek(0)
      useApp.setState((s) => ({ layers: { ...s.layers, labels: false } }))
      fit()
      after(2000, () => useApp.setState({ autoRotate: true }))
    },
  },
  {
    title: 'Building in',
    seconds: 30,
    caption: () => useApp.getState().building?.name ?? '',
    enter: async ({ after }) => {
      resetStage()
      await baseline()
      useClock.getState().seek(0)
      useApp.setState((s) => ({ reveal: s.reveal + 1 }))
      fit()
      after(2000, () => useApp.setState({ explode: 0.5, autoRotate: true }))
    },
  },
  {
    title: "Judge's fire",
    seconds: 45,
    caption: () => {
      const k = useApp.getState().compareKeys[0]
      return `Fire in ${(k && roomOf[k]) || 'the building'}: queues form at the stairs`
    },
    enter: async () => {
      resetStage()
      const key = await baseline()
      if (!key) throw new Error('No demo run for this building')
      useApp.setState((s) => ({ layers: { ...s.layers, heatmap: true } }))
      play(key)
    },
  },
  {
    title: 'What-if',
    seconds: 30,
    caption: variantCaption,
    enter: async ({ setNote }) => {
      resetStage()
      const base = await baseline()
      if (!base) throw new Error('No demo run for this building')
      const v = await variant(base)
      if (!v) {
        setNote("No precomputed what-if yet (A's tools/precompute_demo.py adds one)")
        play(base)
        return
      }
      useApp.setState({ split: true })
      play(v)
    },
  },
  {
    title: 'Risk map',
    seconds: 40,
    caption: () => {
      const st = useApp.getState()
      const hp = st.headlines
      const spot = hp?.weakSpots?.[0]
      if (hp && spot) {
        const b = seedBadge(spot.kind, spot.seedsInTop3, hp.stability?.n)
        const fix = hp.fixes?.find((f) => f.helps)
        return `Fires in every room. Top weak spot: ${spot.label ?? spot.id}${b ? ` (${b.text})` : ''}${fix ? `. Best measured fix: ${fixLine(fix)}` : ''}`
      }
      const top = st.batch?.top[0]
      return top ? `Fires in every room. Top weak spot: ${top.why}` : ''
    },
    enter: async ({ after, setNote }) => {
      resetStage()
      await baseline()
      useClock.getState().seek(0)
      const { batch, building, headlines } = useApp.getState()
      const top = headlines?.weakSpots?.[0] ?? batch?.top[0]
      if ((!batch && !headlines) || !building || !top) {
        setNote(!batch && !headlines ? 'No batch for this building yet' : 'The batch lists no weak spots')
        return
      }
      useApp.setState((s) => ({ layers: { ...s.layers, risk: true }, resultsTab: 'risk', activeSpot: top.id }))
      after(1000, () => {
        const p = spotPosition(building, { id: top.id, floor: top.floor })
        if (p) useApp.getState().flyTo(p.floorId, p.pos)
      })
      after(22000, () => useApp.setState({ resultsTab: 'report' }))
    },
  },
  {
    title: 'Credibility',
    seconds: 20,
    caption: () => {
      const base = 'Door flow against published values. Illustrative fire model, not a compliance tool.'
      const why = useApp.getState().headlines?.sensitivity?.why
      return why ? `${base} ${why}` : base
    },
    enter: async () => {
      resetStage()
      await baseline()
      useClock.getState().seek(0)
      fit()
      useApp.setState({ resultsTab: 'cred' })
    },
  },
]
