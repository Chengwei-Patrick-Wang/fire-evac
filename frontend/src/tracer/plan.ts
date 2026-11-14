// plan/v0 as the tracer builds it: the trace state (image pixels), the export to meters, and the
// checks that mirror what buildings.normalize needs. Pure TypeScript: no React, no Node imports,
// so tsc, Vite and tsx all accept this file.
import { floorScale, pointInPolygon, polygonArea, pxToPlan, snap } from "./geometry";
import type { Pt } from "./geometry";

/** The 13 room types of spec 6. */
export const ROOM_TYPES = [
  "office",
  "classroom",
  "kitchen",
  "dining",
  "lounge",
  "bedroom",
  "lab",
  "storage",
  "restroom",
  "corridor",
  "lobby",
  "stair",
  "other",
] as const;
export type RoomType = (typeof ROOM_TYPES)[number];

export type DoorState = "open" | "closed" | "propped";

/** Every exported floor is 3.5 m tall, as in contracts/plan.example.json; elevation = level * height. */
export const FLOOR_HEIGHT = 3.5;

// ---------------------------------------------------------------- the trace (image pixels, y down)

export interface TraceScale {
  p1: Pt; // two clicked image points ...
  p2: Pt;
  meters: number; // ... and the real distance between them
}

export interface TraceRoom {
  id: string; // trace-time id; the export numbers rooms R1, R2, ... over the whole building
  name: string;
  type: RoomType;
  polygon: Pt[]; // image pixels
  group?: string; // stair rooms: the same group on every floor means the stairs connect
  ai?: boolean; // proposed by the AI first pass and not reviewed yet
}

export interface TraceDoor {
  id: string; // trace-time id; the export numbers doors D1, D2, ... over the whole building
  a: Pt; // the opening's two ends along the wall, image pixels
  b: Pt;
  fireDoor: boolean;
  state: DoorState;
  name?: string; // the exit name; only exterior doors use it
}

export interface TraceFloor {
  id: string; // "F1"
  name: string; // what the floor tab shows
  level: number; // 0 is the ground floor; the export sets elevation = level * FLOOR_HEIGHT
  imageW: number; // size of the plan image in pixels
  imageH: number;
  scale: TraceScale | null; // null until the user sets it
  ref: Pt | null; // the floor's reference point in pixels (null: the image's bottom-left corner)
  rooms: TraceRoom[];
  doors: TraceDoor[];
}

export interface TraceState {
  id: string; // building id, a slug
  name: string;
  credits: string;
  floors: TraceFloor[];
}

// ---------------------------------------------------------------- plan/v0 (meters, y up)

export interface PlanRoom {
  id: string;
  name: string;
  type: RoomType;
  polygon: Pt[];
  group?: string;
}

export interface PlanDoor {
  id: string;
  a: Pt;
  b: Pt;
  width: number;
  fireDoor: boolean;
  state: DoorState;
  name?: string; // the exit name of an exterior door
  rect?: Pt[]; // the opening's own footprint (IFC doors); the tracer never sets it
}

export interface PlanFloor {
  id: string;
  level: number;
  elevation: number;
  height: number;
  rooms: PlanRoom[];
  doors: PlanDoor[];
}

export interface PlanV0 {
  version: "plan/v0";
  id: string;
  name: string;
  source: "ifc" | "trace" | "synthetic";
  credits: string;
  floors: PlanFloor[];
}

// ---------------------------------------------------------------- export

/** Round to millimeters (+ 0 turns -0 into 0). */
function r3(v: number): number {
  return Math.round(v * 1000) / 1000 + 0;
}

function isRoomType(t: string): t is RoomType {
  return (ROOM_TYPES as readonly string[]).includes(t);
}

/** Drop repeated neighbors, and a last point that repeats the first (rings close implicitly). */
function dedupe(poly: Pt[]): Pt[] {
  const out: Pt[] = [];
  for (const p of poly) {
    const prev = out[out.length - 1];
    if (!prev || prev[0] !== p[0] || prev[1] !== p[1]) out.push(p);
  }
  const first = out[0];
  const last = out[out.length - 1];
  if (out.length > 1 && first && last && first[0] === last[0] && first[1] === last[1]) out.pop();
  return out;
}

/**
 * trace -> plan/v0. Floors go in level order. Every floor is measured from its own reference
 * point in its own scale, room vertices are snapped to the 0.25 m grid, and then the whole
 * building is shifted once so that its min x and y are 0 (the floors stay lined up). Rooms are
 * numbered R1... and doors D1... over the whole building. Door ends are not snapped (the page
 * snaps their centers); a door's width is |ab|.
 */
