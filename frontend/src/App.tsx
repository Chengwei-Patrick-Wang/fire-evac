import { lazy, Suspense, useCallback, useEffect } from 'react'
import './App.css'
import { useApp } from './store/app'
import type { LoadedRun } from './store/app'
import TopBar from './ui/TopBar'
import Scene from './scene/Scene'
import Toolbar3D from './ui/Toolbar3D'
import { SAMPLE_BUILDING } from './model/sample'
import {
  ApiError,
  detectMode,
  listBuildings,
  listDemoRuns,
  loadBuilding,
  loadDemoRun,
  openLocalFile,
} from './data/loader'

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
    let list = await listBuildings().catch((e) => {
      useApp.getState().setNotice(msg(e))
      return []
    })
    if (list.length === 0) list = [{ id: SAMPLE_BUILDING.id, name: SAMPLE_BUILDING.name }]
    useApp.getState().setBuildings(list)
    const want = params.get('building')
    const id = list.find((b) => b.id === want)?.id ?? list[0].id
    if (id === SAMPLE_BUILDING.id) {
      useApp.getState().setBuilding(SAMPLE_BUILDING)
      useApp.getState().setLoading(null)
    } else await selectBuilding(id)
  } finally {
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
    } else if (o.kind === 'run') {
      const s = useApp.getState()
      if (!s.building || s.building.id !== o.data.buildingId) {
        s.setNotice(`Run is for building ${o.data.buildingId}; loaded building is ${s.building?.id ?? 'none'}`)
      }
      const key = `file-${o.data.id}-${Date.now().toString(36)}`
      const lr: LoadedRun = { key, label: o.data.id, run: o.data, doors: {} }
      useApp.getState().addRun(lr)
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

export default function App() {
  const { view, building } = useApp()
  const onOpenBuilding = useCallback(async (id: string) => {
    useApp.getState().setBuildings(await listBuildings())
    useApp.getState().setView('replay')
    await selectBuilding(id)
  }, [])

  useEffect(() => {
    void startup()
  }, [])

  return (
    <div className="app">
      <TopBar onSelectBuilding={(id) => void selectBuilding(id)} onOpenFile={(f) => void openFile(f)} />
      <aside className="left">
        <h3>Scenario</h3>
        <p className="dim">Scenario panel arrives in a later task.</p>
      </aside>
      <main className="center">
        {view === 'tracer' ? (
          <Suspense fallback={<div className="pad">Loading tracer…</div>}>
            <TracerPage onOpenBuilding={(id) => void onOpenBuilding(id)} />
          </Suspense>
        ) : (
          <>
            <Scene />
            <Toolbar3D />
          </>
        )}
      </main>
      <aside className="right">
        <h3>Results</h3>
        <p className="dim">Illustrative fire model. Not a compliance tool.</p>
      </aside>
      <footer className="bottom">Bottom bar (scrubber)</footer>
      <div className="credits">{building?.credits ?? ''}</div>
    </div>
  )
}
