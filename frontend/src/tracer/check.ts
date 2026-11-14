// Checks for the tracer's geometry, export and validation. No framework: ok() throws.
//
//   cd frontend && npx --yes tsx src/tracer/check.ts
//
// stdout: the good two-floor fixture, exported as plan/v0 JSON (tools/check_tracer.py feeds it to
// the normalizer); stderr: "tracer check OK". Any failed check throws, so the exit code is 1.
import { floorScale, planToPx, pointInPolygon, polygonArea, pxToPlan, scaleFromClicks, snap, snapPoint } from "./geometry";
import type { Pt } from "./geometry";
import { exportPlan, validatePlan, validateTrace } from "./plan";
import { aiRooms, sentToPx } from "./edit";
import type { DoorState, PlanDoor, PlanV0, RoomType, TraceDoor, TraceFloor, TraceRoom, TraceState } from "./plan";

function ok(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(`tracer check failed: ${msg}`);
}

function must<T>(v: T | null | undefined, what: string): T {
  ok(v !== null && v !== undefined, `missing ${what}`);
  return v;
}

const near = (a: number, b: number, eps = 1e-9) => Math.abs(a - b) <= eps;
const nearPt = (a: Pt, b: Pt, eps = 1e-9) => near(a[0], b[0], eps) && near(a[1], b[1], eps);
const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x)) as T;
const show = (x: unknown) => JSON.stringify(x);

function blankFloor(over: Partial<TraceFloor> = {}): TraceFloor {
  return { id: "F1", name: "F1", level: 0, imageW: 800, imageH: 600, scale: null, ref: null, rooms: [], doors: [], ...over };
}

// ---------------------------------------------------------------- scale

ok(near(scaleFromClicks([0, 0], [100, 0], 5), 0.05, 1e-12), "100 px = 5 m must be 0.05 m/px");
ok(near(scaleFromClicks([100, 50], [220, 210], 10), 0.05, 1e-12), "a diagonal click pair, 200 px = 10 m");
ok(scaleFromClicks([3, 3], [3, 3], 5) === 0, "two equal clicks give no scale");
ok(scaleFromClicks([0, 0], [100, 0], 0) === 0, "a distance of 0 m gives no scale");

// ---------------------------------------------------------------- pixels <-> plan

const H = 600;
const f0 = blankFloor({ imageH: H, scale: { p1: [0, 0], p2: [100, 0], meters: 5 } });
ok(nearPt(pxToPlan([0, H], f0), [0, 0]), `pxToPlan([0, H]) must be [0, 0], got ${show(pxToPlan([0, H], f0))}`);
ok(nearPt(pxToPlan([100, H - 100], f0), [5, 5]), "100 px right and 100 px up is 5 m east, 5 m north");
ok(nearPt(pxToPlan([0, 0], f0), [0, 30]), "the top-left pixel is 30 m north of the bottom-left corner");

const f1 = blankFloor({ imageH: H, scale: f0.scale, ref: [200, 300] });
ok(nearPt(pxToPlan([200, 300], f1), [0, 0]), "a marked reference point is the plan origin");
ok(nearPt(pxToPlan([300, 200], f1), [5, 5]), "x grows to the right and y grows up from the reference point");
for (const f of [f0, f1]) {
  for (const p of [[0, 0], [123.5, 456.25], [799, 599]] as Pt[]) {
    ok(nearPt(planToPx(pxToPlan(p, f), f), p), `planToPx must invert pxToPlan at ${show(p)}`);
  }
}
ok(floorScale(blankFloor()) === 0, "a floor without a scale has scale 0");

ok(snap(1.13) === 1.25, `snap(1.13) must be 1.25, got ${snap(1.13)}`);
ok(snap(1.12) === 1, `snap(1.12) must be 1, got ${snap(1.12)}`);
ok(Object.is(snap(-0.1), 0), "snap never returns -0");
ok(
  nearPt(snapPoint([101, 497], f0), [100, 495]),
  `snapPoint([101, 497]) must be [100, 495], got ${show(snapPoint([101, 497], f0))}`,
);
for (const f of [f0, f1]) {
  const [x, y] = pxToPlan(snapPoint([333.3, 217.7], f), f);
  ok(near(x / 0.25, Math.round(x / 0.25)) && near(y / 0.25, Math.round(y / 0.25)), "a snapped point sits on the 0.25 m grid");
}
ok(nearPt(snapPoint([101, 497], blankFloor()), [101, 497]), "no scale, no grid: the point stays where it is");