export function exportPlan(s: TraceState): PlanV0 {
  const floors = [...s.floors].sort((a, b) => a.level - b.level);

  const placed = floors.map((f) => ({
    f,
    rooms: f.rooms.map((r) => ({
      r,
      polygon: dedupe(
        r.polygon.map((p): Pt => {
          const [x, y] = pxToPlan(p, f);
          return [snap(x), snap(y)];
        }),
      ),
    })),
    doors: f.doors.map((d) => ({ d, a: pxToPlan(d.a, f), b: pxToPlan(d.b, f) })),
  }));

  let minX = Infinity;
  let minY = Infinity;
  for (const c of placed) {
    for (const room of c.rooms) {
      for (const [x, y] of room.polygon) {
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
      }
    }
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY)) {
    minX = 0;
    minY = 0;
  }
  const shift = (p: Pt): Pt => [r3(p[0] - minX), r3(p[1] - minY)];

  let nRoom = 0;
  let nDoor = 0;
  const planFloors = placed.map(({ f, rooms, doors }, k): PlanFloor => ({
    id: f.id.trim() || `F${k + 1}`,
    level: f.level,
    elevation: f.level * FLOOR_HEIGHT,
    height: FLOOR_HEIGHT,
    rooms: rooms.map(({ r, polygon }): PlanRoom => {
      const id = `R${++nRoom}`;
      const room: PlanRoom = {
        id,
        name: (r.name || "").trim() || id,
        type: isRoomType(r.type) ? r.type : "other",
        polygon: polygon.map((p) => shift(p)),
      };
      const group = (r.group || "").trim();
      if (room.type === "stair" && group) room.group = group;
      return room;
    }),
    doors: doors.map(({ d, a, b }): PlanDoor => {
      const pa = shift(a);
      const pb = shift(b);
      const door: PlanDoor = {
        id: `D${++nDoor}`,
        a: pa,
        b: pb,
        width: r3(Math.hypot(pb[0] - pa[0], pb[1] - pa[1])),
        fireDoor: !!d.fireDoor,
        state: d.state === "closed" || d.state === "propped" ? d.state : "open",
      };
      const name = (d.name || "").trim();
      if (name) door.name = name;
      return door;
    }),
  }));

  return {
    version: "plan/v0",
    id: s.id.trim(),
    name: s.name.trim() || s.id.trim(),
    source: "trace",
    credits: s.credits.trim(),
    floors: planFloors,
  };
}

// ---------------------------------------------------------------- checks

const MIN_ROOM_AREA = 1; // m2
const MIN_VERTICES = 3;
const DOOR_PROBE = 0.5; // m: the normalizer looks this far to each side of a door's midpoint
const MIN_STAIR_OVERLAP = 0.5;

type Box = [number, number, number, number]; // minX, minY, maxX, maxY

