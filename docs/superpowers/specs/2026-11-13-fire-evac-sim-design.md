# Fire Evacuation Simulator — Design v1

**Date:** Fri 2026-11-13, 11 PM ET · **Event:** HackUMass XIV (36 h; hacking began 8:30 PM Fri; submission assumed ~8:30 AM Sun, confirm) · **Team:** 5
**Supersedes:** `docs/context/prior-drafts/2026-11-13-fire-evac-sim-design.md`. Research and numbers: `docs/context/01`–`11`.

## 1. Intent

**Pitch:** give us a building, and we'll show where people get stuck before a fire does.

**Lead story (decided): find the chokepoints.** The hero result is a risk map over many fire locations plus a ranked list of the 3–5 worst spots (doors, stairs, corridors), each with the numbers behind it and a suggested fix. Everything else supports that story.

**Success:** a 3-minute demo where (1) a real building appears in 3D, (2) a judge clicks to start a fire and watches queues form at a chokepoint, (3) one what-if (propped stair door) visibly makes it worse, and (4) the risk map and ranked weak spots answer "where should this building worry?"

**Prizes in view:** Best Software and the overall prizes (lead), Best UMass Hack (UMass building through the tracer), Most Impactful AI and MLH Best Use of Gemini (AI reads the plan and writes the report), Best UI/UX. Accessibility is a stretch goal, not the lead.

## 2. Goals, non-goals, anti-goals

**Goals:** see Scope (§9).

**Non-goals:** code compliance; elevators; CFD (FDS); live simulation of thousands of agents; accounts, auth or a database; a mobile app.

**Anti-goals** (failure even if it technically works):
- The demo only works on the synthetic building.
- Results look precise but rest on hidden assumptions. Assumptions sit next to results; the fire model is labeled illustrative.
- A "panic mode", or framing slow evacuees as the problem instead of the building.
- Weak-spot maps of a real UMass building in the public repo, on Devpost or in the video.
- LLM-driven agents in batch runs or what-if comparisons (slow, costly, unrepeatable). An all-LLM crowd is a stretch-goal showcase mode instead (§7.5, §9).

## 3. Constraints

- About 33 h of build time. The demo must survive bad Wi-Fi: static site with precomputed runs, live runs from a laptop.
- Tools: the user is on Claude Max (Claude Code with subagents, overnight runs); teammates are on Claude Pro (Claude Code) or ChatGPT Plus (Codex). Team rules live in `AGENTS.md`, which Codex reads; `CLAUDE.md` is the single line `@AGENTS.md`.
- One strong frontend dev; the rest mainly Python.
- Windows and macOS laptops: Python 3.12, Node 20+. JuPedSim 1.4.2 and IfcOpenShell 0.9 ship wheels for both.
- Data licenses (`docs/context/08-buildings-data.md`): credit every source. The 2007 UMass plans are "credit, don't redistribute", so traced UMass data stays in `data/private/` (gitignored).

## 4. Approaches considered

| Decision | Options | Picked | Why |
| --- | --- | --- | --- |
| Building input | IFC first · plan tracer first · both | **Both in parallel** (team) | IFC gives a richly labeled public building with no tracing; the tracer delivers "plan → 3D" and works on UMass plans and judges' plans. Whichever lands first is the demo building. Both feed one normalizer, so nothing downstream cares |
| Lead story | chokepoints · who waits for help · AI evacuees | **Chokepoints** (team) | Strongest general demo; the batch risk map moves into P0 |
| Crowd engine | JuPedSim · own floor-field cellular automaton in the browser · Vadere | **JuPedSim** (planning session) | Published models, Python API, measured speed and door flow (`07`). A browser automaton would allow live runs but is our own unvalidated model in one big shared TypeScript codebase; Vadere is Java |
| Smoke | grid diffusion (draft) · smoke front on the grid · CFAST | **Smoke front** (my call) | Diffusion spreads in every direction and needs tuning to look right. A front that travels along open paths is cheap, controllable, easy to explain, and gives every spot a "time until unsafe" |
| App LLM | Gemini · Claude | **Gemini** (team) | MLH Gemini prize; one wrapper, swappable |
| LLM agents | situation cache plus live agents (draft) · live agents only, logged · every agent an LLM | **Logged live agents (P2); every agent an LLM as a stretch showcase mode** (team + my call) | No cache to build; decisions saved in the run file keep replays identical; batch runs and what-if comparisons stay rule-based |

