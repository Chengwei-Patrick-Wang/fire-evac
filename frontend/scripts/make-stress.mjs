// Stress fixtures: a 2-floor, 60 x 30 m, 26-room-per-floor campus with 300 agents and smoke on both floors.
//   node scripts/make-stress.mjs [--clinic]  ->  .fixtures/stress.building.json, .fixtures/stress.run.json
// Load them in the app with "Open file" (building first, then run). Seeded (mulberry32, seed 1).
//
// Measurements (Step 6 of plan E18):
//   bench-replay: run `node scripts/bench-replay.mjs`; the result is recorded in the plan.
//   FPS: not measured unattended (no browser). Run `npm run build && npm run preview`, open
//   http://localhost:4173/?perf, load both files, play at 10x, then `await __fps(10)` with default layers,
//   then with heatmap and trails on. Fixes to apply in order if below 30 FPS: room labels off when > 40 rooms
//   (applied), queue-ring labels unmount while n < 2, Trails reuse Float32Arrays, Canvas dpr [1, 1.5].
// Clinic-scale results (plan E27), Windows laptop, viewport 1440x900:
//   fixture: 266 rooms, 264 doors, 3 stair groups, 300 agents, 165 x 30 m.
//   Before (not re-measured; the plan's estimate): about 530 draw calls, about 270 <Html> labels.
//   After (Steps 6-8: dpr [1, 1.5], setTimers only on change, instanced queue rings with a pool of 20 labels,
//   merged floor meshes): calls 28 (29 with trails), triangles 115k, html 0 while nobody queues.
//   SwiftShader (ANGLE Vulkan SwiftShader): default avg 15.3 / 1% low 10.7; rotate 16.5 / 14.4; trails 15.2 / 10.7.
//   GPU (ANGLE NVIDIA GeForce RTX 4060, D3D11): default 144.0 / 138.1; rotate 144.0 / 139.9; trails 144.0 / 139.4 (display cap).
//   bench-replay: clinic: index 7 ms; per tick avg 0.039 ms, max 2.9 ms. Default stress: index 5 ms, avg 0.009 ms.
//   Step 9 (label LOD, Trails arrays) skipped: every GPU case is above 30 FPS.
import { mkdirSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

function mulberry32(a) {
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
const rnd = mulberry32(1)
const between = (a, b) => a + (b - a) * rnd()
const r2 = (v) => Math.round(v * 100) / 100

const CLINIC = process.argv.includes('--clinic')
const SIZE = CLINIC
  ? { id: 'clinic-scale', name: 'Clinic-scale stress (synthetic)', out: 'clinic', ncol: 66, rw: 2.5, stairCols: [0, 33, 65], kitchenCol: 30 }
  : { id: 'stress-campus', name: 'Stress campus (synthetic)', out: 'stress', ncol: 12, rw: 5, stairCols: [0, 11], kitchenCol: 5 }
const NCOL = SIZE.ncol
const RW = SIZE.rw
const W = NCOL * RW
const H = 30
const CY0 = 13.5
const CY1 = 16.5
const CMID = 15
const T = 0.2
const ELEV = [0, 3.5]
const rect = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
const roomX = (i) => i * RW + RW / 2

function floor(fi) {
  const id = `F${fi + 1}`
  const rooms = [{ id: `${id}-C`, name: 'Corridor', type: 'corridor', polygon: rect(0, CY0, W, CY1) }]
  const doors = []
  const stairs = []
  const exits = []
  const gaps = []
  for (let i = 0; i < NCOL; i++) {
    for (const north of [false, true]) {
      const stairIdx = north ? SIZE.stairCols.indexOf(i) : -1
      const isStair = stairIdx >= 0
      const rid = `${id}-${north ? 'N' : 'S'}${i + 1}`
      const type = isStair ? 'stair' : !north && i === SIZE.kitchenCol && fi === 0 ? 'kitchen' : 'office'
      const poly = north ? rect(i * RW, CY1, (i + 1) * RW, H) : rect(i * RW, 0, (i + 1) * RW, CY0)
      rooms.push({ id: rid, name: isStair ? `Stair ${'ABC'[stairIdx]}` : rid, type, polygon: poly })
      const wy = north ? CY1 : CY0
      const cx = roomX(i)
      gaps.push([wy, cx - 0.5, cx + 0.5])
      doors.push({
        id: `${id}-D${north ? 'N' : 'S'}${i + 1}`,
        a: [cx - 0.5, wy],
        b: [cx + 0.5, wy],
        width: 1,
        fireDoor: isStair,
        state: isStair ? 'closed' : 'open',
        rect: rect(cx - 0.5, wy - T, cx + 0.5, wy + T),
        connects: [rid, `${id}-C`],
      })
      if (isStair) {
        const g = `S${'ABC'[stairIdx]}`
        stairs.push({ id: `${g}${fi + 1}`, group: g, room: rid, polygon: poly })
      }
    }
  }
  if (fi === 0) {
    exits.push({ id: 'E1', name: 'West exit', door: 'E1', polygon: rect(-1, CY0, 0, CY1) })
    exits.push({ id: 'E2', name: 'East exit', door: 'E2', polygon: rect(W, CY0, W + 1, CY1) })
  }
  // walls as thin holes in one polygon per floor
  const holes = []
  for (let k = 1; k < NCOL; k++) {
    holes.push(rect(k * RW - T / 2, 0, k * RW + T / 2, CY0))
    holes.push(rect(k * RW - T / 2, CY1, k * RW + T / 2, H))
  }
  for (const wy of [CY0, CY1]) {
    const g = gaps.filter((q) => q[0] === wy).sort((a, b) => a[1] - b[1])
    let x = 0
    for (const [, a, b] of g) {
      if (a > x) holes.push(rect(x, wy - T / 2, a, wy + T / 2))
      x = b
    }
    if (x < W) holes.push(rect(x, wy - T / 2, W, wy + T / 2))
  }
  return {
    id,
    level: String(fi),
    elevation: ELEV[fi],
    height: 3.5,
    walkable: [{ outer: rect(0, 0, W, H), holes }],
    rooms,
    doors,
    stairs,
    exits,
  }
}

const building = {
  version: 'building/v0',
  id: SIZE.id,
  name: SIZE.name,
  source: 'synthetic',
  credits: 'Synthetic stress-test building.',
  floors: [floor(0), floor(1)],
}

// ---- agents ----
const FR = 0.5
const NF = 600
const NA = 300
const kitchen = [roomX(SIZE.kitchenCol), CY0 / 2]
const agents = []
const tracks = []
const events = []
const exitT = []
const exitCounts = { E1: 0, E2: 0 }
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1])

