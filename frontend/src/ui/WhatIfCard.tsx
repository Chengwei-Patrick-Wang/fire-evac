import { useEffect, useMemo, useState } from 'react'
import { useApp } from '../store/app'
import { compareRuns, defaultWhatIfDoor, stairDoors } from '../model/whatif'
import type { DoorState } from '../data/types'

const STATES: DoorState[] = ['propped', 'open', 'closed', 'blocked']
const fmt = (v: number | null) => (v == null ? 'not reached' : `${v.toFixed(0)} s`)
const signed = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(0)} s`

export default function WhatIfCard() {
  const building = useApp((s) => s.building)
  const runs = useApp((s) => s.runs)
  const activeKey = useApp((s) => s.activeRunKey)
  const order = useApp((s) => s.runOrder)
  const busy = useApp((s) => s.whatIfBusy)
  const err = useApp((s) => s.whatIfError)
  const runWhatIf = useApp((s) => s.runWhatIf)
  const switchRun = useApp((s) => s.switchRun)
  const active = activeKey ? runs[activeKey] : null
  const base = active?.whatIf ? runs[active.whatIf.baselineKey] : active
  const fire = base?.run.fire
  const [door, setDoor] = useState('')
  const [state, setState] = useState<DoorState>('propped')
  const [sprinklers, setSprinklers] = useState(false)

  const stair = useMemo(() => (building ? stairDoors(building).map((d) => d.door.id) : []), [building])
  const others = useMemo(
    () => (building ? building.floors.flatMap((f) => f.doors.map((d) => d.id)).filter((id) => !stair.includes(id)) : []),
    [building, stair],
  )
  const def = building && fire ? defaultWhatIfDoor(building, fire) : null
  const chosen = door || def || ''

  // W toggles between the baseline and the latest what-if.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'KeyW' || e.ctrlKey || e.metaKey || e.altKey) return
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
      const s = useApp.getState()
      const a = s.activeRunKey ? s.runs[s.activeRunKey] : null
      if (!a) return
      if (a.whatIf) return switchRun(a.whatIf.baselineKey)
      const w = [...s.runOrder].reverse().find((k) => s.runs[k].whatIf?.baselineKey === a.key)
      if (w) switchRun(w)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [switchRun])

  const variant = active?.whatIf
    ? active
    : order.map((k) => runs[k]).reverse().find((r) => r.whatIf?.baselineKey === active?.key)
  const cmp = variant && base ? compareRuns(base.run, variant.run) : null

  return (
    <div className="whatif">
      <h4>What if…</h4>
      <div className="doorrow">
        <select value={chosen} onChange={(e) => setDoor(e.target.value)} aria-label="Door">
          <optgroup label="Stair doors">
            {stair.map((id) => (
              <option key={id}>{id}</option>
            ))}
          </optgroup>
          <optgroup label="Other doors">
            {others.map((id) => (
              <option key={id}>{id}</option>
            ))}
          </optgroup>
        </select>
        <select value={state} onChange={(e) => setState(e.target.value as DoorState)} aria-label="State">
          {STATES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>
      <label className="check">
        <input type="checkbox" checked={sprinklers} onChange={(e) => setSprinklers(e.target.checked)} />
        Sprinklers
      </label>
      <button className="run" disabled={!base || !chosen || !!busy} onClick={() => void runWhatIf(chosen, state, sprinklers)}>
        {busy ?? 'Run what-if'}
      </button>
      {err && <p className="err">{err}</p>}
      {cmp && variant && (
        <p className="whatif-card" style={{ color: cmp.dT90 != null ? (cmp.dT90 > 0 || cmp.dTrapped > 0 ? '#f87171' : '#4ade80') : cmp.dTrapped > 0 ? '#f87171' : undefined }}>
          t90 {fmt(cmp.t90[0])} → {fmt(cmp.t90[1])}
          {cmp.dT90 != null ? ` (${signed(cmp.dT90)})` : ''}, trapped {base!.run.metrics.trapped} → {variant.run.metrics.trapped}
        </p>
      )}
    </div>
  )
}
