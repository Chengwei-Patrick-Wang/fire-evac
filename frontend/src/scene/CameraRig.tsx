import { useEffect } from 'react'
import { useThree } from '@react-three/fiber'
import { useApp } from '../store/app'
import { buildingBounds, toWorld } from './geometry'

interface Orbit {
  target: { set: (x: number, y: number, z: number) => void }
  update: () => void
}

export default function CameraRig() {
  const building = useApp((s) => s.building)
  const topNonce = useApp((s) => s.topView)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as Orbit | null

  useEffect(() => {
    if (!building) return
    const b = buildingBounds(building)
    const [cx, , cz] = toWorld(b.cx, b.cy)
    const cy = (b.minZ + b.maxZ) / 2
    camera.position.set(cx, cy + 0.8 * b.span, cz + 0.9 * b.span)
    camera.lookAt(cx, cy, cz)
    if (controls) {
      controls.target.set(cx, cy, cz)
      controls.update()
    }
  }, [building, camera, controls])

  useEffect(() => {
    if (!building || !topNonce) return
    const b = buildingBounds(building)
    const [cx, , cz] = toWorld(b.cx, b.cy)
    camera.position.set(cx, b.maxZ + 1.6 * b.span, cz + 0.001)
    if (controls) {
      controls.target.set(cx, 0, cz)
      controls.update()
    } else camera.lookAt(cx, 0, cz)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topNonce])
  return null
}
