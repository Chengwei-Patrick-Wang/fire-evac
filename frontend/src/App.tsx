import { creditParts, loadBuildingIndex } from './model/buildingIndex'
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { Eye, Layers3 } from 'lucide-react'
import './App.css'
import { DEFAULT_EXPLODE, useApp } from './store/app'
import { useClock } from './store/clock'
import type { LoadedRun } from './store/app'
import TopNav from './ui/TopNav'
import TracerBar from './ui/TracerBar'
import AnalyticsSidebar from './ui/AnalyticsSidebar'
import FloorStrip from './ui/FloorStrip'
import Timeline from './ui/Timeline'
import LegendCard from './ui/LegendCard'
import FloatingCard from './ui/FloatingCard'
import LayersCard from './ui/LayersCard'
import VisibilityCard from './ui/VisibilityCard'
import Scene from './scene/Scene'
import SplitView from './scene/SplitView'
import AgentReadout from './ui/AgentReadout'
import ClockDriver from './ui/ClockDriver'
import ScenarioPanel from './ui/ScenarioPanel'
import ReplaySummary from './ui/ReplaySummary'
import AboutOverlay, { shouldAutoOpenAbout } from './ui/AboutOverlay'
import ErrorBoundary from './ui/ErrorBoundary'
import NewBuildingCard from './ui/NewBuildingCard'
import TourCaption from './tour/TourCaption'
import { useTour, useTourKeys } from './tour/tour'
import ShareCard from './ui/ShareCard'
import { makeDraft, nearestPrecomputedRun } from './model/scenarioDraft'
import { findPrecomputedVariant } from './model/whatif'
import { loadHeadlines, readPack } from './model/headlines'
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

const PrintReport = lazy(() => import('./ui/PrintReport'))
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
    const hp = await loadHeadlines(b.id)
    if (useApp.getState().building?.id === b.id) useApp.setState({ headlines: hp })
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
    if (link.tab) {
      patch.resultsTab = link.tab
      // A link's tab is there to be looked at, so show the sidebar that holds it. (A phone's default Overview link leaves the replay uncovered.)
      if (link.tab !== 'results' || !window.matchMedia('(max-width: 900px)').matches) patch.sidebarOpen = true
    }
    if (link.m) patch.riskMetric = link.m
    if (link.l) {
      const l = { ...cur.layers }
      for (const k of Object.keys(l) as (keyof typeof l)[]) l[k] = link.l.includes(k)
      patch.layers = l
    }
    // A link writes the floor gap only when it isn't the default, so a link without one means the default.
    patch.explode = link.x ?? DEFAULT_EXPLODE
    if (link.split !== undefined) patch.split = link.split
    useApp.setState(patch)
    // The floor view: v=side is side by side, v=ghost is ghost on f, f alone is one floor, and none is stacked. A link that carries a camera
    // pose keeps it (the view change doesn't re-frame the camera); one without lets the camera frame the view.
    const floor = link.f && cur.building?.floors.some((f) => f.id === link.f) ? link.f : undefined
    const fit = !link.cam
    const setView = useApp.getState().setViewMode
    if (link.v === 'side') setView('side', undefined, fit)
    else if (link.v === 'ghost') setView('ghost', floor, fit)
    else if (floor) setView('single', floor, fit)
    else setView('stacked', undefined, fit)
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

