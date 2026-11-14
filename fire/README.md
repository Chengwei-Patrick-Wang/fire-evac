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
| `baseSmokeSeconds`, `smokePct` | With `dSmokeSeconds` (D18): the mean person-seconds in smoke of the baseline runs that a successful variant run matches, and `100 * dSmokeSeconds / baseSmokeSeconds` (null when that mean is 0). The `why` line then reads `+427 person-seconds in smoke (+22%)` |
| `dTrappedRooms` | (D22, optional) The up to three ignition rooms that move `dTrapped` most: `[{floor, room, label, delta, fires, opensOnto}]`, `delta` the summed variant-minus-baseline trapped count in that room |
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
Stair doors propped open: 90% out 0 s later on average (slower in 0 of 12 fires); +427 person-seconds in smoke, +0.5 people at an illustrative smoke dose of 1, +0.0 trapped per fire. (before C14; see D19)
Exit Main entrance blocked: 90% out 54 s later on average (slower in 10 of 12 fires); +5,250 person-seconds in smoke, +23.8 people at an illustrative smoke dose of 1, -9.8 trapped per fire. (before C14; see D19)
Sprinklers on: 90% out 1 s sooner on average (slower in 0 of 12 fires); -72 person-seconds in smoke, -0.8 people at an illustrative smoke dose of 1, +0.0 trapped per fire. (before C14; see D19)
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

## Suggested fixes (D14)

`python -m fire.batch contracts/building.example.json contracts/scenario.example.json --rooms 6 --seeds 1,2 --whatif --fixes --out debug/batch-fixes.json`

`--fixes` measures 0.5 m wider openings at the first two ranked doors, stairs or
exits; sprinklers when their cap reduces the fire's peak; self-closers for open
stair doors; and keeping blocked doors clear. `--fix-rooms N` limits reruns to
N highest-risk ignition rooms, with null risk counted as the scenario's time
limit. Geometry changes rebuild a copy through the normalizer, update both the
opening and capacity width, and reject changes in room connections or the
number of walkable pieces. Existing outside-facing doors are never promoted to
new exits.

Every rerun pairs the same ignition and seed with the baseline. Deltas are fix
minus baseline; a null t90 counts as `maxTime`. `smokePct` is the mean change in
person-seconds in smoke divided by the matched baseline mean, times 100; it is
null when exposure is absent or the denominator is zero. `helps` once meant at least
1 s sooner to 90% out, fewer trapped, or at least 5% less smoke exposure; D22
replaced that with one rule for gains and costs, so `helps` now excludes fixes that
cost something (see "Trade-offs (D22)" below). Results sort helping fixes first,
then trade-offs, then the rest, each by lower dT90, then lower dSmokeSeconds. Failed or
unmatched runs do not contribute to comparisons; `n` is the matched count.

With `--whatif`, closing already-closed stair doors is instead compared against
the saved propped-door variant, and keeping an exit clear against its saved
blocked-exit variant. These derived results negate the original deltas and
reverse their ranges and faster/slower counts without rerunning. Their
`derivedFrom` names the comparison and their labels say "vs propped open" or
"vs blocked". Their `smokePct` is `100 * dSmokeSeconds / (b - dSmokeSeconds)`,
where b is the named what-if's `baseSmokeSeconds` (D18; the fix's own baseline is
the propped or blocked state), and null for a batch saved without it. (Until D22 any
reduction in smoke exposure qualified a derived fix as helping; now it must reach
the 5-point line like any other fix, or be negative when there is no percent.)
Derived results retain the original what-if's matched fires, even if a different
`--fix-rooms` subset is requested. Inapplicable or unsafe suggestions are recorded
in `fixesSkipped` with a reason.

These are illustrative model numbers. A fix is an idea for a fire protection
engineer to check, not a design or a compliance result. Geometry checks do not
establish structural feasibility, available wall space, or actual fire-door
performance.

Handoff for A: show `fixes[].why` verbatim as measured fixes in the report card;
Gemini may phrase around these lines but must never change their numbers.
Handoff for E: `fixes` and `fixesSkipped` are optional batch fields; surface the
comparison label, matched `n`, `helps`, and skipped reasons. Smoke exposure is
the primary what-if story, as in D10/D11.

Verified example output (6 sampled rooms x 2 seeds, 12 matched fires per fix;
`LLM_PROVIDER=off`; zero baseline failures):

```text
Keep Exit Main entrance clear (vs blocked): 90% out 55 s sooner on average and 1472 fewer person-seconds in smoke across 12 fires (faster in 12); +1.9 trapped per fire. (before C14; see D19)
Sprinklers: 90% out 2 s sooner on average and 3% less time in smoke across 12 fires (faster in 5); -1.9 trapped per fire. (before C14; see D19)
Self-closers on stair doors (vs propped open): 90% out 0 s later on average and 394 fewer person-seconds in smoke across 12 fires (faster in 0); -0.0 trapped per fire. (before C14; see D19)
Widen Door DL1 from 4.00 m to 4.50 m: 90% out 0 s sooner on average and 1% less time in smoke across 12 fires (faster in 4); +0.2 trapped per fire. (before C14; see D19)
Widen Exit East stair exit from 1.00 m to 1.50 m: 90% out 18 s later on average and 3% less time in smoke across 12 fires (faster in 7); +0.5 trapped per fire. (before C14; see D19)
```

Verification: `python -m fire.smoke_test` and `python -m fire.checks --slow`
both printed `fire checks OK`; the command above wrote `debug/batch-fixes.json`.

## Real office batch (D15)

Regenerate on the lead's machine from the repository root (activate `.venv` first):

```sh
LLM_PROVIDER=off OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m fire.batch data/buildings/office.json data/buildings/office.scenario.json --occupants 250 --fire-type kitchen --seeds 1,2,3 --budget-min 30 --whatif --fixes --out data/runs/batch-office.json > debug/office-batch.log 2>&1
```

The three thread variables change no result. Without them every spawned worker
reserves OpenBLAS buffers for each logical core: on the 16-thread laptop below
a worker commits 515 MB at import, against 33 MB with one thread, so 15
workers hold about 8 GB of commit before they simulate anything. B13/B16 put
250 occupants and the kitchen preset into `office.scenario.json`, so the two
overrides now change nothing; they keep the command valid for older scenario
files.

The batch CLI applies `--occupants` and `--fire-type` before the pilot and saves
those overrides in `base`. Occupant overrides preserve the mobility mix and
replace any per-room counts; fire-type overrides remove a custom growth class.
Invalid overrides fail through the argument parser. The task's design occupancy
is 250: approximately 3,480 m² of walkable floor divided by 13.9 m² per person
(the task's business-load assumption of 150 sq ft/person). This occupancy makes
stair queues visible; 120 occupants barely queue. This is an illustrative scenario
assumption, not an occupancy certification. The fast kitchen preset peaks at
1.5 MW, so the illustrative 500 kW sprinkler cap can change results. The trash
preset already peaks at the cap; no-op sprinkler what-ifs are now omitted.

The budget estimates baseline runs plus what-if runs and non-derived fix runs:
`top` widening fixes (default 2), a sprinkler fix when it reduces the peak,
self-closers when stair doors are open/propped, and one keep-clear fix per blocked
door. Derived inverse comparisons require no new simulations. Both comparison
room limits follow the budget's room count. Geometry checks may skip widening
candidates, so this count is conservative. This remains an estimate, not a hard
deadline. A larger `--budget-min` samples more rooms (up to all eligible rooms).

IFC family strings are replaced with room/stair labels in rankings, blocked-exit
comparisons and suggested fixes. Short, readable exit names are preserved.

### Measured office batch (Sat 08:12, lead's laptop)

Windows 11 Pro, Intel Core i9-10885H (8 cores, 16 threads), 16 GB RAM, 15
workers (the default). The laptop was shared: A's demo precompute (two runs of
6 workers), the merge gate and, from 08:47 to 08:59, this task's slow checks
ran at the same time.