// polygon helpers: the door test relies on shapely's covers(), so boundary points count as inside
const box: Pt[] = [[0, 0], [4, 0], [4, 3], [0, 3]];
const ell: Pt[] = [[0, 0], [4, 0], [4, 1], [1, 1], [1, 3], [0, 3]];
ok(polygonArea(box) === 12 && polygonArea([...box].reverse()) === 12, "the area of a 4 x 3 box, whichever way it winds");
ok(polygonArea(ell) === 6, "the area of an L");
ok(pointInPolygon([2, 1.5], box) && !pointInPolygon([2, 3.5], box) && !pointInPolygon([-0.01, 1], box), "inside and outside a box");
ok(pointInPolygon([4, 1.5], box) && pointInPolygon([2, 0], box), "a point on an edge is inside");
ok(pointInPolygon([0, 0], box) && pointInPolygon([4, 3], box), "a vertex is inside");
ok(pointInPolygon([0.5, 2], ell) && !pointInPolygon([2, 2], ell) && pointInPolygon([3, 0.5], ell), "a concave L");

// ---------------------------------------------------------------- a good two-floor fixture
// Built in building meters, then drawn into two images with different sizes, scales and
// reference pixels. P is the one physical point marked as the reference on both floors.

const P: Pt = [18, 6]; // the SW corner of stair A
interface Spec {
  id: string;
  level: number;
  imageW: number;
  imageH: number;
  pxPerM: number;
  ref: Pt; // where P is in this floor's image
  scale: { p1: Pt; p2: Pt; meters: number }; // the two clicks agree with pxPerM
}
const SPEC1: Spec = { id: "F1", level: 0, imageW: 640, imageH: 480, pxPerM: 20, ref: [400, 300], scale: { p1: [100, 50], p2: [220, 210], meters: 10 } };
const SPEC2: Spec = { id: "F2", level: 1, imageW: 800, imageH: 700, pxPerM: 25, ref: [500, 450], scale: { p1: [60, 40], p2: [300, 360], meters: 16 } };
const toPx = (s: Spec, p: Pt): Pt => [s.ref[0] + s.pxPerM * (p[0] - P[0]), s.ref[1] - s.pxPerM * (p[1] - P[1])];

interface RoomSpec {
  name: string;
  type: RoomType;
  poly: Pt[];
  group?: string;
}
interface DoorSpec {
  a: Pt;
  b: Pt;
  fireDoor?: boolean;
  state?: DoorState;
  name?: string;
}
const rect = (x0: number, y0: number, x1: number, y1: number): Pt[] => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
const hDoor = (cx: number, y: number, w = 0.9, more: Partial<DoorSpec> = {}): DoorSpec => ({ a: [cx - w / 2, y], b: [cx + w / 2, y], ...more });
const vDoor = (x: number, cy: number, w = 0.9, more: Partial<DoorSpec> = {}): DoorSpec => ({ a: [x, cy - w / 2], b: [x, cy + w / 2], ...more });

