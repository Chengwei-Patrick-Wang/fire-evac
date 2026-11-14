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
keeping all existing and unknown keys, plus `doors` and `heatmaps`. Passing a
scenario also adds `rooms` with clearance and smoke margins (D8 below). Run
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
`heatmaps`, `top`) are filled by the D7 aggregation below. Workers retain compact door measurements
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


## Batch ranking and risk map (D7)

`aggregate(building, base, records)` is a pure summary of successful worker
records; failed runs are excluded from every denominator. `run_many` merges
its four result fields into batch/v0 and the CLI prints each `top[].why` after
writing the file. All numeric explanations are ASCII, including building labels.

- `rooms`: one row per ignition room, with `riskT90`, mean `riskTrapped`, and
  successful run count `n`. A missing t90 is censored to `base.maxTime` in the
  mean. If all runs miss 90% evacuation, `riskT90` stays null for the dark-red
  risk-map state; its ranking time is still `maxTime`.
- `doors`: mean waiting person-seconds over all successful runs (an absent door
  contributes zero), maximum queue, and score rounded to one decimal. The score
  uses the smoke-aware weights in D12 below when any door has positive mean
  smoke waiting; otherwise it is 100 times (0.7 times mean wait / maximum mean
  wait + 0.3 times peak queue / maximum peak queue). A zero maximum contributes zero.
- `heatmaps`: decode each floor's Uint8 grids, average across successful runs,
  then rescale the busiest cell to 100 and encode again. Headers are preserved;
  inconsistent headers or byte counts raise ValueError. Empty grids stay zero.
  Per-run maps were already normalized, so this combines relative occupancy,
  not absolute crowd counts or smoke exposure.
- `top`: the four highest positive door scores plus the room with the highest
  room score, sorted by score, at most five entries. The room score is 100 times
  (0.5 times effective t90 / maximum effective t90 + 0.5 times mean trapped /
  max(1, maximum mean trapped)). Door and room scores are relative within this
  batch; they are not calibrated probabilities. A small or empty batch can
  produce fewer than three entries.

Top kinds use `exit` for a door connected to outside, otherwise `stair` for a
connection to a stair room, otherwise `door`. Kind `corridor` is never produced.
Labels use `Exit <name>`, `Stair <group> door`, or `Door <id>`. Explanations give
peak queues, mean waiting person-seconds and successful fire-run counts. Room
explanations give mean trapped, mean censored t90 and that room's run count;
when no run reaches 90%, the explanation says it was not reached by maxTime.
Stable ties retain worker record order, which follows ignition and seed order.

A handoff: wire `POST /batch` to `run_many` and copy the generated example batch
into demo data. UMass batches must use `--out data/private/...`. E handoff:
`base` is a scenario object; risk-map headers match smoke; `rooms[].riskT90`
can be null; `top[].kind` includes stair entries identified by door id. The
optional `failed` list records unsuccessful scenarios; per-run metrics also
include the previously added optional `doors[].crossed` distinct-agent count.
No contract examples or shared frontend files were changed.


D7 verification: `python -m fire.smoke_test` passed, including handmade formula,
null-censoring, kind, ASCII explanation, heatmap, empty-batch and example-shape
checks. The default CLI completed all 18 rooms x 3 seeds (54 successful runs,
0 failures) in 18.0 s and wrote `data/runs/batch-example-office.json` (gitignored),
then printed five explanations. D202 led the door scores; Lobby L1 was the worst
ignition room with 38.0 people trapped on average. All t90 values are null with
the current scaffold's upper-floor stair sinks; rankings retain this limitation
and report that 90% evacuation was not reached by 400 s. C's stair transfers
will change those results. Git syncing remains the overnight runner's job.

## Room RSET/ASET margins (D8)

`fire.model.aset_by_room(building, scenario, t_max)` creates a fresh model and
samples every whole simulation second through `t_max`. For each room it finds
the first second when any graph node inside the room polygon on that floor is
smoke-untenable. Rooms with no qualifying nodes or no threshold crossing in the
horizon return `None`. This uses unrounded model density, not snapshot bytes.

