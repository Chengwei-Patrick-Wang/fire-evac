import { useEffect } from 'react'
import { Pencil } from 'lucide-react'
import { useApp } from '../store/app'
import type { Side } from '../store/app'
import { useClock } from '../store/clock'
import { factsLine, runFacts } from '../model/sides'
import type { Building } from '../data/types'
import Scene from './Scene'

const NAME: Record<Side, string> = { L: 'Left', R: 'Right' }

/** One pane: its 3D view, a header that says which side it is and what it runs (with an Edit button for its settings), and the run's name and t90. */
function Pane({ side, runKey, building, own }: { side: Side; runKey: string; building: Building | null; own: boolean }) {
  const lr = useApp((s) => s.runs[runKey])
  const editing = useApp((s) => s.card === 'scenario' && (s.editSide ?? 'L') === side)
  if (!lr) return null
  const fmt = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v)} s`)
  const facts = runFacts(lr, building)
  const name = NAME[side]
  return (
    <div className="pane" data-side={side}>
      <Scene runKey={runKey} paneId={side} building={own ? building : null} />
      <div className="pane-head" role="group" aria-label={`${name} simulation`}>
        <h2 className="pane-side">{name}</h2>
        <button type="button" className="pane-edit" aria-expanded={editing} aria-label={`Edit ${name.toLowerCase()} settings`} title={`Edit the ${name.toLowerCase()} simulation's settings`} onClick={() => useApp.getState().editSideOpen(side)}>
          <Pencil size={14} strokeWidth={1.75} aria-hidden="true" />
          <span>Edit</span>
        </button>
        <p className="pane-what" title={factsLine(facts)}>
          <b>{facts.building}</b>
          <span>Fire in {facts.fire}</span>
          <span>{facts.material}</span>
          <span>{facts.crowd}</span>
          <span>{facts.people}</span>
        </p>
      </div>
      <div className="pane-caption">
        {lr.label} · t90 {fmt(lr.run.metrics?.t90)}
      </div>
    </div>
  )
}

export default function SplitView({ leftKey, rightKey }: { leftKey: string; rightKey: string }) {
  const runs = useApp((s) => s.runs)
  const building = useApp((s) => s.building)
  const rightBuilding = useApp((s) => s.rightBuilding)
  const viewMode = useApp((s) => s.viewMode)
  const focusFloor = useApp((s) => s.focusFloor)
  const l = runs[leftKey]
  const r = runs[rightKey]
  const dl = l?.index.duration ?? 0
  const dr = r?.index.duration ?? 0
  useEffect(() => {
    useClock.getState().setDuration(Math.max(dl, dr))
    return () => {
      const a = useApp.getState()
      const act = a.activeRunKey ? a.runs[a.activeRunKey] : null
      if (act) useClock.getState().setDuration(act.index.duration)
    }
  }, [dl, dr])
  // One floor (or the ghost view's floor) is named by its id; a right building that has no such floor is shown whole instead.
  useEffect(() => {
    if (!rightBuilding || !focusFloor || (viewMode !== 'single' && viewMode !== 'ghost')) return
    if (rightBuilding.floors.some((f) => f.id === focusFloor)) return
    useApp.getState().setViewMode('stacked')
    useApp.getState().setNotice(`${rightBuilding.name} has no floor ${focusFloor}, so both buildings are shown whole.`)
  }, [rightBuilding, focusFloor, viewMode])
  if (!l || !r) return null
  return (
    <div className="splitview">
      <Pane side="L" runKey={leftKey} building={building} own={false} />
      <Pane side="R" runKey={rightKey} building={rightBuilding ?? building} own={!!rightBuilding} />
    </div>
  )
}
