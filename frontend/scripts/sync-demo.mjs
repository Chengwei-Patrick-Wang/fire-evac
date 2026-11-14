// Copies contracts/*.example.json into public/demo/ and upserts public/demo/index.json.
// Runs as predev and prebuild; safe from any cwd; a missing contracts/ folder is not an error.
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// Extra runs: {run: 'data/runs/x.json', scenario: 'data/runs/x.scenario.json', label?: string, whatIf?: null | 'propped'}
const EXTRA_RUNS = []

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const demo = join(root, 'frontend', 'public', 'demo')
const contracts = join(root, 'contracts')

if (!existsSync(contracts)) {
  console.log('sync-demo: no contracts/ folder, keeping public/demo as is')
  process.exit(0)
}
mkdirSync(demo, { recursive: true })

const readJson = (p) => JSON.parse(readFileSync(p, 'utf8'))
const norm = (s) => s.replace(/\r\n/g, '\n')

function copyFile(src, name) {
  if (!existsSync(src)) {
    console.log(`missing ${src}, keeping the current copy`)
    return existsSync(join(demo, name))
  }
  const bytes = readFileSync(src)
  const dst = join(demo, name)
  if (existsSync(dst) && Buffer.compare(readFileSync(dst), bytes) === 0) {
    console.log(`unchanged ${name}`)
  } else {
    writeFileSync(dst, bytes)
    console.log(`copied ${name} (${Math.round(statSync(dst).size / 1024)} KB)`)
  }
  return true
}

const jobs = [
  { run: join(contracts, 'run.example.json'), scenario: join(contracts, 'scenario.example.json'), label: undefined, whatIf: null, unindexedScenario: true },
  ...EXTRA_RUNS.map((e) => ({
    run: join(root, e.run), scenario: join(root, e.scenario), label: e.label, whatIf: e.whatIf ?? null,
  })),
]

const building = join(contracts, 'building.example.json')
const batch = join(contracts, 'batch.example.json')
const isPrivate = (p) => /private/i.test(p.replace(root, ''))

const indexPath = join(demo, 'index.json')
const oldText = existsSync(indexPath) ? readFileSync(indexPath, 'utf8') : ''
const index = oldText ? JSON.parse(oldText) : { version: 'demo-index/v0', buildings: [], runs: [], batches: [] }
index.buildings ??= []
index.runs ??= []
index.batches ??= []

function upsert(list, entry) {
  let pos = -1
  for (let i = list.length - 1; i >= 0; i--) {
    if (list[i].id === entry.id || list[i].file === entry.file) {
      pos = i
      list.splice(i, 1)
    }
  }
  if (pos < 0) list.push(entry)
  else list.splice(pos, 0, entry)
}

// Building
if (isPrivate(building)) console.warn(`sync-demo: skipping private source ${building}`)
else if (copyFile(building, 'building.example.json') && existsSync(join(demo, 'building.example.json'))) {
  const b = readJson(join(demo, 'building.example.json'))
  if (b.private === true) console.warn('sync-demo: building is private, not indexed')
  else upsert(index.buildings, { id: b.id, name: b.name, file: 'building.example.json', credits: b.credits })
}

// Runs
for (const j of jobs) {
  if (isPrivate(j.run) || isPrivate(j.scenario)) {
    console.warn(`sync-demo: skipping private source ${j.run}`)
    continue
  }
  const name = basename(j.run)
  if (!copyFile(j.run, name)) continue
  if (j.unindexedScenario) copyFile(j.scenario, basename(j.scenario))
  const run = readJson(join(demo, name))
  const bld = index.buildings.find((b) => b.id === run.buildingId)
  if (!bld) {
    console.warn(`sync-demo: run ${run.id} building ${run.buildingId} not indexed, skipping`)
    continue
  }
  let sc = null
  if (existsSync(j.scenario)) {
    sc = readJson(j.scenario)
    if (sc.id !== run.scenarioId) sc = null
  }
  let fire
  if (sc) {
    fire = { floor: sc.fire.floor, room: sc.fire.room, x: sc.fire.x, y: sc.fire.y, type: sc.fire.type }
  } else {
    console.warn(`sync-demo: no scenario matching ${run.scenarioId} for ${run.id}`)
    fire = { floor: run.fire?.floor, room: '?', x: run.fire?.x, y: run.fire?.y, type: 'unknown' }
  }
  const type = fire.type ? fire.type[0].toUpperCase() + fire.type.slice(1) : 'Fire'
  const m = run.metrics ?? {}
  upsert(index.runs, {
    id: run.id,
    buildingId: run.buildingId,
    label: j.label ?? `${type} ${fire.room}, ${j.whatIf ? 'what-if' : 'baseline'}`,
    file: name,
    whatIf: j.whatIf,
    fire,
    doors: sc?.doors ?? {},
    metrics: { t50: m.t50 ?? null, t90: m.t90 ?? null, t100: m.t100 ?? null, evacuated: m.evacuated, trapped: m.trapped },
  })
}

// Batch
if (isPrivate(batch)) console.warn(`sync-demo: skipping private source ${batch}`)
else if (copyFile(batch, 'batch.example.json')) {
  const b = readJson(join(demo, 'batch.example.json'))
  const other = index.batches.some((x) => x.buildingId === b.buildingId && x.file !== 'batch.example.json' && x.id !== b.id)
  if (b.placeholder === true && other) {
    index.batches = index.batches.filter((x) => x.file !== 'batch.example.json')
  } else {
    const old = index.batches.find((x) => x.id === b.id || x.file === 'batch.example.json')
    upsert(index.batches, { id: b.id, buildingId: b.buildingId, file: 'batch.example.json', ...(old?.report ? { report: old.report } : {}) })
  }
}

const text = JSON.stringify(index, null, 2) + '\n'
const changed = norm(oldText) !== text
if (changed) writeFileSync(indexPath, text)
console.log(
  `index.json: ${index.buildings.length} building, ${index.runs.length} run, ${index.batches.length} batch (${changed ? 'written' : 'unchanged'})`,
)
