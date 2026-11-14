import type { Batch, Building, BuildingInfo, DemoIndex, DemoRun, Run, Scenario } from './types'

export class ApiError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

const API = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''
const DEMO = `${import.meta.env.BASE_URL}demo/`

export type Mode = 'live' | 'static'
let mode: Mode = 'static'

async function fetchJson<T>(url: string, init: RequestInit = {}, timeoutMs = 10000): Promise<T> {
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), timeoutMs)
  try {
    const res = await fetch(url, { ...init, signal: ctl.signal })
    if (!res.ok) {
      let detail = ''
      try {
        const j = await res.json()
        detail = typeof j?.detail === 'string' ? j.detail : JSON.stringify(j?.detail ?? j)
      } catch {
        /* ignore */
      }
      throw new ApiError(`Request failed (${res.status})${detail ? ': ' + detail : ''}`)
    }
    return (await res.json()) as T
  } catch (e) {
    if (e instanceof ApiError) throw e
    if (e instanceof DOMException && e.name === 'AbortError') throw new ApiError(`Timed out after ${timeoutMs / 1000} s: ${url}`)
    throw new ApiError(`Could not reach ${url}`)
  } finally {
    clearTimeout(timer)
  }
}

export function assertVersion<T>(obj: unknown, version: string): T {
  const v = (obj as { version?: string } | null)?.version
  if (v !== version) throw new ApiError(`Expected ${version}, got ${v ?? 'no version'}`)
  return obj as T
}

export async function detectMode(): Promise<Mode> {
  if (!API) return (mode = 'static')
  try {
    await fetchJson(`${API}/health`, {}, 1500)
    mode = 'live'
  } catch {
    mode = 'static'
  }
  return mode
}
export const getMode = () => mode
export const setMode = (m: Mode) => {
  mode = m
}

let indexCache: Promise<DemoIndex> | null = null
export function loadIndex(): Promise<DemoIndex> {
  indexCache ??= fetchJson<DemoIndex>(`${DEMO}index.json`, {}, 10000).catch(() => ({
    version: 'demo-index/v0' as const,
    buildings: [],
    runs: [],
    batches: [],
  }))
  return indexCache
}

export async function listBuildings(): Promise<BuildingInfo[]> {
  if (mode === 'live') {
    const r = await fetchJson<BuildingInfo[] | { buildings: BuildingInfo[] }>(`${API}/buildings`)
    return Array.isArray(r) ? r : r.buildings
  }
  const idx = await loadIndex()
  return idx.buildings.map((b) => ({ id: b.id, name: b.name }))
}

export async function loadBuilding(id: string): Promise<Building> {
  if (mode === 'live') {
    return assertVersion<Building>(await fetchJson(`${API}/buildings/${encodeURIComponent(id)}`), 'building/v0')
  }
  const idx = await loadIndex()
  const entry = idx.buildings.find((b) => b.id === id)
  if (!entry) throw new ApiError(`Unknown building ${id}`)
  const b = assertVersion<Building>(await fetchJson(DEMO + entry.file, {}, 30000), 'building/v0')
  if (entry.credits && !b.credits) b.credits = entry.credits
  return b
}

export async function listDemoRuns(buildingId?: string): Promise<DemoRun[]> {
  const idx = await loadIndex()
  return buildingId ? idx.runs.filter((r) => r.buildingId === buildingId) : idx.runs
}

export async function loadDemoRun(entry: DemoRun): Promise<Run> {
  return assertVersion<Run>(await fetchJson(DEMO + entry.file, {}, 60000), 'run/v0')
}

