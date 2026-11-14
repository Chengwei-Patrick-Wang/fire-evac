import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import './App.css'
import { useApp } from './store/app'
import { useClock } from './store/clock'
import type { LoadedRun } from './store/app'
import TopBar from './ui/TopBar'
import Scene from './scene/Scene'
import SplitView from './scene/SplitView'
import Toolbar3D from './ui/Toolbar3D'
import AgentReadout from './ui/AgentReadout'
import ClockDriver from './ui/ClockDriver'
import ScenarioPanel from './ui/ScenarioPanel'
import Scrubber from './ui/Scrubber'
import AboutOverlay, { shouldAutoOpenAbout } from './ui/AboutOverlay'
import AgentLegend from './ui/AgentLegend'
import ErrorBoundary from './ui/ErrorBoundary'
import NewBuildingCard from './ui/NewBuildingCard'
import TourCaption from './tour/TourCaption'
import { useTour, useTourKeys } from './tour/tour'
import ShareCard from './ui/ShareCard'
import { makeDraft, nearestPrecomputedRun } from './model/scenarioDraft'
import { findPrecomputedVariant } from './model/whatif'
import { cameraPose, decodeLink, linkCtl, loadIndexIds, useLinkSync } from './model/link'
import type { LinkState } from './model/link'
import type { DemoRun, DoorState } from './data/types'
import { SAMPLE_BUILDING } from './model/sample'
import {
  ApiError,
  detectMode,
  getMode,
  listBuildings,
  listDemoRuns,
  loadBatch,
  loadBuilding,
  loadDemoRun,
  openLocalFile,
} from './data/loader'

if (import.meta.env.DEV || new URLSearchParams(location.search).has('qa'))
  Object.assign(window, { __app: useApp, __clock: useClock, __tour: useTour, __pose: cameraPose })

const ResultsPanel = lazy(() => import('./ui/ResultsPanel'))
const TracerPage = lazy(() => import('./tracer/TracerPage'))

function msg(e: unknown) {
  return e instanceof ApiError || e instanceof Error ? e.message : String(e)
}

async function selectBuilding(id: string) {
  const app = useApp.getState()
  app.setLoading('Loading building…')
  try {
    const forceSample = new URLSearchParams(location.search).has('sample')
    const b = forceSample && id === SAMPLE_BUILDING.id ? SAMPLE_BUILDING : await loadBuilding(id)
    useApp.getState().setBuilding(b)
    const batch = await loadBatch(b.id).catch(() => null)
    useApp.setState({ batch: batch && batch.buildingId === b.id ? batch : null })
    useApp.getState().setDraft(makeDraft(b, useApp.getState().batch?.base))
    const runs = await listDemoRuns(b.id)
    const first = runs.find((r) => r.whatIf === null)
    if (first) {
      const run = await loadDemoRun(first)
      useApp.getState().addRun({ key: first.id, label: first.label, run, doors: first.doors ?? {} })
    }
    useApp.getState().setNotice(null)
  } catch (e) {
    useApp.getState().setNotice(msg(e))
  } finally {
    useApp.getState().setLoading(null)
  }
}

async function ensureRun(entry: DemoRun, whatIf?: { baselineKey: string; door: string; state: DoorState }) {
  const st = useApp.getState()
  if (st.runs[entry.id]) {
    if (st.activeRunKey !== entry.id) st.switchRun(entry.id)
    return
  }
  const run = await loadDemoRun(entry)
  useApp.getState().addRun({ key: entry.id, label: entry.label, run, doors: entry.doors ?? {}, ...(whatIf ? { whatIf } : {}) })
}

export async function restoreLink(link: LinkState) {
  try {
    const st0 = useApp.getState()
    if (!st0.building || st0.building.id !== link.b) return
    const entries = await listDemoRuns(link.b)
    const entry = link.r ? entries.find((e) => e.id === link.r) : undefined
    if (entry) {
      if (st0.activeRunKey !== entry.id || !st0.runs[entry.id]) {
        if (entry.whatIf === null) await ensureRun(entry)
        else {
          const base = entries.find((e) => e.buildingId === entry.buildingId && e.fire.room === entry.fire.room && e.whatIf === null)
          if (base) {
            await ensureRun(base)
            const hit = findPrecomputedVariant([entry], { buildingId: link.b, doors: base.doors ?? {} })
            await ensureRun(entry, { baselineKey: base.id, door: hit?.door ?? '?', state: hit?.state ?? 'propped' })
          } else await ensureRun(entry)
        }
      }
    } else if (link.ff !== undefined && link.fx !== undefined && link.fy !== undefined) {
      const hit = nearestPrecomputedRun(entries, { floor: link.ff, x: link.fx, y: link.fy })
      if (hit) {
        await ensureRun(hit.entry)
        useApp.getState().setNotice(`Showing the nearest precomputed run (fire in ${hit.entry.fire.room})`)
      }
    } else if (link.r) {
      const s = useApp.getState()
      s.setNotice(`Run ${link.r} isn't precomputed here; showing ${s.activeRunKey ? s.runs[s.activeRunKey]?.label : 'the first run'}.`)
    }
    const patch: Partial<ReturnType<typeof useApp.getState>> = {}
    const cur = useApp.getState()
    if (link.tab) patch.resultsTab = link.tab
    if (link.m) patch.riskMetric = link.m
    if (link.l) {
      const l = { ...cur.layers }
      for (const k of Object.keys(l) as (keyof typeof l)[]) l[k] = link.l.includes(k)
      patch.layers = l
    }
    if (link.x !== undefined) patch.explode = link.x
    if (link.f && cur.building?.floors.some((f) => f.id === link.f)) patch.visibleFloors = [link.f]
    if (link.split !== undefined) patch.split = link.split
    useApp.setState(patch)
    if (link.t !== undefined) {
      useClock.getState().seek(link.t)
      useClock.setState({ playing: false })
    }
  } catch (e) {
    useApp.getState().setNotice(msg(e))
  } finally {
    linkCtl.restoring = false
  }
}

