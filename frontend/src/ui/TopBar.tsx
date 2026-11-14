import { useEffect, useRef, useState } from 'react'
import { useA11y } from './a11y'
import { useApp } from '../store/app'
import { useTour } from '../tour/tour'

export default function TopBar({
  onSelectBuilding,
  onOpenFile,
}: {
  onSelectBuilding: (id: string) => void
  onOpenFile: (f: File) => void
}) {
  const { buildings, building, runOrder, runs, activeRunKey, view, setView, switchRun, mode, loading, summaries } = useApp()
  const touring = useTour((s) => s.scene !== null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [display, setDisplay] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const { contrast, reduceMotion, setContrast, setReduceMotion } = useA11y()
  useEffect(() => {
    if (!display) return
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setDisplay(false)
        btnRef.current?.focus()
      }
    }
    const down = (e: MouseEvent) => {
      const n = e.target as Node
      if (!panelRef.current?.contains(n) && !btnRef.current?.contains(n)) setDisplay(false)
    }
    window.addEventListener('keydown', key)
    window.addEventListener('mousedown', down)
    return () => {
      window.removeEventListener('keydown', key)
      window.removeEventListener('mousedown', down)
    }
  }, [display])
  return (
    <header className="topbar">
      <h1 className="brand">Fire evacuation sim</h1>
      <select aria-label="Building" value={building?.id ?? ''} onChange={(e) => onSelectBuilding(e.target.value)}>
        {building && !buildings.some((b) => b.id === building.id) && <option value={building.id}>{building.name}</option>}
        {buildings.map((b) => (
          <option key={b.id} value={b.id}>
            {summaries[b.id] && summaries[b.id].floors && summaries[b.id].rooms
              ? `${b.name} · ${summaries[b.id].floors} floors · ${summaries[b.id].rooms} rooms`
              : `${b.name}${b.floors ? ` · ${b.floors} floors` : ''}`}
            {b.private ? ' (private)' : ''}
          </option>
        ))}
      </select>
      <nav className="tabs">
        {(['replay', 'tracer'] as const).map((v) => (
          <button key={v} aria-pressed={view === v} className={view === v ? 'on' : ''} onClick={() => setView(v)}>
            {v === 'replay' ? 'Replay' : 'Tracer'}
          </button>
        ))}
      </nav>
      <nav className="tabs">
        {runOrder.map((k) => (
          <button key={k} aria-current={k === activeRunKey ? 'true' : undefined} className={k === activeRunKey ? 'on' : ''} onClick={() => switchRun(k)}>
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
      <button
        ref={btnRef}
        aria-expanded={display}
        aria-controls="display-panel"
        onClick={(e) => {
          setDisplay(!display)
          e.currentTarget.blur()
        }}
      >
        Display
      </button>
      {display && (
        <div id="display-panel" ref={panelRef} className="displaypanel" role="group" aria-label="Display settings">
          <label>
            <input type="checkbox" checked={contrast} onChange={(e) => setContrast(e.target.checked)} /> High contrast
          </label>
          <label>
            <input type="checkbox" checked={reduceMotion} onChange={(e) => setReduceMotion(e.target.checked)} /> Reduce motion
          </label>
        </div>
      )}
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
      {loading && <span className="spinner" role="status" aria-label="Loading" />}
    </header>
  )
}
