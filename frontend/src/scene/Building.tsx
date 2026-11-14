import { useLayoutEffect, useMemo, useRef } from 'react'
import type { ReactNode } from 'react'
import { useA11y } from '../ui/a11y'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { useApp } from '../store/app'
import type { BuildingFloor, DoorState, Vec2 } from '../data/types'
import { classifyWalls, floorAlpha, toWorld } from './geometry'
import type { Segment } from './geometry'
import { usePlace } from './usePlace'
import { floorName } from '../model/floors'

const WALL_T = 0.15
/** Interior walls are a cutaway: low enough to see people and rooms over them from the isometric camera. */
const CUT_H = 1.4
const SLAB_T = 0.15
const RAIL_H = 0.08
const ROOM_COLORS: Record<string, string> = {
  classroom: '#38bdf8', office: '#a78bfa', lobby: '#34d399', corridor: '#64748b',
  lab: '#f472b6', kitchen: '#fb923c', restroom: '#94a3b8', storage: '#a16207',
}
export const DOOR_COLORS: Record<DoorState, string> = { open: '#2563EB', closed: '#1E3A8A', propped: '#0891B2', blocked: '#DC2626' }
const EXIT_COLOR = '#16A34A'
const STAIR_COLOR = '#F97316'

function shapeOf(poly: Vec2[]) {
  const s = new THREE.Shape()
  poly.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)))
  return s
}
function pathOf(ring: Vec2[]) {
  const p = new THREE.Path()
  ring.forEach(([x, y], i) => (i ? p.lineTo(x, y) : p.moveTo(x, y)))
  return p
}

/** A unit box with its base on y = 0, shared by every wall, glass pane and rail. */
const UNIT = new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0)

/** One InstancedMesh of boxes along wall segments: `t` thick, `h` tall, from `y` up. The material is the child. */
function Boxes({ segs, y, h, t, children }: { segs: Segment[]; y: number; h: number; t: number; children: ReactNode }) {
  const ref = useRef<THREE.InstancedMesh>(null)
  useLayoutEffect(() => {
    const m = ref.current
    if (!m) return
    const o = new THREE.Object3D()
    segs.forEach((s, i) => {
      if (import.meta.env.DEV) console.assert(s.len >= 0.01, 'zero-length wall', s)
      const [x, , z] = toWorld(s.mx, s.my)
      o.position.set(x, y, z)
      o.rotation.set(0, s.angle, 0)
      o.scale.set(s.len + t, h, t)
      o.updateMatrix()
      m.setMatrixAt(i, o.matrix)
    })
    m.instanceMatrix.needsUpdate = true
  }, [segs, y, h, t])
  if (segs.length === 0) return null
  return (
    <instancedMesh ref={ref} args={[UNIT, undefined, segs.length]} frustumCulled={false}>
      {children}
    </instancedMesh>
  )
}

/** The floor: the walkable outer ring with its holes, 0.15 m thick, its top face on the floor plane. The notches along interior walls hide under the wall boxes. */
function Slab({ floor, alpha }: { floor: BuildingFloor; alpha: number }) {
  const geo = useMemo(() => {
    const parts: THREE.BufferGeometry[] = []
    for (const w of floor.walkable) {
      if (w.outer.length < 3) continue
      const shape = shapeOf(w.outer)
      for (const h of w.holes) if (h.length >= 3) shape.holes.push(pathOf(h))
      const g = new THREE.ExtrudeGeometry(shape, { depth: SLAB_T, bevelEnabled: false })
      g.rotateX(-Math.PI / 2)
      g.translate(0, -SLAB_T, 0)
      parts.push(g)
    }
    if (parts.length <= 1) return parts[0] ?? null
    const merged = mergeGeometries(parts)
    parts.forEach((g) => g.dispose())
    return merged
  }, [floor])
  useLayoutEffect(() => () => geo?.dispose(), [geo])
  if (!geo) return null
  const ghost = alpha < 1
  // polygonOffset pushes the slab back a little, so the flat room, door and stair marks 2 cm above it never z-fight with it at a distance.
  return (
    <mesh geometry={geo}>
      <meshStandardMaterial key={ghost ? 'ghost' : 'solid'} color="#E2E8F0" roughness={1} toneMapped={false} transparent={ghost} opacity={alpha} depthWrite={!ghost} polygonOffset polygonOffsetFactor={1} polygonOffsetUnits={1} />
    </mesh>
  )
}

