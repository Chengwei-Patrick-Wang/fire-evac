import type { Building, BuildingFloor, Vec2 } from '../data/types'

/** How the floors are laid out: stacked with a gap, one floor alone, all in a row on the ground, or all stacked with one solid. */
export type ViewMode = 'stacked' | 'single' | 'side' | 'ghost'

/** Opacity multiplier of every floor but the focus floor in ghost view. */
export const GHOST = 0.15

export function toWorld(x: number, y: number, elev = 0): [number, number, number] {
  return [x, elev, -y]
}
export function fromWorld(v: { x: number; z: number }): Vec2 {
  return [v.x, -v.z]
}
export function floorY(floor: BuildingFloor, explode: number): number {
  return floor.elevation + explode * floor.level * 4
}

/** Where a floor sits in the scene: its shift along x (side view) and its height. */
export interface Place {
  dx: number
  y: number
}

interface Row {
  /** the x extent of the whole building */
  w: number
  gap: number
  /** floor id to its position by level */
  rank: Map<string, number>
}
const rows = new WeakMap<Building, Row>()

function rowOf(b: Building): Row {
  let r = rows.get(b)
  if (!r) {
    let x0 = Infinity
    let x1 = -Infinity
    for (const f of b.floors)
      for (const w of f.walkable)
        for (const p of w.outer) {
          x0 = Math.min(x0, p[0])
          x1 = Math.max(x1, p[0])
        }
    const w = isFinite(x0) ? x1 - x0 : 10
    const rank = new Map<string, number>()
    ;[...b.floors].sort((a, c) => a.level - c.level).forEach((f, i) => rank.set(f.id, i))
    r = { w, gap: Math.max(4, 0.15 * w), rank }
    rows.set(b, r)
  }
  return r
}

/**
 * Stacked, single and ghost put a floor at its (exploded) height. Side lays every floor flat on the ground in a row along +x, ordered
 * by level, a building width plus a gap apart. Without a building, side falls back to stacked.
 */
export function floorPlace(b: Building | null, f: BuildingFloor, mode: ViewMode, explode: number): Place {
  if (mode === 'side' && b) {
    const r = rowOf(b)
    return { dx: (r.rank.get(f.id) ?? 0) * (r.w + r.gap), y: 0 }
  }
  return { dx: 0, y: floorY(f, explode) }
}

/** The ghost view's opacity multiplier for one floor: GHOST for every floor but the focus floor, else 1. */
export function floorAlpha(mode: ViewMode, focusFloor: string | null, floorId: string): number {
  return mode === 'ghost' && focusFloor !== null && floorId !== focusFloor ? GHOST : 1
}

/** Plan (x, y) and a height above the floor to scene coordinates, in a floor's place. */
export function toPlaced(p: Place, x: number, y: number, h = 0): [number, number, number] {
  return [x + p.dx, p.y + h, -y]
}
/** The plan position under a scene point on a floor placed at p. */
export function fromPlaced(p: Place, v: { x: number; z: number }): Vec2 {
  return [v.x - p.dx, -v.z]
}

export interface Segment {
  mx: number
  my: number
  len: number
  angle: number
}

// Closed-ring segments (last to first), skipping repeated points and segments < 0.01 m.
export function ringSegments(ring: Vec2[]): Segment[] {
  const out: Segment[] = []
  const n = ring.length
  for (let i = 0; i < n; i++) {
    const a = ring[i]
    const b = ring[(i + 1) % n]
    const dx = b[0] - a[0]
    const dy = b[1] - a[1]
    const len = Math.hypot(dx, dy)
    if (len < 0.01) continue
    out.push({ mx: (a[0] + b[0]) / 2, my: (a[1] + b[1]) / 2, len, angle: Math.atan2(dy, dx) })
  }
  return out
}

export function pointInPolygon(p: Vec2, poly: Vec2[]): boolean {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i]
    const [xj, yj] = poly[j]
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

export interface WallSplit {
  interior: Segment[]
  exterior: Segment[]
}

const PROBE = 0.6
const walls = new WeakMap<BuildingFloor, WallSplit>()

/**
 * Walls between rooms (interior) and walls with the outside behind them (exterior), from the walkable rings. The outer ring also
 * traces the interior walls as narrow notches, so a segment is exterior only when one point 0.6 m to a side of its middle is walkable
 * and the point 0.6 m to the other side is outside every room and outside the walkable area. Hole rings (pillars, shafts, courtyards)
 * are always interior. A floor with no rooms has nothing to tell the sides apart, so every outer segment is exterior. Memoized per floor.
 */