const stairs: RoomSpec[] = [
  { name: "Stair A", type: "stair", poly: rect(18, 6, 22, 9), group: "SA" },
  { name: "Stair B", type: "stair", poly: rect(0, 6, 4, 9), group: "SB" },
];
const roomsGround: RoomSpec[] = [
  { name: "Lobby", type: "lobby", poly: rect(4, 0, 10, 6) },
  { name: "Office B", type: "office", poly: rect(10, 0, 18, 6) },
  { name: "Corridor", type: "corridor", poly: rect(4, 6, 18, 9) },
  { name: "Office C", type: "office", poly: rect(4, 9, 12, 15) },
  { name: "Lab D", type: "lab", poly: rect(12, 9, 18, 15) },
  ...stairs,
];
const roomsUpper: RoomSpec[] = [
  { name: "Office E", type: "office", poly: rect(4, 0, 10, 6) },
  { name: "Meeting F", type: "office", poly: rect(10, 0, 18, 6) },
  { name: "Corridor 2", type: "corridor", poly: rect(4, 6, 18, 9) },
  { name: "Küche G", type: "kitchen", poly: rect(4, 9, 12, 15) }, // non-ASCII on purpose: UTF-8 end to end
  { name: "Restroom H", type: "restroom", poly: rect(12, 9, 18, 15) },
  ...stairs,
];
const inner: DoorSpec[] = [
  hDoor(7, 6),
  hDoor(14, 6),
  hDoor(8, 9),
  hDoor(15, 9),
  vDoor(4, 7.5, 0.9, { fireDoor: true, state: "closed" }),
  vDoor(18, 7.5, 0.9, { fireDoor: true, state: "closed" }),
];
const doorsGround: DoorSpec[] = [
  ...inner,
  hDoor(7, 0, 1.8, { name: "Main entrance" }),
  vDoor(22, 7.5, 1, { state: "closed", name: "East stair exit" }),
];
const FLOORS: Array<{ spec: Spec; rooms: RoomSpec[]; doors: DoorSpec[] }> = [
  { spec: SPEC1, rooms: roomsGround, doors: doorsGround },
  { spec: SPEC2, rooms: roomsUpper, doors: inner },
];

function traceFloor(spec: Spec, rooms: RoomSpec[], doors: DoorSpec[]): TraceFloor {
  return {
    id: spec.id,
    name: `Floor ${spec.level + 1}`,
    level: spec.level,
    imageW: spec.imageW,
    imageH: spec.imageH,
    scale: spec.scale,
    ref: spec.ref,
    // trace ids repeat across floors on purpose: the export numbers everything again
    rooms: rooms.map((r, i): TraceRoom => ({
      id: `r${i}`,
      name: r.name,
      type: r.type,
      polygon: r.poly.map((p) => toPx(spec, p)),
      ...(r.group ? { group: r.group } : {}),
    })),
    doors: doors.map((d, i): TraceDoor => ({
      id: `d${i}`,
      a: toPx(spec, d.a),
      b: toPx(spec, d.b),
      fireDoor: d.fireDoor ?? false,
      state: d.state ?? "open",
      ...(d.name ? { name: d.name } : {}),
    })),
  };
}

// the upper floor first: the export must put the floors in level order
const state: TraceState = {
  id: "tracer-check",
  name: "Tracer check fixture",
  credits: "Synthetic fixture for the tracer check; free to use.",
  floors: [...FLOORS].reverse().map((f) => traceFloor(f.spec, f.rooms, f.doors)),
};

// ---------------------------------------------------------------- export

const before = show(state);
const plan = exportPlan(state);
ok(show(state) === before, "exportPlan must not change the trace it is given");
ok(plan.version === "plan/v0", `version must be plan/v0, got ${plan.version}`);
ok(plan.source === "trace", "source must be trace");
ok(plan.id === "tracer-check" && plan.credits.length > 0, "id and credits come from the trace");
ok(plan.floors.map((f) => f.id).join() === "F1,F2", "floors are exported in level order");
for (const f of plan.floors) {
  ok(f.height === 3.5 && f.elevation === f.level * 3.5, `${f.id}: height 3.5 and elevation = level * height`);
}

const roomIds = plan.floors.flatMap((f) => f.rooms.map((r) => r.id));
const doorIds = plan.floors.flatMap((f) => f.doors.map((d) => d.id));
const seq = (prefix: string, n: number) => Array.from({ length: n }, (_, i) => `${prefix}${i + 1}`).join();
ok(roomIds.join() === seq("R", 14), `room ids must run R1..R14 over both floors, got ${roomIds.join()}`);
ok(doorIds.join() === seq("D", 14), `door ids must run D1..D14 over both floors, got ${doorIds.join()}`);

