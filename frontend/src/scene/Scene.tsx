import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Stats } from '@react-three/drei'
import { useApp } from '../store/app'
import Building from './Building'
import CameraRig from './CameraRig'
import Agents from '../replay/Agents'
import Smoke from '../replay/Smoke'
import Fire from '../replay/Fire'
import Heatmap from '../replay/Heatmap'
import QueueRings from '../replay/QueueRings'
import FirePicker from './FirePicker'
import RiskOverlay from './RiskOverlay'
import AgentCam from '../replay/AgentCam'
import { CameraSyncPane } from './cameraSync'
import { CaptureHook } from './capture'
import { useA11y } from '../ui/a11y'
import { perfOn, perfStats } from '../ui/perf'

// Copies the previous frame's render totals (read inside useFrame they are last frame's).
function PerfProbe() {
  const gl = useThree((st) => st.gl)
  useFrame(() => {
    perfStats.calls = gl.info.render.calls
    perfStats.triangles = gl.info.render.triangles
  })
  return null
}

export default function Scene({ runKey, paneId }: { runKey?: string; paneId?: string }) {
  const autoRotate = useApp((s) => s.autoRotate)
  const reduceMotion = useA11y((s) => s.reduceMotion)
  const contrast = useA11y((s) => s.contrast)
  const buildingName = useApp((s) => s.building?.name ?? 'building')
  const following = useApp((s) => s.follow !== null)
  return (
    <div
      role="img"
      aria-label={`3D replay of ${buildingName}`}
      aria-describedby="replay-summary"
      style={{ position: 'relative', overflow: 'hidden', width: '100%', height: '100%', isolation: 'isolate' }}>
      <Canvas dpr={[1, 1.5]} camera={{ fov: 50, near: 0.1, far: 1000 }}>
        <color attach="background" args={[contrast ? '#000000' : '#0b1220']} />
        <ambientLight intensity={0.7} />
        <directionalLight position={[20, 40, 20]} intensity={0.8} />
        <OrbitControls makeDefault enabled={!following} autoRotate={autoRotate && !reduceMotion} autoRotateSpeed={0.5} />
        <CameraRig />
        {!runKey && <AgentCam />}
        {!paneId && <CaptureHook />}
        {!paneId && <PerfProbe />}
        {paneId && <CameraSyncPane paneId={paneId} />}
        <Building runKey={runKey} />
        <Agents runKey={runKey} />
        <Smoke runKey={runKey} />
        <Fire runKey={runKey} />
        <Heatmap runKey={runKey} />
        <QueueRings runKey={runKey} />
        <RiskOverlay />
        {!runKey && <FirePicker />}
        {perfOn() && <Stats />}
      </Canvas>
    </div>
  )
}
