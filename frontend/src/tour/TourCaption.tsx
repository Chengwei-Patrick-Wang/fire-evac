import { useApp } from '../store/app'
import { useTour } from './tour'
import { TOUR } from './scenes'

export default function TourCaption() {
  const { scene, auto, note, startedAt, go, stop } = useTour()
  // Re-render when the data a caption reads changes.
  useApp((s) => s.runs)
  useApp((s) => s.compareKeys)
  useApp((s) => s.batch)
  useApp((s) => s.headlines)
  useApp((s) => s.building)
  if (scene === null) return null
  const sc = TOUR[scene]
  return (
    <div className="tourcap" role="status" aria-live="polite">
      <div className="tourhead">
        <button aria-label="Previous scene" disabled={scene === 0} onClick={() => go(scene - 1, auto)}>‹</button>
        <b>{scene + 1}/{TOUR.length} · {sc.title}</b>
        <button aria-label="Next scene" disabled={scene === TOUR.length - 1} onClick={() => go(scene + 1, auto)}>›</button>
        <button aria-label="Stop demo" onClick={stop}>×</button>
      </div>
      <p>{sc.caption()}</p>
      {note && <p className="dim">{note}</p>}
      {auto && <div key={startedAt} className="tourbar" style={{ animationDuration: `${sc.seconds}s` }} />}
    </div>
  )
}
