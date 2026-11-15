import { Flame } from 'lucide-react'
import { useApp } from '../store/app'
import { BRAND } from './theme'

/** The 44 px bar above the tracer (A's TracerPage assumes it): brand, the way back, the mode chip. */
export default function TracerBar() {
  const mode = useApp((s) => s.mode)
  return (
    <header className="topbar">
      <Flame size={20} strokeWidth={1.75} aria-hidden="true" className="brand-flame" />
      <h1 className="brand">{BRAND}</h1>
      <span className="tracerlabel">Tracer</span>
      <button type="button" className="demo" onClick={() => useApp.getState().setView('replay')}>
        Back to 3D replay
      </button>
      <span className="mode mode-label" title={mode === 'live' ? 'Live: the backend runs new simulations' : 'Static: precomputed runs only, no backend'}>
        {mode}
      </span>
    </header>
  )
}
