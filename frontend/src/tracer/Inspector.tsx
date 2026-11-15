// The tracer's right-hand panel: the building (name, id, credits, Public), floor tabs (add a floor
// with its image, upload the image again after a reload), the AI first pass (its status, Accept
// all and Discard AI draft), the selected room or door, the live checks, and Export, Download
// plan.json, Save trace and Load trace.
import { useMemo, useState } from "react";
import { floorScale } from "./geometry";
import { ROOM_TYPES } from "./plan";
import type { DoorState, RoomType, TraceDoor, TraceFloor, TraceRoom } from "./plan";
import { doorKinds, doorWidth, exportIds, readTrace, resizeDoor, roomArea } from "./edit";
import { downloadJson, readImage } from "./files";
import { EMPTY_TRACE, aiOutcome, traceOf, useTrace } from "./store";
import type { Selection } from "./store";

export type ExportState =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "done"; id: string; warnings: string[] }
  | { kind: "failed"; message: string };

/** The AI first pass as the page runs it (TracerPage). */
export interface AiControls {
  why: string; // why it cannot run on the current floor; "" when it can
  seconds: number; // how long the running pass has waited
  onRun: () => void;
  onCancel: () => void;
}

const DOOR_STATES: DoorState[] = ["open", "closed", "propped"];
const isError = (m: string) => m.startsWith("error:");
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const round = (v: number, d = 2) => Math.round(v * 10 ** d) / 10 ** d;

/** A number input that lets you type freely and commits every valid value. */
function NumField(props: { value: number; onCommit: (v: number) => void; step?: number; min?: number; int?: boolean; label: string }) {
  const { value, onCommit, step, min, int, label } = props;
  const [text, setText] = useState<string | null>(null); // what is typed, while focused
  return (
    <input
      type="number"
      aria-label={label}
      step={step}
      min={min}
      value={text ?? String(value)}
      onFocus={() => setText(String(value))}
      onBlur={() => setText(null)}
      onChange={(e) => {
        setText(e.target.value);
        const v = int ? Number.parseInt(e.target.value, 10) : Number.parseFloat(e.target.value);
        if (Number.isFinite(v) && (min === undefined || v >= min)) onCommit(v);
      }}
    />
  );
}

/** A button that opens a file picker. */
function FileButton(props: { label: string; accept: string; onFile: (f: File) => void; disabled?: boolean }) {
  return (
    <label className={`tr-filebtn${props.disabled ? " tr-disabled" : ""}`}>
      {props.label}
      <input
        type="file"
        accept={props.accept}
        disabled={props.disabled}
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) props.onFile(f);
        }}
      />
    </label>
  );
}

