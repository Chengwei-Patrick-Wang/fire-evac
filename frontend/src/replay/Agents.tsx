import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { toWorld, floorY } from '../scene/geometry'
import { sampleAgent } from './runIndex'
import type { AgentSample } from './runIndex'

const PROFILE_COLORS = ['#38bdf8', '#a78bfa', '#facc15', '#f472b6', '#fb7185', '#34d399']
const WAITING = '#f59e0b'
const NOT_MOVING = '#6b7280'
const TRAPPED = '#ef4444'

export default function Agents({ runKey }: { runKey?: string }) {
  const activeKey = useApp((s) => s.activeRunKey)
  const key = runKey ?? activeKey
  const lr = useApp((s) => (key ? s.runs[key] : undefined))
  const building = useApp((s) => s.building)
  const ix = lr?.index
  const n = ix?.nAgents ?? 0
  const mesh = useRef<THREE.InstancedMesh>(null)
  const keys = useMemo(() => new Int16Array(n).fill(-2), [n, key])
  const colors = useMemo(() => PROFILE_COLORS.map((c) => new THREE.Color(c)), [])
  const tmp = useMemo(
    () => ({
      m: new THREE.Matrix4(),
      q: new THREE.Quaternion(),
      p: new THREE.Vector3(),
      s: new THREE.Vector3(),
      c: new THREE.Color(),
      out: { x: 0, y: 0, fl: 0, st: 0, trapped: false } as AgentSample,
    }),
    [],
  )
  // floor index of the run -> building floor
  const floors = useMemo(
    () => (lr && building ? lr.run.floors.map((id) => building.floors.find((f) => f.id === id)) : []),
    [lr, building],
  )

  useEffect(() => {
    keys.fill(-2)
  }, [keys])

  useFrame(() => {
    const m = mesh.current
    if (!m || !ix) return
    const { explode, visibleFloors } = useApp.getState()
    const t = useClock.getState().t
    const { out, m: mat, q, p, s, c } = tmp
    for (let i = 0; i < n; i++) {
      let ok = sampleAgent(ix, i, t, out)
      const f = ok ? floors[out.fl] : undefined
      if (!f || (visibleFloors && !visibleFloors.includes(f.id))) ok = false
      let k = -1
      if (ok && f) {
        k = out.trapped ? 100 : out.st === 0 ? 0 : out.st === 2 ? 2 : out.st === 3 ? 30 + ix.profile[i] : 10 + ix.profile[i]
        const w = toWorld(out.x, out.y, floorY(f, useApp.getState().explode) + 0.87)
        p.set(w[0], w[1], w[2])
        const sc = k >= 30 && k < 100 ? 0.6 : 1
        s.set(sc, sc, sc)
      } else {
        p.set(0, 0, 0)
        s.set(0, 0, 0)
      }
      mat.compose(p, q, s)
      m.setMatrixAt(i, mat)
      if (k !== keys[i] && k >= 0) {
        keys[i] = k
        if (k === 100) c.set(TRAPPED)
        else if (k === 0) c.set(NOT_MOVING)
        else if (k === 2) c.set(WAITING)
        else if (k >= 30) c.copy(colors[k - 30])
        else c.copy(colors[k - 10])
        m.setColorAt(i, c)
        if (m.instanceColor) m.instanceColor.needsUpdate = true
      }
    }
    void explode
    m.instanceMatrix.needsUpdate = true
  })

  if (!ix || n === 0) return null
  return (
    <instancedMesh key={`${key}-${n}`} ref={mesh} args={[undefined, undefined, n]} frustumCulled={false}>
      <capsuleGeometry args={[0.22, 1.3]} />
      <meshStandardMaterial />
    </instancedMesh>
  )
}
