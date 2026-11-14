import type { Run } from '../data/types'

export const PROFILE_NAMES = ['typical', 'older', 'visitor', 'cane', 'walker', 'wheelchair'] as const

export interface RunIndex {
  nAgents: number
  nFrames: number
  times: Float64Array
  /** nFrames x nAgents, keyed by agent idx */
  x: Float32Array
  y: Float32Array
  /** floor index, -1 = absent */
  fl: Int8Array
  st: Int8Array
  profile: Uint8Array
  exitT: Float64Array
  trapT: Float64Array
  last: { fl: Int8Array; x: Float32Array; y: Float32Array }
  duration: number
  cursor: number
}

export function buildRunIndex(run: Run): RunIndex {
  const nFrames = run.frames.length
  let nAgents = 0
  for (const a of run.agents) nAgents = Math.max(nAgents, a.idx + 1)
  for (const f of run.frames) for (const r of f.a) nAgents = Math.max(nAgents, r[0] + 1)
  const size = nFrames * nAgents
  const times = new Float64Array(nFrames)
  const x = new Float32Array(size)
  const y = new Float32Array(size)
  const fl = new Int8Array(size).fill(-1)
  const st = new Int8Array(size).fill(-1)
  const profile = new Uint8Array(nAgents)
  const exitT = new Float64Array(nAgents).fill(Infinity)
  const trapT = new Float64Array(nAgents).fill(Infinity)
  const last = { fl: new Int8Array(nAgents).fill(-1), x: new Float32Array(nAgents), y: new Float32Array(nAgents) }

  for (const a of run.agents) profile[a.idx] = Math.max(0, PROFILE_NAMES.indexOf(a.profile))
  for (let f = 0; f < nFrames; f++) {
    const fr = run.frames[f]
    times[f] = fr.t
    const base = f * nAgents
    for (const r of fr.a) {
      const k = base + r[0]
      x[k] = r[1]
      y[k] = r[2]
      fl[k] = r[3]
      st[k] = r[4]
      if (r[4] >= 0) {
        last.fl[r[0]] = r[3]
        last.x[r[0]] = r[1]
        last.y[r[0]] = r[2]
      } else fl[k] = -1 // already out: absent
    }
  }
  for (const e of run.events) {
    if (e.idx === undefined || e.idx < 0 || e.idx >= nAgents) continue
    if (e.type === 'exit') exitT[e.idx] = Math.min(exitT[e.idx], e.t)
    else if (e.type === 'trapped') trapT[e.idx] = Math.min(trapT[e.idx], e.t)
  }
  return {
    nAgents, nFrames, times, x, y, fl, st, profile, exitT, trapT, last,
    duration: nFrames ? times[nFrames - 1] : 0,
    cursor: 0,
  }
}

export interface AgentSample {
  x: number
  y: number
  fl: number
  st: number
  trapped: boolean
}

/** Frame i with times[i] <= t (clamped), using a moving cursor. */
function frameAt(ix: RunIndex, t: number): number {
  const n = ix.nFrames
  const ts = ix.times
  let c = ix.cursor
  if (c >= n) c = n - 1
  if (c < 0) c = 0
  if (ts[c] <= t && (c === n - 1 || t < ts[c + 1])) return c
  if (c + 2 < n && ts[c + 1] <= t && t < ts[c + 2]) return (ix.cursor = c + 1)
  if (t < ts[0]) return (ix.cursor = 0)
  let lo = 0
  let hi = n - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (ts[mid] <= t) lo = mid
    else hi = mid - 1
  }
  return (ix.cursor = lo)
}

export function sampleAgent(ix: RunIndex, idx: number, t: number, out: AgentSample): boolean {
  if (ix.nFrames === 0 || idx >= ix.nAgents) return false
  if (t > ix.exitT[idx]) return false
  const n = ix.nAgents
  const i = frameAt(ix, t)
  const j = i + 1 < ix.nFrames ? i + 1 : i
  const a = i * n + idx
  const b = j * n + idx
  const va = ix.fl[a] >= 0 && ix.st[a] >= 0
  const vb = j !== i && ix.fl[b] >= 0 && ix.st[b] >= 0
  out.trapped = t >= ix.trapT[idx]
  let w = 0
  if (j !== i) {
    const dt = ix.times[j] - ix.times[i]
    w = dt > 0 ? Math.min(1, Math.max(0, (t - ix.times[i]) / dt)) : 0
  }
  if (va && vb && ix.fl[a] === ix.fl[b]) {
    out.x = ix.x[a] + (ix.x[b] - ix.x[a]) * w
    out.y = ix.y[a] + (ix.y[b] - ix.y[a]) * w
    out.fl = ix.fl[a]
    out.st = ix.st[a]
    return true
  }
  let k = -1
  if (va && vb) k = w < 0.5 ? a : b
  else if (va) k = a
  else if (vb && w >= 0.5) k = b
  if (k >= 0) {
    out.x = ix.x[k]
    out.y = ix.y[k]
    out.fl = ix.fl[k]
    out.st = ix.st[k]
    return true
  }
  // Absent after being trapped: stay drawn at the last seen position.
  if (out.trapped && ix.last.fl[idx] >= 0) {
    out.x = ix.last.x[idx]
    out.y = ix.last.y[idx]
    out.fl = ix.last.fl[idx]
    out.st = 1
    return true
  }
  return false
}
