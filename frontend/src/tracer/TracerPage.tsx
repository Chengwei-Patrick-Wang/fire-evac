// The tracer page: toolbar | canvas | inspector. Trace floor-plan images into rooms, doors and
// stairs, check the result, and export plan/v0 to POST /api/buildings/from-plan. The page covers
// the app below the top bar while it is open (see tracer.css).
import { useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import "./tracer.css";
import Inspector from "./Inspector";
import type { ExportState } from "./Inspector";
import TracerCanvas from "./TracerCanvas";
import { checkTrace } from "./edit";
import { downloadJson } from "./files";
import { exportPlan } from "./plan";
import { traceOf, useTrace } from "./store";
import type { Tool } from "./store";

const API = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/$/, "");
const TIMEOUT_S = 60;

const TOOLS: { tool: Tool; label: string; key: string; title: string }[] = [
  { tool: "select", label: "Select", key: "V", title: "Select a room or door; drag a room's corners" },
  { tool: "scale", label: "Scale", key: "S", title: "Scale: click two points a known distance apart, then type the distance in meters" },
  { tool: "ref", label: "Ref", key: "O", title: "Reference point: the same physical corner on every floor" },
  { tool: "rect", label: "Rect", key: "R", title: "Rectangle room: drag from corner to corner" },
  { tool: "poly", label: "Poly", key: "P", title: "Polygon room: click the corners, double-click to close" },
  { tool: "door", label: "Door", key: "D", title: "Door: click within 0.5 m of a room edge" },
];

export default function TracerPage({ onOpenBuilding }: { onOpenBuilding?: (id: string) => void }) {
  const trace = useTrace(useShallow((s) => ({ id: s.id, name: s.name, credits: s.credits, floors: s.floors })));
  const isPublic = useTrace((s) => s.isPublic);
  const tool = useTrace((s) => s.tool);
  const showBelow = useTrace((s) => s.showBelow);
  const canUndo = useTrace((s) => s.past.length > 0);
  const canRedo = useTrace((s) => s.future.length > 0);
  const { setTool, undo, redo, requestFit, setShowBelow } = useTrace.getState();
  const [exp, setExp] = useState<ExportState>({ kind: "idle" });

  // validateTrace and validatePlan(exportPlan(trace)), plus the page's own checks; errors first
  const messages = useMemo(() => checkTrace(trace, isPublic), [trace, isPublic]);
  const hasFloor = trace.floors.length > 0;

  const open = (id: string) => {
    if (onOpenBuilding) onOpenBuilding(id);
    else location.assign("/?building=" + encodeURIComponent(id));
  };

  const downloadPlan = () => {
    const plan = exportPlan(traceOf(useTrace.getState()));
    downloadJson(`${plan.id || "plan"}.plan.json`, plan);
  };

  const doExport = async () => {
    const st = useTrace.getState();
    if (checkTrace(traceOf(st), st.isPublic).some((m) => m.startsWith("error:"))) return;
    const plan = exportPlan(traceOf(st));
    if (!API) {
      setExp({ kind: "failed", message: "No API in this build (VITE_API_URL is empty): this is the static demo." });
      return;
    }
    setExp({ kind: "busy" });
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), TIMEOUT_S * 1000);
    try {
      const res = await fetch(`${API}/buildings/from-plan?public=${st.isPublic ? "true" : "false"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(plan),
        signal: ctl.signal,
      });
      const body: unknown = await res.json().catch(() => null);
      if (!res.ok) {
        const detail = (body as { detail?: unknown } | null)?.detail;
        const text = typeof detail === "string" ? detail : detail !== undefined ? JSON.stringify(detail) : res.statusText;
        setExp({ kind: "failed", message: `The API refused the plan (${res.status}): ${text}` });
        return;
      }
      const out = (body ?? {}) as { id?: unknown; warnings?: unknown };
      const id = typeof out.id === "string" && out.id ? out.id : plan.id;
      const warnings = Array.isArray(out.warnings) ? out.warnings.map(String) : [];
      setExp({ kind: "done", id, warnings });
      if (warnings.length === 0) open(id); // with warnings, the user reads them and opens it
    } catch (e) {
      const timedOut = e instanceof DOMException && e.name === "AbortError";
      setExp({
        kind: "failed",
        message: timedOut ? `The API did not answer within ${TIMEOUT_S} s.` : `Could not reach the API at ${API} (static demo, or the server is down).`,
      });
    } finally {
      clearTimeout(timer);
    }
  };

  return (
    <div className="tr-page">
      <nav className="tr-tools" aria-label="Tracer tools">
        {TOOLS.map((t) => (
          <button
            key={t.tool}
            className={tool === t.tool ? "on" : ""}
            disabled={!hasFloor}
            title={`${t.title} (${t.key})`}
            onClick={(e) => {
              e.currentTarget.blur();
              setTool(t.tool);
            }}
          >
            {t.label}
            <kbd>{t.key}</kbd>
          </button>
        ))}
        <hr />
        <button
          disabled={!canUndo}
          title="Undo (Ctrl+Z)"
          onClick={(e) => {
            e.currentTarget.blur();
            undo();
          }}
        >
          Undo
        </button>
        <button
          disabled={!canRedo}
          title="Redo (Ctrl+Y or Ctrl+Shift+Z)"
          onClick={(e) => {
            e.currentTarget.blur();
            redo();
          }}
        >
          Redo
        </button>
        <button
          disabled={!hasFloor}
          title="Fit the plan image into view (0)"
          onClick={(e) => {
            e.currentTarget.blur();
            requestFit();
          }}
        >
          Fit
        </button>
        <button
          className={showBelow ? "on" : ""}
          title="Show the floor below, dashed, once both floors have a reference point"
          onClick={(e) => {
            e.currentTarget.blur();
            setShowBelow(!showBelow);
          }}
        >
          Below
        </button>
        {/* A8 hook: the AI first pass (POST /api/trace/propose) goes here. It should add its rooms
            with useTrace.getState().addRoom(floorId, { ..., ai: true }), so they show dashed until
            someone presses "Mark reviewed" in the room form. */}
      </nav>
      <TracerCanvas />
      <Inspector
        messages={messages}
        exportState={exp}
        onExport={() => void doExport()}
        onDownloadPlan={downloadPlan}
        onOpen={open}
        onDismiss={() => setExp({ kind: "idle" })}
      />
    </div>
  );
}
