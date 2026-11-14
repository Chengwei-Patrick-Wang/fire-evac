// Editing helpers for the tracer page: doors on room edges, door sides (as the normalizer sees
// them), export ids, the page-level checks, and reading a saved trace back. Pure TypeScript: no
// React, no DOM.
import { floorScale, planToPx, pointInPolygon, polygonArea, pxToPlan, snap, snapPoint } from "./geometry";
import type { Pt } from "./geometry";
import { ROOM_TYPES, exportPlan, validatePlan, validateTrace } from "./plan";
import type { DoorState, RoomType, TraceDoor, TraceFloor, TraceRoom, TraceScale, TraceState } from "./plan";

export const DOOR_WIDTH = 0.9; // m: a new door
export const EXIT_WIDTH = 1.0; // m: a door once it is named as an exit
export const DOOR_REACH = 0.5; // m: a door click must be this close to a room edge
const SIDE_PROBE = 0.5; // m: buildings.normalize looks this far to each side of a door's midpoint

/** Building ids the API accepts (backend/app/store.py SAFE_ID). */
export const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;

const add = (a: Pt, b: Pt): Pt => [a[0] + b[0], a[1] + b[1]];
const sub = (a: Pt, b: Pt): Pt => [a[0] - b[0], a[1] - b[1]];
const mul = (a: Pt, k: number): Pt => [a[0] * k, a[1] * k];
const dot = (a: Pt, b: Pt) => a[0] * b[0] + a[1] * b[1];
const norm = (a: Pt) => Math.hypot(a[0], a[1]);

/** Distance from p to the segment ab. */
export function segDist(p: Pt, a: Pt, b: Pt): number {
  const ab = sub(b, a);
  const l2 = dot(ab, ab);
  const t = l2 > 0 ? Math.min(1, Math.max(0, dot(sub(p, a), ab) / l2)) : 0;
  return norm(sub(p, add(a, mul(ab, t))));
}

/** A room polygon in plan meters, snapped to the grid as exportPlan snaps it. */
function planPoly(r: TraceRoom, f: TraceFloor): Pt[] {
  return r.polygon.map((p): Pt => {
    const [x, y] = pxToPlan(p, f);
    return [snap(x), snap(y)];
  });
}

/**
 * A new door's ends (image pixels) on the room edge nearest the click, or null when no edge is
 * within DOOR_REACH meters (or the floor has no scale). The click goes through snapPoint, is
 * projected onto that edge and becomes the door's center; the door runs along the edge and stays
 * inside it when the edge is long enough. Of two coinciding edges (rooms drawn edge to edge) the
 * shorter one wins, so a door into an office stays within the office's wall.
 */
export function placeDoor(f: TraceFloor, click: Pt, width = DOOR_WIDTH): { a: Pt; b: Pt } | null {
  if (!(floorScale(f) > 0)) return null;
  const p = pxToPlan(click, f);
  const c0 = pxToPlan(snapPoint(click, f), f);
  let best: { a: Pt; b: Pt; d: number; l: number } | null = null;
  for (const r of f.rooms) {
    const poly = r.polygon.map((q) => pxToPlan(q, f));
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i];
      const b = poly[(i + 1) % poly.length];
      if (!a || !b) continue;
      const l = norm(sub(b, a));
      if (l < 1e-6) continue;
      const d = segDist(p, a, b);
      if (d > DOOR_REACH) continue;
      if (!best || d < best.d - 1e-6 || (Math.abs(d - best.d) <= 1e-6 && l < best.l)) best = { a, b, d, l };
    }
  }
  if (!best) return null;
  const { a, l } = best;
  const u = mul(sub(best.b, a), 1 / l);
  let t = dot(sub(c0, a), u);
  t = l >= width ? Math.min(Math.max(t, width / 2), l - width / 2) : l / 2;
  const c = add(a, mul(u, t));
  return { a: planToPx(add(c, mul(u, -width / 2)), f), b: planToPx(add(c, mul(u, width / 2)), f) };
}

/** A door's width in meters (0 without a scale). */
export function doorWidth(f: TraceFloor, d: { a: Pt; b: Pt }): number {
  return norm(sub(d.b, d.a)) * floorScale(f);
}

/** The door resized to `width` meters about its center, in the same direction. */
export function resizeDoor(f: TraceFloor, d: { a: Pt; b: Pt }, width: number): { a: Pt; b: Pt } {
  const s = floorScale(f);
  const lpx = norm(sub(d.b, d.a));
  if (!(s > 0) || !(lpx > 0) || !(width > 0)) return { a: d.a, b: d.b };
  const u = mul(sub(d.b, d.a), 1 / lpx);
  const c = mul(add(d.a, d.b), 0.5);
  const half = width / s / 2;
  return { a: add(c, mul(u, -half)), b: add(c, mul(u, half)) };
}

