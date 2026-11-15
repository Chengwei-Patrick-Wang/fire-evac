import { useEffect } from 'react'
import { useApp } from '../store/app'
import { readFixes, readSkipped } from '../model/fixes'
import { floorName, floorsByLevel } from '../model/floors'
import { RISK_NAMES, spotLabel } from '../model/spots'
import type { RiskMetric } from '../model/spots'
import { doorRange, readStability, roomRange, span } from '../model/ranges'
import MeasuredFixes from './MeasuredFixes'
import WhatIfHeadline from './WhatIfHeadline'
import RiskLegend, { Stamps } from './RiskLegend'
import RiskMapSvg from './RiskMapSvg'

/** A weak spot's score or time with its spread over the seeds, for the printed report's table (the cards on screen leave it out). */
export function seedText(batch: unknown, t: { kind: string; id: string; floor: string; score: number }): string | null {
  if (t.kind === 'room') {
    const r = roomRange(batch, t.id)
    return r ? `${RISK_NAMES.riskT90} ${r.median.toFixed(0)} s (${span(r)})` : null
  }
  const r = doorRange(batch, t.id, t.floor)
  return r ? `score ${t.score.toFixed(1)} (${span(r, '', 1)})` : null
}

/** A weak spot's reason without its own name: the card's heading says it ("Exit Stair S1 (west): 17 people queued…" reads "17 people queued…"). */
function reason(t: { why?: string }, label: string): string {
  const why = t.why ?? ''
  const rest = why.startsWith(`${label}: `) ? why.slice(label.length + 2) : why
  return rest.charAt(0).toUpperCase() + rest.slice(1)
}

/**
 * True while the risk layer is on only because this tab turned it on. Leaving the tab (by any route, with the panel hidden or not) turns it off again, so the
 * replay of "This fire" is not painted over; so does starting to place a fire, since the room fills would catch its clicks. Hiding the panel keeps it on, to look
 * at the map in the 3D view. The tab's own checkbox takes the layer over (a map the reader switched on or off is left as they set it).
 */
let autoOn = false
useApp.subscribe((s, prev) => {
  if (!autoOn || !s.layers.risk) return
  if ((prev.resultsTab === 'risk' && s.resultsTab !== 'risk') || (s.placing && !prev.placing)) {
    autoOn = false
    useApp.setState((st) => ({ layers: { ...st.layers, risk: false } }))
  }
})

export default function WeakSpots() {
  const batch = useApp((s) => s.batch)
  const building = useApp((s) => s.building)
  const mode = useApp((s) => s.mode)
  const metric = useApp((s) => s.riskMetric)
  const risk = useApp((s) => s.layers.risk)
  const crowding = useApp((s) => s.crowding)
  const visible = useApp((s) => s.visibleFloors)
  const activeSpot = useApp((s) => s.activeSpot)
  const placing = useApp((s) => s.placing)
  const running = useApp((s) => s.batchRunning)
  const err = useApp((s) => s.batchError)
  const runBatch = useApp((s) => s.runBatch)
  const set = useApp.setState
  const stab = readStability(batch)
  const hasBatch = !!batch

  // The risk map in the 3D view is on when this tab opens (see `autoOn`); a fire being placed takes it off for the time, and it comes back after.
  useEffect(() => {
    if (!hasBatch || placing || useApp.getState().layers.risk) return
    autoOn = true
    useApp.setState((s) => ({ layers: { ...s.layers, risk: true } }))
  }, [hasBatch, placing])

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
          <label>
            Color rooms by{' '}
            <select value={metric} onChange={(e) => set({ riskMetric: e.target.value as RiskMetric })}>
              {(['riskTrapped', 'riskT90'] as const).map((m) => (
                <option key={m} value={m}>{RISK_NAMES[m]}</option>
              ))}
            </select>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={risk}
              onChange={(e) => {
                autoOn = false
                set((s) => ({ layers: { ...s.layers, risk: e.target.checked } }))
              }}
            />{' '}
            Show the risk map in the 3D view
          </label>
          {batch.heatmaps && batch.heatmaps.length > 0 && (
            <label className="check">
              <input type="checkbox" checked={crowding} onChange={(e) => set({ crowding: e.target.checked })} /> Crowding across all fires
            </label>
          )}
          <RiskLegend />
          {building && (
            <div className="riskmaps">
              {floorsByLevel(building).map((f) => <RiskMapSvg key={f.id} floor={f.id} />)}
            </div>
          )}
          <h4>Where people get stuck</h4>
          <p className="dim">
            {batch.runs.length} fires simulated{batch.failed?.length ? (
              <span title={(batch.failed as unknown as { scenarioId: string; error: string }[])
                .slice(0, 3).map((f) => `${f.scenarioId}: ${f.error}`).join('\n')}>
                {`, ${batch.failed.length} failed`}
              </span>
            ) : ''}; {batch.base?.occupants?.total ?? '?'} occupants,
            alarm at {batch.base?.alarmTime ?? '?'} s. The numbers on the map are these spots.
          </p>
          {batch.top.length === 0 && <p className="dim">No weak spots listed.</p>}
          <ol className="spots">
            {batch.top.map((t, i) => {
              const label = spotLabel(t)
              return (
                <li key={t.kind + t.id + i} className={activeSpot === t.id ? 'on' : ''}>
                  <button className="spot" data-spot={t.id} onClick={() => useApp.getState().goToSpot(t.id, t.floor)}>
                    <b>#{i + 1} {label}</b> · {building ? floorName(building, t.floor) : t.floor}
                    <div className="dim">{reason(t, label)}</div>
                  </button>
                </li>
              )
            })}
          </ol>
          {stab && <p className="dim">Across seeds: {stab.why}</p>}
          <WhatIfHeadline />
          <MeasuredFixes fixes={readFixes(batch)} skipped={readSkipped(batch)} top={batch.top} />
          {visible && <button onClick={() => useApp.getState().setViewMode('stacked')}>Show all floors</button>}
        </>
      )}
    </div>
  )
}
