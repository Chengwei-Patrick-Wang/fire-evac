import { useRef } from 'react'
import { useApp } from '../store/app'
import { useTour } from '../tour/tour'

export default function TopBar({
  onSelectBuilding,
  onOpenFile,
}: {
  onSelectBuilding: (id: string) => void
  onOpenFile: (f: File) => void
}) {
  const { buildings, building, runOrder, runs, activeRunKey, view, setView, switchRun, mode, loading } = useApp()
  const touring = useTour((s) => s.scene !== null)
  const fileRef = useRef<HTMLInputElement>(null)
  return (
    <header className="topbar">
      <strong>Fire evacuation sim</strong>
      <select value={building?.id ?? ''} onChange={(e) => onSelectBuilding(e.target.value)}>
        {building && !buildings.some((b) => b.id === building.id) && <option value={building.id}>{building.name}</option>}
        {buildings.map((b) => (
          <option key={b.id} value={b.id}>
            {b.name}
            {b.floors ? ` · ${b.floors} floors` : ''}
            {b.private ? ' (private)' : ''}
          </option>
        ))}
      </select>
      <nav className="tabs">
        {(['replay', 'tracer'] as const).map((v) => (
          <button key={v} className={view === v ? 'on' : ''} onClick={() => setView(v)}>
            {v === 'replay' ? 'Replay' : 'Tracer'}
          </button>
        ))}
      </nav>
      <nav className="tabs">
        {runOrder.map((k) => (
          <button key={k} className={k === activeRunKey ? 'on' : ''} onClick={() => switchRun(k)}>
            {runs[k].label}
          </button>
        ))}
      </nav>
      <button
        className="demo"
        onClick={(e) => {
          const t = useTour.getState()
          if (t.scene !== null) t.stop()
          else t.start()
          e.currentTarget.blur()
        }}
      >
        {touring ? 'Stop demo' : 'Demo'}
      </button>
      <button
        onClick={(e) => {
          useApp.getState().setShare(!useApp.getState().share)
          e.currentTarget.blur()
        }}
      >
        Share
      </button>
      <button onClick={() => useApp.getState().setAbout(true)}>About</button>
      <label className="file">
        Open file
        <input
          ref={fileRef}
          type="file"
          accept=".json,application/json"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) onOpenFile(f)
            if (fileRef.current) fileRef.current.value = ''
          }}
        />
      </label>
      <span
        className="mode mode-label"
        title={mode === 'live' ? 'Live: the backend runs new simulations' : 'Static: precomputed runs only, no backend'}
      >
        {mode}
      </span>
      {loading && <span className="spinner" aria-label="loading" />}
    </header>
  )
}
