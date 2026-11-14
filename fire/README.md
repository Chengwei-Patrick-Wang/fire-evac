# Fire and smoke model (illustrative, not a compliance tool)

Run from the repository root with the project virtual environment active:
`python -m fire.checks` for the model checks, or
`python -m fire.smoke_test` for those checks plus the existing metrics/toy-fire checks.
`--slow` on the checks runner also enables checks whose names end in `_slow`.
`python -m fire.checks --slow` runs the 240 s example with explicit `NoFire`
and `FireModel` instances, prints their evacuation metrics, verifies smoke and
heat-release output, and writes the coupled run to `data/runs/ws-d-coupled.json`.

## Starting constants

These are illustrative assumptions from design spec section 7.3, not calibrated
predictions of a particular building fire. Times below are seconds since ignition.

| Name | Value | Meaning |
| --- | --- | --- |
| `GROWTH_ALPHA[slow]` | 0.00293 kW/s² | Slow quadratic heat-release growth |
| `GROWTH_ALPHA[medium]` | 0.01172 kW/s² | Medium quadratic growth |
| `GROWTH_ALPHA[fast]` | 0.04688 kW/s² | Fast quadratic growth |
| `GROWTH_ALPHA[ultra-fast]` | 0.1876 kW/s² | Ultra-fast quadratic growth |
| `GROWTH_ALPHA[instant]` | `None` | Full peak heat release at ignition |
| `PRESETS[kitchen]` | fast, 1500 kW, smokeFactor 1 | Kitchen preset |
| `PRESETS[bedroom]` | medium, 3000 kW, smokeFactor 1 | Bedroom preset |
| `PRESETS[battery]` | ultra-fast, 1000 kW, smokeFactor 2 | Battery preset with double smoke |
| `PRESETS[trash]` | fast, 500 kW, smokeFactor 1 | Trash preset |
| `PRESETS[liquid]` | instant, 1500 kW, smokeFactor 1 | Liquid preset |
| `SPRINKLER_CAP_KW` | 500 kW | Sprinklers lower the preset peak to at most this value |
| `CELL` | 0.5 m | Default grid spacing; samples at cell centers |
| `MAX_CELLS` | 40,000 per floor | Double the common cell size until all floors fit |
| `CLOSED_DOOR_M` | 15 m | Extra path length on entering a closed-door region |
| `STAIR_UP_M` | 3 m | Directed upward stair-link distance |
| `STAIR_DOWN_M` | 30 m | Directed downward stair-link distance |
| Door passage buffer | cell / 2 | Expand each door rectangle to capture grid nodes |
| Door membership tolerance | 0.001 m | Include nodes on the buffered passage boundary |
| Snap radius | max(1 m, cell) | Non-walkable cells can query the nearest nearby node |
| Graph cache capacity | 4 buildings | Bound retained graph/building objects |

`fire_params` accepts case-insensitive preset/growth names and normalizes spaces
and underscores to hyphens. `hrr_kw` gives zero before ignition, then
`min(alpha * t², peakKw)` (or the peak immediately for instant growth).

## Grid geometry

`grid_specs` uses each floor's original walkable bounds as its origin and extent.
All floors share one cell size, including when a large floor forces coarsening.
The graph unions walkable polygons (with their holes) with buffered door passages.
Eight-neighbor edges are retained only when the entire segment is covered by
that polygon, preventing jumps through thin walls and diagonal wall corners.

`BuildingGraph.node_at` returns a global node index and can restrict snapping to
a room polygon, even when the supplied ignition point lies outside the building.
Unknown floors or rooms containing no grid centers raise `ValueError`.
Each floor exposes local node coordinates, door memberships and a row-major
`snap` grid (`-1` where no node is close enough).

`path_distance` uses Dijkstra with non-negative door penalties, charging once
when a path enters a door region, rather than for every cell inside it.
Unreachable nodes have infinite distance. Consecutive floors sorted by `level`
connect through matching stair groups. Each stair node links to the nearest
node of that group upstairs (+3 m) and downstairs (+30 m). Door-region nodes
are excluded from both ends, so links cannot bypass a closed stair door. `get_graph` retains at most four graphs by building object
identity; callers must treat a building as immutable after caching it.

## Smoke front

`FireModel(building, scenario)` implements the `NoFire` query API without changing
the stub. Smoke propagates over all floors through stair links. Building door
states are overridden by `scenario.doors`; `closed` and `blocked` add 15 m on
entry, while `open` and `propped` add none. The `fireDoor` flag is ignored.
A closed door delays smoke but never seals the passage. `blocked` stops people
in the simulator, and behaves like `closed` for smoke. `step` rebuilds
`blocked_doors()` from doors containing any untenable node (flame or smoke);
the returned set is a copy.

