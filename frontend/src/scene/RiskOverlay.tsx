import { useEffect, useMemo, useState } from 'react'
import * as THREE from 'three'
import { Html } from '@react-three/drei'
import { useApp } from '../store/app'
import { floorY, toWorld } from './geometry'
import { centroidOf, rampColor, riskRange, roomRiskColor, stairScore } from '../model/spots'
import Heatmap from '../replay/Heatmap'
import type { BuildingFloor, Vec2 } from '../data/types'

function RoomFill({ poly, color, onClick }: { poly: Vec2[]; color: string; onClick: () => void }) {
  const geo = useMemo(() => {
    const s = new THREE.Shape()
    poly.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)))
    return new THREE.ShapeGeometry(s)
  }, [poly])
  useEffect(() => () => geo.dispose(), [geo])
  return (
    <mesh geometry={geo} rotation-x={-Math.PI / 2} position-y={0.05} onClick={(e) => { e.stopPropagation(); onClick() }}>
      <meshBasicMaterial color={color} transparent opacity={0.75} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
  )
}

function PulseRing({ pos, y }: { pos: Vec2; y: number }) {
  const [on, setOn] = useState(true)
  useEffect(() => {
    const t = setTimeout(() => setOn(false), 3000)
    return () => clearTimeout(t)
  }, [])
  if (!on) return null
  return (
    <mesh position={toWorld(pos[0], pos[1], y + 0.15)} rotation-x={-Math.PI / 2}>
      <ringGeometry args={[1.0, 1.3, 40]} />
      <meshBasicMaterial color="#f8fafc" transparent opacity={0.9} depthWrite={false} />
    </mesh>
  )
}

function FloorRisk({ floor }: { floor: BuildingFloor }) {
  const explode = useApp((s) => s.explode)
  const batch = useApp((s) => s.batch)
  const metric = useApp((s) => s.riskMetric)
  const building = useApp((s) => s.building)
  const focus = useApp((s) => s.focus)
  const range = useMemo(() => (batch ? riskRange(batch, metric) : null), [batch, metric])
  if (!batch || !building) return null
  const maxScore = Math.max(1e-9, ...batch.doors.map((d) => d.score))
  const stairRooms = new Set(floor.stairs.map((s) => s.room))
  const y = floorY(floor, explode)
  return (
    <group position-y={y}>
      {floor.rooms
        .filter((r) => r.type !== 'stair' && !stairRooms.has(r.id))
        .map((r) => (
          <RoomFill
            key={r.id}
            poly={r.polygon}
            color={roomRiskColor(batch.rooms.find((b) => b.id === r.id), metric, range)}
            onClick={() => useApp.setState({ selectedRoom: r.id })}
          />
        ))}
      {floor.doors.map((d) => {
        const sc = batch.doors.find((x) => x.id === d.id)?.score
        if (sc === undefined) return null
        const [x, yy] = d.rect && d.rect.length >= 3 ? centroidOf(d.rect) : [(d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2]
        const v = sc / maxScore
        return (
          <mesh key={d.id} position={toWorld(x, yy, 0.08)} rotation-x={-Math.PI / 2}>
            <circleGeometry args={[0.4 + 0.8 * v, 24]} />
            <meshBasicMaterial color={rampColor(v)} transparent opacity={0.9} depthWrite={false} />
          </mesh>
        )
      })}
      {floor.stairs.map((s) => {
        const v = stairScore(building, batch, s.room) / maxScore
        return <RoomFill key={s.id} poly={s.polygon} color={rampColor(v)} onClick={() => undefined} />
      })}
      {focus && focus.floorId === floor.id && <PulseRing key={focus.nonce} pos={focus.pos} y={0} />}
    </group>
  )
}

export default function RiskOverlay() {
  const on = useApp((s) => s.layers.risk)
  const building = useApp((s) => s.building)
  const batch = useApp((s) => s.batch)
  const visible = useApp((s) => s.visibleFloors)
  const crowding = useApp((s) => s.crowding)
  const selected = useApp((s) => s.selectedRoom)
  const metric = useApp((s) => s.riskMetric)
  const heat = useApp((s) => s.layers.heatmap)
  // The crowding toggle shows the batch heatmap through the shared Heatmap layer.
  useEffect(() => {
    if (on && crowding && !heat) useApp.setState((s) => ({ layers: { ...s.layers, heatmap: true } }))
  }, [on, crowding, heat])
  if (!building || !batch) return null
  const sel = selected ? batch.rooms.find((r) => r.id === selected) : null
  const selFloor = sel ? building.floors.find((f) => f.id === sel.floor) : null
  const selRoom = selFloor?.rooms.find((r) => r.id === selected)
  return (
    <>
      {on &&
        building.floors
          .filter((f) => !visible || visible.includes(f.id))
          .map((f) => <FloorRisk key={f.id} floor={f} />)}
      {on && crowding && <Heatmap source="batch" />}
      {on && sel && selFloor && selRoom && (
        <Html position={toWorld(...centroidOf(selRoom.polygon), floorY(selFloor, 0) + 1.5)} center style={{ pointerEvents: 'none' }}>
          <div style={{ background: '#0f172ae6', border: '1px solid #475569', borderRadius: 4, padding: '4px 8px', fontSize: 12, whiteSpace: 'nowrap' }}>
            <b>{sel.id}</b> {selRoom.name}
            <br />
            riskT90: {sel.riskT90 === null ? 'not reached' : `${sel.riskT90.toFixed(0)} s`}
            <br />
            riskTrapped: {sel.riskTrapped === null ? 'n/a' : sel.riskTrapped}
            <br />
            fires started here: {sel.n}
            {metric === 'riskT90' ? '' : ''}
          </div>
        </Html>
      )}
    </>
  )
}