// every vertex comes back at the building meters it was drawn from (min x and y are 0 already, so
// the export's shift just undoes the reference point); doors keep their ends and width = |ab|
FLOORS.forEach(({ rooms, doors }, k) => {
  const pf = must(plan.floors[k], `exported floor ${k}`);
  ok(pf.rooms.length === rooms.length && pf.doors.length === doors.length, `${pf.id}: room and door counts`);
  rooms.forEach((r, i) => {
    const pr = must(pf.rooms[i], `${pf.id} room ${i}`);
    ok(pr.name === r.name && pr.type === r.type && pr.group === r.group, `${pf.id}/${pr.id}: name, type and group`);
    ok(
      pr.polygon.length === r.poly.length && r.poly.every((p, j) => nearPt(must(pr.polygon[j], "vertex"), p)),
      `${pf.id}/${pr.id} "${r.name}": polygon ${show(pr.polygon)} must be ${show(r.poly)}`,
    );
  });
  doors.forEach((d, i) => {
    const pd = must(pf.doors[i], `${pf.id} door ${i}`);
    ok(nearPt(pd.a, d.a, 1e-6) && nearPt(pd.b, d.b, 1e-6), `${pf.id}/${pd.id}: ends ${show([pd.a, pd.b])} must be ${show([d.a, d.b])}`);
    ok(near(pd.width, Math.hypot(pd.b[0] - pd.a[0], pd.b[1] - pd.a[1]), 1e-6), `${pf.id}/${pd.id}: width = |ab|`);
    ok(pd.fireDoor === (d.fireDoor ?? false) && pd.state === (d.state ?? "open") && pd.name === d.name, `${pf.id}/${pd.id}: flags and name`);
  });
});

// one physical point marked as the reference on both floors, at different pixels and scales,
// exports to equal coordinates: stair A, whose SW corner is that point, is identical on both
ok(show(SPEC1.ref) !== show(SPEC2.ref) && SPEC1.pxPerM !== SPEC2.pxPerM, "the two floors must differ in reference pixel and scale");
const stairA = plan.floors.map((f) => must(f.rooms.find((r) => r.group === "SA"), `stair A on ${f.id}`));
ok(
  show(stairA[0]?.polygon) === show(stairA[1]?.polygon),
  `stair A must export to equal coordinates on both floors, got ${show(stairA.map((r) => r.polygon))}`,
);
ok(stairA.every((r) => nearPt(must(r.polygon[0], "stair A corner"), P)), "the reference point exports to the same place on both floors");

// unsnapped vertices (an AI draft), a repeated closing point and an off-origin building:
// snapped to 0.25 m, one vertex per corner, shifted so min x and y are 0
const miniFloor = blankFloor({
  imageH: H,
  scale: f0.scale,
  // (3, 2) (9.1, 2) (9.1, 6.9) (3, 6.9) and (3, 2) again, in meters from the bottom-left corner
  rooms: [{ id: "a", name: "A", type: "office", polygon: [[60, 560], [182, 560], [182, 462], [60, 462], [60, 560]] }],
});
const mini = exportPlan({ id: "mini", name: "", credits: "", floors: [miniFloor] });
const miniPoly = must(mini.floors[0], "mini floor").rooms[0]?.polygon;
ok(show(miniPoly) === show([[0, 0], [6, 0], [6, 5], [0, 5]]), `snap, dedupe and shift, got ${show(miniPoly)}`);
ok(mini.name === "mini" && exportPlan({ id: "x", name: "", credits: "", floors: [] }).floors.length === 0, "an empty trace exports without crashing");

// ---------------------------------------------------------------- validation

ok(validatePlan(plan).length === 0, `the good fixture must validate clean, got ${show(validatePlan(plan))}`);
ok(validateTrace(state).length === 0, `the good trace must validate clean, got ${show(validateTrace(state))}`);

const floorOf = (p: PlanV0, id: string) => must(p.floors.find((f) => f.id === id), `floor ${id}`);
const roomOf = (p: PlanV0, floorId: string, i: number) => must(floorOf(p, floorId).rooms[i], `${floorId} room ${i}`);
const doorOf = (p: PlanV0, floorId: string, i: number) => must(floorOf(p, floorId).doors[i], `${floorId} door ${i}`);
const entrance = (p: PlanV0) => must(floorOf(p, "F1").doors.find((d) => d.name === "Main entrance"), "the main entrance");
const stairOn = (p: PlanV0, floorId: string, group: string) =>
  must(floorOf(p, floorId).rooms.find((r) => r.group === group), `stair ${group} on ${floorId}`);
const slide = (d: PlanDoor, dx: number, dy: number) => {
  d.a = [d.a[0] + dx, d.a[1] + dy];
  d.b = [d.b[0] + dx, d.b[1] + dy];
};