| Quantity | Definition |
| --- | --- |
| Smoke untenability / room ASET | Density at least 90 continuously for 30 s; flame footprint alone does not count |
| Agent untenability / blocked doors | Smoke untenability OR the growing flame footprint; existing coupling is preserved |
| Room RSET | Latest exit time among agents spawned in the room; use an agent's stair event when no exit is recorded in v0 runs |
| Room margin | ASET minus RSET, in seconds; negative values flag the room |

`compute(run, building, scenario)` adds `rooms: [{id, rset, aset, margin}]`,
omitting rooms without agents. If any occupant has neither an exit nor a stair
event, RSET is null. Exit events supersede stair entries for agents with both.
ASET is evaluated through `scenario.maxTime` even if the replay ends sooner;
it and the margin are null if the room never becomes smoke-untenable within
that horizon. A missing RSET also gives a null margin. Without a scenario,
`compute` keeps the existing replay-only behavior.

These illustrative margins describe clearance of an origin room's occupants,
with the v0 stair-sink approximation where applicable. A positive margin does
not account for heat, toxic gas, or hazards encountered along the evacuation
route. The flame footprint still traps agents immediately; excluding it from
ASET prevents the fire room's smoke timeline from becoming 1 s by definition.

A handoff: pass the scenario to `compute(run, building, scenario)` in jobs to
enable room margins. The batch worker now passes it explicitly. E handoff:
`rset`, `aset`, and `margin` can be null; a negative numeric margin flags a room.
No shared contracts or frontend files were edited.

D8 verification: `python -m fire.smoke_test` and `python -m fire.checks --slow`
passed. The kitchen scenario gives R101 smoke ASET 169 s and R102 null through
400 s. Checks cover early/late clearance, a missing occupant, stair fallback,
exit precedence, delayed ignition, and flame exclusion. Spawned and inline
batches still match; coupled metrics retain the D4 results.

## Exit criticality (D9)

`add_exit_criticality(building, base, batch, workers=None, timeout_s=7200,
top_rooms=6)` returns a copy of the batch with optional `exits` results and an
updated `top`. Enable it in the CLI with `--exits`:

```sh
python -m fire.batch contracts/building.example.json contracts/scenario.example.json --rooms 4 --seeds 1 --exits --out debug/batch-exits.json
```

The highest-risk ignition rooms are selected by descending `riskT90`, treating
null as `base.maxTime` and keeping original room order for ties. Each exterior
exit door is blocked in a separate deep copy of the base scenario; other door
states stay in effect. Reruns use the selected baseline seeds and rule brains.
The timeout applies to each exit batch separately, with the same inline
execution limitation as `run_many`.

| Field | Definition |
| --- | --- |
| `exits[].id`, `floor` | Exterior exit door id and floor, suitable for lookup in building doors |
| `dT90` | Mean blocked t90 minus baseline t90, seconds; null t90 counts as maxTime on either side |
| `dTrapped` | Mean blocked trapped count minus baseline trapped count |
| `n` | Successful matched ignition-floor/room/seed pairs used for both means |
| Criticality score | 100 times positive dT90 / greatest positive dT90, rounded to one decimal; zero when no increase is measured |

Failed reruns are excluded from both means, so different success counts do not
change the baseline cohort. An exit with no matched runs has zero deltas and
`n=0`, and contributes no ranking entry. Negative deltas remain visible in
`exits` but score zero. Zero deltas with positive n can also reflect censored
evacuation times; they do not establish that an exit is unimportant.

Exit criticality entries replace existing queue-based `top` entries for the
same exit, then merge with other entries, sort by score and retain at most five.
The scores compare different illustrative measures, not calibrated risk. The
CLI prints every measured exit explanation even if it falls outside `top`.

D9 verification: smoke test and `python -m fire.checks --slow` passed. The slow
check compared E1 and E2 with two ignition rooms, seed 1, 60 occupants and a
120 s horizon. Handmade checks verify null censoring, worst-room selection,
nonzero deltas and scores, matching after failure, no-data handling and input
immutability. The four-room `--exits` CLI completed in 5.2 s (four baseline and
eight blocked simulations), wrote `debug/batch-exits.json`, and printed both
exit explanations. Both dT90 values are zero because all t90 values are null
with the current scaffold stair sinks; the capped comparison cannot resolve
exit importance in that case.