function AddFloor({ onDone }: { onDone: () => void }) {
  const floors = useTrace((s) => s.floors);
  const nextLevel = floors.length ? Math.max(...floors.map((f) => f.level)) + 1 : 0;
  const [name, setName] = useState("");
  const [level, setLevel] = useState(nextLevel);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const add = async () => {
    if (!file) {
      setError("Choose the plan image first");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const image = await readImage(file);
      useTrace.getState().addFloor({ name, level, image });
      onDone();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="tr-card">
      <div className="tr-row">
        <label>
          Name
          <input value={name} placeholder={level === 0 ? "Ground floor" : `Floor ${level}`} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="tr-narrow">
          Level
          <NumField label="Level" value={level} int onCommit={setLevel} />
        </label>
      </div>
      <div className="tr-row">
        <FileButton label={file ? "Change image" : "Choose plan image"} accept="image/*" onFile={setFile} />
        <span className="tr-note tr-ellipsis">{file ? file.name : "PNG or JPG"}</span>
      </div>
      <p className="tr-note">Level 0 is the ground floor. Floors line up through a reference point you mark on each.</p>
      {error && <p className="tr-err">{error}</p>}
      <div className="tr-row">
        <button className="on" disabled={!file || busy} onClick={() => void add()}>
          {busy ? "Adding…" : "Add floor"}
        </button>
        <button onClick={onDone}>Cancel</button>
      </div>
    </div>
  );
}

function FloorPanel({ floor }: { floor: TraceFloor }) {
  const image = useTrace((s) => s.images[floor.id]);
  const { updateFloor, setImage, setScale, setRef, setTool, remove } = useTrace.getState();
  const [error, setError] = useState("");
  const hasImage = !!image && image.w === floor.imageW && image.h === floor.imageH;
  const s = floorScale(floor);
  const sc = floor.scale;

  const attach = async (file: File) => {
    setError("");
    try {
      const img = await readImage(file);
      const traced = floor.rooms.length + floor.doors.length > 0 || !!floor.scale || !!floor.ref;
      if (
        traced &&
        (img.w !== floor.imageW || img.h !== floor.imageH) &&
        !window.confirm(
          `This image is ${img.w} × ${img.h} px, but ${floor.id} was traced on a ${floor.imageW} × ${floor.imageH} px image, so the shapes will not line up with it. Use it anyway?`,
        )
      ) {
        URL.revokeObjectURL(img.url);
        return;
      }
      setImage(floor.id, img);
    } catch (e) {
      setError(errText(e));
    }
  };

  return (
    <div className="tr-card">
      <div className="tr-row">
        <label>
          Name
          <input value={floor.name} onChange={(e) => updateFloor(floor.id, { name: e.target.value }, `floor:${floor.id}:name`)} />
        </label>
        <label className="tr-narrow">
          Level
          <NumField label="Level" value={floor.level} int onCommit={(v) => updateFloor(floor.id, { level: v }, `floor:${floor.id}:level`)} />
        </label>
      </div>
      <div className="tr-row">
        {hasImage ? (
          <span className="tr-note tr-ellipsis" title={image.name}>{`Image: ${image.name} (${floor.imageW} × ${floor.imageH} px)`}</span>
        ) : (
          <span className="tr-warn tr-small">{`Image missing: upload the ${floor.imageW} × ${floor.imageH} px plan again (traces keep shapes, not images)`}</span>
        )}
        <FileButton label={hasImage ? "Replace" : "Upload image"} accept="image/*" onFile={(f) => void attach(f)} />
      </div>
      {error && <p className="tr-err">{error}</p>}
      <div className="tr-row">
        <span className={sc && s > 0 ? "tr-small" : "tr-warn tr-small"}>
          {sc && s > 0 ? `Scale: ${sc.meters} m = ${round(sc.meters / s, 1)} px (${round(1 / s, 2)} px/m)` : "Scale: not set"}
        </span>
        <button onClick={() => setTool("scale")}>{sc ? "Redo" : "Set"}</button>
        {sc && <button onClick={() => setScale(floor.id, null)}>Clear</button>}
      </div>
      <div className="tr-row">
        <span className="tr-small">{floor.ref ? `Reference point: (${Math.round(floor.ref[0])}, ${Math.round(floor.ref[1])}) px` : "Reference point: not set (image corner)"}</span>
        <button onClick={() => setTool("ref")}>{floor.ref ? "Move" : "Mark"}</button>
        {floor.ref && <button onClick={() => setRef(floor.id, null)}>Clear</button>}
      </div>
      <div className="tr-row">
        <span className="tr-note">{`${floor.id}: ${floor.rooms.length} rooms, ${floor.doors.length} doors`}</span>
        <button
          className="tr-danger tr-right"
          onClick={() => {
            if (window.confirm(`Delete floor ${floor.id} and everything traced on it? Undo brings it back.`)) remove({ kind: "floor", floorId: floor.id });
          }}
        >
          Delete floor
        </button>
      </div>
    </div>
  );
}

function AiPanel({ floor, ai }: { floor: TraceFloor; ai: AiControls }) {
  const job = useTrace((s) => s.aiJob);
  const { acceptAi, discardAi, setAiJob } = useTrace.getState();
  const drafts = floor.rooms.filter((r) => r.ai).length;
  // the outcome line has done its job; a pass still running (on another floor) keeps its state
  const settle = () => {
    if (useTrace.getState().aiJob.kind !== "busy") setAiJob({ kind: "idle" });
  };
  const busy = job.kind === "busy";
  const here = job.kind !== "idle" && job.floorId === floor.id;
  // once every AI room is reviewed (or the draft is undone), the "N AI rooms" line has done its job
  const stale = job.kind === "done" && job.added > 0 && drafts === 0;
  const outcome = here && !stale ? aiOutcome(job) : null;
  return (
    <div className="tr-card">
      <div className="tr-row">
        <strong className="tr-small">AI first pass</strong>
        {busy && here ? (
          <button className="tr-right" onClick={ai.onCancel}>
            Cancel
          </button>
        ) : (
          <button
            className="tr-right"
            disabled={!!ai.why || busy}
            title={ai.why || "Send this floor's image to Claude; its rooms come back as a dashed draft (rooms only: you add the doors)"}
            onClick={ai.onRun}
          >
            {drafts > 0 ? "Propose again" : "Propose rooms"}
          </button>
        )}
      </div>
      {busy && here ? (
        <p className="tr-small">
          <span className="tr-spin" aria-hidden="true" />
          {` Waiting for Claude: ${ai.seconds} s (usually 20–60 s, at most about 2½ min)`}
        </p>
      ) : outcome ? (
        <>
          <p className={outcome.tone === "err" ? "tr-err" : outcome.tone === "warn" ? "tr-warn tr-small" : "tr-small"}>{outcome.text}</p>
          {outcome.detail && <p className="tr-note">{outcome.detail}</p>}
        </>
      ) : (
        <p className="tr-note">
          {ai.why
            ? `${ai.why}.`
            : "Claude proposes this floor's rooms from its image: a dashed draft until you edit or accept each room. Doors and stair groups stay yours to add. Public plans only."}
        </p>
      )}
      {drafts > 0 && (
        <div className="tr-row">
          <span className="tr-warn tr-small">{`${drafts} AI room${drafts > 1 ? "s" : ""} to review`}</span>
          <button
            className="tr-right"
            title="Keep every AI room on this floor as traced"
            onClick={() => {
              acceptAi(floor.id);
              settle();
            }}
          >
            Accept all
          </button>
          <button
            className="tr-danger"
            title="Remove this floor's unreviewed AI rooms (Undo brings them back)"
            onClick={() => {
              discardAi(floor.id);
              settle();
            }}
          >
            Discard AI draft
          </button>
        </div>
      )}
    </div>
  );
}

function RoomForm({ floor, room, exportId, groups, sel }: { floor: TraceFloor; room: TraceRoom; exportId: string; groups: string[]; sel: Selection }) {
  const { updateRoom, remove } = useTrace.getState();
  return (
    <div className="tr-card">
      <label>
        Name
        <input value={room.name} placeholder={`${exportId} (shown when empty)`} onChange={(e) => updateRoom(floor.id, room.id, { name: e.target.value }, `room:${room.id}:name`)} />
      </label>
      <label>
        Type
        <select value={room.type} onChange={(e) => updateRoom(floor.id, room.id, { type: e.target.value as RoomType })}>
          {ROOM_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>
      {room.type === "stair" && (
        <>
          <label>
            Stair group
            <input list="tr-stair-groups" value={room.group ?? ""} placeholder="SA" onChange={(e) => updateRoom(floor.id, room.id, { group: e.target.value }, `room:${room.id}:group`)} />
            <datalist id="tr-stair-groups">
              {groups.map((g) => (
                <option key={g} value={g} />
              ))}
            </datalist>
          </label>
          <p className="tr-note">Give this stair the same group on every floor: stairs with the same group connect.</p>
        </>
      )}
      {room.ai && (
        <div className="tr-row">
          <span className="tr-warn tr-small">Proposed by the AI first pass</span>
          <button onClick={() => updateRoom(floor.id, room.id, { ai: false })}>Mark reviewed</button>
        </div>
      )}
      <div className="tr-row">
        <span className="tr-note">{`${exportId} on ${floor.id} · ${round(roomArea(floor, room), 1)} m² · ${room.polygon.length} corners`}</span>
        <button className="tr-danger tr-right" onClick={() => remove(sel)}>
          Delete room
        </button>
      </div>
    </div>
  );
}

const KIND_TEXT = {
  exterior: "Exterior door: an exit (the normalizer adds the stub and the exit zone outside)",
  interior: "Interior door between two rooms",
  same: "The same room on both sides: move it onto a wall between two rooms",
  none: "No room on either side: move it onto a room edge",
};

function DoorForm({ floor, door, exportId, sel }: { floor: TraceFloor; door: TraceDoor; exportId: string; sel: Selection }) {
  const { updateDoor, remove } = useTrace.getState();
  const kind = useMemo(() => doorKinds(floor).get(door.id) ?? "none", [floor, door.id]);
  const width = doorWidth(floor, door);
  return (
    <div className="tr-card">
      <p className={kind === "exterior" ? "tr-exit tr-small" : kind === "interior" ? "tr-small" : "tr-err tr-small"}>{KIND_TEXT[kind]}</p>
      <div className="tr-row">
        <label className="tr-narrow">
          Width (m)
          <NumField label="Width" value={round(width, 2)} step={0.05} min={0.3} onCommit={(w) => updateDoor(floor.id, door.id, resizeDoor(floor, door, w), `door:${door.id}:width`)} />
        </label>
        <label>
          State
          <select value={door.state} onChange={(e) => updateDoor(floor.id, door.id, { state: e.target.value as DoorState })}>
            {DOOR_STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="tr-check">
        <input type="checkbox" checked={door.fireDoor} onChange={(e) => updateDoor(floor.id, door.id, { fireDoor: e.target.checked })} />
        Fire door
      </label>
      <label>
        Exit name
        <input
          value={door.name ?? ""}
          placeholder={kind === "exterior" ? "Main entrance" : "exterior doors only"}
          onChange={(e) => updateDoor(floor.id, door.id, { name: e.target.value }, `door:${door.id}:name`)}
        />
      </label>
      <p className="tr-note">Naming an exit makes a 0.9 m door 1.0 m wide.</p>
      <div className="tr-row">
        <span className="tr-note">{`${exportId} on ${floor.id}`}</span>
        <button className="tr-danger tr-right" onClick={() => remove(sel)}>
          Delete door
        </button>
      </div>
    </div>
  );
}

export default function Inspector(props: {
  messages: string[];
  exportState: ExportState;
  ai: AiControls;
  onExport: () => void;
  onDownloadPlan: () => void;
  onOpen: (id: string) => void;
  onDismiss: () => void;
}) {
  const { messages, exportState, ai, onExport, onDownloadPlan, onOpen, onDismiss } = props;
  const id = useTrace((s) => s.id);
  const name = useTrace((s) => s.name);
  const credits = useTrace((s) => s.credits);
  const floors = useTrace((s) => s.floors);
  const floorId = useTrace((s) => s.floorId);
  const selection = useTrace((s) => s.selection);
  const isPublic = useTrace((s) => s.isPublic);
  const saveError = useTrace((s) => s.saveError);
  const { setMeta, setPublic, setFloor, loadDraft } = useTrace.getState();
  const [adding, setAdding] = useState(false);
  const [fileError, setFileError] = useState("");

  const sorted = useMemo(() => [...floors].sort((a, b) => a.level - b.level), [floors]);
  const floor = floors.find((f) => f.id === floorId) ?? null;
  const ids = useMemo(() => exportIds({ id, name, credits, floors }), [id, name, credits, floors]);
  const groups = useMemo(
    () => [...new Set(floors.flatMap((f) => f.rooms.filter((r) => r.type === "stair" && r.group?.trim()).map((r) => (r.group ?? "").trim())))].sort(),
    [floors],
  );
  const selFloor = selection ? floors.find((f) => f.id === selection.floorId) : undefined;
  const selRoom = selection?.kind === "room" ? selFloor?.rooms.find((r) => r.id === selection.id) : undefined;
  const selDoor = selection?.kind === "door" ? selFloor?.doors.find((d) => d.id === selection.id) : undefined;
  const errors = messages.filter(isError).length;
  const warnings = messages.length - errors;
  const busy = exportState.kind === "busy";

  /** A check message names a room, door or floor: select it. */
  const pick = (m: string) => {
    const st = useTrace.getState();
    const item = /\b(?:room|door) ([RD]\d+)\b/.exec(m);
    const ref = item ? ids.byExport.get(item[1] ?? "") : undefined;
    if (ref) {
      st.setTool("select");
      st.select({ kind: ref.kind, floorId: ref.floorId, id: ref.id });
      return;
    }
    const fl = /\bfloor (\S+)/.exec(m);
    const f = fl ? floors.find((x) => x.id === fl[1]) : undefined;
    if (f) setFloor(f.id);
  };

  const saveTrace = () => downloadJson(`${id.trim() || "trace"}.trace.json`, { version: "trace/v0", ...traceOf(useTrace.getState()) });

  const loadTrace = async (file: File) => {
    setFileError("");
    try {
      const raw: unknown = JSON.parse(await file.text());
      const t = readTrace(raw);
      if (!t) {
        const v = (raw as { version?: unknown } | null)?.version;
        setFileError(`${file.name} is not a trace${typeof v === "string" ? ` (it is ${v})` : ""}; Load trace takes the files Save trace writes`);
        return;
      }
      loadDraft(t);
    } catch (e) {
      setFileError(`${file.name}: ${errText(e)}`);
    }
  };

  return (
    <aside className="tr-inspector">
      <section>
        <h3>Building</h3>
        <label>
          Name
          <input value={name} placeholder="Example office" onChange={(e) => setMeta({ name: e.target.value }, "meta:name")} />
        </label>
        <label>
          Id
          <input value={id} placeholder="example-office" spellCheck={false} onChange={(e) => setMeta({ id: e.target.value }, "meta:id")} />
        </label>
        <label>
          Credits (required)
          <textarea rows={2} value={credits} placeholder="Where the plan image comes from, and its license" onChange={(e) => setMeta({ credits: e.target.value }, "meta:credits")} />
        </label>
        <label className="tr-check">
          <input type="checkbox" checked={isPublic} onChange={(e) => setPublic(e.target.checked)} />
          Public
        </label>
        <p className={isPublic ? "tr-warn tr-small" : "tr-note"}>
          {isPublic
            ? "Public: saved to data/buildings/, which is committed and can reach the static site. Never for UMass plans."
            : "Private (default): saved to data/private/, which stays out of git."}
        </p>
      </section>

      <section>
        <h3>Floors</h3>
        <div className="tr-tabs">
          {sorted.map((f) => (
            <button key={f.id} className={f.id === floorId ? "on" : ""} onClick={() => setFloor(f.id)} title={`${f.id}, level ${f.level}`}>
              {f.name || f.id}
              <small>{` L${f.level}`}</small>
            </button>
          ))}
          <button className={adding ? "on" : ""} onClick={() => setAdding(!adding)}>
            + Floor
          </button>
        </div>
        {adding && <AddFloor onDone={() => setAdding(false)} />}
        {floor && <FloorPanel floor={floor} />}
        {floor && <AiPanel floor={floor} ai={ai} />}
      </section>

      <section>
        <h3>Selection</h3>
        {selection && selFloor && selRoom ? (
          <RoomForm floor={selFloor} room={selRoom} exportId={ids.byTrace.get(selRoom.id) ?? "?"} groups={groups} sel={selection} />
        ) : selection && selFloor && selDoor ? (
          <DoorForm floor={selFloor} door={selDoor} exportId={ids.byTrace.get(selDoor.id) ?? "?"} sel={selection} />
        ) : (
          <p className="tr-note">Nothing selected. With Select (V), click a room or a door to edit it.</p>
        )}
      </section>

      <section>
        <h3>
          Checks
          {errors > 0 && <span className="tr-badge err">{`${errors} error${errors > 1 ? "s" : ""}`}</span>}
          {warnings > 0 && <span className="tr-badge warn">{`${warnings} warning${warnings > 1 ? "s" : ""}`}</span>}
        </h3>
        {messages.length === 0 ? (
          <p className="tr-ok">No problems found.</p>
        ) : (
          <ul className="tr-msgs">
            {messages.map((m, i) => (
              <li key={i} className={isError(m) ? "err" : "warn"} onClick={() => pick(m)} title="Click to select what it names">
                {m.replace(/^(error|warning): /, "")}
              </li>
            ))}
          </ul>
        )}
        <p className="tr-note">Errors block the export; warnings are advice.</p>
      </section>

      <section>
        <h3>Export</h3>
        <button className="tr-primary" disabled={errors > 0 || busy} onClick={onExport} title={errors > 0 ? "Fix the errors above first" : "Send plan/v0 to the API"}>
          {busy ? "Exporting…" : "Export"}
        </button>
        <p className="tr-note">{`POST /api/buildings/from-plan?public=${isPublic}: saved to ${isPublic ? "data/buildings/" : "data/private/"}, then opened in the 3D view.`}</p>
        {exportState.kind === "done" && (
          <div className="tr-result">
            <strong className="tr-ok">{`Saved as ${exportState.id}.`}</strong>
            {exportState.warnings.length > 0 && (
              <>
                <span>The normalizer says:</span>
                <ul className="tr-msgs">
                  {exportState.warnings.map((w, i) => (
                    <li key={i} className="warn">
                      {w.replace(/^WARNING \((normalize|store)\):\s*/, "")}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <div className="tr-row">
              <button className="on" onClick={() => onOpen(exportState.id)}>
                Open in 3D
              </button>
              <button onClick={onDismiss}>Keep tracing</button>
            </div>
          </div>
        )}
        {exportState.kind === "failed" && (
          <div className="tr-result">
            <span className="tr-err">{exportState.message}</span>
            <span className="tr-note">You can download the plan instead, fix it by hand if needed, and POST it to /api/buildings/from-plan later.</span>
            <div className="tr-row">
              <button className="on" onClick={onDownloadPlan}>
                Download plan.json
              </button>
              <button onClick={onDismiss}>Dismiss</button>
            </div>
          </div>
        )}
        <div className="tr-row">
          <button onClick={onDownloadPlan} title="The plan/v0 the export sends; works with errors too">
            Download plan.json
          </button>
          <button onClick={saveTrace} title="The drawing in image pixels, without the images">
            Save trace
          </button>
          <FileButton label="Load trace" accept=".json,application/json" onFile={(f) => void loadTrace(f)} />
          <button
            onClick={() => {
              if (window.confirm("Start a new, empty trace? Undo brings the current one back.")) loadDraft(EMPTY_TRACE);
            }}
          >
            New
          </button>
        </div>
        {fileError && <p className="tr-err">{fileError}</p>}
        {saveError && <p className="tr-err">{saveError}</p>}
        <p className="tr-note">The trace autosaves in this browser, without the images: after a reload, upload each floor's image again.</p>
      </section>
    </aside>
  );
}