```text
pilot 51.4 s; budget 30 min, 15 workers, 3 seeds, 3 what-ifs, 3 fixes -> 12 rooms (est. 28.8 min)
```

12 rooms × 3 seeds = 36 baseline fires (R104, R113b, R123, R131, R143, R146,
R210, R219, R226, R227, R230b, R237b), then 36 paired reruns for each of the
3 what-ifs and 3 non-derived fixes: 252 runs plus the pilot, none failed, every
comparison `n == 36`, nothing in `fixesSkipped`. Runtime 2942.7 s (49 min), not
the estimated 28.8 min: with 15 runs at once a run took 120-225 s against the
51.4 s pilot, about 3× rather than the planned contention of 2.0. Baseline
`timing`:

```json
{"runs": 36, "failed": 0, "workers": 15, "wallS": 410.68, "meanRunS": 131.40}
```

`top` and `stability.why`, then the `whatIf` and `fixes` `why` lines, as printed:

```text
Fire in OPEN OFFICE (R237b): 14.3 people trapped on average; 90% out after 141 s (3 fires).
Exit Stair S1 (west): 15 people queued at peak; 181 person-seconds of waiting on average, 1 of them in smoke, across 36 fires.
Exit Stair S2 (east): 10 people queued at peak; 114 person-seconds of waiting on average across 36 fires.
Door DQnt_pi (SECURE DOC ROOM to OPEN OFFICE): 5 people queued at peak; 26 person-seconds of waiting on average, 26 of them in smoke, across 36 fires.
Stair S1 door: 12 people queued at peak; 71 person-seconds of waiting on average across 36 fires.
The top 3 weak spots hold in 2 of 3 seeds: Exit Stair S1 (west), Exit Stair S2 (east), Door DQnt_pi (SECURE DOC ROOM to OPEN OFFICE). Exit Stair S1 (west) ranks first in 3 of 3.

Stair doors propped open: 90% out 0 s later on average (slower in 3 of 36 fires); +152 person-seconds in smoke, +0.1 people at an illustrative smoke dose of 1, +0.0 trapped per fire.
Exit Stair S1 (west) blocked: 90% out 13 s later on average (slower in 36 of 36 fires); +154 person-seconds in smoke, -0.2 people at an illustrative smoke dose of 1, -0.2 trapped per fire.
Sprinklers on: 90% out 0 s sooner on average (slower in 0 of 36 fires); +132 person-seconds in smoke, -0.0 people at an illustrative smoke dose of 1, -1.2 trapped per fire.

Keep Exit Stair S1 (west) clear (vs blocked): 90% out 13 s sooner on average and 154 fewer person-seconds in smoke across 36 fires (faster in 36); +0.2 trapped per fire.
Widen Exit Stair S1 (west) from 0.86 m to 1.36 m: 90% out 2 s sooner on average and 6% less time in smoke across 36 fires (faster in 23); -0.1 trapped per fire.
Widen Exit Stair S2 (east) from 0.86 m to 1.36 m: 90% out 1 s sooner on average and 3% more time in smoke across 36 fires (faster in 20); +0.1 trapped per fire.
Self-closers on stair doors (vs propped open): 90% out 0 s sooner on average and 152 fewer person-seconds in smoke across 36 fires (faster in 3); -0.0 trapped per fire.
Sprinklers: 90% out 0 s sooner on average and 47% more time in smoke across 36 fires (faster in 1); -1.2 trapped per fire.
```

Reading the numbers (all from this batch unless a probe is named):

- Evacuation time hardly depends on where the fire is: every room's mean t90
  lies between 135 and 141 s. The ranking comes from queues at the two stair
  exits and from one room.
- Fires in R237b trap people: 14.3 per fire, against 1.0 in R123 and 0 in the
  other 10 rooms. R237b is an F2 open office, and the SECURE DOC ROOM (R205)
  has a single door into it, `DQnt_pi`. That is the #3 door, and nearly all of
  its 26 waiting person-seconds are spent in smoke.
- Propping the stair doors leaves t90 unchanged (+0.1 s) and adds 152
  person-seconds in smoke per fire, 54% of the 281 baseline mean. This is the
  exposure story from D10/D11 again, now on the real building.
- Blocking Stair S1's exit slows all 36 fires, by 13 s on average (5-22 s).
  The matching fix, keep it clear, is derived from that what-if, not rerun.
- The best rerun fix is widening Stair S1's exit by 0.5 m: 2 s sooner, 6% less
  time in smoke, faster in 23 of 36 fires.
- Do not read the sprinkler smoke numbers as harm. Trapped agents leave the
  replay frames, so their time in smoke stops counting. Sprinklers save the
  people an R237b fire traps, and those people then walk out through smoke. A
  paired probe (seed 1, same code) showed it: in R237b sprinklers cut trapped
  12 → 0 and raised person-seconds in smoke 2,003 → 3,626; in R143 trapped
  stayed 0 and smoke time fell 691 → 637. Present sprinklers by trapped
  (−1.2 per fire), not by smoke.

The blocked-exit sweep stopped D's first attempt (macOS, 7 workers,
`pilot 6.2 s ... -> 48 rooms`). Back then `sim/run.py` put a stair arrival within
0.2 m of the boundary next to blocked exit `D$77wwb` (R106, seed 2). That
`RuntimeError` is gone: C13b fixed the arrival region on main, the same
repro now finishes (t90 147.4 s), and this batch's blocked-exit sweep, again
`D$77wwb`, had no failures.

Handoff for A: `data/runs/batch-office.json` (gitignored) is on the lead's
machine. To regenerate it, use the command above. On a laptop shared with
other jobs, `--budget-min 20` should take about 30-35 minutes. Show the `why` lines
verbatim, with the sprinkler caveat above. The sprinkler what-if and the
sprinkler fix rerun the same scenario, so deriving the fix from the what-if
would save a seventh of the runtime. All numbers use the illustrative model and
suggest ideas for a fire protection engineer to examine; they are not design
or compliance results.

Verification (same machine): `python -m fire.smoke_test` and
`python -m fire.checks --slow` both printed `fire checks OK`, the slow suite
including the 250-occupant office check.

## Ranges across seeds (D16)

Batches with at least two successful seeds include optional ranges. Room
`riskT90Range`, `riskTrappedRange` and (when dose is available) `riskDosedRange`
are `{min, median, max}` over that room's successful runs, using plain floats.
A missing t90 counts as `base.maxTime`; when every t90 for a room is missing,
`riskT90Range` is null, matching `riskT90`. These are observed ranges across the
sampled runs, not confidence intervals. Failed runs are excluded.

Door `scoreRange` and `meanWaitRange` summarize one aggregate per successful
seed, over its ignition rooms. Scores are normalized separately within each
seed, so score ranges describe relative ranking variation rather than absolute
queue load. A door absent from a seed contributes zero. Different successful
ignition subsets can affect the comparison if runs fail.