A/E handoff: opt in through `add_exit_criticality` after `run_many`; optional
`exits` contains door ids, floor, dT90, dTrapped and n. Existing batch fields
are preserved. No shared contract or frontend files changed. Git syncing and
integration are left to the overnight runner.

## Smoke exposure and illustrative dose (D10)

`exposure(run, building, scenario)` replays one fresh `FireModel` at the saved
frame times, reading unrounded density through each floor's snap grid. Density
lookups are vectorized per floor with the same cell arithmetic as `_node`;
off-grid positions and unknown floors count as clear air. Every inside status
(0 through 3, including waiting, landing and stair-transfer rows) contributes.
Exited people disappear from frames and stop accumulating exposure.

| Constant or field | Definition |
| --- | --- |
| `DOSE_UNIT`, `doseUnit` | 2,700 density-seconds = `UNTENABLE_D * UNTENABLE_HOLD_S`, or 30 s at density 90 |
| `SMOKE_D`, `smokeD` | Density 10, corresponding to visibility at or below 10 m |
| Per-agent dose | Sum of density times `run.frameInterval`, divided by `DOSE_UNIT` |
| `personSecondsInSmoke` | Sum of `frameInterval` across all inside rows with density at least `SMOKE_D` |
| `agentsInSmoke` | Distinct people with at least one row at or above `SMOKE_D` |
| `meanDose` | Total dose divided by `len(run.agents)`, including unexposed people; 0 with no agents |
| `maxDose` | Greatest observed individual dose; 0 with no rows |
| `dosed`, `dosedIdx` | Count and sorted agent indexes whose accumulated dose reached 1 |
| `stairs[].floor`, `group`, `smokeAt` | First whole second when any grid node inside that stair polygon reaches `SMOKE_D`; null if never observed through `scenario.maxTime` |
| Batch `runs[].dosed`, `smokeSeconds` | Run dose count and `personSecondsInSmoke`, respectively |
| Batch `rooms[].riskDosed` | Mean dosed count for fires ignited in that room; included only when every successful record carries `dosed` |

This is an illustrative FED-style sum of the model's illustrative smoke
density, not gas concentrations. It is not a prediction of injury or survival.
`dosed` removes nobody from the replay. Exposure uses the saved position:
stairwell time is sampled at the arrival stair below during a transfer, and at
the landing during a wait. It does not reconstruct motion between frames.
Whole-second stair probes and frame times share one forward model timeline;
stair probes continue to `maxTime` even when the replay ends early or has no
frames. Stair polygons are measured separately on each floor.

A/E handoff: passing a scenario to `compute(run, building, scenario)` adds the
optional `metrics.exposure` object. Batch `runs[].dosed`, `runs[].smokeSeconds`
and `rooms[].riskDosed` are optional additions; older records still aggregate
without them. Use exposure for the propped-stair-door comparison: the lead's
paired runs show an exposure increase despite nearly unchanged evacuation
times and trapped counts. D10 does not change the ranking formula.

D10 fixed-position checks give doses 3.413 and 1.386 for two people remaining
until 200 s, and 0.015 for a person present only through 40 s. On the example
kitchen fire, F1 Stair A reaches the smoke threshold at 93 s with the doors as
built and 62 s with DSA1 propped, including when no replay frames are supplied.
Checks also cover all inside statuses, off-grid positions, floor lookup,
empty runs, unchanged inputs and finite JSON output.

D10 verification: `python -m fire.smoke_test` and `python -m fire.checks --slow`
both print `fire checks OK`. Spawned and inline batches match with the new
fields, room dose risks are present, and older hand-made records retain their
previous output shape when dose data is absent.

## What-if sweep (D11)

`fire.whatif.add_whatif(building, base, batch, variants=None, rooms=None,
workers=None, timeout_s=7200, progress=True)` returns a deep copy with optional
`whatIf` comparisons. The CLI enables it with `--whatif`, after any `--exits`
comparison; `--whatif-rooms N` restricts it to the N highest-risk rooms in the
baseline (null `riskT90` counts as `maxTime`). Ignitions retain baseline order
and seeds come from the baseline. Each variant receives a fresh copy of the
base, merged door overrides, its explicit sprinkler setting, and a distinct id.
Each rerun is rule-based and has its own batch timeout.

