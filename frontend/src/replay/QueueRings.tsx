import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { floorAlpha, floorPlace, toPlaced } from '../scene/geometry'
import type { Place } from '../scene/geometry'
import { nearestIndex } from './runIndex'
import { queueCounts, queueTargets } from './queues'
import type { QueueTarget } from './queues'
import type { Building } from '../data/types'

const COL = { lo: new THREE.Color('#facc15'), mid: new THREE.Color('#fb923c'), hi: new THREE.Color('#ef4444') }

interface Counts {
  v: Uint16Array
  frame: number
  /** bumped whenever v is replaced, so the ring matrices are rewritten */
  rev: number
}

const LABELS = 20
const COUNT_EVERY_MS = 100
const ringGeo = new THREE.RingGeometry(0.9, 1, 40)
const ringMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.8, side: THREE.DoubleSide, depthWrite: false })

/** One InstancedMesh for every ring, plus a fixed pool of imperatively moved count labels. */
function Rings({ targets, counts, building }: { targets: QueueTarget[]; counts: Counts; building: Building }) {
  const mesh = useRef<THREE.InstancedMesh>(null)
  const groups = useRef<(THREE.Group | null)[]>([])
  const divs = useRef<(HTMLDivElement | null)[]>([])
  const last = useRef({ rev: -1, explode: NaN, visible: undefined as string[] | null | undefined, mode: '', focus: undefined as string | null | undefined })
  const tmp = useMemo(
    () => ({ m: new THREE.Matrix4(), q: new THREE.Quaternion().setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0)), p: new THREE.Vector3(), s: new THREE.Vector3(), c: new THREE.Color() }),
    [],
  )
  const floorOf = useMemo(() => {
    const m = new Map<string, Building['floors'][number]>()
    for (const f of building.floors) m.set(f.id, f)
    return m
  }, [building])

  useFrame(() => {
    const m = mesh.current
    if (!m) return
    const { explode, visibleFloors, viewMode, focusFloor } = useApp.getState()
    const l = last.current
    if (l.rev === counts.rev && l.explode === explode && l.visible === visibleFloors && l.mode === viewMode && l.focus === focusFloor) return
    l.rev = counts.rev
    l.explode = explode
    l.visible = visibleFloors
    l.mode = viewMode
    l.focus = focusFloor
    const { m: mat, q, p, s, c } = tmp
    const big: { i: number; n: number }[] = []
    const places = new Map<string, Place>()
    const placeOf = (f: Building['floors'][number]) => {
      let pl = places.get(f.id)
      if (!pl) places.set(f.id, (pl = floorPlace(building, f, viewMode, explode)))
      return pl
    }
    // Rings and counts are left off the faint floors of the ghost view.
    const hidden = (f: Building['floors'][number] | undefined) => !f || (!!visibleFloors && !visibleFloors.includes(f.id)) || floorAlpha(viewMode, focusFloor, f.id) < 1
    for (let i = 0; i < targets.length; i++) {
      const t = targets[i]
      const f = floorOf.get(t.floorId)
      const n = counts.v[i] ?? 0
      if (!f || hidden(f) || n < 2) {
        p.set(0, 0, 0)
        s.set(0, 0, 0)
      } else {
        const w = toPlaced(placeOf(f), t.cx, t.cy, 0.1)
        p.set(w[0], w[1], w[2])
        const r = Math.min(3, 0.5 + 0.12 * n)
        s.set(r, r, 1)
        c.copy(n >= 15 ? COL.hi : n >= 5 ? COL.mid : COL.lo)
        m.setColorAt(i, c)
        big.push({ i, n })
      }
      mat.compose(p, q, s)
      m.setMatrixAt(i, mat)
    }
    m.instanceMatrix.needsUpdate = true
    if (m.instanceColor) m.instanceColor.needsUpdate = true
    big.sort((a, b) => b.n - a.n)
    for (let j = 0; j < LABELS; j++) {
      const g = groups.current[j]
      const d = divs.current[j]
      if (!g || !d) continue
      const b = big[j]
      if (!b) {
        d.style.display = 'none'
        g.visible = false
        continue
      }
      const t = targets[b.i]
      const f = floorOf.get(t.floorId)!
      const w = toPlaced(placeOf(f), t.cx, t.cy, 0.1)
      g.position.set(w[0], w[1], w[2])
      g.visible = true
      d.style.display = ''
      d.textContent = String(b.n)
    }
  })

  return (
    <>
      <instancedMesh ref={mesh} args={[ringGeo, ringMat, targets.length]} frustumCulled={false} />
      {Array.from({ length: LABELS }, (_, j) => (
        <group key={j} ref={(g) => { groups.current[j] = g }} visible={false}>
          <Html center style={{ pointerEvents: 'none' }}>
            <div ref={(d) => { divs.current[j] = d }} className="l3d count" style={{ display: 'none' }} />
          </Html>
        </group>
      ))}
    </>
  )
}

export default function QueueRings({ runKey }: { runKey?: string }) {
  const activeKey = useApp((s) => s.activeRunKey)
  const on = useApp((s) => s.layers.queues)
  const building = useApp((s) => s.building)
  const key = runKey ?? activeKey
  const lr = useApp((s) => (key ? s.runs[key] : undefined))
  const targets = useMemo(() => (building ? queueTargets(building) : []), [building])
  const counts = useMemo<Counts>(() => ({ v: new Uint16Array(targets.length), frame: -2, rev: 0 }), [targets, key])

  const lastMs = useRef(0)
  useFrame(() => {
    if (!lr || !building || !on) return
    const f = nearestIndex(lr.index.times, useClock.getState().t)
    if (f === counts.frame) return
    const now = performance.now()
    if (counts.frame !== -2 && now - lastMs.current < COUNT_EVERY_MS) return
    lastMs.current = now
    counts.frame = f
    counts.v = queueCounts(lr.index, building, lr.run.floors, f, targets)
    counts.rev++
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
  return <Rings key={key} targets={targets} counts={counts} building={building} />
}
