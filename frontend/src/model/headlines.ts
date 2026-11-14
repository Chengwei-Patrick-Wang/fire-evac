import { loadIndex } from '../data/loader'
import type { Fix } from './fixes'
import type { Stability } from './ranges'

export interface HeadlineSpot {
  rank?: number
  kind: string
  id: string
  floor: string
  label?: string
  score?: number
  why: string
  scoreRange?: unknown
  riskT90Range?: unknown
  seedsInTop3?: number
}
export interface HeadlineWhatIf {
  id: string
  label?: string
  n?: number
  dT90?: number
  smokePct?: number | null
  why: string
  [k: string]: unknown
}
export interface HeadlineChange {
  key: string
  label?: string
  old?: unknown
  new?: unknown
  changed: boolean
  why: string
}
export interface HeadlinePack {
  version: 'headlines/v0'
  buildingId: string
  buildingName?: string
  generated: string
  note?: string
  sources?: { batch?: { file?: string; id?: string; modified?: string }; sensitivity?: { file?: string; modified?: string } }
  scenario?: {
    id?: string
    occupants?: number
    fireType?: string
    seeds?: number[]
    rooms?: number
    runs?: number
    failed?: number
    [k: string]: unknown
  }
  headline?: string
  weakSpots?: HeadlineSpot[]
  whatIf?: HeadlineWhatIf[]
  fixes?: Fix[]
  stability?: Stability
  sensitivity?: { note?: string; why?: string; variants?: { id: string; why: string }[] }
  changes?: HeadlineChange[]
  [k: string]: unknown
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const isStr = (v: unknown): v is string => typeof v === 'string'
const withWhy = (v: unknown) => (Array.isArray(v) ? v.filter((e) => isObj(e) && isStr(e.why)) : undefined)

export function readPack(obj: unknown, buildingId: string): HeadlinePack | null {
  if (!isObj(obj) || obj.version !== 'headlines/v0' || obj.buildingId !== buildingId) return null
  const p: Record<string, unknown> = { ...obj }
  if (!isStr(p.headline)) delete p.headline
  if (!isStr(p.note)) delete p.note
  for (const k of ['weakSpots', 'whatIf', 'fixes']) {
    const a = withWhy(p[k])
    if (a) p[k] = a
    else delete p[k]
  }
  if (p.weakSpots) p.weakSpots = (p.weakSpots as Record<string, unknown>[]).filter((e) => isStr(e.id) && isStr(e.floor))
  if (!isObj(p.stability) || !isStr(p.stability.why)) delete p.stability
  if (!isObj(p.scenario)) delete p.scenario
  if (!isObj(p.sources)) delete p.sources
  if (!isObj(p.sensitivity)) delete p.sensitivity
  if (Array.isArray(p.changes)) p.changes = p.changes.filter((e) => isObj(e) && isStr(e.why) && typeof e.changed === 'boolean')
  else delete p.changes
  return p as HeadlinePack
}

export async function loadHeadlines(buildingId: string): Promise<HeadlinePack | null> {
  try {
    const idx = await loadIndex()
    const entry = idx.batches.find((b) => b.buildingId === buildingId && typeof (b as { headlines?: unknown }).headlines === 'string')
    if (!entry) return null
    const file = (entry as unknown as { headlines: string }).headlines
    const res = await fetch(`${import.meta.env.BASE_URL}demo/${file}`)
    if (!res.ok) return null
    return readPack(await res.json(), buildingId)
  } catch {
    return null
  }
}
