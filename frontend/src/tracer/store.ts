// The tracer's state: A2's TraceState (image pixels) plus 50-step undo and redo, this session's
// floor images, and what the canvas is doing. The trace autosaves, without the images, to
// localStorage["fire-evac-trace"]; an image re-attaches when its floor's image is uploaded again.
import { create } from "zustand";
import type { Pt } from "./geometry";
import type { TraceDoor, TraceFloor, TraceRoom, TraceScale, TraceState } from "./plan";
import { DOOR_WIDTH, EXIT_WIDTH, doorWidth, readTrace, resizeDoor, slugify } from "./edit";

export const STORAGE_KEY = "fire-evac-trace";
export const HISTORY = 50; // undo steps
const MERGE_MS = 1500; // edits with the same key this close together are one undo step

export type Tool = "select" | "scale" | "ref" | "rect" | "poly" | "door";

/** A floor's plan image, for this session only (an object URL). */
export interface FloorImage {
  url: string;
  w: number;
  h: number;
  name: string;
}

export interface Selection {
  kind: "room" | "door";
  floorId: string;
  id: string;
}

export type RemoveTarget = { kind: "floor"; floorId: string } | Selection;

type Meta = Pick<TraceState, "id" | "name" | "credits">;
type RoomPatch = Partial<Omit<TraceRoom, "id">>;
type DoorPatch = Partial<Omit<TraceDoor, "id">>;

export interface TraceStore extends TraceState {
  past: TraceState[];
  future: TraceState[];
  images: Record<string, FloorImage>; // by floor id; shown only while the size matches the floor's
  floorId: string | null; // the floor on the canvas
  tool: Tool;
  selection: Selection | null;
  isPublic: boolean; // export to data/buildings/ instead of data/private/; never saved
  showBelow: boolean; // draw the floor below faintly
  fitNonce: number; // bump to fit the image into the canvas
  saveError: string | null;
  mergeKey: string | null;
  mergeAt: number;

  // Trace edits: each one is an undo step. `key` merges quick repeats (typing, dragging).
  setMeta: (patch: Partial<Meta>, key?: string) => void;
  addFloor: (f: { name: string; level: number; image: FloorImage }) => string;
  updateFloor: (floorId: string, patch: Partial<Pick<TraceFloor, "name" | "level">>, key?: string) => void;
  setImage: (floorId: string, img: FloorImage) => void;
  setScale: (floorId: string, scale: TraceScale | null) => void;
  setRef: (floorId: string, ref: Pt | null) => void;
  addRoom: (floorId: string, room: Omit<TraceRoom, "id">) => string;
  updateRoom: (floorId: string, id: string, patch: RoomPatch, key?: string) => void;
  addDoor: (floorId: string, door: Omit<TraceDoor, "id">) => string;
  updateDoor: (floorId: string, id: string, patch: DoorPatch, key?: string) => void;
  remove: (target: RemoveTarget) => void;
  loadDraft: (t: TraceState) => void;
  undo: () => void;
  redo: () => void;

  // Page state: not part of the trace, not undoable.
  setFloor: (floorId: string) => void;
  setTool: (tool: Tool) => void;
  select: (sel: Selection | null) => void;
  setPublic: (on: boolean) => void;
  setShowBelow: (on: boolean) => void;
  requestFit: () => void;
}

/** Just the TraceState fields (what history, autosave and export use). */
export function traceOf(s: TraceState): TraceState {
  return { id: s.id, name: s.name, credits: s.credits, floors: s.floors };
}

export const EMPTY_TRACE: TraceState = { id: "", name: "", credits: "", floors: [] };

function loadSaved(): TraceState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return readTrace(JSON.parse(raw)) ?? EMPTY_TRACE;
  } catch {
    // storage blocked, or junk in it: start empty
  }
  return EMPTY_TRACE;
}

let seq = 0;
const newId = (prefix: string) => `${prefix}${Date.now().toString(36)}${(seq++).toString(36)}`;

function nextFloorId(floors: TraceFloor[]): string {
  for (let n = 1; ; n++) if (!floors.some((f) => f.id === `F${n}`)) return `F${n}`;
}

