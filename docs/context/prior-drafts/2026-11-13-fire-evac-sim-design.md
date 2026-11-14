# Fire Evacuation Simulator — Design

**Date:** 2026-11-13 · **Team:** 5 · **Mode:** hackathon (36 h). Speed beats rigor; see Testing.

## Goal

Load a building (an open IFC model, or a traced plan image), place a fire, simulate a few hundred evacuees, and show where people get stuck: a 3D replay, heatmaps, a ranked list of weak spots, and a plain-language report.

## Decisions (defaults; change any of them at kickoff)

| Area | Decision |
| --- | --- |
| Building input | **P0:** IFC models (NIBS clinic or office, VTT office). **P1:** tracing editor for plan images and photos |
| Dev building | `contracts/building.example.json` (synthetic, 2 floors) until a real IFC building parses |
| Crowd | JuPedSim 1.4 `CollisionFreeSpeedModel`, one simulation per floor stepped in lockstep, stair transfer between floors |
| Fire | Own NumPy grid model, t-squared growth, smoke to visibility to walking speed |
| Frontend | React + Vite + TypeScript, react-three-fiber; the replay runs from static JSON files |
| Backend | FastAPI; scenarios run in a process pool; results saved as files |
| LLM | Gemini behind one wrapper (`backend/llm`), swappable to Claude. Used for personas, the report, situation-cached decisions and 10–20 live LLM agents |
| Hosting | Static replay site (Vercel or GitHub Pages) with precomputed runs; live runs from a laptop backend |
| Testing | One smoke test per module, no TDD |

## Scope tiers

- **P0 (the demo depends on it):** IFC to `building.json`; multi-floor simulation with stairs and exit choice; fire grid with smoke slowing people and blocking routes; 3D replay with smoke and a heatmap; evacuation curve and basic metrics; one what-if (stair door propped open).
- **P1:** batch over ignition points, then a risk map and weak-spot ranking; LLM report card; personas; situation-cached LLM decisions plus live LLM agents with reasoning tooltips; split-screen what-if; accessibility lens; tracing editor.
- **P2:** calibration chart against Jülich bottleneck data; agent's-eye view; trails; exit criticality; CFAST import; web-ifc rendering of the original model.

## Architecture

```
IFC model / traced plan ──► [B] buildings ──► building.json ─────────────┐
scenario.json (from UI) ──────────────────────────────────────────────────┤
                                                                          ▼
                                              [C] sim  ◄── step(t) ──►  [D] fire
                                                   │
                                                   ▼
                                              run.json ──► [D] metrics / batch ──► metrics.json
                                                   │                                   │
              [A] FastAPI + llm (personas, decide, report) ◄───────────────────────────┤
                                                   │                                   │
                                                   ▼                                   ▼
                                     [E] frontend: 3D replay, dashboard, risk map, report
```

Letters are workstreams; each has its own plan in `docs/superpowers/plans/`.

## Repo layout

```
contracts/            building.example.json, run.example.json   (frozen v0 contracts)
tools/                build_examples.py, plot_building.py
buildings/            IFC -> building.json (B); tracing helpers (B, P1)
sim/                  JuPedSim runner, agents, routing (C)
fire/                 fire grid, metrics, batch (D)
backend/app/          FastAPI (A)      backend/llm/   LLM wrapper (A)
frontend/             React + r3f app (E)
data/raw/  data/buildings/  data/runs/   (generated; only demo picks are committed)
docs/superpowers/specs/  docs/superpowers/plans/
```

## Contracts (v0, frozen at kickoff)

Change field names only by team agreement in chat; new optional fields are fine. Coordinates are meters, floor-local.

**building/v0** (see `contracts/building.example.json`)
- `floors[]`: `id`, `level`, `elevation`, `height`
- `walkable[]`: `{outer, holes}` rings. **Walls are the boundary of the walkable area**: the renderer extrudes boundary rings, and door gaps come for free
- `rooms[]`: `{id, name, type, polygon}`; types include `office`, `kitchen`, `lounge`, `bedroom`, `lab`
- `doors[]`: `{id, a, b, width, fireDoor, state, connects}`; state is `open`, `closed` or `propped`
- `stairs[]`: `{id, group, polygon}`; stairs sharing a `group` connect consecutive floors
- `exits[]`: `{id, name, polygon}`; ground floor only

**scenario/v0**: `{id, buildingId, seed, occupants: {perRoom | total, mix}, fire: {floor, room, x, y, type, growth, start}, doors: {doorId: state}, alarmTime, maxTime}`

