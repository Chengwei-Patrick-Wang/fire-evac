import { useMemo } from 'react'
import { useApp } from '../store/app'
import type { LoadedRun } from '../store/app'
import { useThrottledT } from '../store/clock'
import { nearestIndex, sampleAgent } from '../replay/runIndex'
import type { AgentSample } from '../replay/runIndex'
import { QUEUE_RADIUS, queueCounts, queueTargets } from '../replay/queues'
import type { QueueTarget } from '../replay/queues'
import { doorLabels } from '../model/spots'
import { floorName } from '../model/floors'
import type { Building } from '../data/types'

/** People queued at a door or stair: a warning from 5, critical from 15 (the colours of QueueRings' rings). */
export const QUEUE_WARN = 5
export const QUEUE_CRIT = 15
export const MAX_ALERTS = 5

export const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`

export interface Alert {
  key: string
  target: QueueTarget
  n: number
  level: 'critical' | 'warning'
  title: string
  reason: string
}

export interface LiveStats {
  /** the clock time these numbers are for */
  t: number
  /** every agent of the run, on every floor */
  n: number
  out: number
  inside: number
  trapped: number
  waiting: number
  targets: QueueTarget[]
  /** moving people within 2 m of each target (queueCounts at the frame nearest t), in `targets` order */
  counts: Uint16Array
  /** people queued per floor id, each counted once even when they stand by both a door and a stair */
  queuedByFloor: Map<string, number>
  /** targets with 5 or more queued (all of them; `alerts` lists the largest few) */
  chokepoints: number
  alerts: Alert[]
}

const targetCache = new WeakMap<Building, QueueTarget[]>()
function targetsFor(b: Building): QueueTarget[] {
  let t = targetCache.get(b)
  if (!t) targetCache.set(b, (t = queueTargets(b)))
  return t
}

/** A door or stair in words, never its raw id. */
function targetName(b: Building, t: QueueTarget): string {
  if (t.kind === 'stair') {
    const s = b.floors.find((f) => f.id === t.floorId)?.stairs.find((x) => x.id === t.id)
    return s?.group ? `Stair ${s.group}` : 'Stair'
  }
  return doorLabels(b).get(t.id)?.label ?? 'Door'
}

function near(t: QueueTarget, x: number, y: number): boolean {
  if (t.box) {
    const dx = Math.max(t.box[0] - x, 0, x - t.box[2])
    const dy = Math.max(t.box[1] - y, 0, y - t.box[3])
    return Math.hypot(dx, dy) <= QUEUE_RADIUS
  }
  return Math.hypot(x - t.cx, y - t.cy) <= QUEUE_RADIUS
}

function compute(lr: LoadedRun, building: Building, t: number): LiveStats {
  const ix = lr.index
  const floors = lr.run.floors
  const targets = targetsFor(building)
  let out = 0
  let inside = 0
  let waiting = 0
  let trapped = 0
  const s: AgentSample = { x: 0, y: 0, fl: 0, st: 0, trapped: false }
  for (let i = 0; i < ix.nAgents; i++) {
    // Out means exitT < t, as in ReplaySummary.
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
  const frame = nearestIndex(ix.times, t)
  const counts = queueCounts(ix, building, floors, frame, targets)
  const queuedByFloor = new Map<string, number>()
  if (frame >= 0 && frame < ix.nFrames) {
    const byFloor = floors.map((id) => targets.filter((x) => x.floorId === id))
    const base = frame * ix.nAgents
    for (let a = 0; a < ix.nAgents; a++) {
      const k = base + a
      if (ix.st[k] !== 1 || ix.fl[k] < 0) continue
      const f = ix.fl[k]
      const list = byFloor[f]
      if (list && list.some((tg) => near(tg, ix.x[k], ix.y[k]))) queuedByFloor.set(floors[f], (queuedByFloor.get(floors[f]) ?? 0) + 1)
    }
  }
  const order: number[] = []
  for (let i = 0; i < counts.length; i++) if (counts[i] >= QUEUE_WARN) order.push(i)
  order.sort((a, b) => counts[b] - counts[a] || a - b)
  const alerts: Alert[] = order.slice(0, MAX_ALERTS).map((i) => {
    const tg = targets[i]
    const n = counts[i]
    const level = n >= QUEUE_CRIT ? 'critical' : 'warning'
    return {
      key: `${tg.kind}-${tg.floorId}-${tg.id}`,
      target: tg,
      n,
      level,
      title: `${floorName(building, tg.floorId)} · ${targetName(building, tg)}`,
      reason: `${n} people queued within 2 m · ${level}`,
    }
  })
  return { t, n: ix.nAgents, out, inside, trapped, waiting, targets, counts, queuedByFloor, chokepoints: order.length, alerts }
}

// One computation per active run and time, shared by every reader of the same render (the last result is kept here).
const last: { lr: LoadedRun | null; building: Building | null; t: number; value: LiveStats | null } = { lr: null, building: null, t: NaN, value: null }

function statsFor(lr: LoadedRun, building: Building, t: number): LiveStats {
  if (last.value && last.lr === lr && last.building === building && last.t === t) return last.value
  const value = compute(lr, building, t)
  Object.assign(last, { lr, building, t, value })
  return value
}

/**
 * Live numbers for the active run at the clock time, refreshed twice a second. They count every agent on every floor and
 * never read `visibleFloors`: hiding a floor must not change what the analytics say. Null with no run or building.
 */
export function useLiveStats(): LiveStats | null {
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : undefined))
  const building = useApp((s) => s.building)
  const t = useThrottledT(500)
  return useMemo(() => (lr && building ? statsFor(lr, building, t) : null), [lr, building, t])
}
