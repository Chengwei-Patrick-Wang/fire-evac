import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import Trails from './Trails'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { floorAlpha, floorPlace, toPlaced } from '../scene/geometry'
import type { Place } from '../scene/geometry'
import { usePlace } from '../scene/usePlace'
import { claudeIdx, decisionAt, decisionText, readDecisions } from '../model/brain'
import { nearestIndex, sampleAgent } from './runIndex'
import type { AgentSample } from './runIndex'

const GREEN = '#16A34A'
const AMBER = '#F59E0B'
const RED = '#DC2626'
/** Colour by status, the default: green when moving or in a stairwell, amber when not moving yet or waiting for help, red when trapped. */
export const STATUS_COLORS = { moving: GREEN, stairwell: GREEN, notMoving: AMBER, waiting: AMBER, trapped: RED }
/**
 * Colour by type, in PROFILE_NAMES order: the Okabe-Ito set without yellow (it vanishes on the light slab) and without vermillion (it
 * reads as fire). It also colours the exit-use bars and the mobility table.
 */
export const TYPE_COLORS = ['#0072B2', '#CC79A7', '#56B4E9', '#009E73', '#E69F00', '#000000']
const DIM = '#CBD5E1'
const STATUS_NAMES = ['not moving yet', 'moving', 'waiting for help', 'in a stairwell']