## 5. Architecture

```
plan image ─► [A] tracer page (+ Gemini first pass) ─┐
                                                     ├─► plan.json ─► [B] normalize ─► building.json
IFC model ──► [B] ifc extract ───────────────────────┘                                     │
scenario.json (from the UI) ───────────────────────────────────────────────────────────────┤
                                                                                           ▼
                                        [C] sim (JuPedSim, one per floor) ◄─ step/query ─► [D] fire (smoke front)
                                                          │
                                                          ▼
                                      run.json (+ metrics from [D]) ──► [D] batch ──► batch.json
                                                          │                                │
                                   [A] FastAPI + Gemini (plan first pass, report) ◄────────┤
                                                          ▼                                ▼
                                    [E] 3D replay · dashboard · risk map · what-if   (+ [A] tracer page)
```

Letters are workstreams (§10).

### Repo layout

```
AGENTS.md  CLAUDE.md  README.md  requirements.txt  .env.example  .gitignore
contracts/        *.example.json for every contract (the source of truth)
tools/            build_examples.py, plot_building.py, precompute_demo.py
buildings/        normalize.py, ifc.py, inspect_ifc.py, overrides/      (B)
sim/              run.py, floors.py, brain.py, profiles.py              (C)
fire/             stub.py, model.py, presets.py, metrics.py, batch.py   (D)
backend/app/      main.py, jobs.py      backend/llm/  client.py, features.py   (A)
frontend/         Vite app: src/replay, src/dashboard (E) · src/tracer (A) · src/data (shared types + loader)
data/raw/  data/buildings/  data/runs/  data/private/   (downloaded or generated; gitignored except chosen demo files)
docs/context/  docs/superpowers/specs/  docs/superpowers/plans/
```

## 6. Contracts v0

Frozen at kickoff: rename or remove a field only by team agreement; new optional fields are fine. Units are meters, coordinates are floor-local. Every file carries `"version"`. The example files in `contracts/` are the source of truth; `frontend/src/data/types.ts` mirrors them.

**plan/v0**: what both input paths produce.
- `{version, id, name, source: "ifc"|"trace"|"synthetic", credits, floors[]}`
- floor: `{id, level, elevation, height, rooms[], doors[]}`
- room: `{id, name, type, polygon, group?}`. `type` is one of office, classroom, kitchen, dining, lounge, bedroom, lab, storage, restroom, corridor, lobby, stair, other. Stairwells are rooms with `type: "stair"` and a `group`; the same group on consecutive floors means they connect.
- door: `{id, a, b, width, fireDoor, state, rect?}`. `a` and `b` are the endpoints of the opening along the wall. `state` is open, closed or propped. A door in the building's outside wall is an exterior door. `rect` (optional) is the opening's own footprint, for IFC doors.

**building/v0**: what `normalize(plan)` returns, and what the sim and renderer use.
- `{version, id, name, source, credits, floors[]}`
- floor: `{id, level, elevation, height, walkable[], rooms[], doors[], stairs[], exits[]}`
- `walkable[]`: `{outer, holes}` rings. **Walls are the boundary of the walkable area**: the renderer extrudes the rings, and door gaps come for free.
- `doors[]`: the plan fields plus `connects: [roomId, roomId | "outside"]` and `rect`.
- `stairs[]`: `{id, group, room, polygon}`.
- `exits[]`: `{id, name, door, polygon}`. Exits may be on any floor (sloped sites like the Student Union have exits on several levels).

How `normalize` builds the walkable area (B owns it; the tracer and the example building depend on it):
1. Shrink every room by half a wall: 0.1 m for traced plans, so rooms drawn edge to edge get a wall between them. IFC spaces already stop at the walls.
2. Each door becomes a rectangle across the wall, reaching 0.2 m into the rooms on both sides (or its `rect`).
3. Each exterior door gets a 2 m stub outside the wall, and the exit polygon is the far end of the stub. **Never draw exit zones against a wall:** JuPedSim then lets people out about 4× faster per meter (`07`).
4. walkable = union(rooms, door rectangles, stubs). Warn about disconnected pieces and unreachable rooms.

