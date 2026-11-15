import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useApp } from '../../store/app'
import { useClock } from '../../store/clock'
import { useA11y } from '../../ui/a11y'
import { floorAlpha, floorPlace } from '../../scene/geometry'
import type { Building, BuildingFloor } from '../../data/types'
import { FRAMES, GRID, flameAtlas } from './flameAtlas'
import { fadeIn, flameHeight } from './heat'

/** One flame: where it stands (plan x, y on a floor), when it lights, and its heat at t (kW). */
export interface FlameSource {
  floor: BuildingFloor
  x: number
  y: number
  ignite: number
  heat: (t: number) => number
}

/** Drawn after the ceiling smoke (2), so a fire always reads through it. */
export const FLAME_ORDER = 3
/** The flipbook's speed, frames per second (16 frames: one loop a second). */
const FPS = 16

const VERT = /* glsl */ `
attribute vec3 iPos;
attribute vec2 iSize;
attribute float iPhase;
attribute float iAlpha;
varying vec2 vUv;
varying float vAlpha;
varying float vPhase;
void main() {
  vec3 right = vec3(viewMatrix[0][0], viewMatrix[1][0], viewMatrix[2][0]);
  vec3 camUp = vec3(viewMatrix[0][1], viewMatrix[1][1], viewMatrix[2][1]);
  vec3 back = vec3(viewMatrix[0][2], viewMatrix[1][2], viewMatrix[2][2]);
  // Upright flames that turn to face the camera; looking almost straight down they tip toward the screen's up, so they never go edge-on.
  float steep = smoothstep(0.75, 0.98, back.y);
  vec3 r = normalize(vec3(right.x, 0.0, right.z) + vec3(1e-5, 0.0, 0.0));
  vec3 up = normalize(mix(vec3(0.0, 1.0, 0.0), camUp, steep));
  vec3 p = iPos + r * position.x * iSize.x + up * position.y * iSize.y;
  vUv = uv;
  vAlpha = iAlpha;
  vPhase = iPhase;
  gl_Position = projectionMatrix * viewMatrix * vec4(p, 1.0);
}
`

const FRAG = /* glsl */ `
uniform sampler2D uMap;
uniform float uTime;
varying vec2 vUv;
varying float vAlpha;
varying float vPhase;
const float N = ${FRAMES.toFixed(1)};
const float G = ${GRID.toFixed(1)};
vec4 frame(float f, vec2 uv) {
  return texture2D(uMap, (vec2(mod(f, G), floor(f / G)) + uv) / G);
}
void main() {
  // inset half a texel so filtering never reaches the next frame of the atlas
  vec2 uv = clamp(vUv, vec2(0.01, 0.004), vec2(0.99, 0.996));
  float f = uTime * ${FPS.toFixed(1)} + vPhase * N;
  float f0 = mod(floor(f), N);
  vec4 c = mix(frame(f0, uv), frame(mod(f0 + 1.0, N), uv), fract(f));
  float a = c.a * vAlpha;
  if (a < 0.004) discard;
  // Premultiplied: the colour adds like light (additive) while 55% of the alpha darkens what is behind, so the flame keeps its colour on the light floor.
  gl_FragColor = vec4(c.rgb * a, a * 0.55);
}
`

/** A quad 1 wide and 1 tall, its base on y = 0. */
function quad(): THREE.InstancedBufferGeometry {
  const g = new THREE.InstancedBufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-0.5, 0, 0, 0.5, 0, 0, 0.5, 1, 0, -0.5, 1, 0]), 3))
  g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]), 2))
  g.setIndex([0, 1, 2, 0, 2, 3])
  return g
}

/**
 * Flames as camera-facing billboards with an animated flipbook, one draw call for all of them. A flame shows from its ignition, fading
 * in over 3 s; its height follows its heat (flameHeight), times the glow setting's size factor (0.6x to 1.4x, as the fire marker had).
 * Hidden floors draw none; the faint floors of the ghost view draw them faint. Reduce motion holds one frame.
 */
export default function FlameSprites({ sources, building }: { sources: FlameSource[]; building: Building }) {
  const n = Math.max(1, sources.length)
  const { geo, mat, attrs } = useMemo(() => {
    const g = quad()
    const iPos = new THREE.InstancedBufferAttribute(new Float32Array(n * 3), 3)
    const iSize = new THREE.InstancedBufferAttribute(new Float32Array(n * 2), 2)
    const iPhase = new THREE.InstancedBufferAttribute(new Float32Array(n), 1)
    const iAlpha = new THREE.InstancedBufferAttribute(new Float32Array(n), 1)
    for (const a of [iPos, iSize, iAlpha]) a.setUsage(THREE.DynamicDrawUsage)
    g.setAttribute('iPos', iPos)
    g.setAttribute('iSize', iSize)
    g.setAttribute('iPhase', iPhase)
    g.setAttribute('iAlpha', iAlpha)
    g.instanceCount = 0
    const m = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      uniforms: { uMap: { value: flameAtlas() }, uTime: { value: 0 } },
      transparent: true,
      depthWrite: false,
      blending: THREE.CustomBlending,
      blendEquation: THREE.AddEquation,
      blendSrc: THREE.OneFactor,
      blendDst: THREE.OneMinusSrcAlphaFactor,
      toneMapped: false,
    })
    return { geo: g, mat: m, attrs: { iPos, iSize, iPhase, iAlpha } }
  }, [n])
  useEffect(() => () => {
    geo.dispose()
    mat.dispose()
  }, [geo, mat])
  const mesh = useRef<THREE.Mesh>(null)

  useFrame(({ clock }) => {
    const st = useApp.getState()
    const { visibleFloors, viewMode, focusFloor, explode, fireGlow } = st
    const t = useClock.getState().t
    const still = useA11y.getState().reduceMotion
    mat.uniforms.uTime.value = still ? 0 : clock.elapsedTime
    const size = 0.6 + 0.4 * fireGlow
    const bright = Math.min(1.25, 0.5 + 0.5 * fireGlow)
    let k = 0
    for (let i = 0; i < sources.length; i++) {
      const s = sources[i]
      if (t < s.ignite || (visibleFloors && !visibleFloors.includes(s.floor.id))) continue
      const fade = fadeIn(t, s.ignite)
      const h = flameHeight(s.heat(t)) * size * (0.35 + 0.65 * fade)
      const p = floorPlace(building, s.floor, viewMode, explode)
      attrs.iPos.setXYZ(k, s.x + p.dx, p.y, -s.y)
      attrs.iSize.setXY(k, h * 0.75, h)
      // a fixed spread of phases, so neighbouring flames never move in step
      attrs.iPhase.setX(k, (i * 0.618034) % 1)
      attrs.iAlpha.setX(k, fade * bright * floorAlpha(viewMode, focusFloor, s.floor.id))
      k++
    }
    geo.instanceCount = k
    attrs.iPos.needsUpdate = true
    attrs.iSize.needsUpdate = true
    attrs.iPhase.needsUpdate = true
    attrs.iAlpha.needsUpdate = true
    if (mesh.current) mesh.current.visible = k > 0
  })

  return <mesh ref={mesh} geometry={geo} material={mat} frustumCulled={false} renderOrder={FLAME_ORDER} visible={false} raycast={() => null} />
}
