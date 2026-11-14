import { useApp } from '../store/app'
import { PROFILE_NAMES } from '../replay/runIndex'

export default function Toolbar3D() {
  const building = useApp((s) => s.building)
  const explode = useApp((s) => s.explode)
  const visible = useApp((s) => s.visibleFloors)
  const labels = useApp((s) => s.layers.labels)
  const smoke = useApp((s) => s.layers.smoke)
  const fire = useApp((s) => s.layers.fire)
  const heatmap = useApp((s) => s.layers.heatmap)
  const queues = useApp((s) => s.layers.queues)
  const risk = useApp((s) => s.layers.risk)
  const split = useApp((s) => s.split)
  const lens = useApp((s) => s.lens)
  const trails = useApp((s) => s.trails)
  const agentColor = useApp((s) => s.agentColor)
  const pick = useApp((s) => s.pickAgent)
  const hasSmoke = useApp((s) => {
    const r = s.activeRunKey ? s.runs[s.activeRunKey]?.run : undefined
    return !!r?.smoke?.length
  })
  const hasHeat = useApp((s) => {
    const r = s.activeRunKey ? s.runs[s.activeRunKey]?.run : undefined
    return !!r?.metrics.heatmaps?.length
  })
  const crowding = useApp((s) => s.crowding)
  const hasBatch = useApp((s) => s.batch !== null)
  const hasRun = useApp((s) => s.activeRunKey !== null)
  const nRuns =useApp((s) => s.runOrder.length)
  if (!building) return null
  const set = useApp.setState
  const floorsByLevel = [...building.floors].sort((a, b) => a.level - b.level)
  return (
    <div className="toolbar3d">
      <label>
        Explode{' '}
        <input type="range" min={0} max={1} step={0.05} value={explode} onChange={(e) => set({ explode: +e.target.value })} />
      </label>
      {building.floors.length >= 2 && (
        <select
          aria-label="Floor"
          value={visible && visible.length === 1 ? visible[0] : ''}
          onChange={(e) =>
            set((s) => ({
              visibleFloors: e.target.value ? [e.target.value] : null,
              focus: null,
              fitView: s.fitView + 1,
            }))
          }
        >
          <option value="">All floors</option>
          {floorsByLevel.map((f) => (
            <option key={f.id} value={f.id}>
              {f.id}
            </option>
          ))}
        </select>
      )}
      <label>
        <input
          type="checkbox"
          checked={labels}
          onChange={(e) => set((s) => ({ layers: { ...s.layers, labels: e.target.checked } }))}
        />{' '}
        Labels
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
        <label key={k} className={why ? 'off' : ''} title={why || undefined}>
          <input
            type="checkbox"
            disabled={!!why}
            checked={val && !(k === 'smoke' && !hasSmoke) && !(k === 'heatmap' && !hasHeat && !(crowding && risk)) && !(k === 'risk' && !hasBatch)}
            onChange={(e) => set((s) => ({ layers: { ...s.layers, [k]: e.target.checked } }))}
          />{' '}
          {name}
        </label>
        )
      })}
      <label>
        <input type="checkbox" checked={trails} onChange={(e) => set({ trails: e.target.checked })} /> Trails
      </label>
      {PROFILE_NAMES.map((n, i) => (
        <button
          key={n}
          title="Lens: highlight this profile"
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
      <button
        title="Color agents by status or by profile"
        onClick={() => set((s) => ({ agentColor: s.agentColor === 'status' ? 'profile' : 'status' }))}
      >
        Color: {agentColor}
      </button>
      <button
        disabled={split || !hasRun}
        className={pick ? 'on' : ''}
        onClick={(e) => {
          const on = !useApp.getState().pickAgent
          set({ pickAgent: on, notice: on ? 'Click a person to see what they see' : null })
          e.currentTarget.blur()
        }}
      >
        Agent view
      </button>
      <button disabled={nRuns < 2} className={'split ' + (split ? 'on' : '')} onClick={() => set((s) => ({ split: !s.split }))}>Split</button>
      <button onClick={() => set((s) => ({ topView: s.topView + 1 }))}>Top view</button>
    </div>
  )
}
