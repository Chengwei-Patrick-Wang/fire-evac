// Mirrors spec §6 and contracts/*.example.json (the examples win on any disagreement).

export type Vec2 = [number, number]
export type DoorState = 'open' | 'closed' | 'propped' | 'blocked'
export type Profile = 'typical' | 'older' | 'visitor' | 'cane' | 'walker' | 'wheelchair'

export interface Room {
  id: string
  name: string
  type: string
  polygon: Vec2[]
  group?: string
}
export interface Door {
  id: string
  a: Vec2
  b: Vec2
  width: number
  fireDoor?: boolean
  state: DoorState
  rect?: Vec2[]
  connects: string[]
}
export interface Stair {
  id: string
  group: string
  room: string
  polygon: Vec2[]
}
export interface Exit {
  id: string
  name: string
  door?: string
  polygon: Vec2[]
}
export interface WalkablePolygon {
  outer: Vec2[]
  holes: Vec2[][]
}
export interface BuildingFloor {
  id: string
  level: number
  elevation: number
  height: number
  walkable: WalkablePolygon[]
  rooms: Room[]
  doors: Door[]
  stairs: Stair[]
  exits: Exit[]
}
export interface Building {
  version: 'building/v0'
  id: string
  name: string
  source?: string
  credits?: string
  private?: boolean
  floors: BuildingFloor[]
}

/** Illustrative room-to-room fire spread speed (fire/spread.py); `drywall` when a scenario leaves it out. */
export type Material = 'concrete' | 'drywall' | 'wood'
/** A room that catches fire by maxTime, `ignite` in seconds. The first entry of `Run.fire.rooms` is the ignition room. */
export interface FireRoom {
  room: string
  floor: string
  ignite: number
}

export interface Scenario {
  version: 'scenario/v0'
  id?: string
  buildingId?: string
  seed: number
  occupants: { total: number; mix: Partial<Record<Profile, number>> }
  fire: { floor?: string; room?: string; x?: number; y?: number; type: string; start?: number; material?: Material }
  sprinklers?: boolean
  doors?: Record<string, DoorState>
  alarmTime?: number
  maxTime?: number
}

export interface RunAgent {
  idx: number
  profile: Profile
  floor: string
  room: string
  v0: number
  startDelay: number
  llm?: boolean
  note?: string
}
/** [idx, x, y, floorIdx, status] */
export type FrameRow = [number, number, number, number, number]
export interface RunFrame {
  t: number
  a: FrameRow[]
}
export interface SmokeFrame {
  t: number
  d: string
}
export interface SmokeLayer {
  floor: string
  origin: Vec2
  cell: number
  cols: number
  rows: number
  interval?: number
  frames: SmokeFrame[]
}
export interface Heatmap {
  floor: string
  origin: Vec2
  cell: number
  cols: number
  rows: number
  d: string
}
export interface RunEvent {
  t: number
  type: string
  idx?: number
  floor?: string
  exit?: string
  group?: string
  door?: string
  until?: number
  reason?: string
  [k: string]: unknown
}
export interface DoorMetric {
  id: string
  floor: string
  peakQueue: number
  waitPersonSeconds: number
  flow: number | null
}
export interface RunMetrics {
  agents: number
  evacuated: number
  trapped: number
  inStairs?: number
  remaining?: number
  t50: number | null
  t90: number | null
  t100: number | null
  exitCounts: Record<string, number>
  doors?: DoorMetric[]
  heatmaps?: Heatmap[]
  rooms?: unknown
}
export interface Run {
  version: 'run/v0'
  id: string
  buildingId: string
  scenarioId?: string
  seed: number
  frameInterval: number
  floors: string[]
  agents: RunAgent[]
  frames: RunFrame[]
  smoke?: SmokeLayer[]
  /** `rooms`: every room that catches fire by maxTime, sorted by `ignite`; absent on runs made before the spread model. */
  fire: { floor: string; x: number; y: number; hrr?: [number, number][]; rooms?: FireRoom[]; material?: Material }
  events: RunEvent[]
  metrics: RunMetrics
}

export interface BatchRoom {
  id: string
  floor: string
  riskT90: number | null
  riskTrapped: number | null
  n: number
}
export interface BatchDoor {
  id: string
  floor: string
  meanWait: number
  peakQueue: number
  score: number
}
export interface BatchTop {
  kind: string
  id: string
  floor: string
  score: number
  why: string
}
export interface Batch {
  version: 'batch/v0'
  id: string
  buildingId: string
  placeholder?: boolean
  note?: string
  base: Scenario
  runs: { scenarioId: string; seed: number; ignition: { floor: string; room: string }; t90: number | null; t100: number | null; trapped: number }[]
  failed?: unknown[]
  exits?: unknown
  rooms: BatchRoom[]
  doors: BatchDoor[]
  heatmaps?: Heatmap[]
  top: BatchTop[]
}

export interface BuildingInfo {
  id: string
  name: string
  source?: string
  floors?: number
  private?: boolean
}

// A's A5 index format.
export interface DemoRun {
  id: string
  buildingId: string
  label: string
  file: string
  /** `'propped'`: a door what-if. `'material'`: the same fire at another (illustrative) material. */
  whatIf: null | 'propped' | 'material'
  material?: Material
  fire: { floor: string; room: string; x: number; y: number; type: string }
  doors: Record<string, DoorState>
  metrics?: { t50: number | null; t90: number | null; t100: number | null; evacuated: number; trapped: number }
}
export interface DemoIndex {
  version: 'demo-index/v0'
  generated?: string
  buildings: { id: string; name: string; file: string; credits?: string }[]
  runs: DemoRun[]
  batches: { id: string; buildingId: string; file: string; report?: string; headlines?: string }[]
  calibration?: string
}
