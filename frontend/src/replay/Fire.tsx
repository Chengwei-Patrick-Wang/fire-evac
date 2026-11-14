import { useRef } from 'react'
import { useA11y } from '../ui/a11y'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { floorAlpha, toPlaced } from '../scene/geometry'
import { usePlace } from '../scene/usePlace'
import { hrrAt } from './runIndex'

export default function Fire({ runKey }: { runKey?: string }) {
  const activeKey = useApp((s) => s.activeRunKey)
  const on = useApp((s) => s.layers.fire)
  const building = useApp((s) => s.building)
  const visible = useApp((s) => s.visibleFloors)
  const viewMode = useApp((s) => s.viewMode)
  const focusFloor = useApp((s) => s.focusFloor)
  const glow = useApp((s) => s.fireGlow)
  const place = usePlace()
  const key = runKey ?? activeKey
  const lr = useApp((s) => (key ? s.runs[key] : undefined))
  const mesh = useRef<THREE.Mesh>(null)
  const light = useRef<THREE.PointLight>(null)
  const fire = lr?.run.fire
  const floor = building?.floors.find((f) => f.id === fire?.floor)
  const alpha = floor ? floorAlpha(viewMode, focusFloor, floor.id) : 1

  useFrame(({ clock }) => {
    if (!mesh.current || !fire) return
    const kw = hrrAt(fire.hrr, useClock.getState().t)
    const g = useApp.getState().fireGlow
    const r = fire.hrr && fire.hrr.length ? 0.3 + 0.9 * Math.sqrt(kw / 1500) : 0.3
    const flick = useA11y.getState().reduceMotion ? 1 : 1 + 0.05 * Math.sin(clock.elapsedTime * 17) * Math.cos(clock.elapsedTime * 5.3)
    // The glow setting scales the picture only: the size (0.6x to 1.4x) and the light; the simulation never reads it.
    mesh.current.scale.setScalar(r * (0.6 + 0.4 * g) * flick)
    if (light.current) light.current.intensity = (2 + 6 * Math.min(1, kw / 1500)) * flick * g * alpha
  })

  if (!on || !fire || !floor || (visible && !visible.includes(floor.id))) return null
  const pos = toPlaced(place(floor), fire.x, fire.y, 0.5)
  const ghost = alpha < 1
  return (
    <group position={pos}>
      <mesh ref={mesh}>
        <sphereGeometry args={[1, 24, 16]} />
        <meshStandardMaterial key={ghost ? 'ghost' : 'solid'} color="#ff5a1f" emissive="#ff5a1f" emissiveIntensity={0.5 + glow} transparent={ghost} opacity={alpha} depthWrite={!ghost} />
      </mesh>
      <pointLight ref={light} color="#ff5a1f" distance={12} />
    </group>
  )
}
