import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { useA11y } from '../ui/a11y'
import { toWorld, floorY } from '../scene/geometry'
import { nearestIndex } from './runIndex'
import type { RunIndex } from './runIndex'
import type { Building } from '../data/types'

const TRAIL_SECONDS = 20
const TRAIL_MAX_AGENTS = 300

type FloorT = Building['floors'][number] | undefined

/** Fading trails of the last 20 s for up to 300 agents; rebuilt only when the frame index changes. */
export default function Trails({ ix, floors }: { ix: RunIndex; floors: FloorT[] }) {
  const geo = useMemo(() => new THREE.BufferGeometry(), [])
  const last = useRef('')
  useEffect(() => () => geo.dispose(), [geo])
  useEffect(() => {
    last.current = ''
  }, [ix])
  useFrame(() => {
    const t = useClock.getState().t
    const { explode, visibleFloors } = useApp.getState()
    const fi = nearestIndex(ix.times, t)
    // Slate on the light canvas, white on black in high contrast.
    const rgb = useA11y.getState().contrast ? [1, 1, 1] : [0.2, 0.25, 0.33]
    const sig = `${fi}|${explode}|${visibleFloors?.join(',')}|${rgb[0]}`
    if (fi < 0 || sig === last.current) return
    last.current = sig
    const n = ix.nAgents
    let f0 = fi
    while (f0 > 0 && ix.times[fi] - ix.times[f0 - 1] <= TRAIL_SECONDS) f0--
    const pos: number[] = []
    const col: number[] = []
    const span = Math.max(1e-6, ix.times[fi] - ix.times[f0])
    const na = Math.min(n, TRAIL_MAX_AGENTS)
    for (let i = 0; i < na; i++) {
      if (t > ix.exitT[i]) continue
      for (let g = f0; g < fi; g++) {
        const a = g * n + i
        const b = a + n
        if (ix.fl[a] < 0 || ix.fl[a] !== ix.fl[b] || ix.st[a] < 0 || ix.st[b] < 0) continue
        const f = floors[ix.fl[a]]
        if (!f || (visibleFloors && !visibleFloors.includes(f.id))) continue
        const y = floorY(f, explode) + 0.1
        const w0 = toWorld(ix.x[a], ix.y[a], y)
        const w1 = toWorld(ix.x[b], ix.y[b], y)
        pos.push(w0[0], w0[1], w0[2], w1[0], w1[1], w1[2])
        const al0 = (ix.times[g] - ix.times[f0]) / span
        const al1 = (ix.times[g + 1] - ix.times[f0]) / span
        col.push(rgb[0], rgb[1], rgb[2], al0 * 0.8, rgb[0], rgb[1], rgb[2], al1 * 0.8)
      }
    }
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 4))
    geo.computeBoundingSphere()
  })
  return (
    <lineSegments geometry={geo} frustumCulled={false}>
      <lineBasicMaterial vertexColors transparent depthWrite={false} />
    </lineSegments>
  )
}
