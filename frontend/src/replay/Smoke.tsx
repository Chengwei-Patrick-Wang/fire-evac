import { useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { useA11y } from '../ui/a11y'
import { b64ToBytes } from '../model/decode'
import { floorAlpha, gridPlacement, toPlaced } from '../scene/geometry'
import { usePlace } from '../scene/usePlace'
import { nearestIndex } from './runIndex'
import { smokeNoise } from './fx/smokeNoise'
import type { SmokeLayer } from '../data/types'
import { useSceneBuilding } from '../scene/sceneBuilding'

/** After the floor marks and burning-room tints, before the flames (3). */
const SMOKE_ORDER = 2
/** Each plane's share of the reach (below) at which it shows: the top plane first, the lowest once the density nears 90. */
const LEVELS = [0, 0.45, 0.85]

const VERT = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

const FRAG = /* glsl */ `
uniform sampler2D uA;
uniform sampler2D uB;
uniform sampler2D uNoise;
uniform float uMix;
uniform float uOpacity;
uniform float uLevel;
uniform float uTime;
uniform vec2 uOrigin;
uniform vec2 uSize;
varying vec2 vUv;
void main() {
  // the model's density (bytes 0 to 100) between two snapshots; reach is 1 at 90, the density the model calls untenable
  float d = mix(texture2D(uA, vUv).r, texture2D(uB, vUv).r, uMix) * 2.55;
  float reach = clamp(d / 0.9, 0.0, 1.0);
  float show = smoothstep(uLevel - 0.15, uLevel + 0.15, reach);
  // slow billows in plan metres
  vec2 w = uOrigin + vUv * uSize;
  float n = texture2D(uNoise, w * 0.06 + vec2(uTime * 0.010, uTime * 0.006) + uLevel * 0.37).r;
  float m = texture2D(uNoise, w * 0.17 - vec2(uTime * 0.016, -uTime * 0.009)).r;
  float puff = 0.7 + 0.6 * (0.6 * n + 0.4 * m);
  float a = 0.3 * pow(reach, 0.6) * show * puff * uOpacity;
  if (a < 0.003) discard;
  // light grey haze when thin, near black when dense
  vec3 col = mix(vec3(0.36, 0.35, 0.34), vec3(0.10, 0.09, 0.09), reach) * (0.9 + 0.2 * n);
  gl_FragColor = vec4(col, min(a, 0.9));
}
`

function grayTexture(cols: number, rows: number, data: Uint8Array): THREE.DataTexture {
  const t = new THREE.DataTexture(data, cols, rows, THREE.RedFormat, THREE.UnsignedByteType)
  t.magFilter = THREE.LinearFilter
  t.minFilter = THREE.LinearFilter
  t.unpackAlignment = 1
  t.needsUpdate = true
  return t
}

/**
 * One floor's smoke as a layer under the ceiling: three stacked planes that read the model's density from the run's snapshots,
 * interpolated between them on the GPU. The top plane shows first; the lower ones join as the density grows, so the layer deepens and
 * darkens from the ceiling down, reaching its lowest plane (about 1.9 m) as the density nears the model's untenable 90. Opacity follows
 * the density times the smoke opacity setting (and the ghost view's share for a faint floor).
 */
function CeilingSmoke({ layer, runKey }: { layer: SmokeLayer; runKey: string }) {
  const building = useSceneBuilding()
  const visible = useApp((s) => s.visibleFloors)
  const place = usePlace()
  const floor = building?.floors.find((f) => f.id === layer.floor)
  const { cols, rows } = layer
  const times = useMemo(() => Float64Array.from(layer.frames.map((f) => f.t)), [layer])
  const r = useMemo(() => {
    const zeros = new Uint8Array(cols * rows)
    const { center, size } = gridPlacement(layer)
    const shared = {
      uA: { value: grayTexture(cols, rows, zeros) },
      uB: { value: grayTexture(cols, rows, zeros) },
      uNoise: { value: smokeNoise() },
      uMix: { value: 0 },
      uOpacity: { value: 0 },
      uTime: { value: 0 },
      uOrigin: { value: new THREE.Vector2(layer.origin[0], layer.origin[1]) },
      uSize: { value: new THREE.Vector2(size[0], size[1]) },
    }
    const mats = LEVELS.map(
      (level) =>
        new THREE.ShaderMaterial({
          vertexShader: VERT,
          fragmentShader: FRAG,
          uniforms: { ...shared, uLevel: { value: level } },
          transparent: true,
          depthWrite: false,
          side: THREE.DoubleSide,
        }),
    )
    const geo = new THREE.PlaneGeometry(size[0], size[1])
    // decoded snapshots by index (each decoded once); `a`/`b` are the arrays in the two textures
    return { zeros, center, shared, mats, geo, frames: [] as (Uint8Array | undefined)[], a: zeros as Uint8Array, b: zeros as Uint8Array, warned: false }
  }, [layer, cols, rows, runKey])
  useEffect(
    () => () => {
      r.shared.uA.value.dispose()
      r.shared.uB.value.dispose()
      r.mats.forEach((m) => m.dispose())
      r.geo.dispose()
    },
    [r],
  )

  const frame = (i: number): Uint8Array | null => {
    let f = r.frames[i]
    if (!f) {
      f = b64ToBytes(layer.frames[i].d)
      if (f.length !== cols * rows) {
        console.warn(`smoke ${layer.floor}: ${f.length} bytes, expected ${cols * rows}; layer skipped`)
        r.warned = true
        return null
      }
      r.frames[i] = f
    }
    return f
  }

  useFrame(({ clock }) => {
    const n = times.length
    if (r.warned || n === 0 || !floor) return
    const t = useClock.getState().t
    const st = useApp.getState()
    const step = layer.interval ?? (n > 1 ? times[1] - times[0] : 2)
    const i = t < times[0] ? -1 : nearestIndex(times, t)
    let a: Uint8Array | null
    let b: Uint8Array | null
    let w: number
    if (i === -1) {
      // before the first snapshot the floor is clear; it thickens into the first one over one interval
      a = r.zeros
      b = frame(0)
      w = Math.min(1, Math.max(0, (t - (times[0] - step)) / step))
    } else if (i >= n - 1) {
      a = b = frame(n - 1)
      w = 0
    } else {
      a = frame(i)
      b = frame(i + 1)
      w = Math.min(1, Math.max(0, (t - times[i]) / (times[i + 1] - times[i])))
    }
    if (!a || !b) return
    const s = r.shared
    if (a !== r.a) {
      s.uA.value.image.data = a
      s.uA.value.needsUpdate = true
      r.a = a
    }
    if (b !== r.b) {
      s.uB.value.image.data = b
      s.uB.value.needsUpdate = true
      r.b = b
    }
    s.uMix.value = w
    s.uOpacity.value = st.smokeOpacity * floorAlpha(st.viewMode, st.focusFloor, floor.id)
    s.uTime.value = useA11y.getState().reduceMotion ? 0 : clock.elapsedTime
  })

  if (!floor || (visible && !visible.includes(floor.id))) return null
  // from just under the ceiling (clear of the slab above) down to about head height
  const top = floor.height - 0.25
  const low = Math.min(top - 0.5, 1.9)
  const at = place(floor)
  return (
    <>
      {r.mats.map((m, k) => (
        <mesh
          key={k}
          geometry={r.geo}
          material={m}
          position={toPlaced(at, r.center[0], r.center[1], top - ((top - low) * k) / (LEVELS.length - 1))}
          rotation={[-Math.PI / 2, 0, 0]}
          renderOrder={SMOKE_ORDER}
          raycast={() => null}
        />
      ))}
    </>
  )
}

/** The smoke layer: a ceiling layer per floor with smoke frames, while the Smoke layer is on. */
export default function Smoke({ runKey }: { runKey?: string }) {
  const activeKey = useApp((s) => s.activeRunKey)
  const on = useApp((s) => s.layers.smoke)
  const key = runKey ?? activeKey
  const lr = useApp((s) => (key ? s.runs[key] : undefined))
  if (!on || !lr || !lr.run.smoke || lr.run.smoke.length === 0) return null
  return (
    <>
      {lr.run.smoke.map((l) => (
        <CeilingSmoke key={key + l.floor} layer={l} runKey={key!} />
      ))}
    </>
  )
}