`stability.seeds` lists the successful seeds; `top3` lists the first three door,
stair or exit ids from the overall ranking (rooms are excluded). `heldIn` counts
seeds with the same top-three set, regardless of order; `n` is the successful
seed count and `stable` means `heldIn == n`. The text also reports how often the
overall first door ranks first. If fewer than three doors queue, the comparison
uses that smaller set. Each `top` entry has `seedsInTop3` and `seeds`: for a room,
the former counts how often it is the seed's worst room. One-seed batches keep
the existing shape, without ranges or stability fields. All results use the
illustrative model.

Verification commands (from the repository root with `.venv` active):

```sh
LLM_PROVIDER=off python -m fire.smoke_test
LLM_PROVIDER=off python -m fire.checks --slow
LLM_PROVIDER=off python -m fire.batch contracts/building.example.json contracts/scenario.example.json --rooms 6 --seeds 1,2,3 --out debug/batch-ranges.json
LLM_PROVIDER=off python -m fire.batch data/buildings/office.json data/buildings/office.scenario.json --occupants 250 --fire-type kitchen --seeds 1,2,3 --budget-min 10 --out debug/batch-office-ranges.json > debug/office-ranges.log 2>&1
```

Handoff for E: show `riskT90Range` beside the mean, for example
`95 s (88-104)`, and `stability.why` below the weak spots; handle null ranges.
Handoff for A: regenerate the office batch so it carries these optional fields;
`stability.why` can appear verbatim in the report card. No contracts or frontend
files were changed.

Measured results on macOS 14.5 arm64, 8 logical cores, 7 workers:

```text
Example: 6 rooms x 3 seeds = 18 runs, 0 failed.
The top 3 weak spots hold in 2 of 3 seeds: Door DL1 (Lobby to Corridor 1), Exit East stair exit, Exit Main entrance. Door DL1 (Lobby to Corridor 1) ranks first in 3 of 3.
pilot 9.7 s; budget 10 min, 7 workers, 3 seeds, 0 what-ifs -> 72 rooms (est. 10.0 min)
Office: 72 rooms x 3 seeds = 216 attempted; 213 successful, 3 failed.
The top 3 weak spots hold in 2 of 3 seeds: Stair S1 exit, Door D$77u2P (VEST/ENTRY to NOC), Stair S1 door. Stair S1 exit ranks first in 2 of 3.
```

Office timing (seconds):

```json
{
  "runs": 216,
  "failed": 3,
  "workers": 7,
  "wallS": 370.15573766618036,
  "meanRunS": 11.789803746751407
}
```

Three sampled office rooms (seconds for t90; people for trapped and dosed):

| Room | riskT90Range (min / median / max) | riskTrappedRange | riskDosedRange |
| --- | --- | --- | --- |
| R102 | 132.02 / 134.38 / 135.09 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |
| R104 | 133.90 / 134.27 / 134.33 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |
| R105 | 132.22 / 135.45 / 139.44 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |

Both verification suites printed `fire checks OK`. Both CLI batches wrote
their output files and printed the stability lines above. Output JSON and logs
are gitignored; the commands above regenerate them.

Office limitation: all three R203b seeds failed with
`ValueError: No grid nodes inside the requested room on F2`.
The room is an OPEN OFFICE fragment, 1.16 m² with bounds
`(0.331, 23.818, 5.897, 24.026)`: only 0.208 m wide, below the 0.5 m
smoke-grid spacing. The 71 other sampled rooms succeeded in all three seeds.
Ranges and stability exclude those failures; R203b has no risk estimate.
This is not the blocked-stair simulator failure recorded under D15.
Handoff for B/A: inspect the narrow IFC room fragment before using this
batch as a complete office survey. No geometry or grid-resolution changes
are included in the ranges task.

## Headline numbers (D18)

`python -m fire.headlines BUILDING BATCH [--sensitivity PATH] [--out PATH]` reads a
saved batch and writes `data/runs/headlines-<buildingId>.json` (gitignored): the few
numbers that demo scenes 4-6, A's report card and E's Report tab all quote, so none
of them has to dig them out of the full batch. Nothing reruns. Without
`--sensitivity` it adds D17's `data/runs/sensitivity-<buildingId>.json` when that file
exists. Run it from the repository root with repo-relative paths: `sources` holds the
paths as given, and the pack ships with the demo, so an absolute path is shortened to
a relative one (or to its file name).

Contract (every field but `version`, `buildingId` and `generated` may be absent; a
missing section or field is left out, never null; readers ignore unknown fields;
times are ISO 8601 UTC ending in `Z`; all text is ASCII):

```text
headlines/v0 = {version, buildingId, buildingName, generated, note, sources: {batch: {file, id, modified}, sensitivity: {file, modified}}, scenario: {id, occupants, mix, fireType, growth, sprinklers, alarmTime, maxTime, doors, exitChoice, seeds, rooms, runs, failed}, headline, weakSpots: [{rank, kind, id, floor, label, score, why, scoreRange, riskT90Range, seedsInTop3}], whatIf: [{id, label, n, dT90, slower, faster, dTrapped, dSmokeSeconds, baseSmokeSeconds, smokePct, dDosed, why}], fixes: [{id, kind, label, helps, tradeoff, costs, n, dT90, dTrapped, dSmokeSeconds, smokePct, derivedFrom, why}], stability: {why, heldIn, n}, sensitivity: {note, why, variants: [{id, why}]}, timing}
```

- `scenario` is the batch's `base` (`id`, `occupants.total` as `occupants`, `mix`,
  `fire.type` as `fireType`, `fire.growth` as `growth`, `sprinklers`, `alarmTime`,
  `maxTime`, `doors`, and C14's `exitChoice` when set) plus `seeds`, the number of
  ignition `rooms`, and the `runs` and `failed` counts.
- `weakSpots` is `top` in order, `rank` from 1. `label` comes from `door_label` (a
  room is `<room name> (<id>)`), `seedsInTop3` from D16, `scoreRange` from the
  matching `doors[]` entry and `riskT90Range` from the matching `rooms[]` entry.
- `whatIf` and `fixes` keep the fields above, in batch order. The pack never holds
  `runs`, `doors` or heatmaps, so it stays small (well under 20 KB).
- `headline` comes from the `proppedStairs` what-if when its `n > 0`, else from the
  first what-if with `n > 0`:
  `Stair doors propped open: +22% person-seconds in smoke across 36 paired fires; 90% out 0 s later on average.`
  It says `sooner` for a negative `dT90`, `+427 person-seconds in smoke per fire`
  when there is no `smokePct`, and only the time when there is no `dSmokeSeconds`.
  With no usable what-if it is the first weak spot's `why`; with neither there is
  no `headline` key.
- `note` is always `Illustrative fire model and rule-based simulated occupants; ideas
  for a fire protection engineer to check, not a compliance result.`