**run/v0** (see `contracts/run.example.json`)
- `agents[]`: `{idx, profile, floor, room, target, v0}`; `idx` is ours, never JuPedSim's agent id
- `frames[]`: `{t, a: [[idx, x, y, floorIdx, status]]}` every `frameInterval` s; status 0 = not moving yet, 1 = moving, 2 = waiting for help
- `smoke[]`: per floor `{floor, origin, cell, cols, rows, frames: [{t, d: [0..100 row-major]}]}`
- `events[]`: `{t, type, idx, ...}` with types `exit`, `reroute`, `trapped`, `wait`, `llm` (`llm` carries `reason`)
- `metrics`: `{agents, evacuated, trapped, t50, t90, t100, exitCounts}`

**metrics/v0** (batch output): `{buildingId, runs: [{scenarioId, seed, ignition, t90, t100, trapped}], rooms: [{room, floor, riskT90, riskTrapped}], doors: [{id, peakQueue, waitPersonSeconds}], heatmaps: [{floor, cell, cols, rows, counts}], top: [{kind, id, why}]}`

## Module APIs (so nobody blocks)

- **B:** `buildings.ifc.load(path) -> dict` (building/v0); CLI `python -m buildings.ifc in.ifc out.json`.
- **C:** `sim.run(building, scenario, fire=None) -> dict` (run/v0). Use `fire.stub.NoFire` until D lands.
- **D:** `FireModel(building, scenario)` with `step(t)`, `visibility(floor_id, x, y) -> m`, `untenable(floor_id, x, y) -> bool`, `blocked_doors() -> set[str]`, `snapshot(floor_id) -> dict`. Plus `fire.metrics.compute(run) -> dict` and `fire.batch.run_many(building, scenario, ignitions, seeds) -> dict`.
- **A:** `GET /buildings`, `GET /buildings/{id}`, `POST /runs` → `{run_id}`, `GET /runs/{id}`, `POST /batch`, `GET /batch/{id}`, `POST /report`. LLM: `llm.personas(building, n)`, `llm.decide(obs) -> {action, target, reason} | None`, `llm.report(metrics) -> markdown`.
- **E:** one loader for both sources (static `/demo/*.json` or the API).

## Agents

- **Body:** JuPedSim moves agents every 0.01 s (collision avoidance, queues).
- **Brain:** rules run every 1 s or on events. Exit cost for agent $i$ and exit $e$:

$$C_e = \frac{d_e}{v_i} + \frac{q_e}{F_e} + \beta\, s_e + \gamma\, u_{i,e}$$

  Pick with a softmax over $-C_e/\tau$; switch only if $C_{\text{new}} < 0.8\, C_{\text{current}}$.
- **States:** not moving yet (start delay by profile) → moving → re-planning → waiting for help (wheelchair users on upper floors) → out or trapped.
- **Stairs:** an agent entering a stair zone on floor $k$ is removed there and re-added at the same stair group on floor $k-1$ after a delay of stair length over stair speed, through a FIFO with a capacity limit.
- **Smoke:** walking speed from visibility $S$:

$$v = \min\left(v_0,\ \max\left(0.2,\ v_0 - 0.34\,(3 - S)\right)\right)$$

- **Determinism:** every random draw comes from `scenario.seed`. LLM decisions are cached by situation key and logged in `events`.

## Sync points (hours from kickoff)

| Hour | Milestone |
| --- | --- |
| H+0.5 | Kickoff: contracts frozen, everyone regenerates the examples |
| H+3 | Walking skeleton: example building → sim → run.json → 3D replay |
| H+8 | Real IFC building end to end; then sleep in shifts |
| H+14 | Fire coupled: smoke slows people, routes close; metrics on screen |
| H+20 | Batch, risk map, report card, split screen |
| H+26 | Feature freeze; demo scenarios precomputed |
| H+30 | Devpost, video, slides |
| H+34 | Final test and submit |

Each workstream works on its own branch (`ws-a` … `ws-e`) in its own git worktree, merges small PRs to `main` (owned by A), and rebases at every sync point.

## Testing (hackathon mode)

No TDD. Each module ships `smoke_test.py`, run on the example files before each push:
- **B:** ≥1 floor with walkable area > 0 and ≥1 ground-floor exit.
- **C:** the example scenario evacuates everyone before `maxTime`; both exits get used.
- **D:** smoke near the ignition rises over time; a fast fire makes its room untenable.
- **A:** `POST /runs` with the example scenario returns frames.
- **E:** the app loads the example files with no console errors (manual).

Run the golden demo scenario before every sync.

## Risks

| Risk | Fallback |
| --- | --- |
| IFC model lacks spaces or stairs | Try the next model; else the synthetic building |
| Stair transfer is fiddly | Single floor with stair doors as exits |
| 3D performance | Instancing; else a 2D canvas replay |
| LLM latency | Situation cache; else rules |
| Live demo fails | Precomputed runs plus a recorded video |
