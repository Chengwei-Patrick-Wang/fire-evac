// Builds test fixtures in frontend/.fixtures/ from public/demo/run.example.json.
// Usage (from frontend/): node scripts/make-fixtures.mjs
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = JSON.parse(readFileSync(join(root, 'public/demo/run.example.json'), 'utf8'))
const out = join(root, '.fixtures')
mkdirSync(out, { recursive: true })
const clone = (o) => JSON.parse(JSON.stringify(o))

// stress: 6x agents, all present in all 1,200 frames, positions looped from source frames.
{
  const COPIES = 6
  const N = 1200
  const nSrc = src.agents.length
  const nsf = src.frames.length
  // last known row per source agent per frame (fill gaps with the previous row)
  const rows = src.agents.map(() => new Array(nsf).fill(null))
  src.frames.forEach((f, fi) => {
    for (const r of f.a) if (r[4] >= 0 && rows[r[0]]) rows[r[0]][fi] = r
  })
  for (const arr of rows) {
    let prev = arr.find((r) => r) ?? [0, 1, 1, 0, 1]
    for (let i = 0; i < nsf; i++) {
      if (arr[i]) prev = arr[i]
      else arr[i] = prev
    }
  }
  const run = clone({ ...src, frames: [], events: [] })
  run.id = 'stress'
  run.agents = []
  for (let c = 0; c < COPIES; c++)
    for (const a of src.agents) run.agents.push({ ...a, idx: c * nSrc + a.idx, startDelay: 0 })
  run.metrics.agents = run.agents.length
  const dt = src.frameInterval
  for (let f = 0; f < N; f++) {
    const a = []
    for (let c = 0; c < COPIES; c++)
      for (let s = 0; s < nSrc; s++) {
        const r = rows[s][(f + c * 37) % nsf]
        a.push([c * nSrc + s, r[1], r[2], r[3], 1])
      }
    run.frames.push({ t: +(f * dt).toFixed(2), a })
  }
  writeFileSync(join(out, 'stress.run.json'), JSON.stringify(run))
}

// floorchange: first F2 agent moves to floor index 0 from t = 20 s on, with a position jump.
{
  const run = clone(src)
  run.id = 'floorchange'
  const f2 = run.floors.indexOf('F2')
  const who = run.agents.find((a) => a.floor === 'F2')
  if (who) {
    for (const f of run.frames)
      if (f.t >= 20)
        for (const r of f.a)
          if (r[0] === who.idx && r[4] >= 0) {
            r[3] = 0
            r[1] = +(r[1] + 4).toFixed(2)
            r[2] = +(r[2] + 2).toFixed(2)
          }
    console.log(`floorchange: agent ${who.idx} (F2 index ${f2}) -> floor 0 from t=20`)
  }
  writeFileSync(join(out, 'floorchange.run.json'), JSON.stringify(run))
}

