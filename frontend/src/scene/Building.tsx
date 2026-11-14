import { useLayoutEffect, useMemo, useRef } from 'react'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { useApp } from '../store/app'
import type { BuildingFloor, DoorState, Vec2 } from '../data/types'
import { floorY, ringSegments, toWorld } from './geometry'
import type { Segment } from './geometry'

const WALL_T = 0.15
const ROOM_COLORS: Record<string, string> = {
  classroom: '#38bdf8', office: '#a78bfa', lobby: '#34d399', corridor: '#64748b',
  lab: '#f472b6', kitchen: '#fb923c', restroom: '#94a3b8', storage: '#a16207',
}
const DOOR_COLORS: Record<DoorState, string> = { open: '#3b82f6', closed: '#1e3a8a', propped: '#22d3ee', blocked: '#ef4444' }

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

function centroid(poly: Vec2[]): Vec2 {
  const n = poly.length || 1
  return [poly.reduce((s, p) => s + p[0], 0) / n, poly.reduce((s, p) => s + p[1], 0) / n]
}

const labelStyle = { pointerEvents: 'none' as const }

function Floor({ floor, doors }: { floor: BuildingFloor; doors: Record<string, DoorState> }) {
  const explode = useApp((s) => s.explode)
  const labels = useApp((s) => s.layers.labels)
  const roomsOn = useApp((s) => s.layers.rooms)
  const rooms = floor.rooms.filter((r) => r.type !== 'stair')
  return (
    <group position-y={floorY(floor, explode)}>
      <group name="walls">
        <Walls floor={floor} />
      </group>
      {roomsOn &&
        rooms.map((r) => <Flat key={r.id} poly={r.polygon} y={0.02} color={ROOM_COLORS[r.type] ?? '#94a3b8'} opacity={0.12} />)}
      {labels &&
        rooms.map((r) => {
          const [x, y] = centroid(r.polygon)
          return (
            <Html key={r.id} position={toWorld(x, y, 0.3)} center style={labelStyle}>
              <div style={{ fontSize: 11, color: '#e2e8f0', whiteSpace: 'nowrap', textShadow: '0 0 3px #000' }}>{r.id}</div>
            </Html>
          )
        })}
      {floor.doors.map((d) => {
        const poly = d.rect ?? []
        if (poly.length < 3) return null
        return <Flat key={d.id} poly={poly} y={0.03} color={DOOR_COLORS[doors[d.id] ?? d.state]} opacity={1} />
      })}
      {floor.stairs.map((s) => {
        const [x, y] = centroid(s.polygon)
        return (
          <group key={s.id}>
            <Flat poly={s.polygon} y={0.04} color="#f97316" opacity={0.6} />
            {labels && (
              <Html position={toWorld(x, y, 0.3)} center style={labelStyle}>
                <div style={{ fontSize: 11, color: '#fdba74', textShadow: '0 0 3px #000' }}>{s.group}</div>
              </Html>
            )}
          </group>
        )
      })}
      {floor.exits.map((e) => {
        const [x, y] = centroid(e.polygon)
        return (
          <group key={e.id}>
            <Flat poly={e.polygon} y={0.04} color="#22c55e" opacity={0.8} />
            <Html position={toWorld(x, y, 0.3)} center style={labelStyle}>
              <div style={{ fontSize: 11, color: '#86efac', whiteSpace: 'nowrap', textShadow: '0 0 3px #000' }}>{e.name}</div>
            </Html>
          </group>
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
          <Floor key={building.id + f.id} floor={f} doors={doors} />
        ))}
    </>
  )
}