The default variants are all interior stair doors propped open, the most-used
exterior exit blocked (only for buildings with at least two exits), and
sprinklers on (unless already on). Stair doors join a room listed in `stairs`
or typed `stair`, excluding outside connections. Exit use is summed from
`runs[].exitCounts`, keyed by exit id; ties prefer the wider door, then the
lexically first exit id. The blocked override uses that exit's door id. All
variants preserve other base door states and preserve base sprinklers except
for the sprinkler variant.

| Field | Definition |
| --- | --- |
| `id`, `label`, `doors`, `sprinklers` | Variant identity, display label, door overrides and explicit sprinkler setting |
| `n` | Successful matched ignition-floor/room/seed pairs |
| `dT90`, `dT90Min`, `dT90Max` | Mean, minimum and maximum variant-minus-baseline evacuation-time differences; null t90 counts as base maxTime |
| `slower`, `faster` | Pair counts with evacuation-time difference strictly above +1 s or below -1 s |
| `dTrapped` | Mean variant-minus-baseline trapped count over matched pairs |
| `dDosed`, `dSmokeSeconds` | Mean variant-minus-baseline illustrative dose count and person-seconds in smoke; each included only if both sides of every matched pair carry that measure |
| `why` | ASCII explanation of paired time, exposure and trapped differences |
| Batch `runs[].exitCounts` | Per-exit evacuated counts retained from simulator metrics |

Missing or failed runs drop the pair from both sides. No matched pairs gives
`n=0`, zero time/trapped deltas, omitted exposure deltas, and an explicit
no-data explanation. A zero censored time delta cannot establish equal
clearance times. These are illustrative model comparisons, and the dose is
not a prediction of injury or survival. Exposure is the useful headline for
propped stair doors even when evacuation times barely change.

A handoff: call `add_whatif` after `run_many` in the precompute; its `why` lines
suit the report card. E handoff: optional batch `whatIf` contains these paired
comparisons; optional `runs[].exitCounts` supports exit-use displays. No shared
contract or frontend files changed.

D11 verification: `python -m fire.smoke_test` and
`python -m fire.checks --slow` both print `fire checks OK`. The requested
six-room, seeds 1 and 2 CLI completed 48 simulations in 83.9 s with 12
baseline runs, no baseline failures, and 12 matched pairs per variant:

```text
Stair doors propped open: 90% out 0 s later on average (slower in 0 of 12 fires); +427 person-seconds in smoke, +0.5 people at an illustrative smoke dose of 1, +0.0 trapped per fire.
Exit Main entrance blocked: 90% out 54 s later on average (slower in 10 of 12 fires); +5,250 person-seconds in smoke, +23.8 people at an illustrative smoke dose of 1, -9.8 trapped per fire.
Sprinklers on: 90% out 1 s sooner on average (slower in 0 of 12 fires); -72 person-seconds in smoke, -0.8 people at an illustrative smoke dose of 1, +0.0 trapped per fire.
```

These measured examples include the lobby routing artifact identified in the
lead's overnight notes, pending C10. The lobby rank and the reduction in
trapped people when blocking the main entrance must not be used as demo
headlines; regenerate these comparisons after the routing fix. Propping
stair doors increases exposure despite the nearly unchanged t90.


## Queues in smoke (D12)

With a scenario, `compute` adds optional `doors[].smokeWait`: person-seconds
queued within 2 m of an opening, moving below 0.3 m/s with status 1, at smoke
density at least `SMOKE_D` (10). This is the smoky subset of
`waitPersonSeconds`, sampled from the same snap-grid row-density calculation
as illustrative exposure. Calls without a scenario retain the existing shape.

Batch workers carry `smokeWait` in door records. `aggregate` adds optional
`doors[].meanSmokeWait` when all available records for that door carry the
measure. As with `meanWait`, the denominator is all successful runs; a missing
door contributes zero. Failed runs contribute to neither measure.

When any door has positive `meanSmokeWait`, the relative score is
`round(100 * (0.5 * wait/maxWait + 0.2 * peak/maxPeak + 0.3 * smoke/maxSmoke), 1)`.
Otherwise the original 0.7 wait / 0.3 peak weights apply, including to old
records without smoke waits. Zero maxima contribute zero. Explanations include
", N of them in smoke" when mean smoke waiting is at least one person-second.
These model-based relative scores are illustrative, not calibrated risk.

