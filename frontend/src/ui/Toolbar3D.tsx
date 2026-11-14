import { useApp } from '../store/app'

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
  if (!building) return null
  const set = useApp.setState
  const isOn = (id: string) => !visible || visible.includes(id)
  const toggleFloor = (id: string) => {
    const cur = visible ?? building.floors.map((f) => f.id)
    const next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]
    set({ visibleFloors: next.length === building.floors.length ? null : next })
  }
  return (
    <div className="toolbar3d">
      <label>
        Explode{' '}
        <input type="range" min={0} max={1} step={0.05} value={explode} onChange={(e) => set({ explode: +e.target.value })} />
      </label>
      {building.floors.map((f) => (
        <label key={f.id}>
          <input type="checkbox" checked={isOn(f.id)} onChange={() => toggleFloor(f.id)} /> {f.id}
        </label>
      ))}
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
      ] as const).map(([k, name, val]) => (
        <label key={k}>
          <input
            type="checkbox"
            checked={val}
            onChange={(e) => set((s) => ({ layers: { ...s.layers, [k]: e.target.checked } }))}
          />{' '}
          {name}
        </label>
      ))}
      <button onClick={() => set((s) => ({ topView: s.topView + 1 }))}>Top view</button>
    </div>
  )
}