/** Each stair as a translucent column the height of the floor, so a stairwell reads from far away. */
function StairCores({ floor, alpha }: { floor: BuildingFloor; alpha: number }) {
  const geo = useMemo(() => {
    const parts = floor.stairs
      .filter((s) => s.polygon.length >= 3)
      .map((s) => {
        const g = new THREE.ExtrudeGeometry(shapeOf(s.polygon), { depth: floor.height, bevelEnabled: false })
        g.rotateX(-Math.PI / 2)
        return g
      })
    if (parts.length <= 1) return parts[0] ?? null
    const merged = mergeGeometries(parts)
    parts.forEach((g) => g.dispose())
    return merged
  }, [floor])
  useLayoutEffect(() => () => geo?.dispose(), [geo])
  if (!geo) return null
  return (
    <mesh geometry={geo}>
      <meshStandardMaterial color="#FDBA74" toneMapped={false} transparent opacity={0.22 * alpha} depthWrite={false} />
    </mesh>
  )
}

function Flat({ poly, y, color, opacity }: { poly: Vec2[]; y: number; color: string; opacity: number }) {
  const geo = useMemo(() => new THREE.ShapeGeometry(shapeOf(poly)), [poly])
  return (
    <mesh geometry={geo} rotation-x={-Math.PI / 2} position-y={y}>
      <meshBasicMaterial color={color} toneMapped={false} transparent opacity={opacity} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
  )
}

let warned = false

/** Flat polygons merged into one mesh with per-vertex colours (one draw call per layer). */
function FlatBatch({ items, y, opacity }: { items: { poly: Vec2[]; color: string }[]; y: number; opacity: number }) {
  const { geo, fallback } = useMemo(() => {
    const parts = items.map(({ poly, color }) => {
      const g = new THREE.ShapeGeometry(shapeOf(poly))
      g.rotateX(-Math.PI / 2)
      g.translate(0, y, 0)
      const c = new THREE.Color(color)
      const n = g.getAttribute('position').count
      const arr = new Float32Array(n * 3)
      for (let i = 0; i < n; i++) {
        arr[i * 3] = c.r
        arr[i * 3 + 1] = c.g
        arr[i * 3 + 2] = c.b
      }
      g.setAttribute('color', new THREE.BufferAttribute(arr, 3))
      return g
    })
    if (parts.length === 0) return { geo: null, fallback: false }
    const merged = mergeGeometries(parts)
    parts.forEach((g) => g.dispose())
    if (!merged) {
      if (!warned) console.warn('mergeGeometries failed; drawing floor shapes one by one')
      warned = true
      return { geo: null, fallback: true }
    }
    return { geo: merged, fallback: false }
  }, [items, y])
  useLayoutEffect(() => () => geo?.dispose(), [geo])
  if (fallback)
    return (
      <>
        {items.map((it, i) => (
          <Flat key={i} poly={it.poly} y={y} color={it.color} opacity={opacity} />
        ))}
      </>
    )
  if (!geo) return null
  return (
    <mesh geometry={geo}>
      <meshBasicMaterial vertexColors toneMapped={false} transparent opacity={opacity} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
  )
}

function centroid(poly: Vec2[]): Vec2 {
  const n = poly.length || 1
  return [poly.reduce((s, p) => s + p[0], 0) / n, poly.reduce((s, p) => s + p[1], 0) / n]
}

const labelStyle = { pointerEvents: 'none' as const }

const RISE_S = 1.4
const STAGGER_S = 0.25
const reduced = () => useA11y.getState().reduceMotion

/** "Floor N" at the floor's front-left corner (the plan's smallest x and y); the focus floor's pill is blue. */
function FloorTag({ floor, name, on }: { floor: BuildingFloor; name: string; on: boolean }) {
  const corner = useMemo(() => {
    let x0 = Infinity
    let y0 = Infinity
    for (const w of floor.walkable)
      for (const [x, y] of w.outer) {
        if (x < x0) x0 = x
        if (y < y0) y0 = y
      }
    return isFinite(x0) ? ([x0, y0] as Vec2) : null
  }, [floor])
  if (!corner) return null
  return (
    <Html position={toWorld(corner[0], corner[1], 0.05)} style={labelStyle}>
      <div className={'floortag' + (on ? ' on' : '')}>{name}</div>
    </Html>
  )
}

