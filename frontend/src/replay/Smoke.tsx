import { useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { b64ToBytes } from '../model/decode'
import { floorY, gridPlacement, toWorld } from '../scene/geometry'
import { nearestIndex } from './runIndex'
import type { SmokeLayer } from '../data/types'

function SmokePlane({ layer, runKey }: { layer: SmokeLayer; runKey: string }) {
  const building = useApp((s) => s.building)
  const visible = useApp((s) => s.visibleFloors)
  const explode = useApp((s) => s.explode)
  const floor = building?.floors.find((f) => f.id === layer.floor)
  const { cols, rows } = layer
  const tex = useMemo(() => {
    const data = new Uint8Array(cols * rows * 4)
    const t = new THREE.DataTexture(data, cols, rows, THREE.RGBAFormat)
    t.magFilter = THREE.LinearFilter
    t.minFilter = THREE.LinearFilter
    t.needsUpdate = true
    return t
  }, [cols, rows, runKey])
  const times = useMemo(() => Float64Array.from(layer.frames.map((f) => f.t)), [layer])
  const state = useMemo(() => ({ shown: -2, warned: false }), [layer, runKey])
  useEffect(() => () => tex.dispose(), [tex])

  useFrame(() => {
    if (state.warned || times.length === 0) return
    const t = useClock.getState().t
    const i = t < times[0] ? -1 : nearestIndex(times, t)
    if (i === state.shown) return
    if (i === -1) {
      ;(tex.image.data as Uint8Array).fill(0)
      tex.needsUpdate = true
      state.shown = -1
      return
    }
    const bytes = b64ToBytes(layer.frames[i].d)
    if (bytes.length !== cols * rows) {
      console.warn(`smoke ${layer.floor}: ${bytes.length} bytes, expected ${cols * rows}; layer skipped`)
      state.warned = true
      return
    }
    const out = tex.image.data as Uint8Array
    for (let k = 0; k < bytes.length; k++) {
      const o = k * 4
      out[o] = 0x3a
      out[o + 1] = 0x3a
      out[o + 2] = 0x3a
      out[o + 3] = Math.min(200, bytes[k] * 1.8)
    }
    tex.needsUpdate = true
    state.shown = i
  })

  if (!floor || (visible && !visible.includes(floor.id))) return null
  const { center, size } = gridPlacement(layer)
  return (
    <mesh position={toWorld(center[0], center[1], floorY(floor, explode) + 1.6)} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[size[0], size[1]]} />
      <meshBasicMaterial map={tex} transparent depthWrite={false} side={THREE.DoubleSide} />
    </mesh>
  )
}

export default function Smoke({ runKey }: { runKey?: string }) {
  const activeKey = useApp((s) => s.activeRunKey)
  const on = useApp((s) => s.layers.smoke)
  const key = runKey ?? activeKey
  const lr = useApp((s) => (key ? s.runs[key] : undefined))
  if (!on || !lr || !lr.run.smoke || lr.run.smoke.length === 0) return null
  return (
    <>
      {lr.run.smoke.map((l) => (
        <SmokePlane key={key + l.floor} layer={l} runKey={key!} />
      ))}
    </>
  )
}
