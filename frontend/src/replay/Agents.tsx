import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import Trails from './Trails'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { toWorld, floorY } from '../scene/geometry'
import { nearestIndex, sampleAgent } from './runIndex'
import type { AgentSample } from './runIndex'

const PROFILE_COLORS = ['#38bdf8', '#a78bfa', '#facc15', '#f472b6', '#fb7185', '#34d399']
export { PROFILE_COLORS }
export const STATUS_COLORS = {
  notMoving: '#94a3b8',
  moving: '#38bdf8',
  waiting: '#fbbf24',
  stairwell: '#c084fc',
  trapped: '#ef4444',
}
const WAITING = STATUS_COLORS.waiting
const NOT_MOVING = STATUS_COLORS.notMoving
const TRAPPED = STATUS_COLORS.trapped
const DIM = '#1f2937'
const STATUS_NAMES = ['not moving', 'moving', 'waiting', 'exiting']
type Timer = { i: number; p: [number, number, number]; s: number }

export default function Agents({ runKey }: { runKey?: string }) {
  const activeKey = useApp((s) => s.activeRunKey)
  const key = runKey ?? activeKey
  const lr = useApp((s) => (key ? s.runs[key] : undefined))
  const building = useApp((s) => s.building)
  const ix = lr?.index
  const n = ix?.nAgents ?? 0
  const mesh = useRef<THREE.InstancedMesh>(null)
  const ring = useRef<THREE.InstancedMesh>(null)
  const lens = useApp((s) => s.lens)
  const trails = useApp((s) => s.trails)
  const agentColor = useApp((s) => s.agentColor)
  const lensOn = !lens.every(Boolean)
  const lensKey = lens.map((v) => (v ? 1 : 0)).join('')
  const [hover, setHover] = useState<number | null>(null)
  const [timers, setTimers] = useState<Timer[]>([])
  const timerKey = useRef(-1)
  const llmIdx = useMemo(() => {
    const set = new Set<number>()
    if (lr) {
      for (const a of lr.run.agents) if (a.llm) set.add(a.idx)
      for (const e of lr.run.events) if (e.llm && e.idx !== undefined) set.add(e.idx)
    }
    return [...set].filter((i) => i >= 0 && i < n).sort((a, b) => a - b)
  }, [lr, n])
  const keys = useMemo(() => new Int16Array(n).fill(-2), [n, key, lensKey, agentColor])
  const colors = useMemo(
    () => (agentColor === 'profile' ? PROFILE_COLORS : [0, 1, 2, 3, 4, 5].map(() => STATUS_COLORS.moving)).map((c) => new THREE.Color(c)),
    [agentColor],
  )
  const stairColor = useMemo(() => new THREE.Color(STATUS_COLORS.stairwell), [])
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
        k = lensOn && !lens[ix.profile[i]] ? 200 : out.trapped ? 100 : out.st === 0 ? 0 : out.st === 2 ? 2 : out.st === 3 ? 30 + ix.profile[i] : 10 + ix.profile[i]
        const w = toWorld(out.x, out.y, floorY(f, useApp.getState().explode) + 0.87)
        p.set(w[0], w[1], w[2])
        const sc = i === useApp.getState().follow ? 0 : k >= 30 && k < 100 ? 0.6 : 1
        s.set(sc, sc, sc)
      } else {
        p.set(0, 0, 0)
        s.set(0, 0, 0)
      }
      mat.compose(p, q, s)
      m.setMatrixAt(i, mat)
      if (k !== keys[i] && k >= 0) {
        keys[i] = k
        if (k === 200) c.set(DIM)
        else if (k === 100) c.set(TRAPPED)
        else if (k === 0) c.set(NOT_MOVING)
        else if (k === 2) c.set(WAITING)
        else if (k >= 30) c.copy(agentColor === 'profile' ? colors[k - 30] : stairColor)
        else c.copy(colors[k - 10])
        m.setColorAt(i, c)
        if (m.instanceColor) m.instanceColor.needsUpdate = true
      }
    }
    void explode
    m.instanceMatrix.needsUpdate = true
    const r = ring.current
    if (r) {
      for (let j = 0; j < llmIdx.length; j++) {
        const ok = sampleAgent(ix, llmIdx[j], t, out)
        const f = ok ? floors[out.fl] : undefined
        if (!f || (visibleFloors && !visibleFloors.includes(f.id))) {
          p.set(0, 0, 0)
          s.set(0, 0, 0)
        } else {
          const w = toWorld(out.x, out.y, floorY(f, explode) + 0.05)
          p.set(w[0], w[1], w[2])
          s.set(1, 1, 1)
        }
        mat.compose(p, q, s)
        r.setMatrixAt(j, mat)
      }
      r.instanceMatrix.needsUpdate = true
    }
    // waiting timers, refreshed twice a second
    const tk = Math.floor(t * 2)
    if (tk !== timerKey.current) {
      timerKey.current = tk
      const fi = nearestIndex(ix.times, t)
      const list: Timer[] = []
      for (let i = 0; i < n && list.length < 30 && fi >= 0; i++) {
        if (lensOn && !lens[ix.profile[i]]) continue
        if (!sampleAgent(ix, i, t, out) || out.st !== 2) continue
        const f = floors[out.fl]
        if (!f || (visibleFloors && !visibleFloors.includes(f.id))) continue
        let g = fi
        while (g > 0 && ix.st[(g - 1) * n + i] === 2) g--
        const w = toWorld(out.x, out.y, floorY(f, explode) + 2.3)
        list.push({ i, p: [w[0], w[1], w[2]], s: Math.max(0, Math.round(t - ix.times[g])) })
      }
      setTimers(list)
    }
  })

  if (!ix || n === 0) return null
  const hv = hover !== null && lr ? lr.run.agents.find((a) => a.idx === hover) : undefined
  let hp: [number, number, number] | null = null
  let hst = ''
  let hreason = ''
  if (hv && lr) {
    const t = useClock.getState().t
    if (sampleAgent(ix, hv.idx, t, tmp.out)) {
      const f = floors[tmp.out.fl]
      if (f) {
        const w = toWorld(tmp.out.x, tmp.out.y, floorY(f, useApp.getState().explode) + 2.2)
        hp = [w[0], w[1], w[2]]
      }
      hst = STATUS_NAMES[tmp.out.st] ?? ''
    }
    for (const e of lr.run.events) if (e.idx === hv.idx && e.reason && e.t <= t) hreason = e.reason
  }
  return (
    <>
      <instancedMesh
        key={`${key}-${n}`}
        ref={mesh}
        args={[undefined, undefined, n]}
        frustumCulled={false}
        onPointerMove={(e) => {
          if (e.instanceId !== undefined) setHover(e.instanceId)
        }}
        onPointerOut={() => setHover(null)}
        onClick={(e) => {
          if (!useApp.getState().pickAgent || e.instanceId === undefined) return
          e.stopPropagation()
          useApp.getState().setFollow(e.instanceId)
          useApp.getState().setNotice(null)
        }}
      >
        <capsuleGeometry args={[0.22, 1.3]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
      {llmIdx.length > 0 && (
        <instancedMesh key={`ring-${key}-${llmIdx.length}`} ref={ring} args={[undefined, undefined, llmIdx.length]} frustumCulled={false}>
          <ringGeometry args={[0.45, 0.6, 24]} />
          <meshBasicMaterial color="#e879f9" side={THREE.DoubleSide} />
        </instancedMesh>
      )}
      {timers.map((tm) => (
        <Html key={tm.i} position={tm.p} center style={{ pointerEvents: 'none', color: '#fbbf24', font: '11px monospace', textShadow: '0 0 3px #000' }}>
          {tm.s}s
        </Html>
      ))}
      {hv && hp && (
        <Html position={hp} center style={{ pointerEvents: 'none' }}>
          <div style={{ background: '#111827ee', color: '#e5e7eb', padding: '4px 8px', borderRadius: 4, font: '12px sans-serif', width: 220, whiteSpace: 'normal' }}>
            <b>{hv.profile}</b> · {hst}
            {hv.note && <div>{hv.note}</div>}
            {hreason && <div style={{ color: '#e879f9' }}>{hreason}</div>}
          </div>
        </Html>
      )}
      {trails && <Trails ix={ix} floors={floors} />}
    </>
  )
}