async function startup() {
  const app = useApp.getState()
  app.setLoading('Starting…')
  void loadBuildingIndex().then((summaries) => useApp.setState({ summaries }))
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

// Parsed JSON when the file is a headlines/v0 pack, else undefined.
async function headlinesFile(f: File): Promise<unknown> {
  try {
    const j = JSON.parse(await f.text())
    return j?.version === 'headlines/v0' ? j : undefined
  } catch {
    return undefined
  }
}

async function openFile(f: File) {
  const app = useApp.getState()
  app.setLoading(`Loading ${f.name}…`)
  try {
    const pack = f.size < 1024 * 1024 ? await headlinesFile(f) : undefined
    if (pack !== undefined) {
      const s = useApp.getState()
      const hp = s.building ? readPack(pack, s.building.id) : null
      if (hp) useApp.setState({ headlines: hp })
      else s.setNotice(`Headlines are for building ${(pack as { buildingId?: unknown }).buildingId}; loaded building is ${s.building?.id ?? 'none'}`)
      return
    }
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

function linkify(text: string) {
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
  return parts.map((p, i) =>
    typeof p === 'string' ? (
      p
    ) : (
      <span key={i}>
        <a href={p.url} target="_blank" rel="noreferrer">{p.url}</a>
        {p.tail}
      </span>
    ),
  )
}

function Credits() {
  const building = useApp((s) => s.building)
  const summary = useApp((s) => (s.building ? s.summaries[s.building.id] : undefined))
  if (!building) return <div className="credits" />
  const text = building.credits ? `${building.name}: ${building.credits}` : `${building.name}: no credits in this building file`
  const cp = building.credits ? creditParts(building.credits, summary?.shortCredit) : null
  if (cp?.license) {
    return (
      <div className="credits split" title={text}>
        <span className="src">
          {linkify(`${building.name}: ${cp.short}`)}
          {cp.source && (
            <>
              {' · '}
              <a href={cp.source} target="_blank" rel="noreferrer">source</a>
            </>
          )}
        </span>
        <span className="lic">
          License:{' '}
          {cp.licenseUrl ? <a href={cp.licenseUrl} target="_blank" rel="noreferrer">{cp.license}</a> : cp.license}
          {cp.changes && <span title={cp.changes}> · modified</span>}
        </span>
      </div>
    )
  }
  return (
    <div className="credits" title={text}>
      {linkify(text)}
    </div>
  )
}

/** Screen-reader announcements for the two drawers: navigation and analytics. */
function ShellStatus() {
  const navOpen = useApp((s) => s.navOpen)
  const sidebarOpen = useApp((s) => s.sidebarOpen)
  const prev = useRef({ navOpen, sidebarOpen })
  const [msg, setMsg] = useState('')
  useEffect(() => {
    const p = prev.current
    prev.current = { navOpen, sidebarOpen }
    const m: string[] = []
    if (p.navOpen !== navOpen) m.push(navOpen ? 'Navigation expanded' : 'Navigation collapsed')
    if (p.sidebarOpen !== sidebarOpen) m.push(sidebarOpen ? 'Analytics shown' : 'Analytics hidden')
    if (m.length) setMsg(m.join('. '))
  }, [navOpen, sidebarOpen])
  return (
    <p id="shell-status" className="sr-only" role="status">
      {msg}
    </p>
  )
}

export default function App() {
  const { view, split, runs, runOrder, activeRunKey, notice, loading, printView, navOpen, sidebarOpen, card } = useApp()
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
    })
  }, [])

  if (view === 'tracer')
    return (
      <div className="app tracing" key="tracing">
        <TracerBar />
        <main className="center">
          <Suspense fallback={<div className="pad">Loading tracer…</div>}>
            <TracerPage onOpenBuilding={(id) => void onOpenBuilding(id)} />
          </Suspense>
        </main>
        <AboutOverlay />
      </div>
    )

  return (
    <div className={'app' + (sidebarOpen ? '' : ' sb-closed') + (navOpen ? ' nav-open' : '')} key="replay">
      <button className="skip" onClick={() => document.getElementById('play')?.focus()}>Skip to replay controls</button>
      <TopNav onSelectBuilding={(id) => void selectBuilding(id)} onOpenFile={(f) => void openFile(f)} />
      <AnalyticsSidebar />
      <main className="center">
        <ErrorBoundary label="3D view">
          {splitOn ? <SplitView leftKey={base as string} rightKey={activeRunKey as string} /> : <Scene />}
        </ErrorBoundary>
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
        <div className="rightcol">
          <LegendCard />
          <div className="rail">
            <button
              type="button"
              className="railbtn"
              aria-label="Layers"
              title="Layers"
              aria-expanded={card === 'layers'}
              onClick={() => useApp.getState().setCard(card === 'layers' ? null : 'layers')}
            >
              <Layers3 size={18} strokeWidth={1.75} aria-hidden="true" />
            </button>
            {card === 'layers' && (
              <FloatingCard id="layers" title="Layers" className="layerscard">
                <LayersCard />
              </FloatingCard>
            )}
            <button
              type="button"
              className="railbtn"
              aria-label="Fire and smoke visibility"
              title="Fire and smoke visibility"
              aria-expanded={card === 'visibility'}
              onClick={() => useApp.getState().setCard(card === 'visibility' ? null : 'visibility')}
            >
              <Eye size={18} strokeWidth={1.75} aria-hidden="true" />
            </button>
            {card === 'visibility' && (
              <FloatingCard id="visibility" title="Fire and smoke visibility" className="visibilitycard">
                <VisibilityCard />
              </FloatingCard>
            )}
          </div>
        </div>
        {card === 'scenario' && (
          <FloatingCard id="scenario" title="Fire and scenario" className="scenariocard">
            <ScenarioPanel />
          </FloatingCard>
        )}
        <AgentReadout />
        <NewBuildingCard />
        <TourCaption />
        <ReplaySummary />
      </main>
      <footer className="dock">
        <FloorStrip />
        <Timeline />
        <Credits />
      </footer>
      <ClockDriver />
      <AboutOverlay />
      <ShareCard />
      {printView && (
        <Suspense fallback={null}>
          <PrintReport />
        </Suspense>
      )}
      <ShellStatus />
    </div>
  )
}
