import { useEffect, useMemo, useRef } from 'react'
import { useA11y } from '../ui/a11y'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { floorAlpha, floorPlace, toPlaced } from '../scene/geometry'
import { usePlace } from '../scene/usePlace'
import { readSpread } from '../model/fireSpread'
import type { BuildingFloor } from '../data/types'
import FlameSprites from './fx/FlameSprites'
import type { FlameSource } from './fx/FlameSprites'
import { fadeIn, flicker, readHeat } from './fx/heat'
import { useSceneBuilding } from '../scene/sceneBuilding'

/** The fire light's colour, and its height above the floor (m). */
const LIGHT = '#ff7a1a'
const LIGHT_H = 1.5

/**
 * The light's pool on the floor: the light floor is lit nearly white already, so a point light barely shows on it. A soft warm disc that
 * follows the same intensity and flicker shows it. Above the floor marks and tints (0.02 to 0.06), under the smoke (render order 2).
 */
const POOL_Y = 0.07
const poolGeo = new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2)
const POOL_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform float uAlpha;
uniform vec4 uBox;
varying vec2 vUv;
varying vec2 vXZ;
void main() {
  // never past the floor's outline box (a pool spilling into the air beside the building would float)
  if (vXZ.x < uBox.x || vXZ.y < uBox.y || vXZ.x > uBox.z || vXZ.y > uBox.w) discard;
  float r = length(vUv - 0.5) * 2.0;
  float a = uAlpha * pow(max(0.0, 1.0 - r), 2.2);
  if (a < 0.003) discard;
  gl_FragColor = vec4(uColor, a);
}
`
const POOL_VERT = /* glsl */ `
varying vec2 vUv;
varying vec2 vXZ;
void main() {
  vUv = uv;
  vec4 w = modelMatrix * vec4(position, 1.0);
  vXZ = w.xz;
  gl_Position = projectionMatrix * viewMatrix * w;
}
`

/** A floor's walkable outline box in plan metres: [minX, minY, maxX, maxY]. */
function outlineBox(floor: BuildingFloor): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const w of floor.walkable)
    for (const [x, y] of w.outer) {
      x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y)
    }
  return isFinite(x0) ? [x0, y0, x1, y1] : [-1e6, -1e6, 1e6, 1e6]
}

/**
 * The fire at its ignition point: a flame sprite and a warm point light 1.5 m up, with its pool on the floor. The light follows the run's
 * heat release at the replay time (fire.hrr: the square root of its share of 1.5 MW, capped), times the glow setting, with a 4 to 10 Hz
 * flicker (steady under Reduce motion). All show only from the ignition, on a floor the view shows, while the Fire layer is on.
 */
export default function Fire({ runKey }: { runKey?: string }) {
  const activeKey = useApp((s) => s.activeRunKey)
  const on = useApp((s) => s.layers.fire)
  const building = useSceneBuilding()
  const visible = useApp((s) => s.visibleFloors)
  const place = usePlace()
  const key = runKey ?? activeKey
  const lr = useApp((s) => (key ? s.runs[key] : undefined))
  const light = useRef<THREE.PointLight>(null)
  const fire = lr?.run.fire
  const floor = building?.floors.find((f) => f.id === fire?.floor)
  const heat = useMemo(() => (lr ? readHeat(lr.run, readSpread(lr.run)) : null), [lr])
  const sources = useMemo<FlameSource[]>(
    () => (fire && floor && heat ? [{ floor, x: fire.x, y: fire.y, ignite: heat.ignite, heat: heat.main }] : []),
    [fire, floor, heat],
  )

  const poolMat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: POOL_VERT,
        fragmentShader: POOL_FRAG,
        // raw sRGB (a shader material writes its colour as is): a warmer, lighter orange than the light, so the pool reads on the red tints
        uniforms: { uColor: { value: new THREE.Vector3(1.0, 0.62, 0.22) }, uAlpha: { value: 0 }, uBox: { value: new THREE.Vector4() } },
        transparent: true,
        depthWrite: false,
      }),
    [],
  )
  useEffect(() => () => poolMat.dispose(), [poolMat])
  const pool = useRef<THREE.Mesh>(null)
  const box = useMemo(() => (floor ? outlineBox(floor) : null), [floor])

  useFrame(({ clock }) => {
    const l = light.current
    if (!l || !heat || !floor || !building || !box) return
    const t = useClock.getState().t
    const st = useApp.getState()
    const flick = useA11y.getState().reduceMotion ? 1 : flicker(clock.elapsedTime)
    const level = Math.min(1.2, 0.15 + Math.sqrt(heat.total(t) / 1500))
    const k = t < heat.ignite ? 0 : level * fadeIn(t, heat.ignite) * flick * st.fireGlow * floorAlpha(st.viewMode, st.focusFloor, floor.id)
    l.intensity = 6 * k
    poolMat.uniforms.uAlpha.value = Math.min(0.75, 0.42 * k)
    const dx = floorPlace(building, floor, st.viewMode, st.explode).dx
    poolMat.uniforms.uBox.value.set(box[0] + dx, -box[3], box[2] + dx, -box[1])
    const p = pool.current
    if (p) {
      const r = (2.5 + 4 * Math.min(1, level)) * (0.6 + 0.4 * st.fireGlow)
      p.scale.set(2 * r, 1, 2 * r)
      p.visible = k > 0
    }
  })

  if (!on || !fire || !floor || !building || (visible && !visible.includes(floor.id))) return null
  return (
    <>
      <pointLight ref={light} position={toPlaced(place(floor), fire.x, fire.y, LIGHT_H)} color={LIGHT} intensity={0} distance={18} decay={1.2} />
      <mesh ref={pool} geometry={poolGeo} material={poolMat} position={toPlaced(place(floor), fire.x, fire.y, POOL_Y)} renderOrder={1} visible={false} raycast={() => null} />
      <FlameSprites sources={sources} building={building} />
    </>
  )
}
