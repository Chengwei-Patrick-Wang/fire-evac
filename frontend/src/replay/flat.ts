import * as THREE from 'three'
import type { Vec2 } from '../data/types'

/** A flat polygon (plan x, y) lying in the scene's floor plane, y = 0; place the mesh with `toPlaced`. */
export function flatGeometry(poly: Vec2[]): THREE.ShapeGeometry {
  const s = new THREE.Shape()
  poly.forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)))
  const g = new THREE.ShapeGeometry(s)
  g.rotateX(-Math.PI / 2)
  return g
}