// Each fault is made on a copy of the good plan; validatePlan must return a line of the given
// kind that has all of the given words in it.
interface Fault {
  what: string;
  make: (p: PlanV0) => void;
  kind: "error:" | "warning:";
  words: string[];
}
const faults: Fault[] = [
  // the three the task names: no exit, a stair group on one floor, a door off its wall
  { what: "no exterior door", kind: "error:", words: ["no exterior door"],
    make: (p) => { for (const f of p.floors) f.doors = f.doors.filter((d) => !d.name); } },
  { what: "a renamed stair group", kind: "error:", words: ['group "SA"', "F2"],
    make: (p) => { stairOn(p, "F2", "SA").group = "SX"; } },
  { what: "the renamed group is alone too", kind: "error:", words: ['group "SX"', "F1"],
    make: (p) => { stairOn(p, "F2", "SA").group = "SX"; } },
  { what: "an exterior door moved off its wall", kind: "error:", words: ["door D7", "not on a wall"],
    make: (p) => { slide(entrance(p), 0, -3); } },
  { what: "an interior door moved off its wall", kind: "error:", words: ["door D1", "not on a wall"],
    make: (p) => { slide(doorOf(p, "F1", 0), 40, 0); } },
  // more
  { what: "a door pushed into the middle of a room", kind: "warning:", words: ["door D1", "same room (R1)"],
    make: (p) => { slide(doorOf(p, "F1", 0), 0, -2); } },
  { what: "a door with no width", kind: "error:", words: ["door D1", "no width"],
    make: (p) => { const d = doorOf(p, "F1", 0); d.b = [d.a[0], d.a[1]]; } },
  { what: "a duplicate room id", kind: "error:", words: ['duplicate room id "R1"'],
    make: (p) => { roomOf(p, "F2", 0).id = "R1"; } },
  { what: "a duplicate door id", kind: "error:", words: ['duplicate door id "D1"'],
    make: (p) => { doorOf(p, "F2", 0).id = "D1"; } },
  { what: "a duplicate floor id", kind: "error:", words: ['duplicate floor id "F1"'],
    make: (p) => { must(p.floors[1], "floor 1").id = "F1"; } },
  { what: "a room with 2 vertices", kind: "error:", words: ["room R1", "2 vertices"],
    make: (p) => { const r = roomOf(p, "F1", 0); r.polygon = r.polygon.slice(0, 2); } },
  { what: "a room under 1 m2", kind: "error:", words: ["room R1", "0.25 m2"],
    make: (p) => { roomOf(p, "F1", 0).polygon = rect(0, 0, 0.5, 0.5); } },
  { what: "a stair room without a group", kind: "error:", words: ["stair room", "no group"],
    make: (p) => { delete stairOn(p, "F1", "SA").group; } },
  { what: "an exterior door without a name", kind: "warning:", words: ["exterior door D7", "no name"],
    make: (p) => { delete entrance(p).name; } },
  { what: "a named interior door", kind: "warning:", words: ["door D1", "Side door", "outside wall"],
    make: (p) => { doorOf(p, "F1", 0).name = "Side door"; } },
  { what: "stairs that do not line up", kind: "warning:", words: ['group "SA"', "25%", "F1 and F2"],
    make: (p) => { const r = stairOn(p, "F2", "SA"); r.polygon = r.polygon.map(([x, y]): Pt => [x + 3, y]); } },
];
for (const { what, make, kind, words } of faults) {
  const p = clone(plan);
  make(p);
  const got = validatePlan(p);
  ok(
    got.some((l) => l.startsWith(kind) && words.every((w) => l.includes(w))),
    `${what}: expected an ${kind} line with ${show(words)}, got ${show(got)}`,
  );
}

// errors come before warnings
const mixed = clone(plan);
delete entrance(mixed).name;
roomOf(mixed, "F2", 0).id = "R1";
const lines = validatePlan(mixed);
const firstWarning = lines.findIndex((l) => l.startsWith("warning:"));
ok(firstWarning > 0 && lines.slice(firstWarning).every((l) => l.startsWith("warning:")), `errors must come before warnings, got ${show(lines)}`);