Percent at the source: `add_whatif` now writes `baseSmokeSeconds` (the mean
person-seconds in smoke of the baseline runs that a successful variant run matches)
and `smokePct` (`100 * dSmokeSeconds / baseSmokeSeconds`, null when that mean is 0)
on every what-if that has `dSmokeSeconds`, and its `why` reads `+427 person-seconds
in smoke (+22%)`. A derived fix gets `smokePct = 100 * dSmokeSeconds / (b -
dSmokeSeconds)`, with b the `baseSmokeSeconds` of the what-if named in its
`derivedFrom`. `compare` is unchanged. With `--whatif-rooms` (D13 and D15 set it) the
what-ifs cover fewer fires than the baseline has runs, which is why E's
`batchHeadline` fell back to raw person-seconds: a batch saved without
`baseSmokeSeconds` gets `smokePct` in the pack from the mean `runs[].smokeSeconds`
only when `n` equals the number of runs (E's rule), and otherwise the headline says
`person-seconds in smoke per fire`.

The CLI exits 1 with `no batch at <path>: run D15's command (fire/README.md) first`
when the batch file is missing (or when `--sensitivity` names a missing file), and 2,
naming both ids, when the batch's `buildingId` is not the building's `id`. It writes
`json.dumps(pack, indent=1)`, then prints the headline, every `why` (weak spots,
stability, what-ifs, fixes, sensitivity) and `wrote <path> (<n> bytes)`.
`fire.headlines.build_headlines(building, batch, sensitivity=None, sources=None,
generated=None)` builds the same dict for callers that already hold the files.

Measured (Windows 11, lead's laptop shared with A's demo precompute, 4 workers, Sat
09:26-09:45). Verification first: `python -m fire.smoke_test` and `python -m fire.checks
--slow` both printed `fire checks OK` (the slow suite took 6 minutes). Then:

```text
$ python -m fire.batch contracts/building.example.json contracts/scenario.example.json --rooms 6 --seeds 1,2 --whatif --fixes --workers 4 --out data/runs/batch-example-office.json
runtime 1002.2 s
wrote data\runs\batch-example-office.json (12 runs, 0 failed)

$ python -m fire.headlines contracts/building.example.json data/runs/batch-example-office.json
Stair doors propped open: +26% person-seconds in smoke across 12 paired fires; 90% out 0 s later on average.
  ... the 5 weak-spot lines and the stability line, then:
Stair doors propped open: 90% out 0 s later on average (slower in 2 of 12 fires); +401 person-seconds in smoke (+26%), +0.1 people at an illustrative smoke dose of 1, +0.0 trapped per fire.
Exit Main entrance blocked: 90% out 48 s later on average (slower in 11 of 12 fires); +1,443 person-seconds in smoke (+94%), +1.5 people at an illustrative smoke dose of 1, -2.4 trapped per fire.
Sprinklers on: 90% out 6 s sooner on average (slower in 0 of 12 fires); -55 person-seconds in smoke (-4%), -3.6 people at an illustrative smoke dose of 1, -2.4 trapped per fire.
Keep Exit Main entrance clear (vs blocked): 90% out 48 s sooner on average and 49% less time in smoke across 12 fires (faster in 11); +2.4 trapped per fire.
  ... three more fix lines
wrote data/runs/headlines-example-office.json (7043 bytes)

$ python -m fire.headlines data/buildings/office.json data/runs/batch-office.json
Stair doors propped open: +54% person-seconds in smoke across 36 paired fires; 90% out 0 s later on average.
  ... the same weak-spot, what-if and fix lines as D15 printed
wrote data/runs/headlines-office.json (6811 bytes)
```

- The example batch has the percent at the source: `baseSmokeSeconds` 1532.5 on
  all three what-ifs (12 matched fires each), so the derived fixes get a percent too:
  -48.5% for keeping the main entrance clear, -20.7% for self-closers (the sprinklers
  fix, rerun, shows the same -3.6% as the sprinklers what-if).
- The office batch is D15's, saved before this task and not rerun (it takes 50
  minutes): its what-ifs carry no `baseSmokeSeconds`, so the pack's `smokePct` comes
  from the fallback, valid because every what-if has `n` 36 for 36 runs: +54% for
  propped stairs (+152 on a 281 baseline mean), +55% for the blocked exit and +47% for
  sprinklers (the trapped-agents caveat above). Its derived fixes have no `smokePct`
  until the batch is regenerated.

Handoff for A: the precompute runs `python -m fire.headlines` on each batch it
saves, copies `data/runs/headlines-<id>.json` into `frontend/public/demo/` and lists
it as `batches[].headlines`. The report card may use `headline` as its template
headline and quotes the `why` lines verbatim; `whatIf[].baseSmokeSeconds` (written by
`add_whatif` from now on) already feeds `_base_smoke`. Do not headline the sprinklers
entry by smoke: trapped agents leave the replay frames, so sprinklers read as more
time in smoke (D15); quote them by `dTrapped`. That is why the headline rule starts
with propped stairs.

Handoff for E: the Report tab can show the whole pack with no API or Gemini call.
Use `smokePct` instead of recomputing the percent, `label` for names (it is already
readable), `scoreRange` and `riskT90Range` beside the score and time, and
`stability.why` below the weak spots; handle every missing field. `generated` and
`sources` say which batch the numbers came from.

All numbers use the illustrative model and are ideas for a fire protection engineer
to check; they are not design or compliance results.

## Refresh after C14 and C13b (D19)

`python -m fire.refresh BUILDING SCENARIO [--occupants N] [--fire-type T] [--rooms 12] [--seeds 1,2,3] [--workers N] [--check] [--resume]`
says which of the numbers we quote moved because of C14, the smoke-aware exit choice (people avoid a stair they can
see filling with smoke), and which did not. It runs the same rooms and seeds twice on the same code, so only C14
differs:

- the **C14 terms off** side sets the scenario's `exitChoice` to `{"smoke": 0, "unfamiliar": 0}` and appends `-c14off`
  to the scenario id. It is not "before C14": C14's separate `smoke` reroute trigger stays on;
