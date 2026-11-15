import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { floorAlpha, floorPlace, pointInPolygon, toPlaced } from '../scene/geometry'
import { insidePoint } from '../model/scenarioDraft'
import { readSpread, spreadTint } from '../model/fireSpread'
import { flatGeometry } from './flat'
import type { Spread } from '../model/fireSpread'
import type { Building, BuildingFloor, Run, Vec2 } from '../data/types'

/**
 * What the replay draws of the spread right now, for the qa step: `burning` is the rooms of `fire.rooms` with `ignite <= t`, `drawn`
 * the tints visible (a room the building lacks, a hidden floor and the fire layer switched off all leave one out), and `closed` the
 * red door overlays shown (BlockedDoors). It follows the active run only.
 */
export const spreadStats = { burning: 0, drawn: 0, closed: 0 }
if (typeof window !== 'undefined' && (import.meta.env.DEV || new URLSearchParams(location.search).has('qa')))
  (window as unknown as { __spread: typeof spreadStats }).__spread = spreadStats

/** Above the room fills (0.02), doors (0.03) and stairs and exits (0.04) of Building, below the heatmap (0.06). */
const TINT_Y = 0.05
const CONE_R = 0.35
const CONE_H = 0.9
const FIRE = '#F97316'
/** The base sits on the floor, so a bigger glow grows the cone upward from it instead of sinking it through the slab. */
const coneGeo = new THREE.ConeGeometry(CONE_R, CONE_H, 16).translate(0, CONE_H / 2, 0)
const coneMat = new THREE.MeshStandardMaterial({ color: FIRE, emissive: FIRE, emissiveIntensity: 1, roughness: 0.6 })

interface Item {
  floor: BuildingFloor
  ignite: number
  geo: THREE.BufferGeometry
  /** where the marker cone stands; null in the room that holds the fire sphere */
  cone: Vec2 | null
}

const warned = new WeakSet<Run>()

/** One tint per room of the spread. A room the building lacks is skipped, with one warning per run. */
function buildItems(spread: Spread, building: Building, run: Run): Item[] {
  const items: Item[] = []
  const missing: string[] = []
  const fire = run.fire
  for (const fr of spread.rooms) {
    const floor = building.floors.find((f) => f.id === fr.floor)
    const room = floor?.rooms.find((r) => r.id === fr.room)
    if (!floor || !room || room.polygon.length < 3) {
      missing.push(`${fr.floor}/${fr.room}`)
      continue
    }
    const holdsFire = fire.floor === floor.id && pointInPolygon([fire.x, fire.y], room.polygon)
    items.push({ floor, ignite: fr.ignite, geo: flatGeometry(room.polygon), cone: holdsFire ? null : insidePoint(room.polygon) })
  }
  if (missing.length > 0 && !warned.has(run)) {
    warned.add(run)
    console.warn(`fire.rooms of run ${run.id} names rooms that building ${building.id} lacks, skipped: ${missing.join(', ')}`)
  }
  return items
}

