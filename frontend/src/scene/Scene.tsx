import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, Stats } from '@react-three/drei'
import { useApp } from '../store/app'
import Building from './Building'
import CameraRig from './CameraRig'
import Agents from '../replay/Agents'
import Smoke from '../replay/Smoke'
import Fire from '../replay/Fire'
import BurningRooms from '../replay/BurningRooms'
import BlockedDoors from '../replay/BlockedDoors'
import Heatmap from '../replay/Heatmap'
import QueueRings from '../replay/QueueRings'
import FirePicker from './FirePicker'
import RiskOverlay from './RiskOverlay'
import { CameraSyncPane } from './cameraSync'
import { useA11y } from '../ui/a11y'
import { perfOn, perfStats } from '../ui/perf'
import { sceneBg } from '../ui/theme'
import { SceneBuildingProvider } from './sceneBuilding'
import type { Building as BuildingT } from '../data/types'
import type { Side } from '../store/app'

// Copies the previous frame's render totals (read inside useFrame they are last frame's).
function PerfProbe() {
  const gl = useThree((st) => st.gl)
  useFrame(() => {
    perfStats.calls = gl.info.render.calls
    perfStats.triangles = gl.info.render.triangles
  })
  return null
}

/**
 * The 3D view. In the split view each pane is one: `runKey` is the run it shows, `paneId` its side, and `building` the building it draws when
 * that is not the loaded one (the right pane on another building).
 */
export default function Scene({ runKey, paneId, building }: { runKey?: string; paneId?: Side; building?: BuildingT | null }) {
  const autoRotate = useApp((s) => s.autoRotate)
  const reduceMotion = useA11y((s) => s.reduceMotion)
  const contrast = useA11y((s) => s.contrast)
  const loadedName = useApp((s) => s.building?.name ?? 'building')
  const buildingName = building?.name ?? loadedName
  return (
    <div
      role="img"
      aria-label={`3D replay of ${buildingName}`}
      aria-describedby="replay-summary"
      style={{ position: 'relative', overflow: 'hidden', width: '100%', height: '100%', isolation: 'isolate' }}>
      <Canvas dpr={[1, 1.5]} camera={{ fov: 50, near: 0.1, far: 1000 }}>
        <color attach="background" args={[sceneBg(contrast)]} />
        <hemisphereLight args={['#FFFFFF', '#CBD5E1', 1.8]} />
        <directionalLight position={[20, 40, 20]} intensity={1.6} />
        <OrbitControls makeDefault autoRotate={autoRotate && !reduceMotion} autoRotateSpeed={0.5} />
        <SceneBuildingProvider building={building ?? null}>
          <CameraRig paneId={paneId} />
          {!paneId && <PerfProbe />}
          {paneId && <CameraSyncPane paneId={paneId} />}
          <Building />
          <Agents runKey={runKey} />
          <Smoke runKey={runKey} />
          <Fire runKey={runKey} />
          <BurningRooms runKey={runKey} />
          <BlockedDoors runKey={runKey} />
          <Heatmap runKey={runKey} />
          <QueueRings runKey={runKey} />
          <RiskOverlay />
          <FirePicker side={paneId} />
          {perfOn() && <Stats />}
        </SceneBuildingProvider>
      </Canvas>
    </div>
  )
}