- the **current** side leaves the scenario alone (C14's weights: 4 s per smoky metre seen, 30 s for an unfamiliar exit).

Both sides get the same what-if variants (taken from the current baseline, so `blockedExit` blocks the same door) and
their own measured fixes (widening follows each side's own `top`). The order is both baselines, then each what-if on
both sides in turn (one `add_whatif` call per variant and side, all from the one variant list), then the fixes, the
current side first. So a run that is stopped early still holds paired what-ifs and, before anything of the legacy
side's fixes, the whole current side, which is the one the demo quotes. After every stage the CLI saves that side's
batch so far to `data/runs/batch-<id>[-c14off].partial.json` (deleted when the run finishes). It writes `data/runs/batch-<id>.json`, `batch-<id>-c14off.json`, `headlines-<id>.json` and
`headlines-<id>-c14off.json` (all gitignored), after renaming an existing `batch-<id>.json` and `headlines-<id>.json`
to `.prev.json` (`.prev2.json` and so on when that name is taken: nothing is overwritten or deleted).

A baseline or what-if stage whose runs did not all finish is run again once, and the attempt with the most finished
runs is kept (`retries=1`): on a shared laptop a worker can die, `BrokenProcessPool` then takes every run that pool had
not finished, and a what-if with fewer pairs than baseline fires is not comparable. `--resume` continues a stopped run
from its `.partial.json` checkpoints: stages they hold in full are not run again, a baseline or what-if that lacks
fires is redone (and the fixes measured against it are dropped), and a checkpoint made with another scenario is refused.

`add_fixes` (D14) now reuses a sprinkler what-if instead of rerunning the sprinkler fix, as D15 suggested, when that
what-if paired every baseline fire (same scenario: sprinklers on, no door change). D15's and D18's saved batches show the
two agree on every number (`n`, `dT90` and its range, `slower`, `faster`, `dTrapped`, `dDosed`, `dSmokeSeconds`), so this
changes no result and saves a seventh of the runtime. Without that what-if, or with a `--fix-rooms` limit that leaves
some of its fires out, the fix is rerun as before. The office refresh below used it from its fixes stage on.

`--check` prints which of the two fixes this checkout has and exits 0:
`C14 smoke-aware exit choice: yes|no; C13b stair arrivals: yes|no|n/a`. C14 is read from the simulator's source
(`SMOKE_BETA` in `sim/brain.py`, or `exitChoice` in `sim/run.py`). C13b has no flag, so the probe is D15's repro
(office, kitchen in R106, seed 2, 250 occupants, `D$77wwb` blocked, `maxTime` 240, through `_run_one`), which used to
raise `too close to geometry boundaries`; it runs only for the building `office` (`n/a` for any other) and costs one
run (88 s on the lead's laptop). Without `--check` the CLI exits 3 after that line and `nothing to refresh yet` when C14
is missing, or C13b on the office; it exits 1 when a file is missing.

What counts as changed (`diff_headlines(old, new)`, old = C14 terms off; the constants are at the top of
`fire/refresh.py`):

| Compared number | Changed when |
| --- | --- |
| `smokePct` (else `dSmokeSeconds`) of each what-if and fix | it moves by 5 points (`dSmokeSeconds`: by 10% of the larger value) |
| `dT90` of each what-if and fix | it moves by 5 s |
| `dTrapped` of each what-if and fix | it moves by 0.5 people per fire |
| a fix's `helps` | it flips |
| the ids of the top 3 weak spots, in order | they differ |
| a what-if or fix id | it is on one side only |
| `exitUse`: the baseline `runs[].exitCounts` summed per exit | an exit moves by 5% of the evacuees |

Contract additions to `headlines/v0` (current pack only; all optional; readers ignore unknown fields; ASCII text):
`features: {smokeAwareExits, stairArrivalsFixed}` (`stairArrivalsFixed` only on the office), `legacyHeadline` (the
C14-off pack's `headline`) and `changes: [{key, label, old, new, changed, why}]`. `changes` holds only the entries that
changed, so every one has `changed: true` (an entry measured on one side only leaves the other side's value out);
`key` is `top3`, `whatIf.<id>.<smokePct|dSmokeSeconds|dT90|dTrapped>`, `fixes.<id>.<same four, or helps>` or
`exitUse`. The CLI prints every changed `why` and the keys that did not change.

### Measured: the example building (Sat 10:07-10:33, lead's laptop)

Windows 11 Pro, Intel Core i9-10885H (8 cores, 16 threads), 16 GB RAM, 6 workers, shared with A's demo precompute
(two more groups of 6 workers). Verification first: `python -m fire.smoke_test` and `python -m fire.checks --slow` both
printed `fire checks OK` (the slow suite took 10 minutes on the shared laptop).

```text
$ OPENBLAS_NUM_THREADS=1 python -m fire.refresh contracts/building.example.json contracts/scenario.example.json --rooms 6 --seeds 1,2 --workers 6
C14 smoke-aware exit choice: yes; C13b stair arrivals: n/a
refresh plan: 6 rooms x 2 seeds = 12 fires per side; up to 6 paired reruns of each -> about 168 runs on 6 workers
previous pack: Stair doors propped open: +26% person-seconds in smoke across 12 paired fires; 90% out 0 s later on average.
C14 terms off: Stair doors propped open: +25% person-seconds in smoke across 12 paired fires; 90% out 0 s sooner on average.
C14 terms on:  Stair doors propped open: +26% person-seconds in smoke across 12 paired fires; 90% out 0 s later on average.
4 of 31 compared numbers changed:
Exit Main entrance blocked, smoke exposure: +89% -> +94% with C14's exit-choice terms on (same 12 fires).
Widen Door DL1 (Lobby to Corridor 1) from 4.00 m to 4.50 m, 90% out time: +4 s -> -5 s with C14's exit-choice terms on (same 12 fires).
Widen Door DL1 (Lobby to Corridor 1) from 4.00 m to 4.50 m, trapped per fire: +0.5 -> -0.4 with C14's exit-choice terms on (same 12 fires).
Widen Door DL1 (Lobby to Corridor 1) from 4.00 m to 4.50 m, helps: no -> yes with C14's exit-choice terms on (same 12 fires).
wrote data/runs/batch-example-office-c14off.json (12 runs, 0 failed) and data/runs/headlines-example-office-c14off.json (7053 bytes)
wrote data/runs/batch-example-office.json (12 runs, 0 failed) and data/runs/headlines-example-office.json (8507 bytes)
runtime 1537.9 s
```

168 runs, none failed, 1,538 s (this run did the fixes of the C14-off side first; the code now starts with the current
side, which changes no number). The exit-use line is not in the pack's `changes` because it did not change (no exit moved
by 5% of the 1,895 evacuees); `exit_shift` on the two saved batches gives `Exit use across the baseline fires: Exit East stair exit 838 -> 829 people, Exit Main entrance 1057 -> 1062.`

- **The headline does not move.** Propped stair doors cost +25% person-seconds in smoke with C14's terms off and +26%
  with them on, and 90% out is 0 s either way (the sign flips from -0.23 s to +0.02 s, which is why the text says
  "sooner" and "later"). The top 3 weak spots (Door DL1, the Lobby fire, Exit East stair exit) are the same; ranks 4
  and 5 swap (Exit Main entrance and Door D104).
- **The previous pack is the current side.** `batch-example-office.prev.json` (D18, Sat 09:43) and the new current batch
  agree on all 12 runs, all 3 what-ifs and all 5 fixes to the last digit, so the simulator is deterministic and D18 already ran with C14. The
  D11 and D14 lines above (+22% and so on) are older: they predate C14 and other simulator fixes, and since the C14-off
  side on today's code gives +25%, most of the step from +22% to +26% is not C14's.
- **What C14 does move** is small: the blocked main entrance costs +94% person-seconds in smoke instead of +89%, and the
  measured fix "Widen Door DL1" goes from not helping (+3.9 s, +0.5 trapped per fire) to helping (-5.4 s, -0.4 trapped
  per fire), a 9 s swing on a 12-fire sample. Exit use is nearly unchanged (East stair exit 838 -> 829 people, Main
  entrance 1,057 -> 1,062 over the 12 baseline fires).

### Measured: the office (Sat 10:33-12:50, lead's laptop)

Same machine, 6 workers until 12:30 and 12 for the last stretch, once A's precompute had finished. Started at 10:33
(log `debug/refresh-office.log`) and continued three times with `--resume` (`debug/refresh-office-resume.log`,
`-resume2.log` and `-resume3.log`):

```text
$ LLM_PROVIDER=off OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python -m fire.refresh data/buildings/office.json data/buildings/office.scenario.json --occupants 250 --fire-type kitchen --rooms 12 --seeds 1,2,3 --workers 6
C14 smoke-aware exit choice: yes; C13b stair arrivals: yes
refresh plan: 12 rooms x 3 seeds = 36 fires per side; up to 6 paired reruns of each -> about 504 runs on 6 workers
```

The last continuation (the same command with `--workers 12 --resume`, 12:38 to 12:50, 695 s, no failed run) measured the
C14-off side's fixes, which the earlier invocations had not reached, and wrote the files. What it printed:

```text
resuming from data/runs/batch-office.partial.json, data/runs/batch-office-c14off.partial.json
renamed data/runs/batch-office.json to data/runs/batch-office.prev2.json
renamed data/runs/headlines-office.json to data/runs/headlines-office.prev2.json
renamed data/runs/batch-office-c14off.json to data/runs/batch-office-c14off.prev.json
renamed data/runs/headlines-office-c14off.json to data/runs/headlines-office-c14off.prev.json
previous pack: Stair doors propped open: +54% person-seconds in smoke across 36 paired fires; 90% out 0 s later on average.
C14 terms off: Stair doors propped open: +49% person-seconds in smoke across 36 paired fires; 90% out 0 s later on average.
C14 terms on:  Stair doors propped open: +54% person-seconds in smoke across 36 paired fires; 90% out 0 s later on average.
4 of 29 compared numbers changed:
Top 3 weak spots: OPEN OFFICE (R237b), Exit Stair S1 (west), Door DQnt_pi (SECURE DOC ROOM to OPEN OFFICE) -> OPEN OFFICE (R237b), Exit Stair S1 (west), Exit Stair S2 (east) with C14's exit-choice terms on.
Exit Stair S1 (west) blocked, smoke exposure: +60% -> +55% with C14's exit-choice terms on (same 36 fires).
Widen Door DQnt_pi (SECURE DOC ROOM to OPEN OFFICE) from 0.86 m to 1.36 m: measured only with C14's exit-choice terms off.
Widen Exit Stair S2 (east) from 0.86 m to 1.36 m: measured only with C14's exit-choice terms on.
wrote data/runs/batch-office-c14off.json (36 runs, 0 failed) and data/runs/headlines-office-c14off.json (7125 bytes)
wrote data/runs/batch-office.json (36 runs, 0 failed) and data/runs/headlines-office.json (8821 bytes)
runtime 695.3 s
```

The exit-use line (`exit_shift`, not in `changes` because it did not change): `Exit use across the baseline fires: Exit
Entry (south) 976 -> 1224 people, Exit Open Office (west) 1410 -> 1313.`

**What finished.** Both sides are complete: baseline, 3 what-ifs and 5 fixes, 36 fires each, none failed. The `.prev.json`
files of the current side (`batch-office.prev.json`, `headlines-office.prev.json`) are D15's batch and D18's pack; the
`.prev2.json` pair and the C14-off `.prev.json` pair are the files written at 12:30, before the C14-off fixes were measured.

**What happened to the run** (the reasons `retries`, `--resume` and the sprinkler reuse exist):

- 11:08: a worker died. `BrokenProcessPool` took 15 of the 36 runs of the current side's propped-stairs what-if (`n` 21,
  an unusable +172%), after a 60 s stall and two Windows power-source events (11:08:27 and 11:09:46). The old code
  had no retry. The first process was stopped at 11:18 after the C14-off blocked-exit stage and `--resume` redid the short
  stage (36 runs, no failure) and went on.
- 11:52: resumed once more to use the sprinkler reuse for the fixes stage (the current side's fixes finished 12:07, 13 minutes).
- 12:07-12:30: the C14-off fixes stage started at 12:07:43, but Windows logged a standby from 12:14:37 to 12:29:30
  (Kernel-Power 506 and 507), and at 12:30 its second widened-door stage had 6 of 36 runs. The run was stopped there (the
  12:30 rule) and the files were written from the checkpoints, with no C14-off fixes (a fixes stage is saved only when it ends).
- 12:38-12:50: with the laptop free, `--resume --workers 12` measured the C14-off fixes (two widened-door reruns of 36 fires; the
  sprinkler fix is reused) and rewrote all four files.

**Reading the numbers.**

- **The headline barely moves.** Propped stair doors add +152 person-seconds in smoke per fire with C14's terms off and
  on, and 90% out is 0 s later either way (+0.11 s and +0.05 s). The percent goes from +49% to +54%, 4.9 points and so just
  under the 5-point line, because C14 lowers the baseline: the mean person-seconds in smoke per fire falls from 309 to 281
  (-9%), since people steer away from stairs they can see filling with smoke.
- **The third weak spot changes, and the fix list follows it.** With the terms off it is Door DQnt_pi (the SECURE DOC ROOM's
  only door, 29 waiting person-seconds, all in smoke); with them on it is Exit Stair S2 (east), whose waiting rises from 72
  to 114 person-seconds per fire (score 31.4 to 44.8) while DQnt_pi stays near its score (44.3 to 43.9) and drops to 4th. The
  R237b fire and Stair S1's exit keep ranks 1 and 2. The seed-stability lines of the two packs differ as well. Widening
  follows each side's own `top`, so the second widened door differs, and these are the two "measured only" entries: with
  the terms off, Door DQnt_pi (0 s sooner, 3% less time in smoke, -0.2 trapped per fire, faster in 11 of 36); with them on,
  Exit Stair S2 (east) (1 s sooner, 3% more time in smoke, +0.1 trapped per fire, faster in 20 of 36).
- **The measured fixes that both sides have hardly move**, each under the thresholds (5 points of smoke, 5 s, 0.5
  trapped), so none is in `changes`: keeping Stair S1's exit clear is 15 s sooner and 38% less time in smoke with the terms
  off and 13 s and 35% with them on; widening that exit (0.86 m to 1.36 m) is 2 s sooner with 8% and then 6% less time in
  smoke (faster in 26 and then 23 of 36); self-closers on the stair doors 33% and then 35% less time in smoke; sprinklers
  -1.3 and then -1.2 trapped per fire (and 45% and then 47% more time in smoke, the accounting caveat of D15). All five fixes
  help on both sides.
- **Blocking Stair S1's exit** is the one what-if line that moves: 15 s later with the terms off and 13 s with them on,
  +187 person-seconds in smoke (+60%) against +154 (+55%).
- **Exit use** shifts toward the south entry: Exit Entry (south) 976 -> 1,224 people and Exit Open Office (west) 1,410 ->
  1,313 across the 36 baseline fires. The largest move, 248 people, is 2.8% of the 8,954 evacuees (the line is 5%), and the stair
  exits hardly move (S1 2,749 -> 2,709, S2 2,512 -> 2,517). People trapped: 50 -> 46 over the 36 fires; mean 90% out
  136.4 -> 136.6 s.
- **D15's batch is the current side.** The current batch agrees with D15's `batch-office.prev.json` on all 36
  runs, all 3 what-ifs and all 5 fixes to the last digit (the sprinkler fix included, which was reused from its what-if
  this time and rerun in D15: the reuse checks out). D15 ran Sat 08:12, after C14 (04:21) and C13b (04:26), so D15's and
  D18's lines are not marked "(before C14)": they already include C14. The new pack adds the percent at the source, so the derived fixes
  have one now (keeping Stair S1's exit clear -35%, self-closers -35%). With the example (D18's batch reproduced exactly as well), the
  simulator is deterministic: the same fires give the same numbers, whatever else the laptop is doing.
- **The C13b probe passed** (`C13b stair arrivals: yes`): the blocked-exit sweeps ran on both sides with no failed run.

Handoff for A: quote only the newest `data/runs/headlines-<id>.json` (the `.prev` and `-c14off` files are for
comparison only; do not copy them into the demo), regenerate the precompute from the new `batch-<id>.json`, and use the
changed `why` lines above in the demo notes and the report card: they say in plain words what the smoke-aware exit
choice did to each number. The earlier caveats stand: do not headline the sprinklers entry by smoke (D15), and every
number is an illustrative model result, an idea for a fire protection engineer to check.

Handoff for E: the current pack may carry `features`, `legacyHeadline` and `changes`. Show the changed entries under the
headline as "Updated for smoke-aware exit choice" (each `why` is ready to print and each entry has `changed: true`),
and say nothing when `changes` is absent. The `-c14off` pack has the same shape as any other pack and carries no
`changes`; its `scenario.exitChoice` is `{"smoke": 0, "unfamiliar": 0}`.

## Trade-offs (D22)

D14's `helps` counted any gain, so a fix that is faster and less smoky but traps people still read as a win. The
example's "Keep Exit Main entrance clear (vs blocked)" was the first measured fix, with `+1.3 trapped per fire` at
the end of a line that otherwise reads as good news. Fixes that cost something now say so, in a `Trade-off:` line
that names the fires behind the number.

**Where the +1.3 comes from.** It is the same 47 people as the blocked-exit what-if's "-1.3 trapped per fire".
The lead's rerun of the demo batch's three Lobby (L1) fires (160 occupants, kitchen, seeds 1-3) shows all 47 are in
those fires. `remaining` is 0 in all six runs, so this is the model's behaviour and not a counting artifact: E1 is
the lobby's own exit, so in a lobby fire the people heading for it walk past the fire. Sprinklers trap 0 there
as well, which is why the sprinkler what-if shows the same -1.3.

| Lobby (L1) fire, 160 occupants, kitchen | Seed 1 | Seed 2 | Seed 3 |
| --- | --- | --- | --- |
| E1 open: trapped | 16 | 13 | 18 |
| of those, `untenable` / `no route` | 11 / 5 | 10 / 3 | 14 / 4 |
| E1 open: leave through E1 | 77 | 79 | 68 |
| E1 open: 90% out | 221.8 s | 169.2 s | not reached |
| E1 open: person-seconds in smoke | 4,132 | 3,986 | 4,082 |
| E1 blocked: trapped | 0 | 0 | 0 |
| E1 blocked: leave through E2 | 160 | 160 | 160 |
| E1 blocked: 90% out | 186.0 s | 185.9 s | 190.4 s |
| E1 blocked: person-seconds in smoke | 5,624 | 5,191 | 5,812 |

The batch's L1 `riskTrapped` is 15.7 (47 over 3 fires) and the what-if's `dTrapped` is -47/36 = -1.31 over 36 fires,
all of it in L1. Blocking E1 sends everyone to E2 (nobody is trapped), and the same fires cost more person-seconds
in smoke; the counting note below is the model's accounting for that.

### The rule

One rule for a measured gain and a measured cost, shared with E34 (`fire.fixes.VERDICT = {"t90": 1.0, "trapped":
0.05, "smokePct": 5.0}`):

| | Gain | Cost |
| --- | --- | --- |
| 90% out | `dT90 <= -1` s | `dT90 >= +1` s |
| People trapped | `dTrapped <= -0.05` per fire | `dTrapped >= +0.05` per fire |
| Smoke | `smokePct <= -5` (`dSmokeSeconds < 0` when `smokePct` is null) | `smokePct >= +5` (`dSmokeSeconds > 0` when null) |

`verdict(fix) -> {"helps", "tradeoff", "costs"}` uses only the fix's numbers. `helps` means a gain and no cost,
`tradeoff` a gain and a cost, and with `n == 0` neither. `costs` lists the cost phrases: `1.3 more trapped per
fire`, `18% more time in smoke` (`427 more person-seconds in smoke` without `smokePct`), `90% out 12 s later on
average`, each list in the order time, smoke, trapped. A smoke cost adds ` (people no longer trapped keep counting)`
when trapped is a gain: people who stop being trapped stay in the replay frames, and their time in smoke counts
(D15's sprinkler caveat). `add_fixes` writes `helps`, `tradeoff` and `costs` on every fix, and sorts helping fixes
first, then trade-offs, then the rest, each by `dT90`, then `dSmokeSeconds`. A fix with no gain (neither, so no
`Trade-off:` line) keeps D14's sentence, and its `costs` are still listed. The 5-point smoke line now also applies
to a fix derived from a what-if, which used to help on any smoke reduction.

### Which fires

`fire.whatif.room_deltas(baseline_runs, variant_runs, key="trapped", building=None, doors=())` pairs runs as
`compare` does (same floor, room and seed; failed runs dropped), sums `variant[key] - baseline[key]` per ignition
room, drops rooms that sum to zero and sorts by |delta|, then floor, room. Each row is `{floor, room, label, delta,
fires, opensOnto}`: `label` is `<room name> (<id>)`, `fires` the matched fires in the room, and `opensOnto` is
`"exit"` when one of `doors` (the variant's or the fix's door overrides) joins that room to outside, `"door"` when
it joins it to another room, else null. `add_whatif` stores the first three rows as `dTrappedRooms` (when there are
any), `add_fixes` does the same for a rerun fix, a fix derived from a what-if inherits them with each `delta`
negated, and the sprinkler fix reused from its what-if copies them.

`trapped_note(stats)` turns them into the parenthesis after a trapped number. The total is `round(dTrapped * n)`.
When it is at least 1 in size and the first row has the same sign and holds at least half of it, the number gets
` (47 of 47 in fires in Lobby (L1), which this exit opens onto)`. It says `door` for `opensOnto == "door"` and
drops the `which ...` part when it is null. A row that holds more than the whole total (other rooms moving the
other way) gets no note, so the "of" never exceeds the total.

### Wording

- A helping or no-gain fix keeps D14's sentence, with the parenthesis after its trapped number when there is one:
  `Widen Exit East stair exit from 1.00 m to 1.50 m: 90% out 11 s sooner on average and 3% less time in smoke across 36 fires (faster in 23); -0.2 trapped per fire.`
- A trade-off lists its gains, then `but` and its costs (commas and a final `and`):
  `Trade-off: Keep Exit Main entrance clear (vs blocked): 90% out 58 s sooner on average and 68% less time in smoke across 36 fires (faster in 34), but 1.3 more trapped per fire (47 of 47 in fires in Lobby (L1), which this exit opens onto).`
- A what-if keeps its sentence and gets the same parenthesis:
  `... -1.3 trapped per fire (47 of 47 in fires in Lobby (L1), which this exit opens onto).`

`fire.fixes.restate(batch)` returns a copy of a saved batch with `helps`, `tradeoff`, `costs` and `why` written again
on every fix (re-sorted) and every what-if `why` written again, from the numbers the batch holds. Nothing reruns, so
a saved batch gets the `Trade-off:` wording but no "in fires in ..." parenthesis: that needs `dTrappedRooms`, which
only a sweep run with this code writes. `FIX_KEYS` in `fire/headlines.py` gains `tradeoff` and `costs`.

### Changed lines

`restate` on the three demo batches (`frontend/public/demo/batch-<id>.json`, written to
`debug/d22-restated-<id>.json`) changes five fix lines and no what-if line (none of them has `dTrappedRooms`). Each
`helps` flips from true to false, and the fix moves behind the fixes that only gain. Before, then after:

```text
Example (36 fires):
Keep Exit Main entrance clear (vs blocked): 90% out 58 s sooner on average and 68% less time in smoke across 36 fires (faster in 34); +1.3 trapped per fire.
Trade-off: Keep Exit Main entrance clear (vs blocked): 90% out 58 s sooner on average and 68% less time in smoke across 36 fires (faster in 34), but 1.3 more trapped per fire.

Office (24 fires):
Keep Exit Stair S1 (west) clear (vs blocked): 90% out 11 s sooner on average and 43% less time in smoke across 24 fires (faster in 21); +0.4 trapped per fire.
Trade-off: Keep Exit Stair S1 (west) clear (vs blocked): 90% out 11 s sooner on average and 43% less time in smoke across 24 fires (faster in 21), but 0.4 more trapped per fire.
Sprinklers: 90% out 7 s sooner on average and 18% more time in smoke across 24 fires (faster in 2); -2.2 trapped per fire.
Trade-off: Sprinklers: 90% out 7 s sooner on average and 2.2 fewer trapped per fire across 24 fires (faster in 2), but 18% more time in smoke (people no longer trapped keep counting).
Self-closers on stair doors (vs propped open): 90% out 0 s later on average and 37% less time in smoke across 24 fires (faster in 2); +0.4 trapped per fire.
Trade-off: Self-closers on stair doors (vs propped open): 37% less time in smoke across 24 fires (faster in 2), but 0.4 more trapped per fire.

Clinic (9 fires):
Keep Exit Corridor (north) clear (vs blocked): 90% out 4 s sooner on average and 37% more time in smoke across 9 fires (faster in 5); -0.2 trapped per fire.
Trade-off: Keep Exit Corridor (north) clear (vs blocked): 90% out 4 s sooner on average and 0.2 fewer trapped per fire across 9 fires (faster in 5), but 37% more time in smoke (people no longer trapped keep counting).
```

In the example, "Best measured fix" (the first fix with `helps`, E31's scene 5) is now `Widen Exit East stair exit from
1.00 m to 1.50 m`; the order is widen-E2, sprinklers, widen-DL1, self-closers, then the trade-off. The office's two
widened exits still help and come first. All other fix lines are unchanged.

### Rerun: the example, with the fires named

```sh
OPENBLAS_NUM_THREADS=1 python -m fire.batch contracts/building.example.json contracts/scenario.example.json --seeds 1,2,3 --whatif --whatif-rooms 3 --fixes --fix-rooms 3 --workers 4 --out data/runs/batch-example-tradeoff.json > debug/d22-example.log 2>&1
```

Windows 11 Pro, Intel Core i9-10885H (8 cores, 16 threads), 16 GB RAM, 4 workers on a shared laptop: 99 runs (the 54
baseline fires, 27 what-if reruns and 18 for the two widened doors; the sprinkler fix is the what-if's, and the
other two fixes are derived), none failed, 1,159.5 s. Every `dTrappedRooms` is Lobby (L1) alone: blocked E1 -47
(`exit`), sprinklers -47, keep E1 clear +47 (`exit`), widened DL1 -5 (`door`), widened E2 -7, propped stairs +1
and self-closers -1. The what-if and fix lines the batch printed:

```text
Stair doors propped open: 90% out 1 s later on average (slower in 3 of 9 fires); +789 person-seconds in smoke (+32%), +1.2 people at an illustrative smoke dose of 1, +0.1 trapped per fire (1 of 1 in fires in Lobby (L1)).
Exit Main entrance blocked: 90% out 10 s later on average (slower in 7 of 9 fires); +2,662 person-seconds in smoke (+109%), +7.1 people at an illustrative smoke dose of 1, -5.2 trapped per fire (47 of 47 in fires in Lobby (L1), which this exit opens onto).
Sprinklers on: 90% out 36 s sooner on average (slower in 0 of 9 fires); -153 person-seconds in smoke (-6%), -6.7 people at an illustrative smoke dose of 1, -5.2 trapped per fire (47 of 47 in fires in Lobby (L1)).

Widen Exit East stair exit from 1.00 m to 1.50 m: 90% out 36 s sooner on average and 3% less time in smoke across 9 fires (faster in 8); -0.8 trapped per fire (7 of 7 in fires in Lobby (L1)).
Sprinklers: 90% out 36 s sooner on average and 6% less time in smoke across 9 fires (faster in 7); -5.2 trapped per fire (47 of 47 in fires in Lobby (L1)).
Widen Door DL1 (Lobby to Corridor 1) from 4.00 m to 4.50 m: 90% out 8 s sooner on average and 0% more time in smoke across 9 fires (faster in 6); -0.6 trapped per fire (5 of 5 in fires in Lobby (L1), which this door opens onto).
Self-closers on stair doors (vs propped open): 90% out 1 s sooner on average and 24% less time in smoke across 9 fires (faster in 3); -0.1 trapped per fire (1 of 1 in fires in Lobby (L1)).
Trade-off: Keep Exit Main entrance clear (vs blocked): 90% out 10 s sooner on average and 52% less time in smoke across 9 fires (faster in 7), but 5.2 more trapped per fire (47 of 47 in fires in Lobby (L1), which this exit opens onto).
```

The fixes come in the new order, widen E2, sprinklers, widen DL1, self-closers, then the trade-off, and `restate` on
this batch returns it unchanged (the saved numbers and the restated ones agree). The six lobby fires were rerun with
this branch's code, E1 open from this batch's baseline and E1 blocked in a separate three-fire run, and every number in
the table matches: trapped, exit counts, 90% out and person-seconds in smoke (the table rounds the half seconds).

### Verification

`python -m fire.smoke_test` and `python -m fire.checks --slow` both print `fire checks OK` (the slow suite took 9
minutes on the shared laptop). `check_tradeoffs` (fast, no simulation) pins the verdicts on the demo numbers and their
boundaries, `room_deltas`, `trapped_note`, the exact trade-off sentence, `restate` on the example's five fixes and the
office's three, and the `dTrappedRooms` that `add_whatif` and `add_fixes` write (a what-if, a derived fix, a rerun fix
and a reused sprinkler what-if). `check_tradeoffs_slow` reruns the example's L1 and R105 fires (seed 1, 160 occupants)
with E1 blocked: the lobby accounts for 16 of the people the blocked main entrance spares, and the line names it.
`check_fixes` changed one assertion: its hand-made sprinkler rerun is 2 s slower, a cost, so the sprinklers there are
now a trade-off and no longer helping.

To see any saved batch in the new wording without rerunning it:

```sh
python -c "import json; from fire.fixes import restate; b = json.load(open('frontend/public/demo/batch-office.json')); print(*[f['why'] for f in restate(b)['fixes']], sep=chr(10))"
```

The three restated demo batches are in `debug/d22-restated-example-office.json`, `-office.json` and `-clinic.json`, and
the rerun batch is `data/runs/batch-example-tradeoff.json` (all gitignored).

### Handoffs

- **A:** call `fire.fixes.restate(batch)` on each batch in the precompute before writing `batch-<id>.json` and the pack
  (no reruns; `_why(fix)` and `whatif._why(label, stats)` keep their signatures). Rerun the sweeps without `--resume`
  to get the "in fires in ..." parentheses: a `--resume` run reuses saved sweeps, which have no `dTrappedRooms`.
- **E:** E34 mirrors `VERDICT` (above). `tradeoff` and `costs` are optional (older batches lack them) and `helps` now
  excludes trade-offs, so a reader that shows only `helps` stops showing the trade-offs as good news. `why` already
  holds the whole line, starting `Trade-off:`; `costs` has the cost phrases alone, for a badge or a second line. They
  are in the headline pack's `fixes[]` too (`FIX_KEYS`).
- The report card quotes `fixes[].why` verbatim, so it now says "Trade-off" and the parenthesis for a rerun batch.

All numbers use the illustrative model and are ideas for a fire protection engineer to check; they are not design or
compliance results.
