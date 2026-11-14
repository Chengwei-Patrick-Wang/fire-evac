import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { create } from 'zustand'

interface Sync {
  position: [number, number, number]
  target: [number, number, number]
  from: string | null
}

export const useCameraSync = create<Sync>(() => ({ position: [0, 0, 0], target: [0, 0, 0], from: null }))

interface Orbit {
  target: { x: number; y: number; z: number; set: (x: number, y: number, z: number) => void }
  update: () => void
  addEventListener: (t: string, f: () => void) => void
  removeEventListener: (t: string, f: () => void) => void
}

/** Inside a Canvas: publishes user-driven camera moves and copies the other pane's. */
export function CameraSyncPane({ paneId }: { paneId: string }) {
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as Orbit | null
  const dragging = useRef(false)
  const syncing = useRef(false)

  useEffect(() => {
    if (!controls) return
    const start = () => (dragging.current = true)
    const end = () => (dragging.current = false)
    const change = () => {
      if (!dragging.current || syncing.current) return
      const p = camera.position
      const t = controls.target
      useCameraSync.setState({ position: [p.x, p.y, p.z], target: [t.x, t.y, t.z], from: paneId })
    }
    controls.addEventListener('start', start)
    controls.addEventListener('end', end)
    controls.addEventListener('change', change)
    return () => {
      controls.removeEventListener('start', start)
      controls.removeEventListener('end', end)
      controls.removeEventListener('change', change)
    }
  }, [controls, camera, paneId])

  useFrame(() => {
    const s = useCameraSync.getState()
    if (!controls || s.from === null || s.from === paneId || dragging.current) return
    const p = camera.position
    if (
      Math.abs(p.x - s.position[0]) + Math.abs(p.y - s.position[1]) + Math.abs(p.z - s.position[2]) < 1e-4 &&
      Math.abs(controls.target.x - s.target[0]) + Math.abs(controls.target.y - s.target[1]) + Math.abs(controls.target.z - s.target[2]) < 1e-4
    )
      return
    syncing.current = true
    camera.position.set(...s.position)
    controls.target.set(...s.target)
    controls.update()
    syncing.current = false
  })
  return null
}