**scenario/v0**: `{version, id, buildingId, seed, occupants: {total | perRoom: {roomId: n}, mix: {profile: share}}, fire: {floor, room, x, y, type, growth?, start, material?}, sprinklers, doors: {doorId: open|closed|propped|blocked}, alarmTime, maxTime}`
- `fire.type` is a preset: kitchen, bedroom, battery, trash, liquid (§7.3). `growth` overrides the preset's growth class.
- `fire.material` (optional): `concrete`, `drywall` (the default when absent) or `wood`, the illustrative room-to-room spread speed (`fire/spread.py`, `fire/README.md`). Any other value is an error.
- Door states for people: open, closed and propped are passable; `blocked` is not (blocked-exit what-if). For smoke: closed doors hold it back; open and propped doors don't.
- P0 profiles: `typical`, `older`, `visitor`. P1 adds `cane`, `walker`, `wheelchair`.
- `brain` (optional, P2): `rules` (default), `mixed` (10–20 LLM agents), or `llm` (every agent asks the LLM).

**run/v0**
- `{version, id, buildingId, scenarioId, seed, frameInterval: 0.5, floors: [floorId, …], agents[], frames[], smoke[], fire, events[], metrics}`
- `agents[]`: `{idx, profile, floor, room, v0, startDelay}`. `idx` is ours, never JuPedSim's id.
- `frames[]`: `{t, a: [[idx, x, y, floorIdx, status], …]}`, coordinates rounded to 0.01 m. Status: 0 not moving yet, 1 moving, 2 waiting for help, 3 in a stairwell (drawn at the stair). An agent disappears after its `exit` event.
- `smoke[]`: per floor `{floor, origin, cell, cols, rows, interval: 2, frames: [{t, d}]}`. `d` is base64 of a row-major Uint8 array with values 0–100, which feeds a Three.js DataTexture directly.
- `fire`: `{floor, x, y, hrr: [[t, kW], …], rooms?, material?}`.
- `fire.rooms` (optional): `[{room, floor, ignite}]`, every room that catches fire by `maxTime`, sorted by `ignite` (s); the first is the ignition room, at the fire's `start`. `fire.material`: the material the run used. `sim/run.py` writes both whenever the run has a fire model. `hrr` is the total of every burning room. A person inside a burning room is trapped with `reason: "burning room"`.
- `events[]`: `{t, type, idx?, …}`. Types: exit, reroute, trapped, wait, door_blocked, llm (carries `reason`).
- `metrics`: `{agents, evacuated, trapped, t50, t90, t100, exitCounts}` from the sim. `fire.metrics.compute` adds `doors: [{id, floor, peakQueue, waitPersonSeconds, flow}]`, `heatmaps: [{floor, origin, cell, cols, rows, d}]` and (P1) `rooms: [{id, rset, aset, margin}]`.

**batch/v0**: `{version, id, buildingId, base, runs: [{scenarioId, seed, ignition: {floor, room}, t90, t100, trapped}], rooms: [{id, floor, riskT90, riskTrapped, n}], doors: [{id, floor, meanWait, peakQueue, score}], heatmaps[], top: [{kind: door|stair|corridor|exit|room, id, floor, score, why}]}`. `base` is the scenario the batch varies. `why` is one line with numbers, for example "Stair SB door: 41 people queued at peak; 2,300 person-seconds of waiting across 36 fires."

## 7. Components

### 7.1 Buildings (B; tracer page by A)

- **IFC path:** run `buildings/inspect_ifc.py` first (counts of storeys, spaces, doors and stairs; unit scale) and pick the model with spaces on every storey and at least two stairs. `buildings/ifc.py` then extracts plan/v0: space footprints (project triangles to 2D and union them), doors from `IfcDoor` footprints and `OverallWidth`, stair rooms from spaces or `IfcStair` footprints, grouped by XY overlap across storeys. Hand fixes go in `buildings/overrides/<id>.json`. Candidates: NIBS office or clinic, VTT office (CC BY-SA).
- **Tracer path:** per floor, upload an image and set the scale (click two points, type the length). Optionally ask Gemini for a first pass. Then draw or fix rooms as rectangles or polygons (snapped to a grid), place doors on walls, label stairs and their groups, and mark exterior doors. Floors line up through a shared reference point. Export plan/v0 to `POST /api/buildings/from-plan`. UMass target: the Student Union, 2007 plans (`08`).
- **Demo buildings:** the synthetic 2-floor example (always works), one IFC building, and the traced Student Union (private).