// Colour keys, cached per agent so a colour is written only when it changes.
const K_MOVING = 1
const K_DELAYED = 2
const K_TRAPPED = 100
const K_DIM = 200
const K_TYPE = 10 // + profile

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
  const trapRing = useRef<THREE.InstancedMesh>(null)
  const lens = useApp((s) => s.lens)
  const trails = useApp((s) => s.trails)
  const colorBy = useApp((s) => s.colorBy)
  const viewMode = useApp((s) => s.viewMode)
  const focusFloor = useApp((s) => s.focusFloor)
  const explode = useApp((s) => s.explode)
  const visibleFloors = useApp((s) => s.visibleFloors)
  const place = usePlace()
  const byType = colorBy === 'type'
  const lensOn = !lens.every(Boolean)
  const lensKey = lens.map((v) => (v ? 1 : 0)).join('')
  const [hover, setHover] = useState<number | null>(null)
  const [timers, setTimers] = useState<Timer[]>([])
  const timerKey = useRef(-1)
  // The people who ask Claude (agents flagged `llm`, and anyone with an `llm` decision in the run) wear a ring.
  const llmIdx = useMemo(() => claudeIdx(lr?.run).filter((i) => i >= 0 && i < n), [lr, n])
  // Everyone who is trapped at some point gets a slot for the red ring that marks them besides their colour.
  const trapIdx = useMemo(() => {
    const out: number[] = []
    if (ix) for (let i = 0; i < n; i++) if (Number.isFinite(ix.trapT[i])) out.push(i)
    return out
  }, [ix, n])
  // The colours depend on the scheme, the view mode and the focus floor (ghost floors are drawn pale): all start over when one changes.
  const keys = useMemo(() => new Int16Array(n).fill(-2), [n, key, lensKey, colorBy, viewMode, focusFloor])
  const pal = useMemo(
    () => ({
      moving: new THREE.Color(STATUS_COLORS.moving),
      delayed: new THREE.Color(STATUS_COLORS.waiting),
      trapped: new THREE.Color(STATUS_COLORS.trapped),
      dim: new THREE.Color(DIM),
      types: TYPE_COLORS.map((c) => new THREE.Color(c)),
    }),
    [],
  )
  const tmp = useMemo(
    () => ({
      m: new THREE.Matrix4(),
      q: new THREE.Quaternion(),
      /** lies a ring flat on the floor */
      qFlat: new THREE.Quaternion().setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0)),
      p: new THREE.Vector3(),
      s: new THREE.Vector3(),
      c: new THREE.Color(),
      out: { x: 0, y: 0, fl: 0, st: 0, trapped: false } as AgentSample,
      /** per run floor, rewritten every frame: where it sits (null: not drawn) and whether the ghost view paints it pale */
      pl: [] as (Place | null)[],
      ghost: [] as boolean[],
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
  // The waiting timers are placed when they refresh (twice a second): when the picture is rearranged while paused they refresh at once.
  useEffect(() => {
    timerKey.current = -1
  }, [viewMode, focusFloor, explode, visibleFloors, lensKey])

  useFrame(() => {
    const m = mesh.current
    if (!m || !ix) return
    const st = useApp.getState()
    const { explode, visibleFloors, viewMode, focusFloor, follow } = st
    const t = useClock.getState().t
    const { out, m: mat, q, qFlat, p, s, c, pl, ghost } = tmp
    for (let fi = 0; fi < floors.length; fi++) {
      const f = floors[fi]
      pl[fi] = f && (!visibleFloors || visibleFloors.includes(f.id)) ? floorPlace(building, f, viewMode, explode) : null
      ghost[fi] = !!f && floorAlpha(viewMode, focusFloor, f.id) < 1
    }
    for (let i = 0; i < n; i++) {
      let ok = sampleAgent(ix, i, t, out)
      const at = ok ? pl[out.fl] : null
      if (!at) ok = false
      let k = -1
      if (ok && at) {
        const prof = ix.profile[i]
        k = (lensOn && !lens[prof]) || ghost[out.fl]
          ? K_DIM
          : byType
            ? K_TYPE + prof
            : out.trapped
              ? K_TRAPPED
              : out.st === 0 || out.st === 2
                ? K_DELAYED
                : K_MOVING
        p.set(out.x + at.dx, at.y + 0.87, -out.y)
        // people in a stairwell are drawn smaller, whatever colour the scheme gives them
        const sc = i === follow ? 0 : out.st === 3 ? 0.6 : 1
        s.set(sc, sc, sc)
      } else {
        p.set(0, 0, 0)
        s.set(0, 0, 0)
      }
      mat.compose(p, q, s)
      m.setMatrixAt(i, mat)
      if (k !== keys[i] && k >= 0) {
        keys[i] = k
        c.copy(k === K_DIM ? pal.dim : k === K_TRAPPED ? pal.trapped : k === K_DELAYED ? pal.delayed : k === K_MOVING ? pal.moving : pal.types[k - K_TYPE])
        m.setColorAt(i, c)
        if (m.instanceColor) m.instanceColor.needsUpdate = true
      }
    }
    m.instanceMatrix.needsUpdate = true
    const r = ring.current
    if (r) {
      for (let j = 0; j < llmIdx.length; j++) {
        const at = sampleAgent(ix, llmIdx[j], t, out) ? pl[out.fl] : null
        if (!at || ghost[out.fl]) {
          p.set(0, 0, 0)
          s.set(0, 0, 0)
        } else {
          p.set(out.x + at.dx, at.y + 0.07, -out.y)
          s.set(1, 1, 1)
        }
        // lies flat on the floor like the red ring of the trapped, a little above it
        mat.compose(p, qFlat, s)
        r.setMatrixAt(j, mat)
      }
      r.instanceMatrix.needsUpdate = true
    }
    // the red ring under everyone who is trapped (not on pale floors, and not for people the lens dims)
    const tr = trapRing.current
    if (tr) {
      for (let j = 0; j < trapIdx.length; j++) {
        const i = trapIdx[j]
        const at = sampleAgent(ix, i, t, out) && out.trapped ? pl[out.fl] : null
        if (!at || ghost[out.fl] || (lensOn && !lens[ix.profile[i]])) {
          p.set(0, 0, 0)
          s.set(0, 0, 0)
        } else {
          p.set(out.x + at.dx, at.y + 0.05, -out.y)
          s.set(1, 1, 1)
        }
        mat.compose(p, qFlat, s)
        tr.setMatrixAt(j, mat)
      }
      tr.instanceMatrix.needsUpdate = true
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
        const at = pl[out.fl]
        if (!at || ghost[out.fl]) continue
        let g = fi
        while (g > 0 && ix.st[(g - 1) * n + i] === 2) g--
        list.push({ i, p: [out.x + at.dx, at.y + 2.3, -out.y], s: Math.max(0, Math.round(t - ix.times[g])) })
      }
      setTimers((cur) =>
        cur.length === list.length && cur.every((c, j) => c.i === list[j].i && c.s === list[j].s && c.p[0] === list[j].p[0] && c.p[1] === list[j].p[1]) ? cur : list,
      )
    }
  })

  if (!ix || n === 0) return null
  const hv = hover !== null && lr ? lr.run.agents.find((a) => a.idx === hover) : undefined
  let hp: [number, number, number] | null = null
  let hst = ''
  let hreason = ''
  let hdecision: ReturnType<typeof decisionAt> = null
  if (hv && lr) {
    const t = useClock.getState().t
    if (sampleAgent(ix, hv.idx, t, tmp.out)) {
      const f = floors[tmp.out.fl]
      if (f) hp = toPlaced(place(f), tmp.out.x, tmp.out.y, 2.2)
      hst = tmp.out.trapped ? 'trapped' : STATUS_NAMES[tmp.out.st] ?? ''
    }
    for (const e of lr.run.events) if (e.idx === hv.idx && e.reason && e.t <= t) hreason = e.reason
    // A run that logged Claude's decisions: this person's latest one at this time (Claude's reason, or the rules' fallback) takes the place of the reason above.
    hdecision = decisionAt(readDecisions(lr.run), hv.idx, t)
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
      {trapIdx.length > 0 && (
        <instancedMesh key={`trapped-${key}-${trapIdx.length}`} ref={trapRing} args={[undefined, undefined, trapIdx.length]} frustumCulled={false}>
          <ringGeometry args={[0.45, 0.62, 28]} />
          <meshBasicMaterial color={STATUS_COLORS.trapped} side={THREE.DoubleSide} toneMapped={false} />
        </instancedMesh>
      )}
      {timers.map((tm) => (
        <Html key={tm.i} position={tm.p} center style={{ pointerEvents: 'none' }}>
          <div className="l3d timer">{tm.s}s</div>
        </Html>
      ))}
      {hv && hp && (
        <Html position={hp} center style={{ pointerEvents: 'none' }}>
          <div className="tip3d" style={{ width: 220, whiteSpace: 'normal' }}>
            <b>{hv.profile}</b> · {hst}
            {hv.note && <div>{hv.note}</div>}
            {hdecision ? (
              <div className={'why' + (hdecision.fallback ? ' rules' : '')}>
                {decisionText(hdecision)}
                {hdecision.action && ` · ${hdecision.action}`}
              </div>
            ) : (
              hreason && <div className="why">{hreason}</div>
            )}
          </div>
        </Html>
      )}
      {trails && <Trails ix={ix} floors={floors} />}
    </>
  )
}
