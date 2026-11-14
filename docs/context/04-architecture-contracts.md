# Architecture and contracts

The full draft is `prior-drafts/2026-11-13-fire-evac-sim-design.md`; this is the short version.

## Pipeline

```
IFC model / traced plan ──► [B] buildings ──► building.json ──────────────┐
scenario.json (from UI) ───────────────────────────────────────────────────┤
                                                                           ▼
                                               [C] sim  ◄── step(t) ──►  [D] fire
                                                    │
                                                    ▼
                                               run.json ──► [D] metrics / batch ──► metrics.json
                                                    │                                    │
              [A] FastAPI + llm (personas, decide, report) ◄─────────────────────────────┤
                                                    ▼                                    ▼
                                     [E] frontend: 3D replay, dashboard, risk map, report
```

Letters are workstreams (see `10-team-workflow.md`).

## Repo layout (proposed)

```
contracts/      building/scenario/run example JSON (frozen v0)
tools/          build_examples.py, plot_building.py
buildings/      IFC -> building.json (B), tracing helpers (B, P1)
sim/            JuPedSim runner, profiles, brain (C)
fire/           fire grid, metrics, batch, stub (D)
backend/app/    FastAPI (A)        backend/llm/  LLM wrapper (A)
frontend/       React + r3f (E)
data/raw/ data/buildings/ data/runs/   generated
docs/superpowers/specs/ docs/superpowers/plans/ docs/context/
```

## Contracts v0

Coordinates are meters, floor-local. Rename or remove fields only by team agreement; new optional fields are fine.

**building/v0**
- `floors[]` holds `id`, `level`, `elevation`, `height`, plus:
  - `walkable[]`: `{outer, holes}` rings. **Walls are the boundary of the walkable area**, so door gaps come for free when the boundary is extruded.
  - `rooms[]`: `{id, name, type, polygon}`.
  - `doors[]`: `{id, a, b, width, fireDoor, state: open|closed|propped, connects}`.
  - `stairs[]`: `{id, group, polygon}`. The same `group` on consecutive floors means they connect.
  - `exits[]`: `{id, name, polygon}`, ground floor only.

**scenario/v0**

`{id, buildingId, seed, occupants: {perRoom | total, mix}, fire: {floor, room, x, y, type, growth, start}, doors: {doorId: state}, alarmTime, maxTime}`.

**run/v0**
- `agents[]`: `{idx, profile, floor, room, target, v0}`. `idx` is ours, never JuPedSim's id.
- `frames[]`: `{t, a: [[idx, x, y, floorIdx, status]]}`, every 0.5 s. Status 0 = not moving yet, 1 = moving, 2 = waiting for help.
- `smoke[]`: per floor `{floor, origin, cell, cols, rows, frames: [{t, d[0..100]}]}`.
- `events[]`: `{t, type: exit|reroute|trapped|wait|llm, idx, ...}`.
- `metrics`: `{agents, evacuated, trapped, t50, t90, t100, exitCounts}`.

**metrics/v0 (batch)**

`{buildingId, runs[], rooms: [{room, floor, riskT90, riskTrapped}], doors: [{id, peakQueue, waitPersonSeconds}], heatmaps[], top: [{kind, id, why}]}`.

## Module APIs (so nobody blocks)

- **B:** `buildings.ifc.load(path) -> building dict`; CLI `python -m buildings.ifc in.ifc out.json`.
- **C:** `sim.run(building, scenario, fire=None) -> run dict`. Uses `fire.stub.NoFire` until D lands.
- **D:**
  - `FireModel(building, scenario)` with `step(t)`, `visibility(floor_id, x, y) -> m`, `untenable(floor_id, x, y) -> bool`, `blocked_doors() -> set`, `snapshot(floor_id)`.
  - `fire.metrics.compute(run)` and `fire.batch.run_many(...)`.
- **A:**
  - Endpoints: `GET /buildings`, `GET /buildings/{id}`, `POST /runs` → `{run_id}`, `GET /runs/{id}`, `POST /batch`, `GET /batch/{id}`, `POST /report`.
  - LLM functions: `llm.personas`, `llm.decide(obs) -> {action, target, reason} | None`, `llm.report`.
- **E:** one loader for static `/demo/*.json` files or the API.

## Example data (in the starter zip)

`tools/build_examples.py` writes three files:
- `building.example.json`: a synthetic 2-floor, 40 × 16 m office with a central corridor, 8 rooms per floor including a kitchen, stairs SA and SB, and exits E1 and E2.
- `scenario.example.json`: a kitchen fire.
- `run.example.json`: a real JuPedSim run on floor 1 with placeholder smoke. 120 agents; t50 24.5 s, t90 38.2 s, t100 44.9 s; 67 used E1 and 53 used E2.