// the trace itself: a floor with shapes but no scale, and a reference point on only one floor
const unscaled = clone(state);
must(unscaled.floors[0], "floor 0").scale = null;
ok(validateTrace(unscaled).some((l) => l.startsWith("error:") && l.includes("no scale")), `no scale must be an error, got ${show(validateTrace(unscaled))}`);
const noRef = clone(state);
must(noRef.floors[0], "floor 0").ref = null;
ok(validateTrace(noRef).some((l) => l.startsWith("warning:") && l.includes("reference point")), `a missing reference point must warn, got ${show(validateTrace(noRef))}`);

// ---------------------------------------------------------------- the AI first pass
// POST /api/trace/propose answers in meters from the sent image's bottom-left corner, y up. Here
// the sent image is the 800 x 600 px floor image halved (400 x 300 px at 0.1 m per pixel), so a
// point (x, y) m comes back at floor pixels (x / 0.05, 600 - y / 0.05).
const aiFloor = blankFloor({ imageW: 800, imageH: 600, scale: { p1: [0, 0], p2: [100, 0], meters: 5 } });
const sent = { w: 400, h: 300, metersPerPixel: 0.1 };
ok(nearPt(sentToPx([0, 0], aiFloor, sent), [0, 600]), "the AI's origin is the floor image's bottom-left corner");
ok(nearPt(sentToPx([40, 30], aiFloor, sent), [800, 0]), `the AI's far corner is the top-right pixel, got ${show(sentToPx([40, 30], aiFloor, sent))}`);
const proposed = [
  { id: "AI1", name: "Office", type: "office", polygon: [[2, 1], [10, 1], [10, 6], [2, 6]] },
  { id: "AI2", name: "Odd", type: "kitchenette", polygon: [[12, 1], [20, 1], [20, 6], [12, 6], [12, 1]] },
  { id: "AI3", name: "Speck", type: "storage", polygon: [[30, 1], [30.5, 1], [30.5, 1.5]] },
  { id: "AI4", name: "Line", type: "office", polygon: [[1, 1], [2, 2]] },
  "junk",
];
const imported = aiRooms(aiFloor, proposed, sent);
ok(imported.rooms.length === 2 && imported.unusable === 3 && imported.overlapping === 0, `2 rooms in, 3 unusable, got ${show(imported)}`);
const [aiOffice, aiOdd] = [must(imported.rooms[0], "the AI office"), must(imported.rooms[1], "the AI room of an unknown type")];
ok(show(aiOffice.polygon) === show([[40, 580], [200, 580], [200, 480], [40, 480]]), `AI room in floor pixels, got ${show(aiOffice.polygon)}`);
ok(aiOffice.ai === true && aiOffice.name === "Office" && aiOffice.type === "office", `AI rooms are marked ai, got ${show(aiOffice)}`);
ok(aiOdd.type === "other" && aiOdd.polygon.length === 4, `an unknown type becomes other, one point per corner, got ${show(aiOdd)}`);
// a floor whose reference point is off the image's grid: AI vertices land on the floor's own grid
const aiRefFloor = { ...aiFloor, ref: [13, 597] as Pt };
for (const r of aiRooms(aiRefFloor, proposed, sent).rooms) {
  for (const v of r.polygon) {
    const [x, y] = pxToPlan(v, aiRefFloor);
    ok(near(x / 0.25, Math.round(x / 0.25)) && near(y / 0.25, Math.round(y / 0.25)), `AI vertex ${show(v)} is off the floor's 0.25 m grid`);
  }
}
// a room already traced by hand keeps its place; the floor's earlier AI draft does not count
const traced: TraceRoom = { id: "h1", name: "Hand", type: "office", polygon: [[40, 580], [200, 580], [200, 480], [40, 480]] };
const oldDraft: TraceRoom = { ...aiOdd, id: "old" };
const again = aiRooms({ ...aiFloor, rooms: [traced, oldDraft] }, proposed, sent);
ok(again.rooms.length === 1 && again.overlapping === 1 && again.rooms[0]?.name === "Odd", `skip only rooms traced by hand, got ${show(again)}`);
ok(aiRooms(blankFloor(), proposed, sent).rooms.length === 0, "no scale, no AI rooms");

// ---------------------------------------------------------------- report

console.log(JSON.stringify(plan, null, 1));
console.error("tracer check OK");
