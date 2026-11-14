import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { useApp } from '../store/app'
import type { Layers } from '../store/app'
import { useClock } from '../store/clock'
import { floorY, toWorld } from '../scene/geometry'
import { sampleAgent } from './runIndex'
import type { AgentSample } from './runIndex'
import { smokeDensityAt, useAgentView, visibility } from './agentView'

const BG = new THREE.Color('#0b1220')
const FOG = new THREE.Color('#3a3a3a')

interface Orbit {
  target: THREE.Vector3
  update: () => void
  enabled: boolean
}

export default function AgentCam() {
  const follow = useApp((s) => s.follow)
  const nAgents = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey]?.index.nAgents ?? 0 : 0))
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const scene = useThree((s) => s.scene)
  const controls = useThree((s) => s.controls) as unknown as Orbit | null
  const active = follow !== null && follow < nAgents
  const saved = useRef<{ pos: THREE.Vector3; target: THREE.Vector3 | null; fov: number; layers: Layers } | null>(null)
  const st = useMemo(
    () => ({
      out: { x: 0, y: 0, fl: 0, st: 0, trapped: false } as AgentSample,
      ahead: { x: 0, y: 0, fl: 0, st: 0, trapped: false } as AgentSample,
      head: null as number | null,
      pose: null as { p: THREE.Vector3; look: THREE.Vector3 } | null,
      fog: null as THREE.Fog | null,
      last: 0,
    }),
    [],
  )

  useEffect(() => {
    if (follow !== null && !active) useApp.getState().setFollow(null)
  }, [follow, active])

  useEffect(() => {
    if (!active) return
    const s = useApp.getState()
    saved.current = { pos: camera.position.clone(), target: controls ? controls.target.clone() : null, fov: camera.fov, layers: s.layers }
    useApp.setState({ layers: { ...s.layers, labels: false, queues: false, heatmap: false, smoke: false } })
    camera.fov = 70
    camera.updateProjectionMatrix()
    st.fog = new THREE.Fog('#3a3a3a', 0.3, 200)
    scene.fog = st.fog
    st.head = null
    st.pose = null
    return () => {
      const sv = saved.current
      if (sv) {
        camera.position.copy(sv.pos)
        camera.fov = sv.fov
        camera.updateProjectionMatrix()
        if (controls && sv.target) {
          controls.target.copy(sv.target)
          controls.update()
        } else if (sv.target) camera.lookAt(sv.target)
        useApp.setState({ layers: sv.layers })
      }
      saved.current = null
      scene.fog = null
      if (scene.background instanceof THREE.Color) scene.background.copy(BG)
    }
  }, [active, camera, controls, scene, st])

  useEffect(() => {
    if (controls) controls.enabled = follow === null
  }, [follow, controls])

  useFrame((_, dt) => {
    if (!active || follow === null) return
    const app = useApp.getState()
    const lr = app.activeRunKey ? app.runs[app.activeRunKey] : undefined
    const building = app.building
    if (!lr || !building) return
    const t = useClock.getState().t
    const { out, ahead } = st
    const now = performance.now()
    if (sampleAgent(lr.index, follow, t, out)) {
      const f = building.floors.find((fl) => fl.id === lr.run.floors[out.fl])
      if (f) {
        // heading: toward the position 0.5 s ahead; before the person moves, toward the first spot 0.3 m away within 30 s
        let dir: [number, number] | null = null
        if (sampleAgent(lr.index, follow, t + 0.5, ahead) && ahead.fl === out.fl && Math.hypot(ahead.x - out.x, ahead.y - out.y) >= 0.05) dir = [ahead.x - out.x, ahead.y - out.y]
        else if (out.st === 0) {
          for (let k = 1; k <= 30 && !dir; k++) {
            if (sampleAgent(lr.index, follow, t + k, ahead) && ahead.fl === out.fl && Math.hypot(ahead.x - out.x, ahead.y - out.y) >= 0.3) dir = [ahead.x - out.x, ahead.y - out.y]
          }
        }
        if (dir) {
          const h = Math.atan2(dir[1], dir[0])
          if (st.head === null) st.head = h
          else {
            let d = h - st.head
            while (d > Math.PI) d -= 2 * Math.PI
            while (d < -Math.PI) d += 2 * Math.PI
            st.head += d * (1 - Math.exp(-4 * dt))
          }
        }
        const h = st.head ?? 0
        const y = floorY(f, app.explode) + 1.6
        st.pose = {
          p: new THREE.Vector3(...toWorld(out.x, out.y, y)),
          look: new THREE.Vector3(...toWorld(out.x + Math.cos(h) * 5, out.y + Math.sin(h) * 5, y)),
        }
        const d = smokeDensityAt(lr.run, f.id, out.x, out.y, t)
        const S = visibility(d)
        if (st.fog) st.fog.far = Math.max(0.5, st.fog.far + ((d < 1 ? 200 : S) - st.fog.far) * (1 - Math.exp(-3 * dt)))
        if (scene.background instanceof THREE.Color) scene.background.copy(BG).lerp(FOG, 1 - S / 30)
        if (now - st.last > 250) {
          st.last = now
          let speed = 0
          if (sampleAgent(lr.index, follow, t - 0.5, ahead) && ahead.fl === out.fl) speed = Math.hypot(out.x - ahead.x, out.y - ahead.y) / 0.5
          const v0 = lr.run.agents.find((a) => a.idx === follow)?.v0 ?? 0
          const desired = S < 3 ? Math.min(v0, Math.max(0.2, v0 - 0.34 * (3 - S))) : v0
          const status = out.trapped ? 'trapped' : out.st === 0 ? 'not moving yet' : out.st === 2 ? 'waiting for help' : out.st === 3 ? 'in a stairwell' : 'moving'
          useAgentView.setState({ vis: S, speed, desired, status })
        }
      }
    } else if (now - st.last > 250) {
      st.last = now
      useAgentView.setState({ speed: 0, status: 'out of the building' })
    }
    if (st.pose) {
      camera.position.copy(st.pose.p)
      camera.lookAt(st.pose.look)
    }
  })

  return null
}
