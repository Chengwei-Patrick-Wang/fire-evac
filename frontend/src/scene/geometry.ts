import type { Building, BuildingFloor, Vec2 } from '../data/types'

export function toWorld(x: number, y: number, elev = 0): [number, number, number] {
  return [x, elev, -y]
}
export function fromWorld(v: { x: number; z: number }): Vec2 {
  return [v.x, -v.z]
}
export function floorY(floor: BuildingFloor, explode: number): number {
  return floor.elevation + explode * floor.level * 4
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

export function buildingBounds(b: Building, floorIds?: string[] | null, explode = 0) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  let minZ = Infinity, maxZ = -Infinity
  for (const f of b.floors) {
    if (floorIds && !floorIds.includes(f.id)) continue
    const y = floorY(f, explode)
    minZ = Math.min(minZ, y)
    maxZ = Math.max(maxZ, y + f.height)
    for (const w of f.walkable)
      for (const [x, y] of w.outer) {
        minX = Math.min(minX, x); maxX = Math.max(maxX, x)
        minY = Math.min(minY, y); maxY = Math.max(maxY, y)
      }
  }
  if (!isFinite(minX)) { minX = minY = 0; maxX = maxY = 10; minZ = 0; maxZ = 3 }
  return { minX, minY, maxX, maxY, minZ, maxZ, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2, span: Math.max(maxX - minX, maxY - minY, maxZ - minZ) }
}

/** Camera distance that fits the box's bounding sphere-ish diagonal in both the vertical and horizontal FOV. */
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

export function gridPlacement(g: { origin: Vec2; cell: number; cols: number; rows: number }) {
  const w = g.cols * g.cell
  const h = g.rows * g.cell
  return { center: [g.origin[0] + w / 2, g.origin[1] + h / 2] as Vec2, size: [w, h] as Vec2 }
}
