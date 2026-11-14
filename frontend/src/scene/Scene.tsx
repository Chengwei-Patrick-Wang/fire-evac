import { Canvas } from '@react-three/fiber'
import { OrbitControls, Stats } from '@react-three/drei'
import Building from './Building'
import CameraRig from './CameraRig'

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
        {import.meta.env.DEV && <Stats />}
      </Canvas>
    </div>
  )
}