let startLink: LinkState | null = null

async function startup() {
  const app = useApp.getState()
  app.setLoading('Starting…')
  try {
    app.setMode(await detectMode())
    const params = new URLSearchParams(location.search)
    if (params.has('sample')) {
      app.setBuildings([{ id: SAMPLE_BUILDING.id, name: SAMPLE_BUILDING.name }])
      await selectBuilding(SAMPLE_BUILDING.id)
      return
    }
    let link: LinkState | null = null
    if (!params.has('demo')) {
      await loadIndexIds()
      link = decodeLink(location.hash)
      if (link) linkCtl.restoring = true
    }
    startLink = link
    let list = await listBuildings().catch((e) => {
      useApp.getState().setNotice(msg(e))
      return []
    })
    if (list.length === 0) list = [{ id: SAMPLE_BUILDING.id, name: SAMPLE_BUILDING.name }]
    useApp.getState().setBuildings(list)
    const want = params.get('building')
    const linked = link ? list.find((b) => b.id === link.b) : undefined
    const id = linked?.id ?? list.find((b) => b.id === want)?.id ?? list[0].id
    if (id === SAMPLE_BUILDING.id) {
      useApp.getState().setBuilding(SAMPLE_BUILDING)
      useApp.getState().setDraft(makeDraft(SAMPLE_BUILDING))
      useApp.getState().setLoading(null)
    } else {
      if (linked && link?.cam) useApp.setState({ pendingCam: link.cam })
      await selectBuilding(id)
    }
    if (link) {
      if (linked) await restoreLink(link)
      else {
        const b = useApp.getState().building
        useApp.getState().setNotice(`This link's building ${link.b} isn't on this site; showing ${b?.name ?? id}.`)
      }
    }
  } finally {
    linkCtl.restoring = false
    useApp.getState().setLoading(null)
  }
}

async function openFile(f: File) {
  const app = useApp.getState()
  app.setLoading(`Loading ${f.name}…`)
  try {
    const o = await openLocalFile(f)
    if (o.kind === 'building') {
      useApp.getState().setBuilding(o.data)
      useApp.getState().setDraft(makeDraft(o.data))
    } else if (o.kind === 'run') {
      const s = useApp.getState()
      if (!s.building || s.building.id !== o.data.buildingId) {
        s.setNotice(`Run is for building ${o.data.buildingId}; loaded building is ${s.building?.id ?? 'none'}`)
      }
      const key = `file-${o.data.id}-${Date.now().toString(36)}`
      const lr: Omit<LoadedRun, 'index'> = { key, label: o.data.id, run: o.data, doors: {} }
      useApp.getState().addRun(lr)
    } else if (o.kind === 'batch') {
      const s = useApp.getState()
      if (!s.building || s.building.id !== o.data.buildingId)
        s.setNotice(`Batch is for building ${o.data.buildingId}; loaded building is ${s.building?.id ?? 'none'}`)
      else useApp.setState({ batch: o.data })
    } else {
      s_notice(`${o.kind} file loaded (not used yet)`)
    }
  } catch (e) {
    useApp.getState().setNotice(msg(e))
  } finally {
    useApp.getState().setLoading(null)
  }
}
function s_notice(m: string) {
  useApp.getState().setNotice(m)
}

function Credits() {
  const building = useApp((s) => s.building)
  if (!building) return <div className="credits" />
  const text = building.credits ? `${building.name}: ${building.credits}` : `${building.name}: no credits in this building file`
  const parts: (string | { url: string; tail: string })[] = []
  let last = 0
  for (const m of text.matchAll(/https?:\/\/[^\s]+/g)) {
    const raw = m[0]
    const url = raw.replace(/[.,;:)]+$/, '')
    parts.push(text.slice(last, m.index))
    parts.push({ url, tail: raw.slice(url.length) })
    last = m.index + raw.length
  }
  parts.push(text.slice(last))
  return (
    <div className="credits" title={text}>
      {parts.map((p, i) =>
        typeof p === 'string' ? (
          p
        ) : (
          <span key={i}>
            <a href={p.url} target="_blank" rel="noreferrer">{p.url}</a>
            {p.tail}
          </span>
        ),
      )}
    </div>
  )
}