| Name | Value | Meaning |
| --- | --- | --- |
| `V_BASE_MS` | 0.25 m/s | Minimum front speed |
| `V_PER_MW` | 0.5 m/s per MW | Front-speed increase with heat release |
| `V_MAX_MS` | 1.0 m/s | Maximum front speed |
| `DECAY_M` | 40 m | Density attenuation distance |
| `RISE_S` | 30 s | Density rise time after front arrival |
| `Q_REF_KW` | 1000 kW | Heat-release reference for density and speed |
| `VIS_MAX_M` | 30 m | Clear-air visibility cap |
| `UNTENABLE_D` | 90 | Density threshold for smoke untenability |
| `UNTENABLE_HOLD_S` | 30 s | Required continuous exposure above the threshold |
| `FOOT_BASE_M` | 0.5 m | Initial flame footprint path radius, only while Q > 0 |
| `FOOT_PER_SQRT_MW_M` | 1 m per sqrt(MW) | Footprint growth with heat release |
| `TABLE_S` | 1800 s | Front-reach table horizon after ignition |
| Reach integration interval | 0.25 s | Trapezoidal integration of front speed |
| Maximum update interval | 1 s | Substep for continuous-density hold accounting |
| Snapshot threshold | 0.5 | Suppress output before a floor reaches this density |

The ignition snaps to the nearest node inside its named room. Unknown rooms or
floors raise `ValueError`. The reach table maps graph distances to arrival times;
nodes beyond the table's reach stay clear. Density is clipped to 0–100, visibility
is `min(30, 100/d)`, and the growing flame footprint follows graph paths rather
than crossing walls. Time is the simulation clock; growth starts at `fire.start`.
Time must be finite and nondecreasing. Queries outside the grid are clear and
tenable. Snapshots encode row-major Uint8 densities in base64, leaving masked
cells zero and rounding to the nearest integer.

Run `python -m fire.model contracts/building.example.json contracts/scenario.example.json`
from the repo root. It uses the headless Agg backend and writes per-floor PNGs to
`debug/`, with walkable outlines and the snapped fire marker. Use
`--times 30,60,120,180 --tag example` to choose times and a filename suffix.
The CLI prints unrounded model maxima; the image uses rounded snapshot bytes.

## Propped stair-door what-if (D3)

Compare `--tag closed --times 90,120` with
`--doors DSA1=propped --tag propped --times 90,120` on the example files.
The CLI accepts comma-separated `ID=state` overrides. At 90 s, F2 maximum
density is about 3 closed versus 23 propped; the corresponding PNGs show Stair A
filling earlier. With DSA1 and DSA2 closed, the path to F2 corridor (7.5, 8)
is 44.83 m. Propping both reduces it to 14.83 m, with density about 18 there
at 90 s versus zero closed. F2 has no snapshot at 60 s closed, and does have
one with DSA1 propped. D101 becomes blocked by 200 s.

Integration handoff: C can use `fire.model.FireModel(building, scenario)` with
the same API as `NoFire`. A can replace `ToyFire` in `tools/build_examples.py`
and regenerate examples. Smoke frames start independently on each floor when
the front reaches it; upper floors may have no frames yet.

## Tuning log (D4)

The example kitchen scenario meets every model target with the starting
constants, so no constants changed. At 100 s the F1 corridor query (7.5, 8)
has visibility 2.61 m. At 180 s only D101 is blocked. Neither trash nor bedroom
fires block a door at any 1 s check through 300 s. At 120 s, battery smoke and
flame make 43.7% of F1 graph nodes untenable, versus 0.9% for kitchen.
`check_tuning()` checks these bounds on every ordinary checks/smoke-test run.

Coupled example results (`maxTime = 240`, seed 1, 160 occupants), for A and C:

| Model | t50 (s) | t90 | t100 | Trapped |
| --- | --- | --- | --- | --- |
| `NoFire` | 115.39 | null | null | 0 |
| `FireModel` | 113.23 | null | null | 1 |

The scaffold still uses upper-floor stair sinks, so these runs cannot establish
whole-building evacuation times. The lower t50 does not demonstrate a slowdown:
one trapped agent changes crowd interactions. The differing metrics establish
coupling, while the local severity targets establish the intended smoke strength;
no constants were increased just to force a slower t50. Re-run the slow check
after C's stair transfers and rerouting land. Both checks and the package smoke
test pass; smoke frames have interval 2 s and heat release is nondecreasing.

## Limits

- The model is illustrative and is not a compliance tool. Constants have not
  been calibrated to measured fires in these buildings.
- There is no heat or toxic-gas model. Heat release drives the front and density;
  untenability uses smoke density and a geometric flame footprint.
- There is no venting through exterior doors or windows, and no smoke clearance.
- Eight-neighbor grid distances can overestimate unobstructed distances by
  about 8%; wall geometry and grid resolution add further approximation.
- Each scenario has one ignition point. Stair links and closed-door penalties
  approximate smoke transport rather than solving airflow.
- Front arrival is tabulated for 1800 s after ignition; farther nodes stay clear.

## Replay metrics (D5)

`compute(run, building, scenario=None)` returns a copy of the simulator metrics,
keeping all existing and unknown keys, plus `doors` and `heatmaps`. The optional
scenario is reserved for room margins. Run
`python -m fire.metrics data/runs/ws-d-coupled.json contracts/building.example.json`
to print five doors ranked by waiting, including flow in distinct people/minute.

