import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { b64ToBytes } from '../model/decode'
import { floorAlpha, gridPlacement, toPlaced } from '../scene/geometry'
import { usePlace } from '../scene/usePlace'
import type { Heatmap as HeatmapT } from '../data/types'

// inferno-like stops
const STOPS: [number, number, number][] = [
  [0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164],
]
const LUT = (() => {
  const l = new Uint8Array(256 * 4)
  for (let i = 0; i < 256; i++) {
    const d = Math.min(i, 100)
    const p = (d / 100) * (STOPS.length - 1)
    const a = Math.floor(p)
    const b = Math.min(STOPS.length - 1, a + 1)
    const w = p - a
    for (let c = 0; c < 3; c++) l[i * 4 + c] = STOPS[a][c] + (STOPS[b][c] - STOPS[a][c]) * w
    l[i * 4 + 3] = i === 0 ? 0 : Math.round(d * 0.0085 * 255)
  }
  return l
})()

function HeatPlane({ hm }: { hm: HeatmapT }) {
  const building = useApp((s) => s.building)
  const visible = useApp((s) => s.visibleFloors)
  const viewMode = useApp((s) => s.viewMode)
  const focusFloor = useApp((s) => s.focusFloor)
  const place = usePlace()
  const floor = building?.floors.find((f) => f.id === hm.floor)
  const tex = useMemo(() => {
    const bytes = b64ToBytes(hm.d)
    if (bytes.length !== hm.cols * hm.rows) {
      console.warn(`heatmap ${hm.floor}: ${bytes.length} bytes, expected ${hm.cols * hm.rows}`)
      return null
    }
    const data = new Uint8Array(bytes.length * 4)
    for (let k = 0; k < bytes.length; k++) data.set(LUT.subarray(bytes[k] * 4, bytes[k] * 4 + 4), k * 4)
    const t = new THREE.DataTexture(data, hm.cols, hm.rows, THREE.RGBAFormat)
    t.magFilter = THREE.LinearFilter
    t.minFilter = THREE.LinearFilter
    t.needsUpdate = true
    return t
  }, [hm])
  useEffect(() => () => tex?.dispose(), [tex])
  if (!tex || !floor || (visible && !visible.includes(floor.id))) return null
  const { center, size } = gridPlacement(hm)
  return (
    <mesh position={toPlaced(place(floor), center[0], center[1], 0.06)} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[size[0], size[1]]} />
      <meshBasicMaterial map={tex} transparent opacity={floorAlpha(viewMode, focusFloor, floor.id)} depthWrite={false} side={THREE.DoubleSide} />
    </mesh>
  )
}

export default function Heatmap({ runKey, source = 'run' }: { runKey?: string; source?: 'run' | 'batch' }) {
  const activeKey = useApp((s) => s.activeRunKey)
  const on = useApp((s) => s.layers.heatmap)
  const key = runKey ?? activeKey
  const lr = useApp((s) => (key ? s.runs[key] : undefined))
  const batch = useApp((s) => s.batch)
  const list = source === 'batch' ? batch?.heatmaps : lr?.run.metrics.heatmaps
  if (!on || !list || list.length === 0) return null
  return (
    <>
      {list.map((h, i) => (
        <HeatPlane key={(key ?? '') + source + h.floor + i} hm={h} />
      ))}
    </>
  )
}
