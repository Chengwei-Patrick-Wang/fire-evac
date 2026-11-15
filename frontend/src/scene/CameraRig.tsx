import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { useApp } from '../store/app'
import type * as THREE from 'three'
import { useA11y } from '../ui/a11y'
import { cameraPose, panePoses } from '../model/link'
import { floorPlace, frameView, framePoints, toPlaced } from './geometry'
import type { ViewMode } from './geometry'
import { useSceneBuilding } from './sceneBuilding'
import { setPaneFrame, releaseSync } from './cameraSync'

interface Orbit {
  target: { x: number; y: number; z: number; set: (x: number, y: number, z: number) => void }
  update: () => void
}

type Vec3 = [number, number, number]

/** The overview's direction: from the building's middle toward the eye (a third of it up, the rest toward the viewer). */
const OVERVIEW: Vec3 = (() => {
  const n = Math.hypot(0.8, 0.9)
  return [0, 0.8 / n, 0.9 / n]
})()
/** Straight down, a hair toward the viewer so the camera's up vector stays defined. */
const TOP: Vec3 = [0, 1, 0.001]
/** Share of the visible viewer left empty on each side of the building: it fills about 91 %. */
const PAD = 0.045
/** Room the "Floor N" pills hang to the left of the building's front corner (they are drawn inside the corner on phones). */
const TAG_PX = 80

const phone = () => typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(max-width: 900px)').matches
/** A smaller desktop (901 to 1099 px) floats the analytics panel over the viewer instead of giving it a column. */
const floatingPanel = () => typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia('(min-width: 901px) and (max-width: 1099px)').matches

/** The pixels of the viewer that are not the building's to use: the floor pills at the left, and the analytics panel while it floats over the viewer. */
function insets(canvas: HTMLElement | null): { left: number } {
  let left = phone() ? 0 : TAG_PX
  if (canvas && floatingPanel()) {
    const sb = document.getElementById('analytics')
    if (sb && !sb.hidden) {
      const over = sb.getBoundingClientRect().right - canvas.getBoundingClientRect().left
      if (over > 0) left += over + 8
    }
  }
  return { left }
}

