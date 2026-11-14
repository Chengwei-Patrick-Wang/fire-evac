// Verifies public/demo/index.json and every file it lists. Exits 1 on any problem.
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const dir = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'demo')
const errors = []
const fail = (m) => errors.push(m)

function load(file, version) {
  const path = join(dir, file)
  if (!existsSync(path)) return fail(`missing file: ${file}`), null
  console.log(`${file}  ${(statSync(path).size / 1024).toFixed(1)} KB`)
  if (!file.endsWith('.json')) return null
  try {
    const j = JSON.parse(readFileSync(path, 'utf8'))
    if (version && j.version !== version) fail(`${file}: version ${j.version}, expected ${version}`)
    return j
  } catch (e) {
    return fail(`${file}: invalid JSON (${e.message})`), null
  }
}

const index = load('index.json', 'demo-index/v0')
if (index) {
  const ids = new Set()
  for (const b of index.buildings ?? []) {
    if (b.private === true) fail(`building ${b.id} is private`)
    ids.add(b.id)
    load(b.file, 'building/v0')
  }
  for (const r of index.runs ?? []) {
    if (!ids.has(r.buildingId)) fail(`run ${r.id}: unknown buildingId ${r.buildingId}`)
    const j = load(r.file, 'run/v0')
    if (j && j.buildingId !== r.buildingId) fail(`run ${r.id}: file buildingId ${j.buildingId} != ${r.buildingId}`)
  }
  for (const b of index.batches ?? []) {
    if (!ids.has(b.buildingId)) fail(`batch ${b.id}: unknown buildingId ${b.buildingId}`)
    const j = load(b.file, 'batch/v0')
    if (j && j.buildingId !== b.buildingId) fail(`batch ${b.id}: file buildingId ${j.buildingId} != ${b.buildingId}`)
    if (b.report) load(b.report)
  }
}

const priv = join(dir, 'private')
if (existsSync(priv) && readdirSync(priv, { recursive: true }).some((f) => statSync(join(priv, f)).isFile()))
  fail('public/demo/private/ holds files; Vite would copy them into dist/')

if (errors.length) {
  console.error('\ncheck-demo FAILED:\n' + errors.map((e) => '  - ' + e).join('\n'))
  process.exit(1)
}
console.log('check-demo ok')
