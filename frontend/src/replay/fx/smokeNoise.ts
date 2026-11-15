import * as THREE from 'three'

const S = 128
let tex: THREE.DataTexture | null = null

/** A tiling grey value noise (three octaves, 128 x 128, one channel) that gives the ceiling smoke its billows; made once in code. */
export function smokeNoise(): THREE.DataTexture {
  if (tex) return tex
  let seed = 987654
  const rand = () => {
    seed = (seed * 1103515245 + 12345) >>> 0
    return (seed >>> 8) / 0xffffff
  }
  const data = new Uint8Array(S * S)
  const acc = new Float32Array(S * S)
  let amp = 1
  let total = 0
  for (const cells of [4, 8, 16]) {
    const lat = new Float32Array(cells * cells)
    for (let i = 0; i < lat.length; i++) lat[i] = rand()
    const at = (x: number, y: number) => lat[(y % cells) * cells + (x % cells)]
    for (let py = 0; py < S; py++)
      for (let px = 0; px < S; px++) {
        const x = (px / S) * cells
        const y = (py / S) * cells
        const x0 = Math.floor(x)
        const y0 = Math.floor(y)
        const fx = x - x0
        const fy = y - y0
        const sx = fx * fx * (3 - 2 * fx)
        const sy = fy * fy * (3 - 2 * fy)
        const a = at(x0, y0) + (at(x0 + 1, y0) - at(x0, y0)) * sx
        const b = at(x0, y0 + 1) + (at(x0 + 1, y0 + 1) - at(x0, y0 + 1)) * sx
        acc[py * S + px] += (a + (b - a) * sy) * amp
      }
    total += amp
    amp *= 0.5
  }
  for (let i = 0; i < acc.length; i++) data[i] = Math.round((acc[i] / total) * 255)
  const t = new THREE.DataTexture(data, S, S, THREE.RedFormat, THREE.UnsignedByteType)
  t.wrapS = THREE.RepeatWrapping
  t.wrapT = THREE.RepeatWrapping
  t.magFilter = THREE.LinearFilter
  t.minFilter = THREE.LinearMipmapLinearFilter
  t.generateMipmaps = true
  t.unpackAlignment = 1
  t.needsUpdate = true
  tex = t
  return t
}
