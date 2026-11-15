import * as THREE from 'three'

/** The flipbook: FRAMES frames of FW x FH texels, in a GRID x GRID atlas, looping once every FRAMES frames. */
export const FRAMES = 16
export const GRID = 4
const FW = 64
const FH = 128

// A small value noise that wraps every P lattice cells in both directions, so the scroll below loops exactly.
const P = 8
const lattice = (() => {
  // A fixed LCG: the same flames on every load (no Math.random).
  let s = 12345
  const out = new Float32Array(P * P)
  for (let i = 0; i < out.length; i++) {
    s = (s * 1103515245 + 12345) >>> 0
    out[i] = (s >>> 8) / 0xffffff
  }
  return out
})()
const at = (x: number, y: number) => lattice[(((y % P) + P) % P) * P + (((x % P) + P) % P)]
function noise(x: number, y: number): number {
  const x0 = Math.floor(x)
  const y0 = Math.floor(y)
  const fx = x - x0
  const fy = y - y0
  const sx = fx * fx * (3 - 2 * fx)
  const sy = fy * fy * (3 - 2 * fy)
  const a = at(x0, y0) + (at(x0 + 1, y0) - at(x0, y0)) * sx
  const b = at(x0, y0 + 1) + (at(x0 + 1, y0 + 1) - at(x0, y0 + 1)) * sx
  return a + (b - a) * sy
}

// Colour stops by flame intensity (sRGB, 0 to 1): transparent red at the edge, then red, orange, yellow, and a yellow-white core.
const STOPS: [number, number, number, number][] = [
  [0.0, 0.45, 0.04, 0.0],
  [0.25, 0.85, 0.16, 0.02],
  [0.5, 1.0, 0.42, 0.05],
  [0.72, 1.0, 0.7, 0.18],
  [0.88, 1.0, 0.9, 0.5],
  [1.0, 1.0, 0.98, 0.85],
]
function ramp(i: number, out: number[]) {
  let k = 1
  while (k < STOPS.length - 1 && STOPS[k][0] < i) k++
  const a = STOPS[k - 1]
  const b = STOPS[k]
  const w = Math.min(1, Math.max(0, (i - a[0]) / (b[0] - a[0])))
  out[0] = a[1] + (b[1] - a[1]) * w
  out[1] = a[2] + (b[2] - a[2]) * w
  out[2] = a[3] + (b[3] - a[3]) * w
}
const smooth = (e0: number, e1: number, x: number) => {
  const k = Math.min(1, Math.max(0, (x - e0) / (e1 - e0)))
  return k * k * (3 - 2 * k)
}

/** One frame's texels into `data` at its atlas cell: noise-shaped tongues that rise one noise period per loop, so frame FRAMES is frame 0 again. */
function drawFrame(data: Uint8Array, f: number, width: number) {
  const phase = f / FRAMES
  const theta = phase * Math.PI * 2
  const ox = (f % GRID) * FW
  const oy = Math.floor(f / GRID) * FH
  const c = [0, 0, 0]
  for (let py = 0; py < FH; py++) {
    // v: 0 at the base, 1 at the top of the frame
    const v = (py + 0.5) / FH
    for (let px = 0; px < FW; px++) {
      const u = ((px + 0.5) / FW) * 2 - 1
      // two octaves scrolling upward by whole periods over the loop (turbulence grows with height)
      const n1 = noise(u * 2 + 4, v * 4 - phase * P)
      const n2 = noise(u * 5 + 1, v * 8 - phase * P * 2)
      const n = n1 * 0.65 + n2 * 0.35
      // the sway: a slow lean that loops with the frames, stronger toward the tip
      const sway = 0.12 * v * Math.sin(theta + v * 3.2) + 0.1 * v * (n1 - 0.5)
      // a teardrop: wide and round at the base, narrowing to the tip
      const half = 0.92 * Math.pow(Math.max(0, 1 - v), 0.5) * (0.6 + 0.4 * smooth(0, 0.18, v))
      const d = Math.abs(u + sway) / Math.max(0.02, half)
      let i = 1 - Math.pow(d, 1.6)
      i += (n - 0.5) * (0.35 + 0.9 * v)
      // tongues: the top breaks up where the noise is low
      i *= smooth(1.02, 0.55, v + 0.35 * (0.5 - n))
      i *= smooth(0, 0.07, v)
      i = Math.min(1, Math.max(0, i))
      const a = smooth(0.02, 0.4, i)
      ramp(i, c)
      const o = ((oy + py) * width + ox + px) * 4
      data[o] = Math.round(c[0] * 255)
      data[o + 1] = Math.round(c[1] * 255)
      data[o + 2] = Math.round(c[2] * 255)
      data[o + 3] = Math.round(a * 255)
    }
  }
}

let atlas: THREE.DataTexture | null = null

/** The flame flipbook, made once in code (no image files) and shared by every flame of every view. */
export function flameAtlas(): THREE.DataTexture {
  if (atlas) return atlas
  const width = FW * GRID
  const height = FH * GRID
  const data = new Uint8Array(width * height * 4)
  for (let f = 0; f < FRAMES; f++) drawFrame(data, f, width)
  const t = new THREE.DataTexture(data, width, height, THREE.RGBAFormat)
  t.magFilter = THREE.LinearFilter
  t.minFilter = THREE.LinearMipmapLinearFilter
  t.generateMipmaps = true
  t.needsUpdate = true
  atlas = t
  return t
}
