import { useApp } from '../store/app'
import { batchHeadline, readWhatIf } from '../model/exposure'

export default function WhatIfHeadline() {
  const batch = useApp((s) => s.batch)
  const list = readWhatIf(batch)
  const h = batchHeadline(batch)
  if (!list.length || !h) return null
  const main = list.find((e) => e.id === 'proppedStairs') ?? list[0]
  const others = list.filter((e) => e !== main)
  return (
    <div className="whatif-headline">
      <div className="dim">What-if over {h.n} paired fires</div>
      <div className="main">{h.main}</div>
      {h.secondary && <div className="dim">{h.secondary}</div>}
      {others.length > 0 && (
        <ul>
          {others.map((e) => (
            <li key={e.id}>{e.why}</li>
          ))}
        </ul>
      )}
      <div className="dim">Illustrative smoke model: time spent in smoke, not a prediction of injury.</div>
    </div>
  )
}