| Name | Value | Meaning |
| --- | --- | --- |
| `QUEUE_RADIUS_M` | 2 m | Maximum distance to the opening segment for a queue |
| `QUEUE_SPEED_MS` | 0.3 m/s | Queue speed must be strictly below this |
| `DOOR_BOX_M` | 3 m | Expand the opening bounds to filter candidate agents |
| `CROSS_SIDE_M` | 1 m | Both crossing observations must be this close to the door line |
| `CROSS_MARGIN_M` | 0.3 m | Allowed projection beyond either end of the opening |
| `FLOW_MIN_SPAN_S` | 30 s | Minimum first-to-last-crossing span for flow |

Every door, including stair and exit doors, receives a result. A queue counts
status-1 agents on that floor with known speed below the threshold and within
the opening radius. Speed is displacement divided by elapsed time since the
agent's previous appearance. First sightings and floor changes have unknown
speed and do not queue. `peakQueue` is the maximum frame count;
`waitPersonSeconds` sums frame counts times `frameInterval`. The standing-agent
smoke fixture starts with a status-0 observation, then ten known-speed frames,
retaining its expected peak 2 and wait 10.0 person-seconds.

A crossing requires opposite signed sides of the door line in consecutive
frames on the same floor, with both observations inside the side-distance and
projection limits. `crossed` counts distinct agents, even if someone crosses
repeatedly. `flow` is that count times 60 divided by the span from the first to
last qualifying crossing, with a minimum span of 30 s; no crossings give 0.0.
An observation exactly on the line is not an opposite-side pair. Disappearing
agents have no inferred crossing; replay sampling can miss fast crossings.

Heatmaps count status-1 agent-frames, excluding unstarted occupants. Their
headers come from `fire.grid.grid_specs`, so origins, cell sizes and dimensions
match smoke, including coarsened large buildings. Each floor is normalized to
its own busiest cell (100), then encoded as row-major base64 Uint8; empty runs
produce zero queues, flow and heatmaps. Positions outside grid bounds are
excluded. These are occupancy counts, not time-weighted exposure estimates.

A/E integration handoff: `doors[].flow` is now numeric people/minute and
`doors[].crossed` is a distinct-agent count. Heatmaps count moving agents and
share smoke grid headers. No contract fields were renamed or removed.
D5 verification: `python -m fire.smoke_test` prints `fire checks OK`; the coupled
run CLI prints five rows, led by D104 (peak 3, wait 55.5, flow 10.00/min).

## Batch runner (D6)

`fire.batch.run_many(building, base, ignitions=None, seeds=(1, 2, 3),
workers=None, timeout_s=7200, progress=True)` runs rule-based scenarios with
explicit `FireModel` instances. The default ignitions are non-corridor,
non-stair rooms in building order; above 50 eligible rooms, it samples 40 using
`base.seed` and restores building order. The CLI's `--rooms N` samples up to N
eligible rooms with the same seed. Each fire uses a polygon representative
point inside its room. Only location, scenario id, seed and brain are changed;
the base preset, growth, start and other settings are preserved.

Run from the repository root:

```sh
python -m fire.batch contracts/building.example.json contracts/scenario.example.json --rooms 4 --seeds 1 --workers 2 --out debug/batch-test.json
```

Default output is `data/runs/batch-<buildingId>.json`; parent folders are created.
For UMass-derived buildings, explicitly use `--out data/private/<name>.json`.
The output is batch/v0 with a copied scenario object in `base`, compact `runs`,
and optional `failed: [{scenarioId, error}]`. Ranking fields (`rooms`, `doors`,
`heatmaps`, `top`) are empty until D7. Workers retain compact door measurements
and heatmaps internally for that aggregation, without transferring full replays.

| Setting | Default | Meaning |
| --- | --- | --- |
| Room sampling threshold | 50 | Above this many eligible rooms, sample |
| Default sampled rooms | 40 | Number selected above the threshold |
| Seeds | 1, 2, 3 | Run each ignition once per distinct seed, sorted numerically |
| Workers | min(61, max(1, CPU count - 1)) | Spawned processes; unknown CPU count uses 1 |
| Batch timeout | 7200 s | Wall-clock deadline for the spawned pool |

The building is initialized once per worker, and tasks carry only scenario and
ignition data. Spawn context and a guarded CLI support Windows and macOS.
Simulation imports stay inside the worker so importing batch setup does not
require JuPedSim. Worker exceptions become strings. A pool timeout or broken
worker preserves finished results, cancels pending work, terminates children,
and records unfinished scenarios in `failed`. Results follow ignition order,
then seed order, irrespective of process completion order. Progress lines show
the completed count and elapsed batch seconds and flush immediately.

One worker or one task runs inline. In that mode the deadline is checked between
runs; it cannot interrupt an active simulation. Use at least two tasks and two
workers when a hard timeout is needed. Callers retain the usual spawn guard when
launching pools from their own scripts.

D6 verification: `python -m fire.checks --slow` passed, including two 60-person,
120 s simulations on R101/R105 in a spawned pool, identical inline results, and
a timeout that records both failures promptly. `python -m fire.smoke_test`
also passed. The four-room CLI check wrote `debug/batch-test.json` with four
runs and no failures. Git syncing is left to the overnight runner.
