import type { Building } from '../data/types'
import type { RunIndex } from './runIndex'

const R = 2 + 1e-4

export interface QueueTarget {
  id: string
  floorId: string
  kind: 'door' | 'stair'
  /** door: midpoint; stair: bounding box centre */
  cx: number
  cy: number
  box?: [number, number, number, number]
}

/** Doors first, then stairs, in building order. */
export function queueTargets(b: Building): QueueTarget[] {
  const out: QueueTarget[] = []
  for (const f of b.floors)
    for (const d of f.doors)
      out.push({ id: d.id, floorId: f.id, kind: 'door', cx: (d.a[0] + d.b[0]) / 2, cy: (d.a[1] + d.b[1]) / 2 })
  for (const f of b.floors)
    for (const s of f.stairs ?? []) {
      let x0 = Infinity
      let y0 = Infinity
      let x1 = -Infinity
      let y1 = -Infinity
      for (const p of s.polygon) {
        x0 = Math.min(x0, p[0])
        y0 = Math.min(y0, p[1])
        x1 = Math.max(x1, p[0])
        y1 = Math.max(y1, p[1])
      }
      out.push({ id: s.id, floorId: f.id, kind: 'stair', cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, box: [x0, y0, x1, y1] })
    }
  return out
}

/** Moving (status 1) agents near each target at one frame. Order = queueTargets(building). */
export function queueCounts(
  ix: RunIndex,
  building: Building,
  floors: string[],
  frame: number,
  targets: QueueTarget[] = queueTargets(building),
): Uint16Array {
  const counts = new Uint16Array(targets.length)
  if (frame < 0 || frame >= ix.nFrames) return counts
  const fiOf = targets.map((t) => floors.indexOf(t.floorId))
  const base = frame * ix.nAgents
  for (let a = 0; a < ix.nAgents; a++) {
    const k = base + a
    if (ix.st[k] !== 1 || ix.fl[k] < 0) continue
    const x = ix.x[k]
    const y = ix.y[k]
    const f = ix.fl[k]
    for (let i = 0; i < targets.length; i++) {
      if (fiOf[i] !== f) continue
      const t = targets[i]
      let d: number
      if (t.box) {
        const dx = Math.max(t.box[0] - x, 0, x - t.box[2])
        const dy = Math.max(t.box[1] - y, 0, y - t.box[3])
        d = Math.hypot(dx, dy)
      } else d = Math.hypot(x - t.cx, y - t.cy)
      if (d <= R) counts[i]++
    }
  }
  return counts
}