// nosmoke: no smoke, no hrr, no heatmaps or door metrics.
{
  const run = clone(src)
  run.id = 'nosmoke'
  run.smoke = []
  run.fire.hrr = []
  delete run.metrics.heatmaps
  delete run.metrics.doors
  writeFileSync(join(out, 'nosmoke.run.json'), JSON.stringify(run))
}
// access: wheelchair users on F2 waiting for help (made-up values, UI only; never copy into public/demo/).
{
  const run = clone(src)
  run.id = 'access'
  const bld = JSON.parse(readFileSync(join(root, 'public/demo/building.example.json'), 'utf8'))
  const st = bld.floors.find((f) => f.id === 'F2').stairs[0]
  const n = st.polygon.length
  const cx = st.polygon.reduce((s, p) => s + p[0], 0) / n
  const cy = st.polygon.reduce((s, p) => s + p[1], 0) / n
  const chosen = run.agents.filter((a) => a.floor === 'F2').filter((_, i) => i % 20 === 0)
  for (const a of chosen) {
    a.profile = 'wheelchair'
    run.events.push({ t: 60, type: 'wait', idx: a.idx, floor: 'F2', x: cx, y: cy, until: 240 })
  }
  run.events.sort((a, b) => a.t - b.t)
  const pOf = new Map(run.agents.map((a) => [a.idx, a.profile]))
  const profiles = {}
  for (const a of run.agents) {
    profiles[a.profile] ??= { agents: 0, evacuated: 0, trapped: 0, t50: null, t90: null, t100: null }
    profiles[a.profile].agents++
  }
  for (const e of run.events) {
    if (e.type === 'trapped' && profiles[pOf.get(e.idx)]) profiles[pOf.get(e.idx)].trapped++
  }
  for (const [name, p] of Object.entries(profiles)) {
    const ts = run.events
      .filter((e) => e.type === 'exit' && pOf.get(e.idx) === name)
      .map((e) => e.t)
      .sort((a, b) => a - b)
    p.evacuated = ts.length
    const at = (f) => {
      const k = Math.ceil(f * p.agents)
      return k >= 1 && ts.length >= k ? ts[k - 1] : null
    }
    p.t50 = at(0.5)
    p.t90 = at(0.9)
    p.t100 = at(1)
  }
  run.metrics.profiles = profiles
  run.metrics.assist = { waiting: chosen.length, meanWait: 180, maxWait: 180, personSeconds: chosen.length * 180 }
  writeFileSync(join(out, 'access.run.json'), JSON.stringify(run))
}
// exposure: example batch with made-up smoke seconds and what-if entries (UI only; keeps placeholder: true).
{
  const batch = clone(JSON.parse(readFileSync(join(root, 'public/demo/batch.example.json'), 'utf8')))
  batch.id = 'exposure'
  batch.runs.forEach((r, i) => {
    r.smokeSeconds = 1500 + (i % 7) * 60
  })
  const n = batch.runs.length
  const mean = batch.runs.reduce((s, r) => s + r.smokeSeconds, 0) / n
  const why = (label, d, extra) => `${label}: 90% out ${d} s later on average (slower in 3 of ${n} fires); ${extra}`
  batch.whatIf = [
    { id: 'proppedStairs', label: 'Stair doors propped open', doors: [], sprinklers: false, n, dT90: 0.2, dT90Min: -3, dT90Max: 9, slower: 3, faster: 1, dTrapped: 0, dDosed: 0.3, dSmokeSeconds: +(mean * 0.22).toFixed(0), why: why('Stair doors propped open', 0, '+366 person-seconds in smoke, +0.3 people at an illustrative smoke dose of 1, +0.0 trapped per fire.') },
    { id: 'blockedExit', label: 'Exit E1 blocked', doors: [], sprinklers: false, n, dT90: 64, dT90Min: 10, dT90Max: 120, slower: n, faster: 0, dTrapped: 2, why: why('Exit E1 blocked', 64, '+2.0 trapped per fire.') },
    { id: 'sprinklers', label: 'Sprinklers on', doors: [], sprinklers: true, n, dT90: -0.5, dT90Min: -4, dT90Max: 3, slower: 10, faster: 20, dTrapped: 0, dSmokeSeconds: -120, why: why('Sprinklers on', -0.5, '-120 person-seconds in smoke, +0.0 trapped per fire.') },
  ]
  writeFileSync(join(out, 'exposure.batch.json'), JSON.stringify(batch))
}
// fixes: example batch with made-up measured fixes (UI only; keeps placeholder: true), plus a runs folder for sync-demo.
{
  const batch = clone(JSON.parse(readFileSync(join(root, 'public/demo/batch.example.json'), 'utf8')))
  batch.id = 'fixes'
  const n = 12
  batch.fixes = [
    { id: 'widen-DSB2', kind: 'widen', label: 'Widen Stair SB door from 1.00 m to 1.50 m', door: 'DSB2', floor: 'F2', width: 1.5, n, dT90: -12, dT90Min: -20, dT90Max: 1, slower: 1, faster: 10, dTrapped: -0.3, dSmokeSeconds: -300, smokePct: -18, helps: true,
      why: 'Widen Stair SB door from 1.00 m to 1.50 m: 90% out 12 s sooner on average and 18% less time in smoke across 12 fires (faster in 10); -0.3 trapped per fire.' },
    { id: 'sprinklers', kind: 'sprinklers', label: 'Sprinklers on', sprinklers: true, n, dT90: -2, dSmokeSeconds: -45, smokePct: -3, dTrapped: -1.9, helps: true,
      why: 'Sprinklers on: 90% out 2 s sooner on average and 3% less time in smoke across 12 fires; -1.9 trapped per fire.' },
    { id: 'selfClosers', kind: 'selfClosers', label: 'Self-closers on stair doors (vs propped open)', doors: { DSA1: 'closed' }, derivedFrom: 'whatIf.proppedStairs', n, dT90: 0, dSmokeSeconds: -394, smokePct: null, helps: true,
      why: 'Self-closers on stair doors (vs propped open): 90% out 0 s sooner on average and 394 fewer person-seconds in smoke across 12 fires.' },
    { id: 'widen-DSA1', kind: 'widen', label: 'Widen Stair SA door from 1.00 m to 1.50 m', door: 'DSA1', floor: 'F1', width: 1.5, n, dT90: 18, smokePct: -3, dTrapped: 0.5, helps: false,
      why: 'Widen Stair SA door from 1.00 m to 1.50 m: 90% out 18 s later on average across 12 fires; +0.5 trapped per fire.' },
  ]
  batch.fixesSkipped = [{ id: 'widen-DSA2', reason: 'Door DSA2: the wider opening reaches a third room' }]
  writeFileSync(join(out, 'fixes.batch.json'), JSON.stringify(batch))
  const real = clone(batch)
  delete real.placeholder
  real.id = 'batch-example-office-example-kitchen-fire'
  mkdirSync(join(out, 'runs'), { recursive: true })
  writeFileSync(join(out, 'runs', 'batch-example-office.json'), JSON.stringify(real))
}
// ranges: made-up seed ranges for the UI only.
{
  const run = clone(src)
  run.id = 'ranges'
  const r2 = (v) => +v.toFixed(2)
  const sr = { seeds: [1, 2, 3, 4, 5] }
  for (const k of ['t50', 't90', 't100']) {
    const v = run.metrics[k]
    sr[k] = v == null ? { min: null, median: null, max: null, missing: 5 } : { min: r2(v * 0.97), median: r2(v), max: r2(v * 1.08), missing: 0 }
  }
  const m = run.metrics
  sr.evacuated = { min: m.agents - 2, median: m.evacuated, max: m.agents, missing: 0 }
  sr.trapped = { min: 0, median: m.trapped, max: m.trapped + 2, missing: 0 }
  run.metrics.seedRange = sr
  writeFileSync(join(out, 'ranges.run.json'), JSON.stringify(run))
  const batch = clone(JSON.parse(readFileSync(join(root, 'public/demo/batch.example.json'), 'utf8')))
  batch.id = 'ranges'
  for (const r of batch.rooms) {
    if (r.riskT90 != null) r.riskT90Range = { min: r.riskT90 - 6, median: r.riskT90, max: r.riskT90 + 9 }
    else r.riskT90Range = null
    if (r.riskTrapped != null) r.riskTrappedRange = { min: Math.max(0, r.riskTrapped - 1), median: r.riskTrapped, max: r.riskTrapped + 1 }
  }
  for (const d of batch.doors) d.scoreRange = { min: +(d.score * 0.9).toFixed(1), median: d.score, max: +Math.min(100, d.score * 1.05).toFixed(1) }
  const in3 = [3, 2, 3]
  batch.top.forEach((t, i) => {
    t.seedsInTop3 = in3[i] ?? 3
    t.seeds = 3
  })
  batch.stability = { seeds: [1, 2, 3], top3: ['DSB2', 'DSA2', 'DSA1'], heldIn: 2, n: 3, stable: false, why: 'The top 3 weak spots hold in 2 of 3 seeds: Stair SB door, Stair SA door, Stair SA door. Stair SB door ranks first in 3 of 3.' }
  writeFileSync(join(out, 'ranges.batch.json'), JSON.stringify(batch))
}
console.log('wrote', out)
