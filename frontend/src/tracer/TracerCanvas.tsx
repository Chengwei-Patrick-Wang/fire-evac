// The tracer's drawing surface in plain SVG: the floor image under the traced shapes. The wheel
// zooms about the cursor; space-drag, middle-drag, or dragging empty space with Select pans.
// Room corners and door centers go through snapPoint (0.25 m); the scale and reference clicks
// stay raw, because they define the grid. Colors follow tools/plot_building.py: stairs orange,
// exterior doors green, other doors blue (red: a door with no room on either side).
import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { floorScale, pxToPlan, snapPoint } from "./geometry";
import type { Pt } from "./geometry";
import { DOOR_REACH, DOOR_WIDTH, doorKinds, labelPoint, placeDoor, segDist } from "./edit";
import type { DoorKind } from "./edit";
import { useTrace } from "./store";

const STAIR = "#ff7f0e";
const EXIT = "#2ca02c";
const DOOR = "#1f77b4";
const BAD = "#ef4444";
const ROOM = "#38bdf8";
const PICKED = "#facc15";
const SCALE = "#e879f9";
const REF = "#f43f5e";
const BELOW = "#94a3b8";

const CLOSE_PX = 10; // a polygon click this close (screen pixels) to its first corner closes it
const EDGE_PX = 8; // a double-click this close (screen pixels) to an edge of the selected room adds a corner

interface View {
  k: number; // screen pixels per image pixel
  tx: number;
  ty: number;
}

type Drag =
  | { kind: "pan"; x: number; y: number; tx: number; ty: number }
  | { kind: "vertex"; roomId: string; index: number; key: string }
  | { kind: "rect"; p0: Pt };

const doorColor = (k: DoorKind | undefined) => (k === "exterior" ? EXIT : k === "interior" ? DOOR : BAD);
const pts = (poly: Pt[]) => poly.map((p) => `${p[0]},${p[1]}`).join(" ");
const m2 = (v: number) => `${Math.round(v * 100) / 100}`;

function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el || typeof el.tagName !== "string") return false;
  return el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable;
}

let gesture = 0;

