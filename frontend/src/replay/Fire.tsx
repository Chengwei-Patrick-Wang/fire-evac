import { useRef } from 'react'
import { useA11y } from '../ui/a11y'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { floorY, toWorld } from '../scene/geometry'
import { hrrAt } from './runIndex'

export default function Fire({ runKey }: { runKey?: string }) {
  const activeKey = useApp((s) => s.activeRunKey)
  const on = useApp((s) => s.layers.fire)
  const building = useApp((s) => s.building)
  const visible = useApp((s) => s.visibleFloors)
  const explode = useApp((s) => s.explode)
  const key = runKey ?? activeKey
  const lr = useApp((s) => (key ? s.runs[key] : undefined))
  const mesh = useRef<THREE.Mesh>(null)
  const light = useRef<THREE.PointLight>(null)
  const fire = lr?.run.fire

  useFrame(({ clock }) => {
    if (!mesh.current || !fire) return
    const kw = hrrAt(fire.hrr, useClock.getState().t)
    const r = fire.hrr && fire.hrr.length ? 0.3 + 0.9 * Math.sqrt(kw / 1500) : 0.3
    const flick = useA11y.getState().reduceMotion ? 1 : 1 + 0.05 * Math.sin(clock.elapsedTime * 17) * Math.cos(clock.elapsedTime * 5.3)
    mesh.current.scale.setScalar(r * flick)
    if (light.current) light.current.intensity = (2 + 6 * Math.min(1, kw / 1500)) * flick
  })

  const floor = building?.floors.find((f) => f.id === fire?.floor)
  if (!on || !fire || !floor || (visible && !visible.includes(floor.id))) return null
  const pos = toWorld(fire.x, fire.y, floorY(floor, explode) + 0.5)
  return (
    <group position={pos}>
      <mesh ref={mesh}>
        <sphereGeometry args={[1, 24, 16]} />
        <meshStandardMaterial color="#ff5a1f" emissive="#ff5a1f" emissiveIntensity={1.5} />
      </mesh>
      <pointLight ref={light} color="#ff5a1f" distance={12} />
    </group>
  )
}