export function classifyWalls(floor: BuildingFloor): WallSplit {
  const hit = walls.get(floor)
  if (hit) return hit
  const interior: Segment[] = []
  const exterior: Segment[] = []
  const rooms = floor.rooms
    .filter((r) => r.polygon.length >= 3)
    .map((r) => {
      let x0 = Infinity
      let y0 = Infinity
      let x1 = -Infinity
      let y1 = -Infinity
      for (const [x, y] of r.polygon) {
        x0 = Math.min(x0, x)
        y0 = Math.min(y0, y)
        x1 = Math.max(x1, x)
        y1 = Math.max(y1, y)
      }
      return { poly: r.polygon, x0, y0, x1, y1 }
    })
  const walkable = (p: Vec2) => floor.walkable.some((w) => pointInPolygon(p, w.outer) && !w.holes.some((h) => pointInPolygon(p, h)))
  const inRoom = (p: Vec2) => rooms.some((r) => p[0] >= r.x0 && p[0] <= r.x1 && p[1] >= r.y0 && p[1] <= r.y1 && pointInPolygon(p, r.poly))
  for (const w of floor.walkable) {
    for (const s of ringSegments(w.outer)) {
      if (rooms.length === 0) {
        exterior.push(s)
        continue
      }
      const nx = -Math.sin(s.angle) * PROBE
      const ny = Math.cos(s.angle) * PROBE
      const a: Vec2 = [s.mx + nx, s.my + ny]
      const b: Vec2 = [s.mx - nx, s.my - ny]
      const wa = walkable(a)
      const wb = walkable(b)
      // one side walkable, the other neither walkable nor inside a room
      ;((wa && !wb && !inRoom(b)) || (wb && !wa && !inRoom(a)) ? exterior : interior).push(s)
    }
    for (const h of w.holes) interior.push(...ringSegments(h))
  }
  const out = { interior, exterior }
  walls.set(floor, out)
  return out
}

/** The box around the drawn floors, each in its place (so `mode` and `explode` move it); span is its longest side. */
export function buildingBounds(b: Building, floorIds?: string[] | null, explode = 0, mode: ViewMode = 'stacked') {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  let minZ = Infinity, maxZ = -Infinity
  for (const f of b.floors) {
    if (floorIds && !floorIds.includes(f.id)) continue
    const p = floorPlace(b, f, mode, explode)
    minZ = Math.min(minZ, p.y)
    maxZ = Math.max(maxZ, p.y + f.height)
    for (const w of f.walkable)
      for (const [x, y] of w.outer) {
        minX = Math.min(minX, x + p.dx); maxX = Math.max(maxX, x + p.dx)
        minY = Math.min(minY, y); maxY = Math.max(maxY, y)
      }
  }
  if (!isFinite(minX)) { minX = minY = 0; maxX = maxY = 10; minZ = 0; maxZ = 3 }
  return { minX, minY, maxX, maxY, minZ, maxZ, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2, span: Math.max(maxX - minX, maxY - minY, maxZ - minZ) }
}

/** Camera distance that fits the box's bounding sphere-ish diagonal in both the vertical and horizontal FOV. (Kept for callers that only need a rough distance; the camera frames with frameView.) */
export function fitDistance(
  b: { minX: number; minY: number; maxX: number; maxY: number; minZ: number; maxZ: number },
  fovDeg: number,
  aspect: number,
  margin = 1.15,
): number {
  const half = Math.hypot(b.maxX - b.minX, b.maxY - b.minY, b.maxZ - b.minZ) / 2
  const v = (fovDeg * Math.PI) / 360
  const limit = Math.min(v, Math.atan(Math.tan(v) * aspect))
  return (half / Math.sin(limit)) * margin
}

/** The outline of the drawn floors as scene points (x, y, z, ...): every outer-ring vertex of every shown floor at the floor's bottom and at its top, each floor in its place. */
export function framePoints(b: Building, floorIds?: string[] | null, explode = 0, mode: ViewMode = 'stacked'): number[] {
  const pts: number[] = []
  for (const f of b.floors) {
    if (floorIds && !floorIds.includes(f.id)) continue
    const p = floorPlace(b, f, mode, explode)
    for (const w of f.walkable) for (const [x, y] of w.outer) pts.push(x + p.dx, p.y, -y, x + p.dx, p.y + f.height, -y)
  }
  if (pts.length === 0) pts.push(0, 0, 0, 10, 0, 0, 0, 0, -10, 10, 3, -10)
  return pts
}

export interface FrameView {
  /** where the camera looks */
  target: [number, number, number]
  /** how far the camera is from the target, along `dir` */
  distance: number
}

/**
 * Where to put a perspective camera so the points fill the visible part of the viewer. The camera sits at target + dir * distance
 * (`dir` points from the target to the eye) and looks at the target. `width` and `height` are the viewport in pixels, `inset` the
 * pixels of it that a panel or a label hides on each side, and `pad` the share of the visible part left empty on each side (0.045: the
 * building fills 91 %). The distance is the smallest one at which every point lies inside the padded part (found by bisection, the
 * target shifted so the points' outline is centred in it); the points are projected exactly, so a long flat building and a tall tower
 * both fill their limiting side.
 */
