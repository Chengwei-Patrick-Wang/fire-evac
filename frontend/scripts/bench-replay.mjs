// Replay CPU benchmark on the stress fixtures (run `node scripts/make-stress.mjs${CL ? ' --clinic' : ''}` first).
// Steps a 10x replay at 60 ticks/s: sampleAgent for every agent per tick, plus queueCounts when the frame changes.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
let ri, q
try {
  ri = await import('../src/replay/runIndex.ts')
  q = await import('../src/replay/queues.ts')
} catch {
  console.log('bench skipped: needs Node 22.18+')
  process.exit(0)
}
const CL = process.argv.includes('--clinic')
const NAME = CL ? 'clinic' : 'stress'
let building, run
try {
  building = JSON.parse(readFileSync(join(root, `.fixtures/${NAME}.building.json`), 'utf8'))
  run = JSON.parse(readFileSync(join(root, `.fixtures/${NAME}.run.json`), 'utf8'))
} catch {
  console.log(`bench skipped: run make-stress.mjs${CL ? ' --clinic' : ''} first`)
  process.exit(0)
}

let t0 = performance.now()
const ix = ri.buildRunIndex(run)
const indexMs = performance.now() - t0

const targets = q.queueTargets(building)
const out = { x: 0, y: 0, fl: 0, st: 0, trapped: false }
const TICK = 1 / 60
const SPEED = 10
const ticks = Math.floor(ix.duration / (TICK * SPEED))
let sum = 0
let max = 0
let lastFrame = -2
for (let k = 0; k < ticks; k++) {
  const t = k * TICK * SPEED
  const s = performance.now()
  for (let i = 0; i < ix.nAgents; i++) ri.sampleAgent(ix, i, t, out)
  const fr = ri.nearestIndex(ix.times, t)
  if (fr !== lastFrame) {
    lastFrame = fr
    q.queueCounts(ix, building, run.floors, fr, targets)
  }
  const d = performance.now() - s
  sum += d
  if (d > max) max = d
}
console.log(
  `${CL ? 'clinic: ' : ''}index ${indexMs.toFixed(0)} ms; per tick avg ${(sum / Math.max(1, ticks)).toFixed(3)} ms, max ${max.toFixed(3)} ms (budget 33 ms for 30 FPS)`,
)
