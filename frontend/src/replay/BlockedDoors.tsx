import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { floorAlpha, floorPlace, toPlaced } from '../scene/geometry'
import { readSpread } from '../model/fireSpread'
import { spreadStats } from './BurningRooms'
import { CLOSED_BY_FIRE_COLOR } from '../scene/Building'
import { flatGeometry } from './flat'
import type { Building, BuildingFloor, Door, Run, Vec2 } from '../data/types'

const OPACITY = 0.85
/** Above the neutral doors Building draws at 0.03, below the stairs, exits and room tints. */
const OVERLAY_Y = 0.035
const STRIP_WIDTH = 0.3

/** The door's footprint, else a 0.3 m wide strip from one end of the opening to the other. */
function doorShape(d: Door): Vec2[] | null {
  if (d.rect && d.rect.length >= 3) return d.rect
  const dx = d.b[0] - d.a[0]
  const dy = d.b[1] - d.a[1]
  const len = Math.hypot(dx, dy)
  if (!(len > 1e-6)) return null
  const nx = (-dy / len) * (STRIP_WIDTH / 2)
  const ny = (dx / len) * (STRIP_WIDTH / 2)
  return [
    [d.a[0] + nx, d.a[1] + ny],
    [d.b[0] + nx, d.b[1] + ny],
    [d.b[0] - nx, d.b[1] - ny],
    [d.a[0] - nx, d.a[1] - ny],
  ]
}

interface Closing {
  floor: BuildingFloor
  /** when the door closes, from the run's `door_blocked` event (the first one of that door) */
  t: number
  poly: Vec2[]
}

/** The doors the run closes: one entry per `door_blocked` event whose door the building has. */
function closingsOf(run: Run, building: Building): Closing[] {
  const out = new Map<string, Closing>()
  for (const e of run.events) {
    if (e.type !== 'door_blocked' || typeof e.door !== 'string' || typeof e.t !== 'number' || !Number.isFinite(e.t)) continue
    const floors = typeof e.floor === 'string' ? building.floors.filter((f) => f.id === e.floor) : building.floors
    for (const floor of floors) {
      const door = floor.doors.find((d) => d.id === e.door)
      if (!door) continue
      const poly = doorShape(door)
      const k = `${floor.id}|${door.id}`
      const prev = out.get(k)
      if (poly && (!prev || e.t < prev.t)) out.set(k, { floor, t: e.t, poly })
      break
    }
  }
  return [...out.values()]
}

function Overlays({ closings, building, runKey }: { closings: Closing[]; building: Building; runKey: string }) {
  const geos = useMemo(() => closings.map((c) => flatGeometry(c.poly)), [closings])
  useEffect(() => () => geos.forEach((g) => g.dispose()), [geos])
  const meshes = useRef<(THREE.Mesh | null)[]>([])

  useFrame(() => {
    const { visibleFloors, viewMode, focusFloor, explode } = useApp.getState()
    const t = useClock.getState().t
    let shown = 0
    for (let i = 0; i < closings.length; i++) {
      const m = meshes.current[i]
      if (!m) continue
      const c = closings[i]
      const on = c.t <= t && (!visibleFloors || visibleFloors.includes(c.floor.id))
      m.visible = on
      if (!on) continue
      shown++
      ;(m.material as THREE.MeshBasicMaterial).opacity = OPACITY * floorAlpha(viewMode, focusFloor, c.floor.id)
      const at = toPlaced(floorPlace(building, c.floor, viewMode, explode), 0, 0, OVERLAY_Y)
      m.position.set(at[0], at[1], at[2])
    }
    if (useApp.getState().activeRunKey === runKey) spreadStats.closed = shown
  })

  return (
    <>
      {geos.map((g, i) => (
        <mesh key={i} ref={(m) => { meshes.current[i] = m }} geometry={g} visible={false} renderOrder={1}>
          <meshBasicMaterial color={CLOSED_BY_FIRE_COLOR} transparent opacity={OPACITY} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </>
  )
}

/**
 * The doors the simulation closes, red from the moment of their `door_blocked` event: Building draws every door in one neutral colour,
 * and a door that a burning room closes mid-run turns red over it. Drawn for runs that carry a spread (`fire.rooms`); every other run
 * has only the neutral doors.
 */
export default function BlockedDoors({ runKey }: { runKey?: string }) {
  const activeKey = useApp((s) => s.activeRunKey)
  const building = useApp((s) => s.building)
  const key = runKey ?? activeKey
  const lr = useApp((s) => (key ? s.runs[key] : undefined))
  const closings = useMemo(() => (lr && building && readSpread(lr.run) ? closingsOf(lr.run, building) : []), [lr, building])
  // With nothing to draw the qa number still follows the active run: no door overlay.
  useFrame(() => {
    if (closings.length === 0 && key === useApp.getState().activeRunKey) spreadStats.closed = 0
  })
  if (!key || !building || closings.length === 0) return null
  return <Overlays key={key} closings={closings} building={building} runKey={key} />
}