function boxOf(points: Pt[]): Box {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

/** Overlap of two boxes as a share of the smaller one (1 when either is flat). */
function boxOverlap(a: Box, b: Box): number {
  const area = (r: Box) => (r[2] - r[0]) * (r[3] - r[1]);
  const smaller = Math.min(area(a), area(b));
  if (!(smaller > 1e-9)) return 1;
  const w = Math.min(a[2], b[2]) - Math.max(a[0], b[0]);
  const h = Math.min(a[3], b[3]) - Math.max(a[1], b[1]);
  return w > 0 && h > 0 ? (w * h) / smaller : 0;
}

/** The first room containing the point, as the normalizer picks it. */
function roomAt(rooms: PlanRoom[], p: Pt): PlanRoom | null {
  for (const r of rooms) if (pointInPolygon(p, r.polygon)) return r;
  return null;
}

/**
 * Problems that would leave a plan unusable ("error:" lines) or suspicious ("warning:" lines);
 * errors come first. The door test mirrors buildings.normalize: it looks at the rooms containing
 * midpoint +- 0.5 * normal; none is an error, one means an exterior door, two an interior door.
 */
export function validatePlan(p: PlanV0): string[] {
  const errors: string[] = [];
  const warnings: string[] = [];
  const error = (msg: string) => {
    errors.push(`error: ${msg}`);
  };
  const warning = (msg: string) => {
    warnings.push(`warning: ${msg}`);
  };
  const floors = [...p.floors].sort((a, b) => a.level - b.level);

  // floors, rooms and doors each need ids that are unique over the whole building
  const seen = new Set<string>();
  const reported = new Set<string>();
  const claim = (kind: string, id: string, where: string) => {
    const key = `${kind}\n${id}`;
    if (!seen.has(key)) seen.add(key);
    else if (!reported.has(key)) {
      reported.add(key);
      error(`duplicate ${kind} id "${id}"${where}`);
    }
  };

  const groups = new Map<string, Map<number, Pt[]>>(); // stair group -> floor index -> vertices
  let exterior = 0;

  floors.forEach((f, k) => {
    claim("floor", f.id, "");

    for (const r of f.rooms) {
      claim("room", r.id, ` on ${f.id}`);
      const label = `room ${r.id}${r.name ? ` "${r.name}"` : ""} (${f.id})`;
      if (r.polygon.length < MIN_VERTICES) {
        error(`${label} has ${r.polygon.length} vertices; a room needs at least ${MIN_VERTICES}`);
      } else if (polygonArea(r.polygon) < MIN_ROOM_AREA - 1e-9) {
        const m2 = Math.round(polygonArea(r.polygon) * 100) / 100;
        error(`${label} is only ${m2} m2; a room needs at least ${MIN_ROOM_AREA} m2`);
      }
      if (r.type !== "stair") continue;
      const group = (r.group || "").trim();
      if (!group) {
        error(`stair ${label} has no group; give it one (for example "SA") and use it on every floor`);
        continue;
      }
      const byFloor = groups.get(group) ?? new Map<number, Pt[]>();
      groups.set(group, byFloor);
      byFloor.set(k, [...(byFloor.get(k) ?? []), ...r.polygon]);
    }

    for (const d of f.doors) {
      claim("door", d.id, ` on ${f.id}`);
      const label = `door ${d.id} (${f.id})`;
      const len = Math.hypot(d.b[0] - d.a[0], d.b[1] - d.a[1]);
      if (!(len > 1e-9)) {
        error(`${label} has no width: its two ends are the same point`);
        continue;
      }
      const n: Pt = [-(d.b[1] - d.a[1]) / len, (d.b[0] - d.a[0]) / len]; // across the wall
      const mid: Pt = [(d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2];
      const side = (sign: number) =>
        roomAt(f.rooms, [mid[0] + sign * DOOR_PROBE * n[0], mid[1] + sign * DOOR_PROBE * n[1]]);
      const neg = side(-1);
      const pos = side(1);
      const named = (d.name || "").trim() !== "";
      if (!neg && !pos) {
        error(`${label} is not on a wall: there is no room on either side of it`);
      } else if (!neg || !pos) {
        exterior += 1;
        if (!named) {
          warning(`exterior ${label} has no name, so the exit shows up as "${d.id}"; name it, for example "Main entrance"`);
        }
      } else if (neg === pos) {
        warning(`${label} has the same room (${neg.id}) on both sides, so it is not on a wall`);
      } else if (named) {
        warning(`${label} is named "${d.name}" but is not in an outside wall; the name is ignored`);
      }
    }
  });

  if (exterior === 0) {
    error("no exterior door: put a door in an outside wall, or nobody can leave the building");
  }

  // a stair group must be on every floor of a multi-floor plan, and line up from floor to floor
  for (const [group, byFloor] of groups) {
    if (floors.length > 1) {
      const on = floors.filter((_, k) => byFloor.has(k)).map((f) => f.id);
      const off = floors.filter((_, k) => !byFloor.has(k)).map((f) => f.id);
      if (off.length > 0) {
        error(`stair group "${group}" is on ${on.join(", ")} but not on ${off.join(", ")}; use the same group on every floor`);
      }
    }
    floors.forEach((f, k) => {
      const below = floors[k - 1];
      const here = byFloor.get(k);
      const there = byFloor.get(k - 1);
      if (!below || !here || !there) return;
      const share = boxOverlap(boxOf(there), boxOf(here));
      if (share < MIN_STAIR_OVERLAP) {
        warning(
          `stair group "${group}" overlaps only ${Math.round(share * 100)}% between ${below.id} and ${f.id}; ` +
            "are the floors lined up (same reference point)?",
        );
      }
    });
  }

  return [...errors, ...warnings];
}

/**
 * Problems in the trace itself, before it is exported: a floor with shapes but no scale (its
 * rooms would all collapse to a point), and floors where only some have a reference point.
 */
export function validateTrace(s: TraceState): string[] {
  const out: string[] = [];
  const someRef = s.floors.some((f) => f.ref);
  for (const f of s.floors) {
    const name = f.name && f.name !== f.id ? `${f.id} "${f.name}"` : f.id;
    if (floorScale(f) <= 0 && f.rooms.length + f.doors.length > 0) {
      out.push(`error: floor ${name} has no scale; click two points a known distance apart and type the distance in meters`);
    }
    if (s.floors.length > 1 && someRef && !f.ref) {
      out.push(`warning: floor ${name} has no reference point but another floor does; mark the same physical point on every floor so they line up`);
    }
  }
  return out;
}