export default function CameraRig({ paneId }: { paneId?: string }) {
  const building = useSceneBuilding()
  const topNonce = useApp((s) => s.topView)
  const camera = useThree((s) => s.camera)
  const controls = useThree((s) => s.controls) as unknown as Orbit | null
  const size = useThree((s) => s.size)
  const gl = useThree((s) => s.gl)

  const get = useThree((s) => s.get)
  const goal = useRef<{ p: Vec3; t: Vec3 } | null>(null)
  /** Where the last fit was made (the viewer's size and the panel state): a different one means the viewer changed under the building. */
  const fittedKey = useRef<string | null>(null)
  /** True while the camera sits at a pose a shared link asked for: a resize leaves it alone until the next reset or view change. */
  const pinned = useRef(false)
  const sidebarOpen = useApp((s) => s.sidebarOpen)
  const sidebarWide = useApp((s) => s.sidebarWide)
  const viewKey = `${size.width}x${size.height}|${sidebarOpen}|${sidebarWide}`

  /**
   * Where the camera goes to fill the visible viewer with the building's drawn floors (the floors where the current view mode puts them),
   * seen from `dir`. Also widens the far plane for big buildings.
   */
  const frame = (floorIds: string[] | null, explode: number, mode: ViewMode, dir: Vec3 = OVERVIEW) => {
    const { width, height } = get().size
    const cam = camera as unknown as THREE.PerspectiveCamera
    const f = frameView(framePoints(building!, floorIds, explode, mode), dir, cam.fov, { width, height, pad: PAD, inset: insets(gl.domElement) })
    cam.far = Math.max(1000, 4 * f.distance)
    cam.updateProjectionMatrix()
    const p: Vec3 = [f.target[0] + dir[0] * f.distance, f.target[1] + dir[1] * f.distance, f.target[2] + dir[2] * f.distance]
    // The pane's frame lets a linked camera pair move one building's view onto another's (see cameraSync).
    if (paneId) setPaneFrame(paneId, f.target, f.distance)
    return { target: f.target, p }
  }

  /** OrbitControls coasts on a little after a drag (damping); a camera that is being put somewhere must not drift on from it. */
  const stop = () => {
    const c = controls as unknown as { enableDamping?: boolean; update: () => void } | null
    if (!c) return
    const on = c.enableDamping
    c.enableDamping = false
    c.update()
    c.enableDamping = on
  }

  const place = (p: Vec3, t: Vec3) => {
    stop()
    camera.position.set(p[0], p[1], p[2])
    camera.lookAt(t[0], t[1], t[2])
    if (controls) {
      controls.target.set(t[0], t[1], t[2])
      controls.update()
    }
  }

  const applyCam = (c: number[]) => {
    stop()
    camera.position.set(c[0], c[1], c[2])
    camera.lookAt(c[3], c[4], c[5])
    if (controls) {
      controls.target.set(c[3], c[4], c[5])
      controls.update()
    }
  }

  /** The floors a reset or a view change frames: the one floor in the single view, else all of them. */
  const framed = () => {
    const s = useApp.getState()
    return { ids: s.visibleFloors?.length === 1 ? s.visibleFloors : null, explode: s.explode, mode: s.viewMode }
  }

  useEffect(() => {
    if (!building) return
    releaseSync()
    const s0 = useApp.getState()
    const f = frame(null, s0.explode, s0.viewMode)
    fittedKey.current = viewKey
    const pc = s0.pendingCam
    if (pc) {
      applyCam(pc)
      pinned.current = true
      if (controls) useApp.setState({ pendingCam: null })
      return
    }
    pinned.current = false
    place(f.p, f.target)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [building, camera, controls])

  const pendingCam = useApp((s) => s.pendingCam)
  useEffect(() => {
    if (!building || !pendingCam) return
    releaseSync()
    applyCam(pendingCam)
    pinned.current = true
    goal.current = null
    if (controls) useApp.setState({ pendingCam: null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingCam])

  useEffect(() => {
    if (!building || !topNonce) return
    releaseSync()
    const s0 = useApp.getState()
    const f = frame(null, s0.explode, s0.viewMode, TOP)
    pinned.current = false
    goal.current = null
    place(f.p, f.target)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topNonce])

  // fitView (Reset camera, and every change of the floor view): fly back to the overview pose; damping ends after 2 s so auto-rotate and the user never fight it.
  // The link between two panes is let go first: the pose a pane last dragged to is not where either of them is going now.
  const fitView = useApp((s) => s.fitView)
  const until = useRef(0)
  useEffect(() => {
    if (!building || !fitView) return
    releaseSync()
    const { ids, explode, mode } = framed()
    const f = frame(ids, explode, mode)
    stop()
    pinned.current = false
    fittedKey.current = viewKey
    goal.current = { p: f.p, t: f.target }
    until.current = performance.now() + 2000
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitView])

  // The window (or the viewer next to the analytics panel) changed size: frame the building again, from where the camera looks now.
  useEffect(() => {
    if (!building || fittedKey.current === null || fittedKey.current === viewKey || pinned.current) return
    const id = window.setTimeout(() => {
      const s = useApp.getState()
      if (s.pendingCam || !controls) return
      fittedKey.current = viewKey
      releaseSync()
      const eye = camera.position
      const t = controls.target
      const d: Vec3 = [eye.x - t.x, eye.y - t.y, eye.z - t.z]
      const len = Math.hypot(...d)
      const { ids, explode, mode } = framed()
      const f = frame(ids, explode, mode, len > 1e-6 ? [d[0] / len, d[1] / len, d[2] / len] : OVERVIEW)
      goal.current = null
      place(f.p, f.target)
    }, 150)
    return () => window.clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey])

  // flyTo: damp camera and target toward the spot (eye 9 m above and 9 m back).
  const focus = useApp((s) => s.focus)
  useEffect(() => {
    if (!building || !focus) return
    releaseSync()
    stop()
    pinned.current = false
    const fl = building.floors.find((f) => f.id === focus.floorId)
    const st = useApp.getState()
    const [x, y, z] = toPlaced(fl ? floorPlace(building, fl, st.viewMode, st.explode) : { dx: 0, y: 0 }, focus.pos[0], focus.pos[1])
    goal.current = { p: [x, y + 9, z + 9], t: [x, y, z] }
    until.current = 0
  }, [focus, building])
  useFrame((_, dt) => {
    // Only the main view publishes its pose for the shareable link; a split pane would overwrite it.
    if (paneId) {
      const e = (panePoses[paneId] ??= { p: [0, 0, 0], t: [0, 0, 0] })
      e.p[0] = camera.position.x
      e.p[1] = camera.position.y
      e.p[2] = camera.position.z
      const c = controls as unknown as { target: { x: number; y: number; z: number } } | null
      if (c) {
        e.t[0] = c.target.x
        e.t[1] = c.target.y
        e.t[2] = c.target.z
      }
    } else {
      cameraPose.p[0] = camera.position.x
      cameraPose.p[1] = camera.position.y
      cameraPose.p[2] = camera.position.z
      const pose = controls as unknown as { target: { x: number; y: number; z: number } } | null
      if (pose) {
        cameraPose.t[0] = pose.target.x
        cameraPose.t[1] = pose.target.y
        cameraPose.t[2] = pose.target.z
      }
    }
    const g = goal.current
    if (!g) return
    if (until.current && performance.now() > until.current) {
      goal.current = null
      until.current = 0
      return
    }
    const k = useA11y.getState().reduceMotion ? 1 : 1 - Math.exp(-4 * dt)
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