function Floor({ floor, doors, order }: { floor: BuildingFloor; doors: Record<string, DoorState>; order: number }) {
  const reveal = useApp((s) => s.reveal)
  const walls = useRef<THREE.Group>(null)
  const t0 = useRef<{ reveal: number; t: number } | null>(null)
  useFrame(({ clock }) => {
    const g = walls.current
    if (!g) return
    if (reduced()) {
      if (g.scale.y !== 1) g.scale.y = 1
      return
    }
    if (!t0.current || t0.current.reveal !== reveal) t0.current = { reveal, t: clock.elapsedTime }
    const k = Math.min(1, Math.max(0, (clock.elapsedTime - t0.current.t - order * STAGGER_S) / RISE_S))
    const y = Math.max(0.001, 1 - Math.pow(1 - k, 3))
    if (g.scale.y !== y) g.scale.y = y
  })
  const place = usePlace()
  const building = useApp((s) => s.building)
  const viewMode = useApp((s) => s.viewMode)
  const focusFloor = useApp((s) => s.focusFloor)
  const labels = useApp((s) => s.layers.labels)
  const roomsOn = useApp((s) => s.layers.rooms)
  const alpha = floorAlpha(viewMode, focusFloor, floor.id)
  const ghost = alpha < 1
  const { interior, exterior } = useMemo(() => classifyWalls(floor), [floor])
  const rooms = useMemo(() => floor.rooms.filter((r) => r.type !== 'stair'), [floor])
  const roomItems = useMemo(() => rooms.map((r) => ({ poly: r.polygon, color: ROOM_COLORS[r.type] ?? '#475569' })), [rooms])
  const doorItems = useMemo(
    () =>
      floor.doors
        .filter((d) => (d.rect ?? []).length >= 3)
        .map((d) => ({ poly: d.rect as Vec2[], color: DOOR_COLORS[doors[d.id] ?? d.state] })),
    [floor, doors],
  )
  const stairItems = useMemo(() => floor.stairs.map((s) => ({ poly: s.polygon, color: STAIR_COLOR })), [floor])
  const exitItems = useMemo(() => floor.exits.map((e) => ({ poly: e.polygon, color: EXIT_COLOR })), [floor])
  const { dx, y } = place(floor)
  return (
    <group position={[dx, y, 0]}>
      <Slab floor={floor} alpha={alpha} />
      <group name="walls" ref={walls} scale-y={0.001}>
        <Boxes segs={interior} y={0} h={Math.min(CUT_H, floor.height)} t={WALL_T}>
          <meshStandardMaterial key={ghost ? 'ghost' : 'solid'} color="#F1F5F9" roughness={0.9} toneMapped={false} transparent={ghost} opacity={alpha} depthWrite={!ghost} />
        </Boxes>
        <Boxes segs={exterior} y={0} h={floor.height} t={WALL_T}>
          <meshStandardMaterial color="#BFDBFE" toneMapped={false} transparent opacity={0.28 * alpha} depthWrite={false} roughness={0.1} metalness={0.1} />
        </Boxes>
        <Boxes segs={exterior} y={floor.height - RAIL_H} h={RAIL_H} t={WALL_T + 0.04}>
          <meshStandardMaterial key={ghost ? 'ghost' : 'solid'} color="#94A3B8" roughness={0.6} toneMapped={false} transparent={ghost} opacity={alpha} depthWrite={!ghost} />
        </Boxes>
      </group>
      <StairCores floor={floor} alpha={alpha} />
      {roomsOn && <FlatBatch items={roomItems} y={0.02} opacity={0.15 * alpha} />}
      {labels &&
        !ghost &&
        rooms.map((r) => {
          const [x, yy] = centroid(r.polygon)
          const main = r.name || r.id
          // The room type goes on a second, muted line unless the name already says it.
          const sub = r.type && !main.toLowerCase().includes(r.type.toLowerCase()) ? r.type : null
          return (
            <Html key={r.id} position={toWorld(x, yy, 0.3)} center style={labelStyle}>
              <div className="l3d room">
                {main}
                {sub && <small>{sub}</small>}
              </div>
            </Html>
          )
        })}
      <FlatBatch items={doorItems} y={0.03} opacity={alpha} />
      <FlatBatch items={stairItems} y={0.04} opacity={0.35 * alpha} />
      <FlatBatch items={exitItems} y={0.04} opacity={0.8 * alpha} />
      {labels &&
        !ghost &&
        floor.stairs.map((s) => {
          const [x, yy] = centroid(s.polygon)
          return (
            <Html key={s.id} position={toWorld(x, yy, 0.3)} center style={labelStyle}>
              <div className="l3d stair">{s.group}</div>
            </Html>
          )
        })}
      {!ghost &&
        floor.exits.map((e) => {
          const [x, yy] = centroid(e.polygon)
          return (
            <Html key={e.id} position={toWorld(x, yy, 0.3)} center style={labelStyle}>
              <div className="l3d exit">{e.name}</div>
            </Html>
          )
        })}
      {building && <FloorTag floor={floor} name={floorName(building, floor.id)} on={(viewMode === 'single' || viewMode === 'ghost') && focusFloor === floor.id} />}
    </group>
  )
}

const NO_DOORS: Record<string, DoorState> = {}

export default function Building({ runKey }: { runKey?: string }) {
  const building = useApp((s) => s.building)
  const visible = useApp((s) => s.visibleFloors)
  const doors = useApp((s) => {
    const k = runKey ?? s.activeRunKey
    return (k && s.runs[k]?.doors) || NO_DOORS
  })
  if (!building) return null
  return (
    <>
      {building.floors
        .filter((f) => !visible || visible.includes(f.id))
        .map((f) => (
          <Floor key={building.id + f.id} floor={f} doors={doors} order={building.floors.indexOf(f)} />
        ))}
    </>
  )
}
