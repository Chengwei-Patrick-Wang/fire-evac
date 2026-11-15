import type { Batch } from '../data/types'
import type { LoadedRun } from '../store/app'
import type { RunIndex } from '../replay/runIndex'

const inferredCache = new WeakMap<RunIndex, number | null>()

/**
 * The alarm's time as the run shows it. A run/v0 file carries no alarm field, but people who wait for the alarm start moving at
 * alarmTime + startDelay, while people who started from a cue (fire in their room, smoke) have a `start` event and moved sooner.
 * So the earliest "first frame moving, minus startDelay" among the people with no start event is the alarm, to within one frame.
 */
function inferred(lr: LoadedRun): number | undefined {
  const cached = inferredCache.get(lr.index)
  if (cached !== undefined) return cached ?? undefined
  const ix = lr.index
  const cued = new Set<number>()
  for (const e of lr.run.events) if (e.type === 'start' && e.idx !== undefined) cued.add(e.idx)
  const delay = new Map(lr.run.agents.map((a) => [a.idx, a.startDelay]))
  const seen = new Uint8Array(ix.nAgents)
  let best = Infinity
  for (let f = 0; f < ix.nFrames; f++) {
    const base = f * ix.nAgents
    for (let i = 0; i < ix.nAgents; i++) {
      if (seen[i] || ix.st[base + i] !== 1 || cued.has(i)) continue
      seen[i] = 1
      best = Math.min(best, ix.times[f] - (delay.get(i) ?? 0))
    }
  }
  const out = isFinite(best) ? Math.max(0, best) : null
  inferredCache.set(ix, out)
  return out ?? undefined
}

/**
 * Replay time (seconds) at which the fire alarm sounds in this run, or undefined when the run doesn't say.
 * In order: the scenario the run was made from (a live run keeps it: the "Alarm sounds after" setting), an `alarm` event if the
 * sim ever writes one, what the people in the run did (precomputed runs carry no scenario), then the batch's base scenario
 * for the same building (every precomputed run of a building was made with it).
 */
export function alarmTimeOf(lr: LoadedRun | undefined, batch?: Batch | null): number | undefined {
  if (!lr) return undefined
  const set = lr.scenario?.alarmTime
  if (typeof set === 'number' && isFinite(set)) return Math.max(0, set)
  const ev = lr.run.events.find((e) => e.type === 'alarm')
  if (ev && isFinite(ev.t)) return Math.max(0, ev.t)
  const seen = inferred(lr)
  if (seen !== undefined) return seen
  const base = batch?.base?.alarmTime
  if (batch && batch.buildingId === lr.run.buildingId && typeof base === 'number' && isFinite(base)) return Math.max(0, base)
  return undefined
}