function walk(tr, t, from, pts, fl, v) {
  let p = from
  for (const q of pts) {
    const dt = dist(p, q) / v
    if (dt > 0) tr.push({ t0: t, t1: t + dt, from: p, to: q, fl, st: 1 })
    t += dt
    p = q
  }
  return { t, p }
}

for (let fi = 0; fi < 2; fi++) {
  for (let k = 0; k < NA / 2; k++) {
    const idx = fi * (NA / 2) + k
    // pick a non-stair room: columns 0..11, south or north; north corner columns are stairs
    let col = Math.floor(rnd() * NCOL)
    let north = rnd() < 0.5
    if (north && SIZE.stairCols.includes(col)) north = false
    const p = [r2(col * RW + between(0.5, RW - 0.5)), r2(north ? between(CY1 + 0.5, H - 0.5) : between(0.5, CY0 - 0.5))]
    const room = `F${fi + 1}-${north ? 'N' : 'S'}${col + 1}`
    const u = rnd()
    const profile = u < 0.85 ? 'typical' : u < 0.95 ? 'older' : 'visitor'
    const v0 = r2(between(1.0, 1.5))
    const delay = r2(between(5, 60))
    agents.push({ idx, profile, floor: `F${fi + 1}`, room, v0, startDelay: delay })
    const tr = [{ t0: 0, t1: delay, from: p, to: p, fl: fi, st: 0 }]
    const wy = north ? CY1 : CY0
    const cx = roomX(col)
    let t = delay
    let cur = p
    ;({ t, p: cur } = walk(tr, t, cur, [[cx, wy], [cx, CMID]], fi, v0))
    const west = cx < W / 2
    if (fi === 0) {
      const ex = west ? 'E1' : 'E2'
      ;({ t, p: cur } = walk(tr, t, cur, [[west ? -0.5 : W + 0.5, CMID]], 0, v0))
      events.push({ t: r2(t), type: 'exit', idx, exit: ex })
      exitCounts[ex]++
    } else {
      let si = 0
      for (let j = 1; j < SIZE.stairCols.length; j++)
        if (Math.abs(roomX(SIZE.stairCols[j]) - cx) < Math.abs(roomX(SIZE.stairCols[si]) - cx)) si = j
      const sx = roomX(SIZE.stairCols[si])
      const grp = `S${'ABC'[si]}`
      ;({ t, p: cur } = walk(tr, t, cur, [[sx, CMID], [sx, CY1], [sx, 23.25]], 1, v0))
      tr.push({ t0: t, t1: t + 10, from: cur, to: cur, fl: 1, st: 3 })
      const enter = t
      t += 10
      events.push({ t: r2(enter), type: 'stair', idx, floor: 'F2', group: grp, to: 'F1', enter: r2(enter), arrive: r2(t) })
      ;({ t, p: cur } = walk(tr, t, cur, [[sx, CY1], [sx, CMID]], 0, v0))
      const exW = sx < W / 2
      const ex = exW ? 'E1' : 'E2'
      ;({ t, p: cur } = walk(tr, t, cur, [[exW ? -0.5 : W + 0.5, CMID]], 0, v0))
      events.push({ t: r2(t), type: 'exit', idx, exit: ex })
      exitCounts[ex]++
    }
    exitT.push(t)
    tr.end = t
    tracks.push(tr)
  }
}
events.sort((a, b) => a.t - b.t)