export function frameView(
  pts: number[],
  dir: [number, number, number],
  fovDeg: number,
  view: { width: number; height: number; pad?: number; inset?: { left?: number; right?: number; top?: number; bottom?: number } },
): FrameView {
  const n = Math.floor(pts.length / 3)
  const w = Math.max(1, view.width)
  const h = Math.max(1, view.height)
  const tanV = Math.tan((fovDeg * Math.PI) / 360)
  const tanH = tanV * (w / h)
  const pad = view.pad ?? 0.045
  const ins = view.inset ?? {}
  // the visible part of the viewport in normalised device coordinates (-1 to 1), and the half extents the points may fill in it
  const x0 = -1 + (2 * (ins.left ?? 0)) / w
  const x1 = 1 - (2 * (ins.right ?? 0)) / w
  const y0 = -1 + (2 * (ins.bottom ?? 0)) / h
  const y1 = 1 - (2 * (ins.top ?? 0)) / h
  const cx = (x0 + x1) / 2
  const cy = (y0 + y1) / 2
  const hw = Math.max(0.05, ((x1 - x0) / 2) * (1 - 2 * pad))
  const hh = Math.max(0.05, ((y1 - y0) / 2) * (1 - 2 * pad))
  // camera basis: forward f = -dir, right r, up v
  const dl = Math.hypot(...dir) || 1
  const ux = dir[0] / dl, uy = dir[1] / dl, uz = dir[2] / dl
  let rx = uz, rz = -ux
  const rl = Math.hypot(rx, rz)
  if (rl < 1e-6) { rx = 1; rz = 0 } else { rx /= rl; rz /= rl }
  const fx = -ux, fy = -uy, fz = -uz
  const vx = -rz * fy, vy = rz * fx - rx * fz, vz = rx * fy
  // bounding box centre and radius: the start
  let a0 = Infinity, a1 = -Infinity, b0 = Infinity, b1 = -Infinity, c0 = Infinity, c1 = -Infinity
  for (let i = 0; i < n; i++) {
    const x = pts[3 * i], y = pts[3 * i + 1], z = pts[3 * i + 2]
    a0 = Math.min(a0, x); a1 = Math.max(a1, x); b0 = Math.min(b0, y); b1 = Math.max(b1, y); c0 = Math.min(c0, z); c1 = Math.max(c1, z)
  }
  const R = Math.max(0.5, Math.hypot(a1 - a0, b1 - b0, c1 - c0) / 2)
  const t: [number, number, number] = [(a0 + a1) / 2, (b0 + b1) / 2, (c0 + c1) / 2]
  /** the outline's extent in the padded part at distance d with the target in `tt` (moved to centre it); ratio <= 1 fits */
  const settle = (d: number, tt: [number, number, number]): number => {
    for (let pass = 0; pass < 4; pass++) {
      const ex = tt[0] + ux * d, ey = tt[1] + uy * d, ez = tt[2] + uz * d
      let nx0 = Infinity, nx1 = -Infinity, ny0 = Infinity, ny1 = -Infinity
      for (let i = 0; i < n; i++) {
        const px = pts[3 * i] - ex, py = pts[3 * i + 1] - ey, pz = pts[3 * i + 2] - ez
        const z = px * fx + py * fy + pz * fz
        if (z < 0.05) return Infinity
        const nx = (px * rx + pz * rz) / (z * tanH)
        const ny = (px * vx + py * vy + pz * vz) / (z * tanV)
        if (nx < nx0) nx0 = nx
        if (nx > nx1) nx1 = nx
        if (ny < ny0) ny0 = ny
        if (ny > ny1) ny1 = ny
      }
      const ox = (nx0 + nx1) / 2 - cx
      const oy = (ny0 + ny1) / 2 - cy
      if (pass === 3 || (Math.abs(ox) < 1e-4 && Math.abs(oy) < 1e-4)) return Math.max((nx1 - nx0) / 2 / hw, (ny1 - ny0) / 2 / hh)
      tt[0] += (rx * ox * tanH + vx * oy * tanV) * d
      tt[1] += vy * oy * tanV * d
      tt[2] += (rz * ox * tanH + vz * oy * tanV) * d
    }
    return Infinity
  }
  let lo = R * 0.3
  let hi = R * 60
  let best: FrameView | null = null
  for (let i = 0; i < 44; i++) {
    const d = (lo + hi) / 2
    const tt: [number, number, number] = [t[0], t[1], t[2]]
    if (settle(d, tt) <= 1) {
      best = { target: tt, distance: d }
      hi = d
    } else lo = d
  }
  return best ?? { target: t, distance: hi }
}

export function gridPlacement(g: { origin: Vec2; cell: number; cols: number; rows: number }) {
  const w = g.cols * g.cell
  const h = g.rows * g.cell
  return { center: [g.origin[0] + w / 2, g.origin[1] + h / 2] as Vec2, size: [w, h] as Vec2 }
}