const lowestFloor = (floors: TraceFloor[]) => [...floors].sort((a, b) => a.level - b.level)[0]?.id ?? null;

/** The active floor and the selection, pointed back at things that still exist. */
function fixView(s: Pick<TraceStore, "floors" | "floorId" | "selection">) {
  const floorId = s.floors.some((f) => f.id === s.floorId) ? s.floorId : lowestFloor(s.floors);
  const sel = s.selection;
  const f = sel ? s.floors.find((x) => x.id === sel.floorId) : undefined;
  const alive = !!sel && !!f && (sel.kind === "room" ? f.rooms : f.doors).some((x) => x.id === sel.id);
  return { floorId, selection: alive ? sel : null };
}

const saved = loadSaved();

export const useTrace = create<TraceStore>()((set, get) => {
  /** Replace trace fields as one undo step; a repeat of the same key soon after merges into it. */
  const commit = (next: Partial<TraceState>, key?: string) => {
    const s = get();
    const now = Date.now();
    const merge = key !== undefined && key === s.mergeKey && now - s.mergeAt < MERGE_MS;
    const past = merge ? s.past : [...s.past, traceOf(s)].slice(-HISTORY);
    set({ ...next, past, future: [], mergeKey: key ?? null, mergeAt: now });
  };
  const mapFloor = (floorId: string, fn: (f: TraceFloor) => TraceFloor) =>
    get().floors.map((f) => (f.id === floorId ? fn(f) : f));
  const has = (floorId: string) => get().floors.some((f) => f.id === floorId);

  return {
    ...saved,
    past: [],
    future: [],
    images: {},
    floorId: lowestFloor(saved.floors),
    tool: "select",
    selection: null,
    isPublic: false,
    showBelow: true,
    fitNonce: 0,
    saveError: null,
    mergeKey: null,
    mergeAt: 0,

    setMeta: (patch, key) => {
      const s = get();
      const next: Partial<Meta> = { ...patch };
      // the id follows the name until someone edits the id by hand
      if (patch.name !== undefined && patch.id === undefined && (!s.id || s.id === slugify(s.name))) {
        next.id = slugify(patch.name);
      }
      commit(next, key);
    },

    addFloor: ({ name, level, image }) => {
      const s = get();
      const id = nextFloorId(s.floors);
      const floor: TraceFloor = {
        id,
        name: name.trim() || id,
        level,
        imageW: image.w,
        imageH: image.h,
        scale: null,
        ref: null,
        rooms: [],
        doors: [],
      };
      commit({ floors: [...s.floors, floor] });
      set({ images: { ...get().images, [id]: image }, floorId: id, selection: null, fitNonce: get().fitNonce + 1 });
      return id;
    },

    updateFloor: (floorId, patch, key) => {
      if (has(floorId)) commit({ floors: mapFloor(floorId, (f) => ({ ...f, ...patch })) }, key);
    },

    setImage: (floorId, img) => {
      const s = get();
      const f = s.floors.find((x) => x.id === floorId);
      if (!f) return;
      const old = s.images[floorId];
      if (old && old.url !== img.url) URL.revokeObjectURL(old.url);
      set({ images: { ...s.images, [floorId]: img } });
      if (f.imageW !== img.w || f.imageH !== img.h) {
        commit({ floors: mapFloor(floorId, (x) => ({ ...x, imageW: img.w, imageH: img.h })) });
        set({ fitNonce: get().fitNonce + 1 });
      }
    },

    setScale: (floorId, scale) => {
      if (has(floorId)) commit({ floors: mapFloor(floorId, (f) => ({ ...f, scale })) });
    },

    setRef: (floorId, ref) => {
      if (has(floorId)) commit({ floors: mapFloor(floorId, (f) => ({ ...f, ref })) });
    },

    addRoom: (floorId, room) => {
      const id = newId("r");
      if (has(floorId)) commit({ floors: mapFloor(floorId, (f) => ({ ...f, rooms: [...f.rooms, { ...room, id }] })) });
      return id;
    },

    updateRoom: (floorId, id, patch, key) => {
      if (!has(floorId)) return;
      commit({ floors: mapFloor(floorId, (f) => ({ ...f, rooms: f.rooms.map((r) => (r.id === id ? { ...r, ...patch } : r)) })) }, key);
    },

    addDoor: (floorId, door) => {
      const id = newId("d");
      if (has(floorId)) commit({ floors: mapFloor(floorId, (f) => ({ ...f, doors: [...f.doors, { ...door, id }] })) });
      return id;
    },

    updateDoor: (floorId, id, patch, key) => {
      if (!has(floorId)) return;
      const edit = (f: TraceFloor, d: TraceDoor): TraceDoor => {
        let next: TraceDoor = { ...d, ...patch };
        // a door becomes 1.0 m wide once it is named as an exit (and 0.9 m again if the name goes)
        if (patch.name !== undefined && patch.a === undefined && patch.b === undefined) {
          const was = (d.name ?? "").trim() !== "";
          const now = patch.name.trim() !== "";
          const w = doorWidth(f, d);
          if (!was && now && Math.abs(w - DOOR_WIDTH) < 0.01) next = { ...next, ...resizeDoor(f, d, EXIT_WIDTH) };
          if (was && !now && Math.abs(w - EXIT_WIDTH) < 0.01) next = { ...next, ...resizeDoor(f, d, DOOR_WIDTH) };
        }
        return next;
      };
      commit({ floors: mapFloor(floorId, (f) => ({ ...f, doors: f.doors.map((d) => (d.id === id ? edit(f, d) : d)) })) }, key);
    },

    remove: (target) => {
      if (!has(target.floorId)) return;
      if (target.kind === "floor") commit({ floors: get().floors.filter((f) => f.id !== target.floorId) });
      else if (target.kind === "room") {
        commit({ floors: mapFloor(target.floorId, (f) => ({ ...f, rooms: f.rooms.filter((r) => r.id !== target.id) })) });
      } else {
        commit({ floors: mapFloor(target.floorId, (f) => ({ ...f, doors: f.doors.filter((d) => d.id !== target.id) })) });
      }
      set(fixView(get()));
    },

    loadDraft: (t) => {
      commit(traceOf(t));
      set({ ...fixView({ floors: t.floors, floorId: null, selection: null }), fitNonce: get().fitNonce + 1 });
    },

    undo: () => {
      const s = get();
      const prev = s.past[s.past.length - 1];
      if (!prev) return;
      set({ ...prev, past: s.past.slice(0, -1), future: [traceOf(s), ...s.future].slice(0, HISTORY), mergeKey: null });
      set(fixView(get()));
    },

    redo: () => {
      const s = get();
      const next = s.future[0];
      if (!next) return;
      set({ ...next, past: [...s.past, traceOf(s)].slice(-HISTORY), future: s.future.slice(1), mergeKey: null });
      set(fixView(get()));
    },

    setFloor: (floorId) => set({ floorId, selection: null }),
    setTool: (tool) => set({ tool }),
    select: (selection) => set(selection ? { selection, floorId: selection.floorId } : { selection: null }),
    setPublic: (isPublic) => set({ isPublic }),
    setShowBelow: (showBelow) => set({ showBelow }),
    requestFit: () => set({ fitNonce: get().fitNonce + 1 }),
  };
});

// ---------------------------------------------------------------- autosave (without the images)

let timer: ReturnType<typeof setTimeout> | undefined;

function saveNow() {
  clearTimeout(timer);
  timer = undefined;
  let saveError: string | null = null;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: "trace/v0", ...traceOf(useTrace.getState()) }));
  } catch (e) {
    saveError = `Autosave failed (${e instanceof Error ? e.name : "storage error"}); use Save trace`;
  }
  if (useTrace.getState().saveError !== saveError) useTrace.setState({ saveError });
}

useTrace.subscribe((s, prev) => {
  if (s.floors === prev.floors && s.id === prev.id && s.name === prev.name && s.credits === prev.credits) return;
  clearTimeout(timer);
  timer = setTimeout(saveNow, 300);
});

if (typeof window !== "undefined") {
  window.addEventListener("beforeunload", () => {
    if (timer !== undefined) saveNow();
  });
}