/** exterior: a room on one side only; interior: different rooms on both sides; same: one room
 * on both sides; none: no room on either side (or no scale). */
export type DoorKind = "exterior" | "interior" | "same" | "none";

/** Every door's kind on a floor, by the test buildings.normalize and validatePlan use. */
export function doorKinds(f: TraceFloor): Map<string, DoorKind> {
  const out = new Map<string, DoorKind>();
  const ok = floorScale(f) > 0;
  const rooms = ok ? f.rooms.map((r) => planPoly(r, f)) : [];
  for (const d of f.doors) {
    if (!ok) {
      out.set(d.id, "none");
      continue;
    }
    const a = pxToPlan(d.a, f);
    const b = pxToPlan(d.b, f);
    const l = norm(sub(b, a));
    if (!(l > 1e-9)) {
      out.set(d.id, "none");
      continue;
    }
    const n: Pt = [-(b[1] - a[1]) / l, (b[0] - a[0]) / l];
    const mid = mul(add(a, b), 0.5);
    const side = (sign: number) => rooms.findIndex((poly) => pointInPolygon(add(mid, mul(n, sign * SIDE_PROBE)), poly));
    const neg = side(-1);
    const pos = side(1);
    out.set(d.id, neg < 0 && pos < 0 ? "none" : neg < 0 || pos < 0 ? "exterior" : neg === pos ? "same" : "interior");
  }
  return out;
}

/** Area of a traced room in m2 (0 without a scale). */
export function roomArea(f: TraceFloor, r: TraceRoom): number {
  return floorScale(f) > 0 ? polygonArea(planPoly(r, f)) : 0;
}

/** Where to put a room's label: its area centroid, or the mean of its vertices. */
export function labelPoint(poly: Pt[]): Pt {
  let a2 = 0;
  let cx = 0;
  let cy = 0;
  poly.forEach((p, i) => {
    const q = poly[(i + 1) % poly.length];
    if (!q) return;
    const c = p[0] * q[1] - q[0] * p[1];
    a2 += c;
    cx += (p[0] + q[0]) * c;
    cy += (p[1] + q[1]) * c;
  });
  if (Math.abs(a2) > 1e-9) return [cx / (3 * a2), cy / (3 * a2)];
  const n = Math.max(1, poly.length);
  return [poly.reduce((s, p) => s + p[0], 0) / n, poly.reduce((s, p) => s + p[1], 0) / n];
}

export interface ExportRef {
  kind: "room" | "door";
  floorId: string;
  id: string; // trace-time id
}

/** The ids exportPlan gives rooms (R1...) and doors (D1...), both ways: export id -> trace item,
 * and trace id -> export id. Numbered exactly as exportPlan numbers them. */
export function exportIds(s: TraceState): { byExport: Map<string, ExportRef>; byTrace: Map<string, string> } {
  const byExport = new Map<string, ExportRef>();
  const byTrace = new Map<string, string>();
  let nRoom = 0;
  let nDoor = 0;
  for (const f of [...s.floors].sort((a, b) => a.level - b.level)) {
    for (const r of f.rooms) {
      const id = `R${++nRoom}`;
      byExport.set(id, { kind: "room", floorId: f.id, id: r.id });
      byTrace.set(r.id, id);
    }
  }
  for (const f of [...s.floors].sort((a, b) => a.level - b.level)) {
    for (const d of f.doors) {
      const id = `D${++nDoor}`;
      byExport.set(id, { kind: "door", floorId: f.id, id: d.id });
      byTrace.set(d.id, id);
    }
  }
  return { byExport, byTrace };
}

/** A building id from its name: lower case, ASCII letters and digits joined by "-". */
export function slugify(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/, "");
}

const isError = (m: string) => m.startsWith("error:");

/**
 * Everything the page shows before export, errors first: the page's own checks (id, credits,
 * Public on a UMass trace, floor levels), then validateTrace, then validatePlan on the export.
 * The plan checks are skipped while the trace itself has errors (a floor without a scale
 * exports every room as a point, so they would only repeat that).
 */