### 7.2 Crowd simulation (C)

- JuPedSim 1.4.2 `CollisionFreeSpeedModel`, one `Simulation` per floor, stepped together at 0.01 s.
- **Stairs:** an agent who reaches a stair zone is removed and re-added in the same group's zone one floor down after (stair length ÷ stair speed). A FIFO per stair group caps throughput at about 1.1 persons/s per meter of stair width.
- **Exits:** one exit stage per exit polygon; journeys target the chosen exit or stair, and JuPedSim routes within the floor. `jps.RoutingEngine` can give path lengths for exit choice (check on 1.4.2).
- **Brain** (every 1 s and on events): P0 cost is route time plus queue time (`d/v + q/F`). Pick with a seeded softmax and switch only if the new choice is 20% better (`05-agent-design.md`). P1 adds smoke and familiarity terms. The brain sits behind one interface, `decide(obs) -> {target, action, reason} | None`: rules now, an LLM implementation later (P2), and `None` falls back to rules.
- **Start delay:** an agent stays put until the alarm plus its profile delay (status 0, kept out of JuPedSim).
- **Fire coupling** (every 1 s): `desired_speed = min(v0, max(0.2, v0 − 0.34·(3 − S)))` with S from `fire.visibility`. `fire.untenable` marks an agent trapped. `fire.blocked_doors()` makes agents who can see the door (or hear the alarm message) re-plan.
- Doors that are `blocked` in the scenario are removed from the geometry before the run.
- **Determinism:** all randomness comes from `scenario.seed`. Check `removed_agents()` every iteration.

### 7.3 Fire and smoke (D): starting values, which D tunes and documents

- **Heat release:** `Q(t) = min(α·t², Q_peak)`, with α by growth class (slow 0.00293, medium 0.01172, fast 0.04688, ultra-fast 0.1876 kW/s²). Presets: kitchen fast/1.5 MW, bedroom medium/3 MW, battery ultra-fast/1 MW with 2× smoke, trash fast/0.5 MW, liquid instant/1.5 MW. Sprinklers cap Q at 0.5 MW.
- **Smoke front:** a grid of 0.5 m cells per floor over the walkable mask. Compute the path distance from the fire through walkable cells (Dijkstra, 8 neighbors). A closed door adds 15 m. Stairwells link floors: +3 m going up, +30 m going down. Smoke reach is `R(t) = ∫ v_s dt` with `v_s = clamp(0.25 + 0.5·Q/1000, 0.25, 1.0)` m/s. A cell's arrival time `T_c` is when R reaches its distance.
- **Density** after arrival: `d = 100 · min(1, Q/1000) · smokeFactor · e^(−dist/40) · (1 − e^(−(t − T_c)/30))`.
- **Visibility:** `S = min(30, 100/d)` meters (d = 100 gives 1 m; d = 33 gives 3 m).
- **Untenable:** inside the fire's footprint (it grows with Q), or d ≥ 90 for 30 s. Doors with untenable cells go into `blocked_doors()`. A cell's ASET is the time it becomes untenable (P1 margins).
- **API** (as in the draft): `FireModel(building, scenario)` with `step(t)`, `visibility(floor, x, y)`, `untenable(floor, x, y)`, `blocked_doors()` and `snapshot(floor)`. `fire.stub.NoFire` has the same API.

### 7.4 Metrics, batch and ranking (D)

- `fire.metrics.compute(run, building)`: t-values, exit counts; per door and stair, the peak queue and person-seconds of waiting (agents within 2 m of the opening per frame) and the flow; density heatmaps.
- `fire.batch.run_many(building, base, ignitions=None, seeds=(1, 2, 3), workers=None)`: one fire per room (or 20–50 sampled rooms) × seeds, in a process pool, with rule-based agents only.
- **Ranking:** score doors and stairs by mean person-seconds of waiting and peak queue, and rooms by mean t90 and trapped when the fire starts there. `top` holds the 3–5 worst spots, each with a `why`. P2: exit criticality (re-run with each exit blocked).

### 7.5 Backend and LLM (A)

