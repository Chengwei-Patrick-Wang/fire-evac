import { useApp } from '../store/app'
import { PROFILE_NAMES } from '../replay/runIndex'

/** Everything Toolbar3D used to hold, minus the camera and agent buttons (they moved to the toolbar and View menu). */
export default function LayersCard() {
  const explode = useApp((s) => s.explode)
  const labels = useApp((s) => s.layers.labels)
  const rooms = useApp((s) => s.layers.rooms)
  const smoke = useApp((s) => s.layers.smoke)
  const fire = useApp((s) => s.layers.fire)
  const heatmap = useApp((s) => s.layers.heatmap)
  const queues = useApp((s) => s.layers.queues)
  const risk = useApp((s) => s.layers.risk)
  const lens = useApp((s) => s.lens)
  const trails = useApp((s) => s.trails)
  const crowding = useApp((s) => s.crowding)
  const hasSmoke = useApp((s) => {
    const r = s.activeRunKey ? s.runs[s.activeRunKey]?.run : undefined
    return !!r?.smoke?.length
  })
  const hasHeat = useApp((s) => {
    const r = s.activeRunKey ? s.runs[s.activeRunKey]?.run : undefined
    return !!r?.metrics.heatmaps?.length
  })
  const hasBatch = useApp((s) => s.batch !== null)
  const set = useApp.setState

  return (
    <div className="layers">
      <label className="slider">
        <span>Floor gap</span>
        <input type="range" min={0} max={1} step={0.05} value={explode} onChange={(e) => set({ explode: +e.target.value })} />
      </label>
      <label className="check">
        <input type="checkbox" checked={labels} onChange={(e) => set((s) => ({ layers: { ...s.layers, labels: e.target.checked } }))} />
        Room labels
      </label>
      <label className="check">
        <input type="checkbox" checked={rooms} onChange={(e) => set((s) => ({ layers: { ...s.layers, rooms: e.target.checked } }))} />
        Room colors
      </label>
      {([
        ['smoke', 'Smoke', smoke],
        ['fire', 'Fire', fire],
        ['heatmap', 'Heatmap', heatmap],
        ['queues', 'Queues', queues],
        ['risk', 'Risk map', risk],
      ] as const).map(([k, name, val]) => {
        const why =
          k === 'smoke' && !hasSmoke ? 'This run has no smoke frames'
          : k === 'heatmap' && !hasHeat && !(crowding && risk) ? 'This run has no heatmap data'
          : k === 'risk' && !hasBatch ? 'No batch for this building'
          : ''
        return (
          <label key={k} className={'check' + (why ? ' off' : '')} title={why || undefined}>
            <input
              type="checkbox"
              disabled={!!why}
              checked={val && !(k === 'smoke' && !hasSmoke) && !(k === 'heatmap' && !hasHeat && !(crowding && risk)) && !(k === 'risk' && !hasBatch)}
              onChange={(e) => set((s) => ({ layers: { ...s.layers, [k]: e.target.checked } }))}
            />
            {name}
          </label>
        )
      })}
      <label className="check">
        <input type="checkbox" checked={trails} onChange={(e) => set({ trails: e.target.checked })} />
        Trails
      </label>
      <h3>Highlight a profile</h3>
      <div className="lensrow" role="group" aria-label="Highlight a profile">
        {PROFILE_NAMES.map((n, i) => (
          <button
            key={n}
            type="button"
            title="Lens: highlight this profile"
            aria-pressed={!lens.every(Boolean) && lens[i]}
            className={'lens ' + (lens.every(Boolean) || !lens[i] ? '' : 'on')}
            onClick={() =>
              set((s) => {
                const all = s.lens.every(Boolean)
                const only = s.lens[i] && s.lens.filter(Boolean).length === 1
                if (only) return { lens: s.lens.map(() => true) }
                if (all) return { lens: s.lens.map((_, j) => j === i) }
                return { lens: s.lens.map((v, j) => (j === i ? !v : v)) }
              })
            }
          >
            {n}
          </button>
        ))}
      </div>
    </div>
  )
}