export default function App() {
  const { view, split, runs, runOrder, activeRunKey, notice, loading } = useApp()
  const base = activeRunKey ? runs[activeRunKey]?.whatIf?.baselineKey ?? runOrder.find((k) => k !== activeRunKey) : undefined
  const splitOn = split && !!activeRunKey && !!base && !!runs[base] && base !== activeRunKey
  const onOpenBuilding = useCallback(async (id: string) => {
    try {
      if (getMode() !== 'live') useApp.getState().setMode(await detectMode())
      if (getMode() !== 'live') {
        useApp.getState().setView('replay')
        useApp.getState().setNotice(`Building ${id} was saved by the backend, but this page can't reach it. Start the backend, then reload with ?building=${id}.`)
        return
      }
      useApp.getState().setBuildings(await listBuildings())
      useApp.getState().setView('replay')
      await selectBuilding(id)
      if (useApp.getState().building?.id === id) useApp.setState({ fromTracer: id })
    } catch (e) {
      useApp.getState().setNotice(msg(e))
    }
  }, [])
  const [phone, setPhone] = useState(() => window.matchMedia('(max-width: 900px)').matches)
  const [openPanel, setOpenPanel] = useState<'left' | 'right' | null>(null)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 900px)')
    const on = () => setPhone(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])

  useTourKeys()
  useLinkSync()
  useEffect(() => {
    const on = async () => {
      const link = decodeLink(location.hash)
      const st = useApp.getState()
      if (!link || linkCtl.restoring || st.loading || st.view !== 'replay') return
      linkCtl.restoring = true
      try {
        if (st.building?.id !== link.b) {
          if (!st.buildings.some((b) => b.id === link.b)) return
          if (link.cam) useApp.setState({ pendingCam: link.cam })
          await selectBuilding(link.b)
        } else if (link.cam) useApp.setState({ pendingCam: link.cam })
        await restoreLink(link)
      } finally {
        linkCtl.restoring = false
      }
    }
    const h = () => void on()
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])
  useEffect(() => {
    if (view === 'tracer') useClock.setState({ playing: false })
  }, [view])
  useEffect(() => {
    void startup().then(() => {
      if (new URLSearchParams(location.search).has('demo')) useTour.getState().start()
      else if (shouldAutoOpenAbout()) useApp.getState().setAbout(true)
      if (startLink && startLink.tab && startLink.tab !== 'results' && window.matchMedia('(max-width: 900px)').matches) setOpenPanel('right')
    })
  }, [])

  if (view === 'tracer')
    return (
      <div className="app tracing" key="tracing">
        <TopBar onSelectBuilding={(id) => void selectBuilding(id)} onOpenFile={(f) => void openFile(f)} />
        <main className="center">
          <Suspense fallback={<div className="pad">Loading tracer…</div>}>
            <TracerPage onOpenBuilding={(id) => void onOpenBuilding(id)} />
          </Suspense>
        </main>
        <AboutOverlay />
      </div>
    )

  return (
    <div className="app" key="replay">
      <TopBar onSelectBuilding={(id) => void selectBuilding(id)} onOpenFile={(f) => void openFile(f)} />
      <aside className={'left' + (phone && openPanel !== 'left' ? ' collapsed' : '')}>
        <h3>Scenario</h3>
        <ScenarioPanel />
      </aside>
      {phone && (
        <div className="toggles">
          {(['left', 'right'] as const).map((k) => (
            <button key={k} className={openPanel === k ? 'on' : ''} onClick={() => setOpenPanel(openPanel === k ? null : k)}>
              {k === 'left' ? 'Scenario' : 'Results'}
            </button>
          ))}
        </div>
      )}
      <main className="center">
        <>
            <ErrorBoundary label="3D view">
              {splitOn ? <SplitView leftKey={base as string} rightKey={activeRunKey as string} /> : <Scene />}
            </ErrorBoundary>
            <Toolbar3D />
            {notice && (
              <div className="banner" role="status">
                <span>{notice}</span>
                <button aria-label="Dismiss" onClick={() => useApp.getState().setNotice(null)}>×</button>
              </div>
            )}
            {loading && !activeRunKey && (
              <div className="loadingcover">
                <span className="spinner" /> {loading}
              </div>
            )}
            <AgentLegend />
            <AgentReadout />
            <NewBuildingCard />
            <TourCaption />
          </>
      </main>
      <aside className={'right' + (phone && openPanel !== 'right' ? ' collapsed' : '')}>
        <Suspense fallback={<div className="pad dim">Loading…</div>}>
          <ErrorBoundary label="Results">
            <ResultsPanel />
          </ErrorBoundary>
        </Suspense>
      </aside>
      <footer className="bottom"><Scrubber /></footer>
      <ClockDriver />
      <AboutOverlay />
      <ShareCard />
      <Credits />

    </div>
  )
}