- **FastAPI under `/api`:**
  - `GET /buildings`, `GET /buildings/{id}`, `POST /buildings/from-plan`
  - `POST /runs` → `{runId}`, `GET /runs/{id}` (status, or run/v0 when done)
  - `POST /batch`, `GET /batch/{id}`
  - `POST /trace/propose` (image → draft plan floor)
  - `POST /report` (`{runId | batchId}` → markdown)

  Runs go through a process pool and are saved as files in `data/runs/`. Until C lands, `POST /runs` returns the example run.
- **`backend/llm/client.py`:** Gemini through the `google-genai` SDK, with `GEMINI_API_KEY` and `GEMINI_MODEL` from `.env`, JSON-schema structured output, a timeout, and `None` on failure. `LLM_PROVIDER=claude` switches to Anthropic with `APP_ANTHROPIC_API_KEY`.
- **Features:** `propose_plan(image, hints)` (the tracer's first pass) and `report(batch | run, building)` (top weak spots, the numbers, fixes, one line on limits). P2: personas, and live LLM agents (C calls `llm.decide(obs)` at junctions; decisions are logged as `llm` events).
- **Stretch: LLM crowd mode** (`brain: "llm"`). Every agent's decisions come from Gemini at decision points: starting to move, junctions, seeing smoke, a blocked or long-queued door. One call per decision tick decides for every agent at a decision point (`llm.decide_batch(observations) -> decisions`), with a timeout and rule fallback. Showcase runs only (up to ~150 agents), precomputed and replayed from the logged decisions. Batch and what-if runs stay rule-based.

### 7.6 Frontend (E; tracer page by A)

- Vite + React + TypeScript, three + @react-three/fiber + drei, Recharts, Zustand. One loader reads static `public/demo/*.json` (listed in `public/demo/index.json`) or the API (`VITE_API_URL`).
- **Screen** (`09`): top bar (building, scenario tabs); left panel (scenario: click to place the fire, preset, occupants, door states, run); 3D in the center; results on the right; a scrubber at the bottom (play, pause, 1–10×, event marks).
- **3D:**
  - walls extruded from the walkable rings, with wall height tweening up on load;
  - floors stacked, with an explode slider;
  - agents as one InstancedMesh, interpolated between frames and colored by status;
  - smoke as a DataTexture plane per floor, and a fire marker scaled by heat release;
  - a heatmap overlay, and queue rings with counts at doors and stairs.
- **Results:** evacuation curve (baseline and what-if overlaid), exit use, ranked weak spots (click one and the camera flies there), risk map (rooms colored by fire-start risk, doors and stairs by chokepoint score), report card.
- **What-if:** P0 runs the same fire with a propped stair door, overlays the two curves, and switches the replay between the runs. P1 is a synced split screen.

## 8. Demo (3 min)

1. **Hook (15 s):** "Where would people get stuck if this building caught fire? Today that takes an engineer and specialist software."
2. **Building in (30 s):** a traced plan rises into 3D (UMass Student Union), or the IFC building does.
3. **Judge's fire (45 s):** a judge clicks a room. It runs live, or loads the nearest precomputed run. Queues ring a stair and the heatmap glows.
4. **What-if (30 s):** prop the stair door open. Smoke climbs the stairwell and the curve shifts right.
5. **Risk map (40 s):** fires in every room produce the map and the top weak spots, with fixes in the report card.
6. **Credibility (20 s):** door flow against published values, the fire model labeled illustrative, the limits.

**Demo-proofing:** precompute every scenario we'll show; keep a static site plus the laptop backend; record a backup video.

## 9. Scope

- **P0 (the demo depends on it):**
  - the synthetic building, plus at least one real building (IFC or traced);
  - a multi-floor sim with stairs and queue-aware exit choice;
  - the smoke front coupled to agents (it slows them, traps them and blocks doors);
  - per-run metrics with door queues and a heatmap;
  - 3D replay with smoke, heatmap and queue rings, plus the evacuation curve;
  - the propped-stair-door what-if;
  - **the batch risk map and ranked chokepoints**.
- **P1:** report card (Gemini); the second real building; Gemini's first pass in the tracer; synced split screen; blocked-exit and sprinkler what-ifs; mobility profiles and waiting for help; RSET/ASET margins; door-flow calibration chart.
- **P2:** accessibility lens; live LLM agents (10–20 per run); **every agent an LLM (showcase mode)**; personas; exit criticality; trails; agent's-eye view; web-ifc overlay; CFAST.

## 10. Workstreams and schedule

| WS | Owner | Owns (folders) |
| --- | --- | --- |
| A | the user (Max) | Repo, contracts, tonight's scaffold, `backend/`, Gemini features, the tracer page (`frontend/src/tracer`), integration and merges, demo precompute, Devpost and video |
| B | Python + geometry | `buildings/`: normalizer (after the scaffold's v0), IFC extraction, overrides, UMass trace (with A) |
| C | Python + algorithms | `sim/`: multi-floor JuPedSim (after the scaffold's single-floor v0), stairs, brain, fire coupling |
| D | NumPy | `fire/`: smoke front, metrics, batch, ranking |
| E | the strong frontend dev | `frontend/` except `src/tracer`: the app from scratch, replay, dashboard, risk map, what-if |

**Nobody waits:** everyone codes against `contracts/*.example.json`. C uses `fire.stub.NoFire` until D lands, E renders the example run, and A's API serves the examples until C lands.

| Clock (ET) | Everyone can see |
| --- | --- |
| Fri 11:45 PM | Spec and plans on GitHub; everyone has cloned and is installing; B is downloading IFC candidates; E is starting the Vite app |
| Sat 12:45 AM | Scaffold pushed: example files, normalizer v0, single-floor sim v0, API serving the examples |
| Sat 2 AM | Walking skeleton: example building → sim → run.json → 3D replay. IFC model picked |
| Sat 10 AM | A real building end to end; multi-floor; smoke visible |
| Sat 4 PM | Smoke slows and blocks people; metrics, heatmap and queue rings on screen; propped-door what-if |
| Sat 10 PM | Batch risk map and ranked chokepoints on screen; report card; second building |
| Sun 2 AM | Feature freeze; demo runs precomputed; static site live |
| Sun 2–7 AM | Devpost, video, slides, rehearsal |
| Sun ~8 AM | Submit |

Sleep in shifts after the 2 AM sync; the user's agents can run long jobs overnight.

## 11. Working agreements (these go into AGENTS.md)

- **Speed over rigor:** no TDD. Each module has one `smoke_test.py` that runs on the example files; run it before each push. No separate code-quality review unless something broke.
- **Stay in your folders.** Shared files (`contracts/`, `AGENTS.md`, `requirements.txt`, `frontend/src/data/`) change only through small PRs that A merges.
- **Branches:** one per workstream (`ws-a` … `ws-e`). Push at least hourly, open a PR to `main` at least every 2 h, and merge `main` back in at each sync.
- **Determinism:** seed everything from `scenario.seed`; key agents by `idx`.
- **Secrets:** `.env` holds `GEMINI_API_KEY`. Never export `ANTHROPIC_API_KEY` in a shell where Claude Code runs: Claude Code would bill that key instead of your plan.
- **Big files:** inspect run JSON with `jq` or `head -c`; never read it whole.
- **Per tool:**
  - Claude Pro: Sonnet at medium effort, `superpowers:executing-plans`, one plan task per session, then `/clear`; `acceptEdits` mode.
  - Codex: reads `AGENTS.md` on its own; work through your plan's checklist in order.
  - The user (Max): subagent-driven development, auto mode for long runs.

## 12. Ethics and credits

- Not a compliance tool: say so in the UI and the pitch.
- Label the fire model illustrative, and keep assumptions next to results.
- No panic mode. Frame long waits as gaps in the building, not traits of people.
- No personal data.
- Credit every data license in the app and on Devpost.
- The UMass trace and its results stay in `data/private/`, out of the public repo, Devpost and the video.

## 13. Risks and fallbacks

| Risk | Fallback |
| --- | --- |
| IFC models lack spaces or stairs | Next candidate; else the traced building |
| Tracer page runs long | Hand-edit plan JSON with `plot_building.py` previews; or rely on IFC |
| Stair transfer is fiddly | Single floor, with stair doors as exits |
| Batch too slow | Fewer rooms or seeds; run overnight on the user's laptop |
| Run files too big | Agent frames every 1 s, smoke every 5 s, fewer agents |
| 3D performance | Instancing; else a 2D canvas replay |
| Gemini slow or down | Template report; tracer without AI |
| Live demo fails | Precomputed runs plus the video |

## 14. Left to the builders

- Exact smoke constants (D; documented in `fire/README.md`).
- Exit-choice weights (C).
- Which IFC model (B, after inspection).
- Visual style (E).
- Gemini model version and prompts (A).
