// The tracer page: toolbar | canvas | inspector. Trace floor-plan images into rooms, doors and
// stairs, check the result, and export plan/v0 to POST /api/buildings/from-plan. The page covers
// the app below the top bar while it is open (see tracer.css). The AI first pass sends the
// floor's image to POST /api/trace/propose and brings the proposed rooms in as a dashed draft.
import { useEffect, useMemo, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import "./tracer.css";
import Inspector from "./Inspector";
import type { AiControls, ExportState } from "./Inspector";
import TracerCanvas from "./TracerCanvas";
import { aiRooms, checkTrace } from "./edit";
import type { SentImage } from "./edit";
import { downloadJson, imageForUpload } from "./files";
import { floorScale } from "./geometry";
import { exportPlan } from "./plan";
import { aiOutcome, traceOf, useTrace } from "./store";
import type { AiJob, Tool } from "./store";

const API = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/$/, "");
const TIMEOUT_S = 60;
const AI_TIMEOUT_S = 150; // the server gives the model chain up to 2 x 60 + 10 s
const AI_MAX_SIDE = 1600; // px, the long side of the image the AI first pass sends
const AI_SHOW_MS = 8000; // how long the canvas shows the AI pass's outcome
const AI_UNAVAILABLE = "AI unavailable, draw by hand";
const UMASS = /umass/i;

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
  const floorId = useTrace((s) => s.floorId);
  const images = useTrace((s) => s.images);
  const aiJob = useTrace((s) => s.aiJob);
  const { setTool, undo, redo, requestFit, setShowBelow } = useTrace.getState();
  const [exp, setExp] = useState<ExportState>({ kind: "idle" });
  const [now, setNow] = useState(() => Date.now());
  const [outcomeUntil, setOutcomeUntil] = useState(0);
  const aiAbort = useRef<{ ctl: AbortController; why: "cancel" | "timeout" | null } | null>(null);

  // validateTrace and validatePlan(exportPlan(trace)), plus the page's own checks; errors first
  const messages = useMemo(() => checkTrace(trace, isPublic), [trace, isPublic]);
  const hasFloor = trace.floors.length > 0;

  // the AI first pass: why it cannot run on the current floor ("" when it can)
  const floor = trace.floors.find((f) => f.id === floorId) ?? null;
  const image = floor ? images[floor.id] : undefined;
  const aiBusy = aiJob.kind === "busy";
  const aiWhy = !floor
    ? "Add a floor first"
    : !image || image.w !== floor.imageW || image.h !== floor.imageH
      ? "Upload this floor's image again first"
      : !(floorScale(floor) > 0)
        ? "Set the scale first: Scale (S), click two points, type the distance"
        : !API
          ? `${AI_UNAVAILABLE}: no API in this build (VITE_API_URL is empty), this is the static demo`
          : "";
  const aiSeconds = aiJob.kind === "busy" ? Math.max(0, Math.round((now - aiJob.since) / 1000)) : 0;

  // tick while the AI works; hide its outcome on the canvas after a while
  useEffect(() => {
    if (!aiBusy) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [aiBusy]);
  useEffect(() => {
    const left = outcomeUntil - Date.now();
    if (left <= 0) return;
    const t = setTimeout(() => setOutcomeUntil(0), left);
    return () => clearTimeout(t);
  }, [outcomeUntil]);

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

  /** The AI first pass on the current floor: the image (downscaled) and hints go to the API, and
   * the proposed rooms come back as the floor's AI draft. Manual tracing works throughout. */
  const runAi = async () => {
    const st = useTrace.getState();
    const f = st.floors.find((x) => x.id === st.floorId);
    const img = f ? st.images[f.id] : undefined;
    if (!f || !img || st.aiJob.kind === "busy" || aiWhy) return;
    const finish = (job: AiJob) => {
      useTrace.getState().setAiJob(job);
      setOutcomeUntil(Date.now() + AI_SHOW_MS);
    };
    // spec 12: only public plans go to Gemini, never a UMass plan
    const words = [st.id, st.name, st.credits, img.name, ...st.floors.map((x) => x.name)];
    if (words.some((w) => UMASS.test(w))) {
      finish({ kind: "failed", floorId: f.id, message: "UMass plans never go to the AI: draw by hand.", detail: "This trace or its image mentions UMass." });
      return;
    }
    if (
      !st.isPublic &&
      !window.confirm("The AI first pass sends this floor's image to Google Gemini. Send only public plans, never UMass plans.\n\nSend it?")
    ) {
      return;
    }
    const scale = floorScale(f);
    const since = Date.now();
    const handle = { ctl: new AbortController(), why: null as "cancel" | "timeout" | null };
    aiAbort.current = handle;
    st.setAiJob({ kind: "busy", floorId: f.id, since });
    setNow(since);
    const timer = setTimeout(() => {
      handle.why = "timeout";
      handle.ctl.abort();
    }, AI_TIMEOUT_S * 1000);
    try {
      const up = await imageForUpload(img.url, AI_MAX_SIDE);
      const sent: SentImage = { w: up.w, h: up.h, metersPerPixel: scale * (f.imageW / up.w) };
      const form = new FormData();
      form.append("image", up.blob, up.blob.type === "image/jpeg" ? "floor.jpg" : "floor.png");
      form.append("hints", JSON.stringify({ metersPerPixel: sent.metersPerPixel, width: up.w, height: up.h, name: f.name, level: f.level }));
      const res = await fetch(`${API}/trace/propose`, { method: "POST", body: form, signal: handle.ctl.signal });
      const body = (await res.json().catch(() => null)) as { floor?: { rooms?: unknown }; model?: unknown; detail?: unknown } | null;
      if (!res.ok) {
        const detail = typeof body?.detail === "string" ? body.detail : res.statusText;
        finish({ kind: "failed", floorId: f.id, message: AI_UNAVAILABLE, detail: `The API answered ${res.status}: ${detail}.` });
        return;
      }
      // the floor may have changed while the AI worked: only map onto the image and scale it saw
      const cur = useTrace.getState().floors.find((x) => x.id === f.id);
      if (!cur || cur.imageW !== f.imageW || cur.imageH !== f.imageH || floorScale(cur) !== scale) {
        finish({ kind: "failed", floorId: f.id, message: "The floor's image or scale changed while the AI worked: run it again." });
        return;
      }
      const got = aiRooms(cur, body?.floor?.rooms, sent);
      if (got.rooms.length > 0) {
        useTrace.getState().addAiRooms(f.id, got.rooms);
        setTool("select");
      }
      finish({
        kind: "done",
        floorId: f.id,
        added: got.rooms.length,
        skipped: got.overlapping + got.unusable,
        seconds: (Date.now() - since) / 1000,
        model: typeof body?.model === "string" ? body.model : "",
      });
    } catch (e) {
      if (handle.why === "cancel") {
        useTrace.getState().setAiJob({ kind: "idle" });
        return;
      }
      const detail =
        handle.why === "timeout"
          ? `No answer within ${AI_TIMEOUT_S} s.`
          : e instanceof TypeError
            ? `Could not reach the API at ${API} (static demo, or the server is down).`
            : e instanceof Error
              ? e.message
              : String(e);
      finish({ kind: "failed", floorId: f.id, message: AI_UNAVAILABLE, detail });
    } finally {
      clearTimeout(timer);
      if (aiAbort.current === handle) aiAbort.current = null;
    }
  };

  const cancelAi = () => {
    const h = aiAbort.current;
    if (!h) return;
    h.why = "cancel";
    h.ctl.abort();
  };

  const ai: AiControls = { why: aiWhy, seconds: aiSeconds, onRun: () => void runAi(), onCancel: cancelAi };
  const outcome = !aiBusy && outcomeUntil > 0 ? aiOutcome(aiJob) : null;

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
        <hr />
        <button
          className={aiBusy ? "on tr-ai" : "tr-ai"}
          disabled={!!aiWhy || aiBusy}
          title={aiWhy || "AI first pass: Gemini proposes this floor's rooms from its image, as a dashed draft (rooms only: you add the doors)"}
          onClick={(e) => {
            e.currentTarget.blur();
            void runAi();
          }}
        >
          AI
          <small>{aiBusy ? `${aiSeconds} s` : "rooms"}</small>
        </button>
      </nav>
      <div className="tr-center">
        <TracerCanvas />
        {aiBusy && (
          <div className="tr-ai-pill" role="status" aria-live="polite">
            <span className="tr-spin" aria-hidden="true" />
            <span>
              {`AI first pass on ${aiJob.floorId}: waiting for Gemini, ${aiSeconds} s`}
              <small>{aiSeconds < 25 ? "Usually 5–20 s. Keep tracing meanwhile." : "Slow today: other models in the chain may answer (up to 2 min)."}</small>
            </span>
            <button onClick={cancelAi}>Cancel</button>
          </div>
        )}
        {outcome && (
          <div className={`tr-ai-pill ${outcome.tone}`} role="status" aria-live="polite">
            <span>
              {outcome.text}
              {outcome.detail && <small>{outcome.detail}</small>}
            </span>
            <button aria-label="Hide" onClick={() => setOutcomeUntil(0)}>
              ×
            </button>
          </div>
        )}
      </div>
      <Inspector
        messages={messages}
        exportState={exp}
        ai={ai}
        onExport={() => void doExport()}
        onDownloadPlan={downloadPlan}
        onOpen={open}
        onDismiss={() => setExp({ kind: "idle" })}
      />
    </div>
  );
}