export async function startRun(scenario: Scenario): Promise<string> {
  const r = await fetchJson<{ runId: string }>(`${API}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(scenario),
  })
  return r.runId
}

type Pending = { status: string; error?: string }
function isPending(o: unknown): o is Pending {
  return !!o && typeof o === 'object' && !('version' in o)
}

export async function pollRun(runId: string, onTick?: (elapsedS: number) => void, maxS = 180): Promise<Run> {
  const t0 = Date.now()
  for (;;) {
    const r = await fetchJson<Run | Pending>(`${API}/runs/${encodeURIComponent(runId)}`, {}, 60000)
    if (!isPending(r)) return assertVersion<Run>(r, 'run/v0')
    if (r.status === 'error') throw new ApiError(r.error ?? 'Run failed')
    const el = (Date.now() - t0) / 1000
    if (el > maxS) throw new ApiError(`Run did not finish within ${maxS} s`)
    onTick?.(Math.round(el))
    await new Promise((res) => setTimeout(res, 1000))
  }
}

export async function loadBatch(buildingId: string): Promise<Batch | null> {
  const idx = await loadIndex()
  const entry = idx.batches.find((b) => b.buildingId === buildingId)
  if (!entry) return null
  return assertVersion<Batch>(await fetchJson(DEMO + entry.file, {}, 30000), 'batch/v0')
}

export async function startBatch(base: Scenario, onTick?: (elapsedS: number) => void, maxS = 1800): Promise<Batch> {
  const r = await fetchJson<{ batchId: string }>(
    `${API}/batch`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base }) },
    60000,
  )
  const t0 = Date.now()
  for (;;) {
    const b = await fetchJson<Batch | Pending>(`${API}/batch/${encodeURIComponent(r.batchId)}`, {}, 60000)
    if (!isPending(b)) return assertVersion<Batch>(b, 'batch/v0')
    if (b.status === 'error') throw new ApiError(b.error ?? 'Batch failed')
    const el = (Date.now() - t0) / 1000
    if (el > maxS) throw new ApiError(`Batch did not finish within ${maxS} s`)
    onTick?.(Math.round(el))
    await new Promise((res) => setTimeout(res, 2000))
  }
}
export async function fetchReport(ref: { runId: string } | { batchId: string }, refresh = false): Promise<string> {
  if (mode === 'live') {
    const r = await fetchJson<{ markdown: string }>(
      `${API}/report${refresh ? '?refresh=1' : ''}`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(ref) },
      20000,
    )
    if (typeof r?.markdown !== 'string') throw new ApiError('Report unavailable')
    return r.markdown
  }
  if (!('batchId' in ref)) return ''
  const idx = await loadIndex()
  const entry = idx.batches.find((b) => b.id === ref.batchId)
  if (!entry?.report) return ''
  const res = await fetch(DEMO + entry.report).catch(() => null)
  if (!res || !res.ok) return ''
  return res.text()
}
export interface Calibration {
  version: 'calibration/v0'
  title: string
  source: string
  points: { label: string; width: number; simulated: number; references: { name: string; value: number }[] }[]
}
export async function loadCalibration(): Promise<{ data: Calibration; example: boolean } | null> {
  const idx = await loadIndex()
  const tries: [string, boolean][] = []
  if (idx.calibration) tries.push([idx.calibration, false])
  tries.push(['calibration.json', false], ['calibration.example.json', true])
  for (const [file, example] of tries) {
    try {
      const res = await fetch(DEMO + file)
      if (!res.ok) continue
      const j = await res.json()
      if (j?.version !== 'calibration/v0' || !Array.isArray(j.points)) continue
      return { data: j as Calibration, example }
    } catch {
      /* try next */
    }
  }
  return null
}

export type OpenedFile =
  | { kind: 'building'; data: Building }
  | { kind: 'run'; data: Run }
  | { kind: 'batch'; data: Batch }
  | { kind: 'scenario'; data: Scenario }

export async function openLocalFile(file: File): Promise<OpenedFile> {
  let obj: { version?: string }
  try {
    obj = JSON.parse(await file.text())
  } catch {
    throw new ApiError(`${file.name} is not valid JSON`)
  }
  switch (obj.version) {
    case 'building/v0':
      return { kind: 'building', data: obj as Building }
    case 'run/v0':
      return { kind: 'run', data: obj as Run }
    case 'batch/v0':
      return { kind: 'batch', data: obj as Batch }
    case 'scenario/v0':
      return { kind: 'scenario', data: obj as Scenario }
    default:
      throw new ApiError(`Expected building/v0, run/v0, batch/v0 or scenario/v0, got ${obj.version ?? 'no version'}`)
  }
}
