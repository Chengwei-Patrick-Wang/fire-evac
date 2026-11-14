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
console.log('wrote', out)