export function checkTrace(s: TraceState, isPublic: boolean): string[] {
  const page: string[] = [];
  const id = s.id.trim();
  if (s.floors.length === 0) page.push("error: no floors yet: add a floor with its plan image");
  if (!id) page.push("error: the building needs an id (letters, digits, '.', '-' and '_')");
  else if (!SAFE_ID.test(id)) {
    page.push(`error: building id "${id}" may only use letters, digits, '.', '-' and '_', starting with a letter or digit`);
  }
  if (!s.credits.trim()) {
    page.push("error: credits are required: say where the plan image comes from and under which license");
  }
  if (isPublic) {
    const text = [s.id, s.name, s.credits, ...s.floors.flatMap((f) => [f.name, ...f.rooms.map((r) => r.name), ...f.doors.map((d) => d.name ?? "")])];
    if (text.some((t) => /umass/i.test(t))) {
      page.push("error: this trace mentions UMass, and UMass-derived plans stay private: untick Public");
    }
  }
  const byLevel = new Map<number, string[]>();
  for (const f of s.floors) byLevel.set(f.level, [...(byLevel.get(f.level) ?? []), f.id]);
  for (const [level, ids] of byLevel) {
    if (ids.length > 1) page.push(`warning: floors ${ids.join(", ")} are all level ${level}; give each floor its own level`);
  }
  const trace = validateTrace(s);
  const plan = trace.some(isError) || s.floors.length === 0 ? [] : validatePlan(exportPlan(s));
  const all = [...page, ...trace, ...plan];
  return [...all.filter(isError), ...all.filter((m) => !isError(m))];
}

// ---------------------------------------------------------------- reading a saved trace

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isPt = (v: unknown): v is Pt => Array.isArray(v) && v.length === 2 && isNum(v[0]) && isNum(v[1]);
const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);
const obj = (v: unknown): Record<string, unknown> | null =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;

function readScale(v: unknown): TraceScale | null {
  const o = obj(v);
  if (!o || !isPt(o.p1) || !isPt(o.p2) || !isNum(o.meters) || o.meters <= 0) return null;
  return { p1: [o.p1[0], o.p1[1]], p2: [o.p2[0], o.p2[1]], meters: o.meters };
}

function readRoom(v: unknown, k: number): TraceRoom | null {
  const o = obj(v);
  if (!o || !Array.isArray(o.polygon)) return null;
  const polygon = o.polygon.filter(isPt).map((p): Pt => [p[0], p[1]]);
  if (polygon.length < 3) return null;
  const type = str(o.type, "other");
  const room: TraceRoom = {
    id: str(o.id) || `r-load-${k}`,
    name: str(o.name),
    type: (ROOM_TYPES as readonly string[]).includes(type) ? (type as RoomType) : "other",
    polygon,
  };
  if (typeof o.group === "string") room.group = o.group;
  if (o.ai === true) room.ai = true;
  return room;
}

function readDoor(v: unknown, k: number): TraceDoor | null {
  const o = obj(v);
  if (!o || !isPt(o.a) || !isPt(o.b)) return null;
  const state = str(o.state, "open");
  const door: TraceDoor = {
    id: str(o.id) || `d-load-${k}`,
    a: [o.a[0], o.a[1]],
    b: [o.b[0], o.b[1]],
    fireDoor: o.fireDoor === true,
    state: (state === "closed" || state === "propped" ? state : "open") as DoorState,
  };
  if (typeof o.name === "string" && o.name) door.name = o.name;
  return door;
}

/** A saved trace (the autosave, or a file from Save trace) checked field by field; null when it
 * is not a trace at all. Broken rooms and doors are dropped; missing fields get defaults. */
export function readTrace(raw: unknown): TraceState | null {
  const o = obj(raw);
  if (!o || !Array.isArray(o.floors)) return null;
  if (typeof o.version === "string" && o.version !== "trace/v0") return null; // plan/v0 and friends
  const used = new Set<string>();
  const floors: TraceFloor[] = [];
  o.floors.forEach((v, k) => {
    const f = obj(v);
    if (!f || !isNum(f.imageW) || !isNum(f.imageH)) return;
    let id = str(f.id).trim() || `F${k + 1}`;
    while (used.has(id)) id = `${id}b`;
    used.add(id);
    floors.push({
      id,
      name: str(f.name) || id,
      level: isNum(f.level) ? Math.round(f.level) : k,
      imageW: f.imageW,
      imageH: f.imageH,
      scale: readScale(f.scale),
      ref: isPt(f.ref) ? [f.ref[0], f.ref[1]] : null,
      rooms: (Array.isArray(f.rooms) ? f.rooms : []).map(readRoom).filter((r): r is TraceRoom => r !== null),
      doors: (Array.isArray(f.doors) ? f.doors : []).map(readDoor).filter((d): d is TraceDoor => d !== null),
    });
  });
  return { id: str(o.id), name: str(o.name), credits: str(o.credits), floors };
}
