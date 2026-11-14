import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { floorY, toWorld } from '../scene/geometry'
import { nearestIndex } from './runIndex'
import { queueCounts, queueTargets } from './queues'
import type { QueueTarget } from './queues'

const COL = { lo: new THREE.Color('#facc15'), mid: new THREE.Color('#fb923c'), hi: new THREE.Color('#ef4444') }

interface Counts {
  v: Uint16Array
  frame: number
}

function Ring({ target, i, counts }: { target: QueueTarget; i: number; counts: Counts }) {
  const building = useApp((s) => s.building)!
  const explode = useApp((s) => s.explode)
  const visible = useApp((s) => s.visibleFloors)
  const mesh = useRef<THREE.Mesh>(null)
  const label = useRef<HTMLDivElement>(null)
  const shown = useRef(-1)
  const geo = useMemo(() => new THREE.RingGeometry(0.9, 1, 40), [])
  const mat = useMemo(
    () => new THREE.MeshBasicMaterial({ color: COL.lo, transparent: true, opacity: 0.8, side: THREE.DoubleSide, depthWrite: false }),
    [],
  )
  useEffect(() => () => {
    geo.dispose()
    mat.dispose()
  }, [geo, mat])
  const floor = building.floors.find((f) => f.id === target.floorId)

  useFrame(() => {
    const m = mesh.current
    if (!m) return
    const n = counts.v[i] ?? 0
    if (n === shown.current) return
    shown.current = n
    m.visible = n >= 2
    const r = Math.min(3, 0.5 + 0.12 * n)
    m.scale.set(r, r, 1)
    mat.color.copy(n >= 15 ? COL.hi : n >= 5 ? COL.mid : COL.lo)
    if (label.current) label.current.textContent = String(n)
  })

  if (!floor || (visible && !visible.includes(floor.id))) return null
  return (
    <mesh
      ref={mesh}
      visible={false}
      geometry={geo}
      material={mat}
      position={toWorld(target.cx, target.cy, floorY(floor, explode) + 0.1)}
      rotation={[-Math.PI / 2, 0, 0]}
    >
      <Html center style={{ pointerEvents: 'none' }}>
        <div ref={label} style={{ color: '#fff', fontSize: 11, textShadow: '0 0 3px #000' }} />
      </Html>
    </mesh>
  )
}

export default function QueueRings({ runKey }: { runKey?: string }) {
  const activeKey = useApp((s) => s.activeRunKey)
  const on = useApp((s) => s.layers.queues)
  const building = useApp((s) => s.building)
  const key = runKey ?? activeKey
  const lr = useApp((s) => (key ? s.runs[key] : undefined))
  const targets = useMemo(() => (building ? queueTargets(building) : []), [building])
  const counts = useMemo<Counts>(() => ({ v: new Uint16Array(targets.length), frame: -2 }), [targets, key])

  useFrame(() => {
    if (!lr || !building) return
    const f = nearestIndex(lr.index.times, useClock.getState().t)
    if (f === counts.frame) return
    counts.frame = f
    counts.v = queueCounts(lr.index, building, lr.run.floors, f, targets)
  })

  // Dev check: client-side peak vs metrics.doors[].peakQueue.
  useEffect(() => {
    if (!import.meta.env.DEV || !lr || !building || !lr.run.metrics.doors) return
    const peaks = new Uint16Array(targets.length)
    for (let f = 0; f < lr.index.nFrames; f++) {
      const c = queueCounts(lr.index, building, lr.run.floors, f, targets)
      for (let i = 0; i < c.length; i++) if (c[i] > peaks[i]) peaks[i] = c[i]
    }
    const bad = lr.run.metrics.doors.filter((d) => {
      const i = targets.findIndex((t) => t.kind === 'door' && t.id === d.id && t.floorId === d.floor)
      return i >= 0 && peaks[i] !== d.peakQueue
    })
    if (bad.length === 0) console.log('queues OK')
    else console.warn('queues differ:', bad.map((d) => d.id).join(', '))
  }, [lr, building, targets])

  if (!on || !lr || !building) return null
  return (
    <>
      {targets.map((t, i) => (
        <Ring key={key + t.kind + t.id} target={t} i={i} counts={counts} />
      ))}
    </>
  )
}
