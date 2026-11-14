import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useApp } from '../store/app'
import type * as THREE from 'three'
import { buildingBounds, fitDistance, floorY, toWorld } from './geometry'

interface Orbit {
  target: { set: (x: number, y: number, z: number) => void }
  update: () => void
}

export default function CameraRig() {
  const building = useApp((s) => s.building)
  const topNonce = useApp((s) => s.topView)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as Orbit | null

  const get = useThree((s) => s.get)

  /** Overview pose and the distance that fits the box; also widens the far plane for big buildings. */
  const fit = (floorIds: string[] | null, explode: number) => {
    const b = buildingBounds(building!, floorIds, explode)
    const cam = camera as unknown as THREE.PerspectiveCamera
    const { width, height } = get().size
    const d = fitDistance(b, cam.fov, width / Math.max(1, height))
    cam.far = Math.max(1000, 4 * d)
    cam.updateProjectionMatrix()
    const [cx, , cz] = toWorld(b.cx, b.cy)
    const cy = (b.minZ + b.maxZ) / 2
    return { b, d, cx, cy, cz }
  }
  const eye = (f: { d: number; cx: number; cy: number; cz: number }): [number, number, number] => {
    const n = Math.hypot(0.8, 0.9)
    return [f.cx, f.cy + (0.8 / n) * f.d, f.cz + (0.9 / n) * f.d]
  }

  useEffect(() => {
    if (!building) return
    const f = fit(null, 0)
    const [x, y, z] = eye(f)
    camera.position.set(x, y, z)
    camera.lookAt(f.cx, f.cy, f.cz)
    if (controls) {
      controls.target.set(f.cx, f.cy, f.cz)
      controls.update()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [building, camera, controls])

  useEffect(() => {
    if (!building || !topNonce) return
    const f = fit(null, 0)
    const cx = f.cx, cz = f.cz
    camera.position.set(cx, f.cy + f.d, cz + 0.001)
    if (controls) {
      controls.target.set(cx, 0, cz)
      controls.update()
    } else camera.lookAt(cx, 0, cz)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topNonce])

  const goal = useRef<{ p: [number, number, number]; t: [number, number, number] } | null>(null)
  // fitView: fly back to the overview pose; damping ends after 2 s so auto-rotate and the user never fight it.
  const fitView = useApp((s) => s.fitView)
  const until = useRef(0)
  useEffect(() => {
    if (!building || !fitView) return
    const s = useApp.getState()
    const f = fit(s.visibleFloors?.length === 1 ? s.visibleFloors : null, s.explode)
    goal.current = { p: eye(f), t: [f.cx, f.cy, f.cz] }
    until.current = performance.now() + 2000
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitView])

  // flyTo: damp camera and target toward the spot (eye 9 m above and 9 m back).
  const focus = useApp((s) => s.focus)
  useEffect(() => {
    if (!building || !focus) return
    const fl = building.floors.find((f) => f.id === focus.floorId)
    const y = fl ? floorY(fl, useApp.getState().explode) : 0
    const [x, , z] = toWorld(focus.pos[0], focus.pos[1])
    goal.current = { p: [x, y + 9, z + 9], t: [x, y, z] }
    until.current = 0
  }, [focus, building])
  useFrame((_, dt) => {
    const g = goal.current
    if (!g || useApp.getState().follow !== null) return
    if (until.current && performance.now() > until.current) {
      goal.current = null
      until.current = 0
      return
    }
    const k = 1 - Math.exp(-4 * dt)
    camera.position.x += (g.p[0] - camera.position.x) * k
    camera.position.y += (g.p[1] - camera.position.y) * k
    camera.position.z += (g.p[2] - camera.position.z) * k
    const c = controls as unknown as { target: { x: number; y: number; z: number; set: (x: number, y: number, z: number) => void }; update: () => void } | null
    if (c) {
      c.target.set(c.target.x + (g.t[0] - c.target.x) * k, c.target.y + (g.t[1] - c.target.y) * k, c.target.z + (g.t[2] - c.target.z) * k)
      c.update()
    }
    if (Math.hypot(g.p[0] - camera.position.x, g.p[1] - camera.position.y, g.p[2] - camera.position.z) < 0.05) goal.current = null
  })
  return null
}