export default function TracerCanvas() {
  const floors = useTrace((s) => s.floors);
  const floorId = useTrace((s) => s.floorId);
  const tool = useTrace((s) => s.tool);
  const selection = useTrace((s) => s.selection);
  const images = useTrace((s) => s.images);
  const showBelow = useTrace((s) => s.showBelow);
  const fitNonce = useTrace((s) => s.fitNonce);
  const floor = floors.find((f) => f.id === floorId) ?? null;
  const image = floor ? images[floor.id] : undefined;
  const hasImage = !!floor && !!image && image.w === floor.imageW && image.h === floor.imageH;
  const scale = floor ? floorScale(floor) : 0;
  const sel = selection && floor && selection.floorId === floor.id ? selection : null;
  const selRoom = sel?.kind === "room" ? floor?.rooms.find((r) => r.id === sel.id) : undefined;

  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<Drag | null>(null);
  const overRef = useRef(false);
  const closedAt = useRef(0);
  const fitted = useRef("");
  const metersRef = useRef<HTMLInputElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [view, setView] = useState<View>({ k: 1, tx: 0, ty: 0 });
  const [hoverRaw, setHoverRaw] = useState<Pt | null>(null);
  const [scalePts, setScalePts] = useState<Pt[]>([]);
  const [meters, setMeters] = useState("");
  const [rect, setRect] = useState<{ p0: Pt; p1: Pt } | null>(null);
  const [poly, setPoly] = useState<Pt[]>([]);
  const [flash, setFlash] = useState<{ text: string; at: number } | null>(null);
  const [space, setSpace] = useState(false);
  const [panning, setPanning] = useState(false);

  const say = (text: string) => setFlash({ text, at: Date.now() });

  // the floor below, mapped into this floor's pixels through both reference points
  const below = useMemo(() => {
    if (!floor || !floor.ref || !(floorScale(floor) > 0)) return null;
    const lower = floors.filter((f) => f.level < floor.level).sort((a, b) => b.level - a.level)[0];
    if (!lower || !lower.ref || !(floorScale(lower) > 0)) return null;
    const k = floorScale(lower) / floorScale(floor);
    const [rx, ry] = floor.ref;
    const [bx, by] = lower.ref;
    const map = (p: Pt): Pt => [rx + (p[0] - bx) * k, ry + (p[1] - by) * k];
    return { floor: lower, map, transform: `translate(${rx} ${ry}) scale(${k}) translate(${-bx} ${-by})` };
  }, [floor, floors]);
  const belowImage = below ? images[below.floor.id] : undefined;
  const belowHasImage = !!below && !!belowImage && belowImage.w === below.floor.imageW && belowImage.h === below.floor.imageH;

  const kinds = useMemo(() => (floor ? doorKinds(floor) : new Map<string, DoorKind>()), [floor]);

  // keep track of the canvas size
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, []);

  // fit the image when the floor, its image size or the Fit button changes
  const fitKey = floor ? `${floor.id}|${floor.imageW}x${floor.imageH}|${fitNonce}` : "";
  const fitW = floor?.imageW ?? 0;
  const fitH = floor?.imageH ?? 0;
  useEffect(() => {
    if (!fitKey || !size.w || !size.h || fitted.current === fitKey) return;
    fitted.current = fitKey;
    const W = Math.max(1, fitW);
    const H = Math.max(1, fitH);
    const k = Math.min(size.w / W, size.h / H) * 0.94;
    setView({ k, tx: (size.w - W * k) / 2, ty: (size.h - H * k) / 2 });
  }, [fitKey, fitW, fitH, size.w, size.h]);

  // a new floor or tool drops whatever was half drawn
  useEffect(() => {
    setScalePts([]);
    setMeters("");
    setRect(null);
    setPoly([]);
    dragRef.current = null;
  }, [floorId, tool]);

  useEffect(() => {
    if (scalePts.length !== 2) return;
    const t = setTimeout(() => metersRef.current?.focus(), 0);
    return () => clearTimeout(t);
  }, [scalePts.length]);

  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 2600);
    return () => clearTimeout(t);
  }, [flash]);

  // wheel zoom about the cursor (a native listener: React's wheel listener is passive)
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const sx = e.clientX - r.left;
      const sy = e.clientY - r.top;
      const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * r.height : e.deltaY;
      const f = Math.exp(-dy * 0.0015);
      setView((v) => {
        const k = Math.min(64, Math.max(0.02, v.k * f));
        const g = k / v.k;
        return { k, tx: sx - (sx - v.tx) * g, ty: sy - (sy - v.ty) * g };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  /** Close the polygon being drawn into a room. */
  const closePoly = () => {
    if (!floor || poly.length < 3) return;
    const st = useTrace.getState();
    const id = st.addRoom(floor.id, { name: "", type: "office", polygon: poly });
    st.select({ kind: "room", floorId: floor.id, id });
    setPoly([]);
    closedAt.current = Date.now();
  };

  // keyboard: tools, undo and redo, delete, escape, enter; space held over the canvas pans
  useEffect(() => {
    const onDown = (e: KeyboardEvent) => {
      if (e.code === "Space") {
        // The replay's play/pause listens for space on window, out of sight while tracing; keep
        // it from firing. Stopping propagation leaves typing and button presses alone.
        e.stopPropagation();
        if (isTyping(e.target) || (!overRef.current && !dragRef.current)) return;
        e.preventDefault();
        if (!e.repeat) setSpace(true);
        return;
      }
      if (isTyping(e.target)) return;
      const st = useTrace.getState();
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      if (mod && !e.altKey && key === "z") {
        e.preventDefault();
        if (e.shiftKey) st.redo();
        else st.undo();
        return;
      }
      if (mod && !e.altKey && key === "y") {
        e.preventDefault();
        st.redo();
        return;
      }
      if (mod || e.altKey) return;
      if (e.key === "Escape") {
        if (poly.length || rect || scalePts.length) {
          setPoly([]);
          setRect(null);
          setScalePts([]);
          dragRef.current = null;
        } else st.select(null);
        return;
      }
      if (e.key === "Enter") {
        if (st.tool === "poly") closePoly();
        return;
      }
      if (e.key === "Backspace" || e.key === "Delete") {
        if (st.tool === "poly" && poly.length) {
          e.preventDefault();
          setPoly(poly.slice(0, -1));
        } else if (st.selection) {
          e.preventDefault();
          st.remove(st.selection);
        }
        return;
      }
      const tools: Record<string, typeof st.tool> = { v: "select", s: "scale", o: "ref", r: "rect", p: "poly", d: "door" };
      if (tools[key]) st.setTool(tools[key]);
      else if (key === "0") st.requestFit();
    };
    const onUp = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      setSpace(false);
      if (!isTyping(e.target) && overRef.current) e.preventDefault();
    };
    const onBlur = () => setSpace(false);
    window.addEventListener("keydown", onDown, true);
    window.addEventListener("keyup", onUp, true);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onDown, true);
      window.removeEventListener("keyup", onUp, true);
      window.removeEventListener("blur", onBlur);
    };
  });

  const toImg = (e: { clientX: number; clientY: number }): Pt => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r) return [0, 0];
    return [(e.clientX - r.left - view.tx) / view.k, (e.clientY - r.top - view.ty) / view.k];
  };
  const snapTo = (p: Pt): Pt => (floor && scale > 0 ? snapPoint(p, floor) : p);

  const capture = (e: ReactPointerEvent) => {
    try {
      svgRef.current?.setPointerCapture(e.pointerId);
    } catch {
      // the pointer is already gone
    }
  };

  const startPan = (e: ReactPointerEvent) => {
    dragRef.current = { kind: "pan", x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty };
    setPanning(true);
    capture(e);
  };

  const onPointerDown = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (e.button === 1 || (e.button === 0 && space)) {
      e.preventDefault();
      startPan(e);
      return;
    }
    if (e.button !== 0 || !floor) return;
    const p = toImg(e);
    const st = useTrace.getState();
    if (tool === "select") {
      st.select(null);
      startPan(e);
      return;
    }
    if (tool === "scale") {
      setScalePts((prev) => (prev.length >= 2 ? [p] : [...prev, p]));
      return;
    }
    if (tool === "ref") {
      st.setRef(floor.id, p);
      say("Reference point set: mark the same physical point on every floor");
      return;
    }
    if (!(scale > 0)) {
      say("Set the scale first: Scale tool (S), click two points, type the distance");
      return;
    }
    const q = snapPoint(p, floor);
    if (tool === "rect") {
      dragRef.current = { kind: "rect", p0: q };
      setRect({ p0: q, p1: q });
      capture(e);
    } else if (tool === "poly") {
      if (Date.now() - closedAt.current < 400) return; // the second click of the double-click that closed it
      const first = poly[0];
      if (first && poly.length >= 3 && Math.hypot(p[0] - first[0], p[1] - first[1]) * view.k < CLOSE_PX) {
        closePoly();
        return;
      }
      const last = poly[poly.length - 1];
      if (last && last[0] === q[0] && last[1] === q[1]) return;
      setPoly([...poly, q]);
    } else if (tool === "door") {
      const d = placeDoor(floor, p);
      if (!d) {
        say(`Click within ${DOOR_REACH} m of a room edge to put a door there`);
        return;
      }
      const id = st.addDoor(floor.id, { a: d.a, b: d.b, fireDoor: false, state: "open" });
      st.select({ kind: "door", floorId: floor.id, id });
    }
  };

  const onPointerMove = (e: ReactPointerEvent<SVGSVGElement>) => {
    const d = dragRef.current;
    if (d?.kind === "pan") {
      setView((v) => ({ ...v, tx: d.tx + e.clientX - d.x, ty: d.ty + e.clientY - d.y }));
      return;
    }
    if (!floor) return;
    const p = toImg(e);
    const q = snapTo(p);
    setHoverRaw(p);
    if (d?.kind === "vertex") {
      const st = useTrace.getState();
      const room = st.floors.find((f) => f.id === floor.id)?.rooms.find((r) => r.id === d.roomId);
      const cur = room?.polygon[d.index];
      if (!room || !cur || (cur[0] === q[0] && cur[1] === q[1])) return;
      st.updateRoom(floor.id, room.id, { polygon: room.polygon.map((v, i) => (i === d.index ? q : v)) }, d.key);
    } else if (d?.kind === "rect") {
      setRect({ p0: d.p0, p1: q });
    }
  };

  const endDrag = (e: ReactPointerEvent<SVGSVGElement>, commit: boolean) => {
    const d = dragRef.current;
    dragRef.current = null;
    setPanning(false);
    try {
      if (svgRef.current?.hasPointerCapture(e.pointerId)) svgRef.current.releasePointerCapture(e.pointerId);
    } catch {
      // already released
    }
    if (d?.kind !== "rect") return;
    setRect(null);
    if (!commit || !floor) return;
    const [x0, y0] = d.p0;
    const [x1, y1] = snapTo(toImg(e));
    if (Math.abs(x1 - x0) < 1e-6 || Math.abs(y1 - y0) < 1e-6) {
      say("Drag from one corner of the room to the opposite corner");
      return;
    }
    const st = useTrace.getState();
    const id = st.addRoom(floor.id, { name: "", type: "office", polygon: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]] });
    st.select({ kind: "room", floorId: floor.id, id });
  };

  /** Double-click near an edge of the selected room: a new corner there (snapped). */
  const insertCorner = (p: Pt) => {
    if (!floor || !selRoom) return;
    const poly0 = selRoom.polygon;
    let best = -1;
    let bestD = EDGE_PX / view.k;
    poly0.forEach((a, i) => {
      const b = poly0[(i + 1) % poly0.length];
      if (!b) return;
      const d = segDist(p, a, b);
      if (d <= bestD) {
        best = i;
        bestD = d;
      }
    });
    if (best < 0) return;
    const q = snapTo(p);
    if (poly0.some((v) => v[0] === q[0] && v[1] === q[1])) return;
    useTrace.getState().updateRoom(floor.id, selRoom.id, { polygon: [...poly0.slice(0, best + 1), q, ...poly0.slice(best + 1)] });
  };

  /** Right-click on a corner of the selected room: remove it (a room keeps at least 3). */
  const removeCorner = (i: number) => {
    if (!floor || !selRoom) return;
    if (selRoom.polygon.length <= 3) {
      say("A room needs at least 3 corners");
      return;
    }
    useTrace.getState().updateRoom(floor.id, selRoom.id, { polygon: selRoom.polygon.filter((_, j) => j !== i) });
  };

  const submitScale = () => {
    if (!floor || scalePts.length < 2) return;
    const [p1, p2] = scalePts as [Pt, Pt];
    const px = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
    const m = parseFloat(meters.replace(",", "."));
    if (!(px >= 2)) {
      say("Click two different points");
      setScalePts([]);
      return;
    }
    if (!(m > 0)) {
      say("Type the real distance in meters, for example 40");
      return;
    }
    useTrace.getState().setScale(floor.id, { p1, p2, meters: m });
    setScalePts([]);
    setMeters("");
    say(`Scale set: ${m2(px / m)} px per meter`);
  };

  // ------------------------------------------------------------ what to tell the user

  const multi = floors.length > 1;
  let hint = "";
  if (!floor) hint = "Add a floor in the inspector: a name, its level and the plan image.";
  else if (tool === "scale") {
    hint = scalePts.length === 0 ? "Scale: click one end of a length you know (a wall, a scale bar)." : scalePts.length === 1 ? "Scale: now click the other end." : "Scale: type the real distance between the two points.";
  } else if (tool === "ref") hint = "Reference point: click a corner you can find on every floor (a stair corner works well).";
  else if (!(scale > 0)) hint = "Start with the scale: pick Scale (S), click both ends of a known length, type it in meters.";
  else if (tool === "rect") hint = "Rectangle: drag from corner to corner. Draw rooms edge to edge; corners snap to 0.25 m.";
  else if (tool === "poly") hint = "Polygon: click the corners; double-click, Enter or click the first corner to close. Backspace undoes a corner, Esc cancels.";
  else if (tool === "door") hint = `Door: click within ${DOOR_REACH} m of a room edge for a ${DOOR_WIDTH} m door. A door in the outside wall is an exit (green).`;
  else if (multi && !floor.ref) hint = "Mark the reference point (O): the same physical corner on every floor lines the floors up.";
  else hint = "Select: click a room or door to edit it; drag a corner to move it, double-click an edge to add one, right-click a corner to drop it; Delete removes the selection. Drag empty space or hold space to pan; the wheel zooms.";

  const hover: Pt | null = hoverRaw && (tool === "scale" || tool === "ref" ? hoverRaw : snapTo(hoverRaw));
  const ghost = floor && hoverRaw && tool === "door" && scale > 0 ? placeDoor(floor, hoverRaw) : null;
  const cursor = panning ? "grabbing" : space ? "grab" : tool === "select" ? "default" : "crosshair";
  const k = view.k;
  const hoverPlan = floor && hover && scale > 0 ? pxToPlan(hover, floor) : null;
  const planDist = (a: Pt, b: Pt) => Math.hypot(b[0] - a[0], b[1] - a[1]) * scale;

  return (
    <div
      className="tr-canvas"
      ref={wrapRef}
      onPointerEnter={() => {
        overRef.current = true;
      }}
      onPointerLeave={() => {
        overRef.current = false;
        setHoverRaw(null);
      }}
    >
      <svg
        ref={svgRef}
        style={{ cursor }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={(e) => endDrag(e, true)}
        onPointerCancel={(e) => endDrag(e, false)}
        onDoubleClick={(e) => {
          if (tool === "poly") closePoly();
          else if (tool === "select") insertCorner(toImg(e));
        }}
        onContextMenu={(e) => e.preventDefault()}
      >
        {floor && (
          <g transform={`translate(${view.tx} ${view.ty}) scale(${k})`}>
            {hasImage && image ? (
              <image href={image.url} x={0} y={0} width={floor.imageW} height={floor.imageH} preserveAspectRatio="none" />
            ) : (
              <g>
                <rect x={0} y={0} width={floor.imageW} height={floor.imageH} fill="#111a2e" stroke="#334155" strokeDasharray="8 6" vectorEffect="non-scaling-stroke" />
                <text x={floor.imageW / 2} y={floor.imageH / 2} fontSize={14 / k} className="tr-label tr-dim" style={{ strokeWidth: 3 / k }}>
                  {`Plan image missing: upload it again in the inspector (${floor.imageW} × ${floor.imageH} px)`}
                </text>
              </g>
            )}

            {showBelow && below && (
              <>
                {belowHasImage && belowImage && (
                  <image href={belowImage.url} width={below.floor.imageW} height={below.floor.imageH} transform={below.transform} opacity={0.35} preserveAspectRatio="none" style={{ mixBlendMode: "multiply" }} pointerEvents="none" />
                )}
                <g pointerEvents="none">
                  {below.floor.rooms.map((r) => (
                    <polygon key={r.id} points={pts(r.polygon.map(below.map))} fill="none" stroke={r.type === "stair" ? STAIR : BELOW} strokeOpacity={0.8} strokeWidth={1.5} strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
                  ))}
                </g>
              </>
            )}

            {floor.rooms.map((r) => {
              const picked = selRoom?.id === r.id;
              const color = r.type === "stair" ? STAIR : ROOM;
              const [lx, ly] = labelPoint(r.polygon);
              const label = `${r.name || r.type}${r.type === "stair" && r.group ? ` · ${r.group}` : ""}`;
              return (
                <g key={r.id}>
                  <polygon
                    points={pts(r.polygon)}
                    fill={color}
                    fillOpacity={picked ? 0.32 : 0.16}
                    stroke={picked ? PICKED : color}
                    strokeWidth={picked ? 2.5 : 1.5}
                    strokeDasharray={r.ai ? "6 4" : undefined}
                    vectorEffect="non-scaling-stroke"
                    style={{ cursor: tool === "select" && !space ? "pointer" : undefined }}
                    onPointerDown={(e) => {
                      if (tool !== "select" || space || e.button !== 0) return;
                      e.stopPropagation();
                      useTrace.getState().select({ kind: "room", floorId: floor.id, id: r.id });
                    }}
                  />
                  <text x={lx} y={ly} fontSize={12 / k} className="tr-label" style={{ strokeWidth: 3 / k }}>
                    {label}
                  </text>
                </g>
              );
            })}

            {floor.doors.map((d) => {
              const kind = kinds.get(d.id);
              const picked = sel?.kind === "door" && sel.id === d.id;
              const line = { x1: d.a[0], y1: d.a[1], x2: d.b[0], y2: d.b[1] };
              return (
                <g key={d.id}>
                  {picked && <line {...line} stroke={PICKED} strokeWidth={10} vectorEffect="non-scaling-stroke" pointerEvents="none" />}
                  <line
                    {...line}
                    stroke={doorColor(kind)}
                    strokeWidth={5}
                    strokeDasharray={kind === "interior" || kind === "exterior" ? undefined : "4 3"}
                    vectorEffect="non-scaling-stroke"
                    pointerEvents="none"
                  />
                  <line
                    {...line}
                    stroke="transparent"
                    strokeWidth={14}
                    vectorEffect="non-scaling-stroke"
                    pointerEvents="stroke"
                    style={{ cursor: tool === "select" && !space ? "pointer" : undefined }}
                    onPointerDown={(e) => {
                      if (tool !== "select" || space || e.button !== 0) return;
                      e.stopPropagation();
                      useTrace.getState().select({ kind: "door", floorId: floor.id, id: d.id });
                    }}
                  />
                  {kind === "exterior" && d.name && (
                    <text x={(d.a[0] + d.b[0]) / 2} y={(d.a[1] + d.b[1]) / 2 - 12 / k} fontSize={11 / k} className="tr-label tr-exit" style={{ strokeWidth: 3 / k }}>
                      {d.name}
                    </text>
                  )}
                </g>
              );
            })}

            {floor.scale && (
              <g pointerEvents="none" opacity={tool === "scale" ? 1 : 0.35}>
                <line x1={floor.scale.p1[0]} y1={floor.scale.p1[1]} x2={floor.scale.p2[0]} y2={floor.scale.p2[1]} stroke={SCALE} strokeWidth={2} strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
                {[floor.scale.p1, floor.scale.p2].map((p, i) => (
                  <circle key={i} cx={p[0]} cy={p[1]} r={4 / k} fill={SCALE} />
                ))}
                {tool === "scale" && (
                  <text x={(floor.scale.p1[0] + floor.scale.p2[0]) / 2} y={(floor.scale.p1[1] + floor.scale.p2[1]) / 2 - 10 / k} fontSize={11 / k} className="tr-label" style={{ strokeWidth: 3 / k, fill: SCALE }}>
                    {`${floor.scale.meters} m`}
                  </text>
                )}
              </g>
            )}

            {floor.ref && (
              <g pointerEvents="none" stroke={REF} strokeWidth={2}>
                <circle cx={floor.ref[0]} cy={floor.ref[1]} r={8 / k} fill="none" vectorEffect="non-scaling-stroke" />
                <line x1={floor.ref[0] - 13 / k} y1={floor.ref[1]} x2={floor.ref[0] + 13 / k} y2={floor.ref[1]} vectorEffect="non-scaling-stroke" />
                <line x1={floor.ref[0]} y1={floor.ref[1] - 13 / k} x2={floor.ref[0]} y2={floor.ref[1] + 13 / k} vectorEffect="non-scaling-stroke" />
                <text x={floor.ref[0] + 16 / k} y={floor.ref[1] - 12 / k} fontSize={11 / k} className="tr-label" style={{ strokeWidth: 3 / k, fill: REF }}>
                  ref
                </text>
              </g>
            )}

            {tool === "scale" && scalePts.length > 0 && (
              <g pointerEvents="none">
                {scalePts.length === 1 && hover && (
                  <line x1={scalePts[0]![0]} y1={scalePts[0]![1]} x2={hover[0]} y2={hover[1]} stroke={SCALE} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
                )}
                {scalePts.length === 2 && (
                  <line x1={scalePts[0]![0]} y1={scalePts[0]![1]} x2={scalePts[1]![0]} y2={scalePts[1]![1]} stroke={SCALE} strokeWidth={2.5} vectorEffect="non-scaling-stroke" />
                )}
                {scalePts.map((p, i) => (
                  <circle key={i} cx={p[0]} cy={p[1]} r={5 / k} fill={SCALE} stroke="#0b1220" strokeWidth={1} vectorEffect="non-scaling-stroke" />
                ))}
              </g>
            )}

            {rect && (
              <g pointerEvents="none">
                <polygon points={pts([rect.p0, [rect.p1[0], rect.p0[1]], rect.p1, [rect.p0[0], rect.p1[1]]])} fill={ROOM} fillOpacity={0.2} stroke={PICKED} strokeWidth={1.5} strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
                <text x={(rect.p0[0] + rect.p1[0]) / 2} y={(rect.p0[1] + rect.p1[1]) / 2} fontSize={12 / k} className="tr-label" style={{ strokeWidth: 3 / k }}>
                  {`${m2(Math.abs(rect.p1[0] - rect.p0[0]) * scale)} × ${m2(Math.abs(rect.p1[1] - rect.p0[1]) * scale)} m`}
                </text>
              </g>
            )}

            {tool === "poly" && poly.length > 0 && (
              <g pointerEvents="none">
                <polyline points={pts(hover ? [...poly, hover] : poly)} fill="none" stroke={PICKED} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
                {poly.map((p, i) => (
                  <circle key={i} cx={p[0]} cy={p[1]} r={(i === 0 ? 6 : 3.5) / k} fill={i === 0 ? PICKED : "#f8fafc"} stroke="#0b1220" strokeWidth={1} vectorEffect="non-scaling-stroke" />
                ))}
                {hover && (
                  <text x={hover[0] + 10 / k} y={hover[1] - 10 / k} fontSize={11 / k} className="tr-label" style={{ strokeWidth: 3 / k, textAnchor: "start" }}>
                    {`${m2(planDist(poly[poly.length - 1]!, hover))} m`}
                  </text>
                )}
              </g>
            )}

            {selRoom && tool === "select" &&
              selRoom.polygon.map((p, i) => (
                <circle
                  key={i}
                  cx={p[0]}
                  cy={p[1]}
                  r={5.5 / k}
                  fill="#f8fafc"
                  stroke="#0b1220"
                  strokeWidth={1.5}
                  vectorEffect="non-scaling-stroke"
                  style={{ cursor: space ? undefined : "move" }}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    removeCorner(i);
                  }}
                  onPointerDown={(e) => {
                    if (space || e.button !== 0) return;
                    e.stopPropagation();
                    dragRef.current = { kind: "vertex", roomId: selRoom.id, index: i, key: `drag:${++gesture}` };
                    capture(e);
                  }}
                />
              ))}

            {ghost && (
              <line x1={ghost.a[0]} y1={ghost.a[1]} x2={ghost.b[0]} y2={ghost.b[1]} stroke={PICKED} strokeWidth={5} strokeOpacity={0.7} vectorEffect="non-scaling-stroke" pointerEvents="none" />
            )}

            {hover && tool !== "select" && !panning && (
              <g pointerEvents="none" stroke={tool === "scale" ? SCALE : tool === "ref" ? REF : PICKED} strokeWidth={1.5}>
                <line x1={hover[0] - 7 / k} y1={hover[1]} x2={hover[0] + 7 / k} y2={hover[1]} vectorEffect="non-scaling-stroke" />
                <line x1={hover[0]} y1={hover[1] - 7 / k} x2={hover[0]} y2={hover[1] + 7 / k} vectorEffect="non-scaling-stroke" />
              </g>
            )}
          </g>
        )}
      </svg>

      <div className={`tr-hint${flash ? " tr-flash" : ""}`}>{flash ? flash.text : hint}</div>

      {floor && (
        <div className="tr-status">
          {`${floor.id}${floor.name && floor.name !== floor.id ? ` "${floor.name}"` : ""} · level ${floor.level}`}
          {scale > 0 ? ` · ${m2(1 / scale)} px/m` : " · no scale"}
          {hoverPlan ? ` · x ${hoverPlan[0].toFixed(2)} m, y ${hoverPlan[1].toFixed(2)} m` : ""}
          {` · zoom ${Math.round(k * 100)}%`}
          {below && showBelow ? ` · dashed: ${below.floor.id} below` : ""}
        </div>
      )}

      {tool === "scale" && scalePts.length === 2 && floor && (
        <form
          className="tr-scaleform"
          onSubmit={(e) => {
            e.preventDefault();
            submitScale();
          }}
        >
          <label>
            Distance between the two points
            <input
              ref={metersRef}
              inputMode="decimal"
              value={meters}
              placeholder="40"
              onChange={(e) => setMeters(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setScalePts([]);
              }}
            />
            m
          </label>
          <button type="submit">Set scale</button>
          <button type="button" onClick={() => setScalePts([])}>
            Cancel
          </button>
        </form>
      )}

      {!floor && <div className="tr-empty">No floor yet. Add one in the inspector on the right: its name, level and plan image (PNG or JPG).</div>}
    </div>
  );
}
