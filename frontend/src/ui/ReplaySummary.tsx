import { useMemo } from 'react'
import { useApp } from '../store/app'
import { useClock, useThrottledT } from '../store/clock'
import { nearestIndex, sampleAgent } from '../replay/runIndex'
import type { AgentSample } from '../replay/runIndex'
import { queueCounts, queueTargets } from '../replay/queues'

const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`

/** Screen-reader text for what the 3D view draws. Only recomputed while paused, so playback is never announced. */
export default function ReplaySummary() {
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : undefined))
  const building = useApp((s) => s.building)
  const playing = useClock((s) => s.playing)
  const t = useThrottledT(500)
  const targets = useMemo(() => (building ? queueTargets(building) : []), [building])
  let text = ''
  if (lr && building && !playing) {
    const ix = lr.index
    let out = 0
    let inside = 0
    let waiting = 0
    let trapped = 0
    const s: AgentSample = { x: 0, y: 0, fl: 0, st: 0, trapped: false }
    for (let i = 0; i < ix.nAgents; i++) {
      if (t > ix.exitT[i]) {
        out++
        continue
      }
      inside++
      if (sampleAgent(ix, i, t, s)) {
        if (s.st === 2) waiting++
        if (s.trapped) trapped++
      }
    }
    text = `At ${mmss(t)}, ${out} of ${ix.nAgents} people are out and ${inside} inside, ${waiting} waiting for help and ${trapped} trapped.`
    const c = queueCounts(ix, building, lr.run.floors, nearestIndex(ix.times, t), targets)
    let best = -1
    for (let i = 0; i < c.length; i++) if (c[i] > 0 && (best < 0 || c[i] > c[best])) best = i
    if (best >= 0) text += ` Longest queue: ${c[best]} people at ${targets[best].id}.`
  }
  return (
    <p id="replay-summary" className="sr-only" aria-live="polite">
      {text}
    </p>
  )
}