const frames = []
for (let f = 0; f < NF; f++) {
  const t = f * FR
  const a = []
  tracks.forEach((tr, idx) => {
    if (t >= tr.end) return
    const s = tr.find((q) => t >= q.t0 && t < q.t1) ?? tr[tr.length - 1]
    const k = s.t1 > s.t0 ? (t - s.t0) / (s.t1 - s.t0) : 0
    a.push([idx, r2(s.from[0] + (s.to[0] - s.from[0]) * k), r2(s.from[1] + (s.to[1] - s.from[1]) * k), s.fl, s.st])
  })
  frames.push({ t, a })
}

// ---- smoke ----
const CELL = 0.5
const COLS = Math.round(W / CELL)
const ROWS = 60
function smokeLayer(floorId, sources) {
  const fr = []
  for (let t = 0; t < NF * FR; t += 2) {
    const g = new Uint8Array(COLS * ROWS)
    for (const { c, t0, speed } of sources) {
      if (t < t0) continue
      const r = (t - t0) * speed
      for (let j = 0; j < ROWS; j++)
        for (let i = 0; i < COLS; i++) {
          const d = Math.hypot((i + 0.5) * CELL - c[0], (j + 0.5) * CELL - c[1])
          const v = d <= r ? 80 : d < r + 3 ? 80 * (1 - (d - r) / 3) : 0
          if (v > g[j * COLS + i]) g[j * COLS + i] = Math.round(v)
        }
    }
    fr.push({ t, d: Buffer.from(g).toString('base64') })
  }
  return { floor: floorId, origin: [0, 0], cell: CELL, cols: COLS, rows: ROWS, interval: 2, frames: fr }
}
const smoke = [
  smokeLayer('F1', [{ c: kitchen, t0: 10, speed: 0.5 }]),
  smokeLayer('F2', SIZE.stairCols.map((c) => ({ c: [roomX(c), 23.25], t0: 90, speed: 0.3 }))),
]

exitT.sort((a, b) => a - b)
const q = (f) => (exitT.length >= Math.ceil(NA * f) ? r2(exitT[Math.ceil(NA * f) - 1]) : null)
const run = {
  version: 'run/v0',
  id: 'stress-run',
  buildingId: SIZE.id,
  seed: 1,
  frameInterval: FR,
  floors: ['F1', 'F2'],
  agents,
  frames,
  smoke,
  fire: { floor: 'F1', x: kitchen[0], y: kitchen[1], hrr: [[0, 0], [60, 1500], [300, 1500]] },
  events,
  metrics: {
    agents: NA,
    evacuated: exitT.length,
    trapped: 0,
    inStairs: 0,
    remaining: NA - exitT.length,
    t50: q(0.5),
    t90: q(0.9),
    t100: q(1),
    exitCounts,
  },
}

const out = join(dirname(fileURLToPath(import.meta.url)), '..', '.fixtures')
mkdirSync(out, { recursive: true })
for (const [name, data] of [[`${SIZE.out}.building.json`, building], [`${SIZE.out}.run.json`, run]]) {
  const p = join(out, name)
  writeFileSync(p, JSON.stringify(data))
  console.log(`${name}: ${(statSync(p).size / 1e6).toFixed(2)} MB`)
}
const nr = building.floors.reduce((n, f) => n + f.rooms.length, 0)
const nd = building.floors.reduce((n, f) => n + f.doors.length, 0)
console.log(`${nr} rooms, ${nd} doors, ${SIZE.stairCols.length} stair groups, ${NA} agents, ${W} x ${H} m`)
