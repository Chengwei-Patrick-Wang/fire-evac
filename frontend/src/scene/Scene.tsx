import { Canvas } from '@react-three/fiber'
import { OrbitControls, Stats } from '@react-three/drei'
import Building from './Building'
import CameraRig from './CameraRig'
import Agents from '../replay/Agents'
import Smoke from '../replay/Smoke'
import Fire from '../replay/Fire'
import Heatmap from '../replay/Heatmap'
import QueueRings from '../replay/QueueRings'
import FirePicker from './FirePicker'
import RiskOverlay from './RiskOverlay'

export default function Scene({ runKey }: { runKey?: string }) {
  return (
    <div style={{ position: 'relative', overflow: 'hidden', width: '100%', height: '100%' }}>
      <Canvas dpr={[1, 2]} camera={{ fov: 50, near: 0.1, far: 1000 }}>
        <color attach="background" args={['#0b1220']} />
        <ambientLight intensity={0.7} />
        <directionalLight position={[20, 40, 20]} intensity={0.8} />
        <OrbitControls makeDefault />
        <CameraRig />
        <Building runKey={runKey} />
        <Agents runKey={runKey} />
        <Smoke runKey={runKey} />
        <Fire runKey={runKey} />
        <Heatmap runKey={runKey} />
        <QueueRings runKey={runKey} />
        <RiskOverlay />
        {!runKey && <FirePicker />}
        {import.meta.env.DEV && <Stats />}
      </Canvas>
    </div>
  )
}
