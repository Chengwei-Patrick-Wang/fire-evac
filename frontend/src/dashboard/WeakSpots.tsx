import { useApp } from '../store/app'
import { readFixes, readSkipped } from '../model/fixes'
import { spotLabel } from '../model/spots'
import { doorRange, readStability, roomRange, seedBadge, span } from '../model/ranges'
import MeasuredFixes from './MeasuredFixes'
import WhatIfHeadline from './WhatIfHeadline'
import RiskLegend, { Stamps } from './RiskLegend'

export function seedText(batch: unknown, t: { kind: string; id: string; floor: string; score: number }): string | null {
  if (t.kind === 'room') {
    const r = roomRange(batch, t.id)
    return r ? `riskT90 ${r.median.toFixed(0)} s (${span(r)})` : null
  }
  const r = doorRange(batch, t.id, t.floor)
  return r ? `score ${t.score.toFixed(1)} (${span(r, '', 1)})` : null
}

function SeedInfo({ batch, t }: { batch: unknown; t: { kind: string; id: string; floor: string; score: number } }) {
  const extra = t as unknown as { seedsInTop3?: number; seeds?: number }
  const b = seedBadge(t.kind, extra.seedsInTop3, extra.seeds)
  const rt = seedText(batch, t)
  if (!b && !rt) return null
  return (
    <div>
      {b && <span className={b.stable ? 'badge ok' : 'badge warn'}>{b.text}</span>}
      {rt && <span className="dim"> {rt}</span>}
    </div>
  )
}

export default function WeakSpots() {
  const batch = useApp((s) => s.batch)
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
  const stab = readStability(batch)

  return (
    <div className="weak">
      {mode === 'live' && (
        <button disabled={!!running} onClick={() => void runBatch()}>
          {running ?? 'Run batch'}
        </button>
      )}
      {err && <p className="err">{err}</p>}
      {!batch ? (
        <div className="empty"><b>No batch for this building</b><span>{mode === 'live' ? 'Run a batch to see the risk map.' : 'Static mode needs a precomputed batch.'}</span></div>
      ) : (
        <>
          <Stamps />
          <WhatIfHeadline />
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
              <li key={t.kind + t.id + i} className={activeSpot === t.id ? 'on' : ''}>
                <button className="spot" onClick={() => useApp.getState().goToSpot(t.id, t.floor)}>
                  <b>#{i + 1}</b> <span className="badge">{t.kind}</span> <b>{spotLabel(t)}</b> · {t.floor} · score {t.score.toFixed(1)}
                  <SeedInfo batch={batch} t={t} />
                  <div className="dim">{t.why}</div>
                </button>
              </li>
            ))}
          </ol>
          {stab && (
            <>
              <p className="dim">Across seeds: {stab.why}</p>
              <p className="dim">Ranges are the spread over the simulated seeds, not confidence intervals.</p>
            </>
          )}
          <MeasuredFixes fixes={readFixes(batch)} skipped={readSkipped(batch)} top={batch.top} />
          {visible && <button onClick={() => useApp.getState().setViewMode('stacked')}>Show all floors</button>}
        </>
      )}
    </div>
  )
}
