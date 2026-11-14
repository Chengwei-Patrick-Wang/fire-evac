import { useEffect } from 'react'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import Scene from './Scene'

export default function SplitView({ leftKey, rightKey }: { leftKey: string; rightKey: string }) {
  const runs = useApp((s) => s.runs)
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
  if (!l || !r) return null
  const fmt = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v)} s`)
  const pane = (k: string, id: string) => (
    <div className="pane">
      <Scene runKey={k} paneId={id} />
      <div className="pane-caption">
        {runs[k].label} · t90 {fmt(runs[k].run.metrics?.t90)}
      </div>
    </div>
  )
  return (
    <div className="splitview">
      {pane(leftKey, 'L')}
      {pane(rightKey, 'R')}
    </div>
  )
}
