import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { create } from 'zustand'

type Vec3 = [number, number, number]

interface Sync {
  position: Vec3
  target: Vec3
  /** The pane the user last dragged: the other follows it. Null while nobody leads (after a reset, a view change or a fly-to, which both panes make on their own). */
  from: string | null
}

export const useCameraSync = create<Sync>(() => ({ position: [0, 0, 0], target: [0, 0, 0], from: null }))

/**
 * Lets go of the leader. A pane that flies to its own overview (Reset camera, a view change, top view, a fly-to) must not be pulled back
 * to the pose the other pane was dragged to earlier: that was why Reset camera only reset the left pane.
 */
export function releaseSync() {
  releasedAt = performance.now()
  if (useCameraSync.getState().from !== null) useCameraSync.setState({ from: null })
}
let releasedAt = 0

interface Frame {
  target: Vec3
  distance: number
}
const frames = new Map<string, Frame>()

/** Where a pane's building is framed (its camera's target and distance at the overview): a pane drawing another building follows the other through it. */
export function setPaneFrame(paneId: string, target: Vec3, distance: number) {
  frames.set(paneId, { target, distance })
}

/**
 * The pose a pane copies from the leader's. Two panes on the same building have the same frame, so it is the leader's pose as it is;
 * on two buildings the pose is moved by the difference of the frames (the leader's offset from its building's middle, scaled to the other building's size).
 */
function followed(s: Sync, paneId: string): { position: Vec3; target: Vec3 } {
  const a = s.from ? frames.get(s.from) : undefined
  const b = frames.get(paneId)
  if (!a || !b || a.distance <= 0 || b.distance <= 0) return { position: s.position, target: s.target }
  const k = b.distance / a.distance
  const map = (p: Vec3): Vec3 => [b.target[0] + (p[0] - a.target[0]) * k, b.target[1] + (p[1] - a.target[1]) * k, b.target[2] + (p[2] - a.target[2]) * k]
  return { position: map(s.position), target: map(s.target) }
}

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
  const lastDragEnd = useRef(0)

  useEffect(() => {
    if (!controls) return
    const start = () => (dragging.current = true)
    const end = () => {
      dragging.current = false
      lastDragEnd.current = performance.now()
    }
    const change = () => {
      if (syncing.current) return
      // A drag, or the coasting that follows one (OrbitControls damping) as long as no reset has come since: the other pane ends where this one does.
      // (A reset's own fly-to is nobody's drag.)
      const coasting = lastDragEnd.current > releasedAt
      if (!dragging.current && !coasting) return
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
      frames.delete(paneId)
    }
  }, [controls, camera, paneId])

  useFrame(() => {
    const s = useCameraSync.getState()
    if (!controls || s.from === null || s.from === paneId || dragging.current) return
    const f = followed(s, paneId)
    const p = camera.position
    if (
      Math.abs(p.x - f.position[0]) + Math.abs(p.y - f.position[1]) + Math.abs(p.z - f.position[2]) < 1e-4 &&
      Math.abs(controls.target.x - f.target[0]) + Math.abs(controls.target.y - f.target[1]) + Math.abs(controls.target.z - f.target[2]) < 1e-4
    )
      return
    syncing.current = true
    camera.position.set(...f.position)
    controls.target.set(...f.target)
    controls.update()
    syncing.current = false
  })
  return null
}