function Tints({ spread, run, building, runKey }: { spread: Spread; run: Run; building: Building; runKey: string }) {
  const items = useMemo(() => buildItems(spread, building, run), [spread, building, run])
  useEffect(() => () => items.forEach((it) => it.geo.dispose()), [items])
  const coned = useMemo(() => items.filter((it) => it.cone !== null), [items])
  const meshes = useRef<(THREE.Mesh | null)[]>([])
  const cones = useRef<THREE.InstancedMesh>(null)
  const tmp = useMemo(() => ({ m: new THREE.Matrix4(), q: new THREE.Quaternion(), p: new THREE.Vector3(), s: new THREE.Vector3() }), [])
  // Until the first frame every cone is scaled to nothing (an instanced mesh starts with identity matrices).
  useLayoutEffect(() => {
    const c = cones.current
    if (!c) return
    tmp.m.makeScale(0, 0, 0)
    for (let j = 0; j < coned.length; j++) c.setMatrixAt(j, tmp.m)
    c.instanceMatrix.needsUpdate = true
  }, [coned, tmp])

  useFrame(() => {
    const st = useApp.getState()
    const { visibleFloors, viewMode, focusFloor, explode, fireGlow } = st
    const t = useClock.getState().t
    let burning = 0
    for (const r of spread.rooms) if (r.ignite <= t) burning++
    let drawn = 0
    const shown = (it: Item) => it.ignite <= t && (!visibleFloors || visibleFloors.includes(it.floor.id))
    // A tint takes its colour and opacity from its age; the faint floors of the ghost view get the ghost's share.
    for (let i = 0; i < items.length; i++) {
      const it = items[i]
      const mesh = meshes.current[i]
      if (!mesh) continue
      const on = shown(it)
      mesh.visible = on
      if (!on) continue
      drawn++
      const tint = spreadTint(it.ignite, t, fireGlow)
      const mat = mesh.material as THREE.MeshBasicMaterial
      mat.color.setRGB(tint.r / 255, tint.g / 255, tint.b / 255, THREE.SRGBColorSpace)
      mat.opacity = tint.opacity * floorAlpha(viewMode, focusFloor, it.floor.id)
      const at = toPlaced(floorPlace(building, it.floor, viewMode, explode), 0, 0, TINT_Y)
      mesh.position.set(at[0], at[1], at[2])
    }
    // The markers: hidden until their room ignites, and left off the faint floors of the ghost view (like the queue rings).
    const c = cones.current
    if (c) {
      const grow = 0.6 + 0.4 * fireGlow
      for (let j = 0; j < coned.length; j++) {
        const it = coned[j]
        const s = shown(it) && floorAlpha(viewMode, focusFloor, it.floor.id) === 1 ? grow : 0
        const at = toPlaced(floorPlace(building, it.floor, viewMode, explode), (it.cone as Vec2)[0], (it.cone as Vec2)[1], 0)
        tmp.p.set(at[0], at[1], at[2])
        tmp.s.set(s, s, s)
        tmp.m.compose(tmp.p, tmp.q, tmp.s)
        c.setMatrixAt(j, tmp.m)
      }
      c.instanceMatrix.needsUpdate = true
    }
    if (st.activeRunKey === runKey) {
      spreadStats.burning = burning
      spreadStats.drawn = drawn
    }
  })

  return (
    <>
      {items.map((it, i) => (
        <mesh key={i} ref={(m) => { meshes.current[i] = m }} geometry={it.geo} visible={false} renderOrder={-1}>
          <meshBasicMaterial color={FIRE} transparent opacity={0} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
        </mesh>
      ))}
      {coned.length > 0 && <instancedMesh key={coned.length} ref={cones} args={[coneGeo, coneMat, coned.length]} frustumCulled={false} />}
    </>
  )
}

/**
 * The rooms the fire has spread to (`run.fire.rooms`): each is tinted from orange to red from its ignition time, and carries a cone
 * marker. It draws only while the Fire layer is on, and nothing at all for a run without `fire.rooms`.
 */
export default function BurningRooms({ runKey }: { runKey?: string }) {
  const activeKey = useApp((s) => s.activeRunKey)
  const on = useApp((s) => s.layers.fire)
  const building = useApp((s) => s.building)
  const key = runKey ?? activeKey
  const lr = useApp((s) => (key ? s.runs[key] : undefined))
  const spread = useMemo(() => readSpread(lr?.run), [lr])
  const drawing = on && !!spread && !!building && !!lr
  // With nothing drawn the numbers still follow the active run: how many rooms burn at t, and no tint.
  useFrame(() => {
    if (drawing || key !== useApp.getState().activeRunKey) return
    const t = useClock.getState().t
    let burning = 0
    if (spread) for (const r of spread.rooms) if (r.ignite <= t) burning++
    spreadStats.burning = burning
    spreadStats.drawn = 0
  })
  if (!on || !spread || !building || !lr || !key) return null
  return <Tints key={key} spread={spread} run={lr.run} building={building} runKey={key} />
}
