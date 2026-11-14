import { create } from 'zustand'
import type { Run, SmokeLayer } from '../data/types'
import { b64ToBytes } from '../model/decode'
import { nearestIndex } from './runIndex'

interface Cache {
  times: Float64Array
  i: number
  bytes: Uint8Array | null
}
const caches = new WeakMap<SmokeLayer, Cache>()

/** Smoke density (0-100) at a point of one floor at time t. */
export function smokeDensityAt(run: Run, floorId: string, x: number, y: number, t: number): number {
  const layer = run.smoke?.find((l) => l.floor === floorId)
  if (!layer || layer.frames.length === 0) return 0
  let c = caches.get(layer)
  if (!c) {
    c = { times: Float64Array.from(layer.frames.map((f) => f.t)), i: -1, bytes: null }
    caches.set(layer, c)
  }
  if (t < c.times[0]) return 0
  const i = nearestIndex(c.times, t)
  if (i !== c.i || !c.bytes) {
    c.bytes = b64ToBytes(layer.frames[i].d)
    c.i = i
  }
  if (c.bytes.length !== layer.cols * layer.rows) return 0
  const col = Math.floor((x - layer.origin[0]) / layer.cell)
  const row = Math.floor((y - layer.origin[1]) / layer.cell)
  if (col < 0 || row < 0 || col >= layer.cols || row >= layer.rows) return 0
  return c.bytes[row * layer.cols + col]
}

/** Visibility in meters; 30 reads as "30 m or more". */
export function visibility(d: number): number {
  return d <= 0 ? 30 : Math.min(30, 100 / d)
}

export const useAgentView = create<{ vis: number; speed: number; desired: number; status: string }>(() => ({
  vis: 30,
  speed: 0,
  desired: 0,
  status: 'not moving yet',
}))
