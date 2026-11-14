import { useEffect } from 'react'
import { useThree } from '@react-three/fiber'

let capture: (() => string) | null = null

/** Renders and reads the canvas in the same call, so preserveDrawingBuffer is not needed. */
export function CaptureHook() {
  const gl = useThree((s) => s.gl)
  const scene = useThree((s) => s.scene)
  const camera = useThree((s) => s.camera)
  useEffect(() => {
    const fn = () => {
      gl.render(scene, camera)
      return gl.domElement.toDataURL('image/png')
    }
    capture = fn
    return () => {
      if (capture === fn) capture = null
    }
  }, [gl, scene, camera])
  return null
}

export function captureView(): string | null {
  return capture ? capture() : null
}
