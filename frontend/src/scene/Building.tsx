import { useLayoutEffect, useMemo, useRef } from 'react'
import { useA11y } from '../ui/a11y'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { useApp } from '../store/app'
import type { BuildingFloor, DoorState, Vec2 } from '../data/types'
import { floorY, ringSegments, toWorld } from './geometry'
import type { Segment } from './geometry'

const WALL_T = 0.15
const ROOM_COLORS: Record<string, string> = {
  classroom: '#38bdf8', office: '#a78bfa', lobby: '#34d399', corridor: '#64748b',
  lab: '#f472b6', kitchen: '#fb923c', restroom: '#94a3b8', storage: '#a16207',
}
export const DOOR_COLORS: Record<DoorState, string> = { open: '#3b82f6', closed: '#1e3a8a', propped: '#22d3ee', blocked: '#ef4444' }

function shapeOf(poly: Vec2[]) {
  const s = new THREE.Shape()
  poly.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)))
  return s
}

function Walls({ floor }: { floor: BuildingFloor }) {
  const ref = useRef<THREE.InstancedMesh>(null)
  const segs = useMemo(() => {
    const out: Segment[] = []
    for (const w of floor.walkable) {
      out.push(...ringSegments(w.outer))
      for (const h of w.holes) out.push(...ringSegments(h))
    }
    return out
  }, [floor])
  const geo = useMemo(() => new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0), [])
  useLayoutEffect(() => {
    const m = ref.current
    if (!m) return
    const o = new THREE.Object3D()
    const c = new THREE.Color('#cbd5e1')
    segs.forEach((s, i) => {
      if (import.meta.env.DEV) console.assert(s.len >= 0.01, 'zero-length wall', s)
      const [x, , z] = toWorld(s.mx, s.my)
      o.position.set(x, 0, z)
      o.rotation.set(0, s.angle, 0)
      o.scale.set(s.len + WALL_T, floor.height, WALL_T)
      o.updateMatrix()
      m.setMatrixAt(i, o.matrix)
      m.setColorAt(i, c)
    })
    m.instanceMatrix.needsUpdate = true
    if (m.instanceColor) m.instanceColor.needsUpdate = true
  }, [segs, floor.height])
  return (
    <instancedMesh ref={ref} args={[geo, undefined, segs.length]} frustumCulled={false}>
      <meshStandardMaterial />
    </instancedMesh>
  )
}

function Flat({ poly, y, color, opacity }: { poly: Vec2[]; y: number; color: string; opacity: number }) {
  const geo = useMemo(() => new THREE.ShapeGeometry(shapeOf(poly)), [poly])
  return (
    <mesh geometry={geo} rotation-x={-Math.PI / 2} position-y={y}>
      <meshBasicMaterial color={color} transparent opacity={opacity} side={THREE.DoubleSide} depthWrite={false} />
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
      <meshBasicMaterial vertexColors transparent opacity={opacity} side={THREE.DoubleSide} depthWrite={false} />
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
  const explode = useApp((s) => s.explode)
  const labels = useApp((s) => s.layers.labels)
  const roomsOn = useApp((s) => s.layers.rooms)
  const rooms = useMemo(() => floor.rooms.filter((r) => r.type !== 'stair'), [floor])
  const roomItems = useMemo(() => rooms.map((r) => ({ poly: r.polygon, color: ROOM_COLORS[r.type] ?? '#475569' })), [rooms])
  const doorItems = useMemo(
    () =>
      floor.doors
        .filter((d) => (d.rect ?? []).length >= 3)
        .map((d) => ({ poly: d.rect as Vec2[], color: DOOR_COLORS[doors[d.id] ?? d.state] })),
    [floor, doors],
  )
  const stairItems = useMemo(() => floor.stairs.map((s) => ({ poly: s.polygon, color: '#f97316' })), [floor])
  const exitItems = useMemo(() => floor.exits.map((e) => ({ poly: e.polygon, color: '#22c55e' })), [floor])
  return (
    <group position-y={floorY(floor, explode)}>
      <group name="walls" ref={walls} scale-y={0.001}>
        <Walls floor={floor} />
      </group>
      {roomsOn && <FlatBatch items={roomItems} y={0.02} opacity={0.15} />}
      {labels &&
        rooms.map((r) => {
          const [x, y] = centroid(r.polygon)
          return (
            <Html key={r.id} position={toWorld(x, y, 0.3)} center style={labelStyle}>
              <div style={{ fontSize: 11, color: '#e2e8f0', whiteSpace: 'nowrap', textShadow: '0 0 3px #000' }}>{r.id}</div>
            </Html>
          )
        })}
      <FlatBatch items={doorItems} y={0.03} opacity={1} />
      <FlatBatch items={stairItems} y={0.04} opacity={0.35} />
      <FlatBatch items={exitItems} y={0.04} opacity={0.8} />
      {labels &&
        floor.stairs.map((s) => {
          const [x, y] = centroid(s.polygon)
          return (
            <Html key={s.id} position={toWorld(x, y, 0.3)} center style={labelStyle}>
              <div style={{ fontSize: 11, color: '#fdba74', textShadow: '0 0 3px #000' }}>{s.group}</div>
            </Html>
          )
        })}
      {floor.exits.map((e) => {
        const [x, y] = centroid(e.polygon)
        return (
          <Html key={e.id} position={toWorld(x, y, 0.3)} center style={labelStyle}>
            <div style={{ fontSize: 11, color: '#86efac', whiteSpace: 'nowrap', textShadow: '0 0 3px #000' }}>{e.name}</div>
          </Html>
        )
      })}
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