A/E handoff: optional per-run `metrics.doors[].smokeWait` and batch
`doors[].meanSmokeWait` support smoky-queue displays. Scores now weight waiting,
peak queue and smoky waiting by 50%, 20% and 30% when smoky queues exist.

D12 verification: `python -m fire.smoke_test` prints `fire checks OK`.
The six-room, seed-1 CLI completed in 3.3 s with six successful runs and no
failures, writing `debug/batch-smoke.json`. Its smoky-queue explanations were:

```text
Exit East stair exit: 12 people queued at peak; 182 person-seconds of waiting on average, 6 of them in smoke, across 6 fires.
Door D106: 3 people queued at peak; 44 person-seconds of waiting on average, 8 of them in smoke, across 6 fires.
Door D104: 4 people queued at peak; 54 person-seconds of waiting on average, 4 of them in smoke, across 6 fires.
Exit Main entrance: 3 people queued at peak; 28 person-seconds of waiting on average, 5 of them in smoke, across 6 fires.
```

The sampled lobby fire still has the C10 routing artifact noted by the lead;
its room ranking is not suitable for a demo headline pending that fix.

## Batch timing and room budget (D13)

`python -m fire.batch BUILDING SCENARIO --budget-min 30 --workers 12 --seeds 1,2,3 --whatif`
measures one inline pilot in the first eligible room with the first seed, then
samples rooms deterministically using the base seed. The pilot uses the same
rule-based simulator and metrics as the sweep. An unsuccessful pilot stops with
its error rather than producing a misleading estimate.

| Field or parameter | Meaning |
| --- | --- |
| Worker record `wallS` | Seconds spent running the simulation and computing its metrics, including caught failures; excluded from batch `runs[]` |
| Progress `eta N.N min` | Elapsed batch time per completed record times remaining records; updates as workers finish |
| `timing.runs`, `timing.failed` | Total attempted records (successes plus failures), and failed records |
| `timing.workers` | Configured worker count, using the existing CPU-based default when omitted |
| `timing.wallS` | Wall seconds collecting baseline records, including pool startup and shutdown; excludes task construction and aggregation |
| `timing.meanRunS` | Mean worker duration among records carrying `wallS`, including caught failures; zero if none; deadline/terminated-worker records have no duration |
| `contention = 2.0` | Planning allowance for slower concurrent runs, not a measured guarantee |
| `plan_rooms(budget_s, pilot_s, seeds, workers, variants=0, contention=2.0)` | `max(1, floor(budget_s * workers / (pilot_s * contention * len(seeds) * (1 + variants))))` |

`--budget-min M` prints the pilot duration, worker/seed/what-if counts, selected
room count and estimated sweep minutes. The selected count is capped at the
building's eligible rooms and at an explicit `--rooms` limit. With `--whatif`,
the estimate counts the available default variants (respecting existing
sprinklers and the number of exits), and the selected count also becomes
`--whatif-rooms`. The blocked exit is still chosen from baseline exit counts.
The inline pilot is measured separately and rerun in the baseline sweep.

This is a planning estimate, not a hard deadline. The printed estimate excludes
pilot overhead, aggregation, pool startup, and optional `--exits` reruns. A single
room can exceed a tiny budget, and room geometry, smoke and worker contention
can make later runs slower than the pilot. Existing per-batch timeouts still
apply. `timing` describes the baseline sweep; additional exit and what-if
sweeps do not overwrite it. Timing is optional metadata; numerical `runs[]`
records remain identical between spawned and inline execution.

A handoff: use `--budget-min` for the real building's precompute, with an explicit
worker count appropriate to the machine. For example:

```sh
python -m fire.batch contracts/building.example.json contracts/scenario.example.json --budget-min 3 --seeds 1 --workers 4 --out debug/batch-budget.json
```

D13 verification: the command above printed
`pilot 2.5 s; budget 3 min, 4 workers, 1 seeds, 0 what-ifs -> 18 rooms (est. 0.4 min)`
and wrote 18 successful runs with zero failures in 16.2 seconds, under the
six-minute verification limit. The smoke test and slow checks also cover worker
failures, empty batches, ETA output, budget clamping, CLI what-if wiring and
spawned/inline result equality. The lobby routing artifact remains unsuitable
for demo headlines, as noted by the lead.
