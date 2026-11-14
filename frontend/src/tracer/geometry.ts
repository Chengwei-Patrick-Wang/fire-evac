// Pixel <-> plan geometry for the tracer.
//
// Image pixels have y pointing down; plan meters have y pointing up and are measured from the
// floor's reference point (the image's bottom-left corner until one is marked):
//   plan = ((px - ref.x) * s, (ref.y - py) * s)      s = meters per pixel
// Pure functions: no React, no Node imports, so tsc, Vite and tsx all accept this file.
import type { TraceFloor } from "./plan";

export type Pt = [number, number];

/** Traced rooms and door centers snap to this many meters (spec 6: a 0.25 m grid). */
export const GRID = 0.25;

/** Meters per pixel from two clicked points and the real distance between them. 0 if unusable. */
export function scaleFromClicks(p1: Pt, p2: Pt, meters: number): number {
  const px = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
  if (!Number.isFinite(px) || !Number.isFinite(meters) || px <= 0 || meters <= 0) return 0;
  return meters / px;
}

/** Meters per pixel of a floor; 0 while its scale is not set. */
export function floorScale(f: TraceFloor): number {
  return f.scale ? scaleFromClicks(f.scale.p1, f.scale.p2, f.scale.meters) : 0;
}

/** The floor's reference point in pixels: the image's bottom-left corner until one is marked. */
export function floorRef(f: TraceFloor): Pt {
  return f.ref ?? [0, f.imageH];
}

/** Image pixels (y down) to plan meters (y up), measured from the floor's reference point. */
export function pxToPlan(p: Pt, f: TraceFloor): Pt {
  const s = floorScale(f);
  const [rx, ry] = floorRef(f);
  return [(p[0] - rx) * s, (ry - p[1]) * s];
}

/** Inverse of pxToPlan. Without a scale every point maps to the reference point. */
export function planToPx(p: Pt, f: TraceFloor): Pt {
  const s = floorScale(f);
  const [rx, ry] = floorRef(f);
  return s > 0 ? [rx + p[0] / s, ry - p[1] / s] : [rx, ry];
}

/** Round to the nearest grid line. */
export function snap(v: number, grid = GRID): number {
  return Math.round(v / grid) * grid + 0; // + 0 turns -0 into 0
}

/** Snap a pixel point to the grid in meters (the grid starts at the floor's reference point);
 * the result is in pixels. Without a scale there is no grid, so the point is returned as it is. */
export function snapPoint(p: Pt, f: TraceFloor): Pt {
  if (!(floorScale(f) > 0)) return [p[0], p[1]];
  const [x, y] = pxToPlan(p, f);
  return planToPx([snap(x), snap(y)], f);
}

/** The polygon's edges as [from, to] pairs, closing the ring. */
function edges(poly: Pt[]): Array<[Pt, Pt]> {
  const out: Array<[Pt, Pt]> = [];
  poly.forEach((p, i) => {
    const q = poly[(i + 1) % poly.length];
    if (q) out.push([p, q]);
  });
  return out;
}

/** Absolute area of a polygon (shoelace formula), in the polygon's own units. */
export function polygonArea(poly: Pt[]): number {
  let twice = 0;
  for (const [a, b] of edges(poly)) twice += a[0] * b[1] - b[0] * a[1];
  return Math.abs(twice) / 2;
}

/** True inside the polygon and on its boundary, like shapely's covers(). Exact by default, so the
 * door test classifies a point the way the normalizer does; eps widens the boundary. */
export function pointInPolygon(p: Pt, poly: Pt[], eps = 0): boolean {
  const [x, y] = p;
  let inside = false;
  for (const [a, b] of edges(poly)) {
    const [ax, ay] = a;
    const [bx, by] = b;
    const len = Math.hypot(bx - ax, by - ay);
    const cross = (bx - ax) * (y - ay) - (by - ay) * (x - ax); // |cross| / len = distance to the line
    if (
      len > 0 &&
      Math.abs(cross) <= eps * len &&
      x >= Math.min(ax, bx) - eps && x <= Math.max(ax, bx) + eps &&
      y >= Math.min(ay, by) - eps && y <= Math.max(ay, by) + eps
    ) {
      return true; // on an edge
    }
    // the edge crosses the horizontal ray from p towards +x: flip
    if (ay > y !== by > y && x < ((bx - ax) * (y - ay)) / (by - ay) + ax) {
      inside = !inside;
    }
  }
  return inside;
}
