import { useApp } from '../store/app'
import { spotPosition } from '../model/spots'
import RiskLegend, { Stamps } from './RiskLegend'

export default function WeakSpots() {
  const batch = useApp((s) => s.batch)
  const building = useApp((s) => s.building)
  const mode = useApp((s) => s.mode)
  const metric = useApp((s) => s.riskMetric)
  const risk = useApp((s) => s.layers.risk)
  const crowding = useApp((s) => s.crowding)
  const visible = useApp((s) => s.visibleFloors)
  const activeSpot = useApp((s) => s.activeSpot)
  const running = useApp((s) => s.batchRunning)
  const err = useApp((s) => s.batchError)
  const runBatch = useApp((s) => s.runBatch)
  const set = useApp.setState

  const go = (id: string, floor: string) => {
    if (!building) return
    const p = spotPosition(building, { id, floor })
    if (!p) {
      console.warn(`weak spot ${id} not found in ${building.id}`)
      return set({ notice: `Unknown spot ${id}` })
    }
    set({ notice: null, activeSpot: id })
    useApp.getState().flyTo(p.floorId, p.pos)
  }

  return (
    <div className="weak">
      {mode === 'live' && (
        <button disabled={!!running} onClick={() => void runBatch()}>
          {running ?? 'Run batch'}
        </button>
      )}
      {err && <p className="err">{err}</p>}
      {!batch ? (
        <p className="dim">No batch for this building. {mode === 'live' ? 'Run a batch to see the risk map.' : 'Static mode needs a precomputed batch.'}</p>
      ) : (
        <>
          <Stamps />
          <label className="check">
            <input type="checkbox" checked={risk} onChange={(e) => set((s) => ({ layers: { ...s.layers, risk: e.target.checked } }))} /> Risk map
          </label>
          <label>
            Metric{' '}
            <select value={metric} onChange={(e) => set({ riskMetric: e.target.value as 'riskT90' | 'riskTrapped' })}>
              <option value="riskT90">riskT90</option>
              <option value="riskTrapped">riskTrapped</option>
            </select>
          </label>
          {batch.heatmaps && batch.heatmaps.length > 0 && (
            <label className="check">
              <input type="checkbox" checked={crowding} onChange={(e) => set({ crowding: e.target.checked })} /> Crowding across all fires
            </label>
          )}
          <RiskLegend />
          <h4>Weak spots</h4>
          <p className="dim">
            {batch.runs.length} fires simulated{batch.failed?.length ? (
              <span title={(batch.failed as unknown as { scenarioId: string; error: string }[])
                .slice(0, 3).map((f) => `${f.scenarioId}: ${f.error}`).join('\n')}>
                {`, ${batch.failed.length} failed`}
              </span>
            ) : ''}; {batch.base?.occupants?.total ?? '?'} occupants,
            alarm at {batch.base?.alarmTime ?? '?'} s.
          </p>
          {batch.top.length === 0 && <p className="dim">No weak spots listed.</p>}
          <ol className="spots">
            {batch.top.map((t, i) => (
              <li key={t.kind + t.id + i} className={activeSpot === t.id ? 'on' : ''} onClick={() => go(t.id, t.floor)}>
                <b>#{i + 1}</b> <span className="badge">{t.kind}</span> <b>{t.id}</b> · {t.floor} · score {t.score.toFixed(1)}
                <div className="dim">{t.why}</div>
              </li>
            ))}
          </ol>
          {visible && <button onClick={() => set({ visibleFloors: null, focus: null })}>Show all floors</button>}
        </>
      )}
    </div>
  )
}
