# Fire-safe building routes

Corridor and lobby fires use building-wide routing by default. Other scenarios
keep the existing route behavior; `scenario.buildingRouting: true` enables the
new planner explicitly. `false` selects the legacy behavior for comparisons.

## What changes

- The fire exclusion is not reduced merely to keep a hallway connected. Every
  remaining connected region gets a separate JuPedSim simulation. Output floor
  indices still refer to the building floors, not these internal regions.
- With D's FireModel, the mandatory exclusion uses its predicted maximum
  flame-footprint radius for this run, plus `fireClearance` (0.35 m by default,
  minimum 0.31 m). The polygon circumscribes the circle rather than cutting
  inside it. Unknown/custom fire models retain `fireKeepout` as a conservative
  hard-radius fallback.
- `fireKeepout` (default 2.5 m) is a preferred separation for FireModel, not a
  wall that seals clear retreat doors. Route walking time inside this preferred
  zone receives an extra factor of 2 as a choice penalty, without making it
  unavailable. A zero `fireKeepout` explicitly disables the cut for comparisons.
- Body-clear connectivity is computed before restoring wall clearance. Overlaps
  between restored components are removed, so the restoration cannot reconnect
  a slit too narrow for a body. Sub-micron duplicate vertices are simplified
  before passing polygons to JuPedSim's triangulation.
- These distances and preferences are illustrative modeling assumptions, not
  safe distances for a real evacuation.
- All regions survive the cut; people are distributed over usable spawn regions
  with the original total count. Explicit per-room counts that cannot fit still
  fail with a clear placement error rather than silently dropping occupants.
- Every offered stair option must lead to a complete exterior-exit route. The
  planner can use an upstairs crossover to another stair. It excludes regions
  an occupant has already left, preventing floor-to-floor loops. A newly blocked
  door or stair resets that memory so a safe retreat remains possible.
- Unavailable routes are removed before either rule or LLM choice. Consequently
  ordinary switch-count and dwell limits do not keep a newly unavailable target.
- Upward flights use 80% of the profile's downward speed. Opposing flights share
  capacity and cannot overlap in transit; this conservative abstraction does not
  simulate lanes, overtaking or physical interactions inside a stairwell.
- Occupants without any available exit route get the existing `trapped` event
  with `reason: "no route"`. That event is a routing outcome, not a prediction of
  injury or death. Assistance waits remain profile/scenario controlled.

## Limits and integration

This implementation reserves the exclusion **before ignition**, including delayed
fires, and gives the planner global hazard/route knowledge. It does not model
personal line of sight or dynamically grow/shrink the navigation mesh. The circle
is conservative near walls and can exclude adjoining space; D's smoke model is
unchanged. A perception-aware, time-varying planner would be a separate change.

`run.routing` records this mode, reserved radius, required clearance, preferred
separation and preference weight as optional
metadata. Existing agents/frames/events/metrics field names remain unchanged.
Upward stair target ids add `@<destinationFloor>` to distinguish directions;
building door and stair ids are not changed. One smoke snapshot is recorded per
actual floor per timestamp even when a floor has several simulation regions.

New simulation code does not update old recordings. Use the live backend to run
a fresh hallway fire, or explicitly regenerate a recording. Batch/risk-map and
what-if results must be regenerated together before comparing them with this
routing behavior; never compare an old baseline with a newly generated variant.

## Checks

`python -m sim.smoke_test` includes a deterministic bisected-corridor case: all
12 occupants go F1 -> F2 -> F1 using different stairs and exit. Without the upper
floor, all 12 receive a no-route outcome and none crosses the fire. It also checks
narrow-gap closure, repeatable events, LLM rule fallback, and opposing-flight
capacity. `--slow` retains the existing real-building and 300-agent checks.

## Doorway retreat regression

For the example's C1 fire at (18.91, 8.07), a 2.5 m hard disc left only a
point-sized slit at D106. The point router offered it while bodies stalled in
R106. The FireModel's kitchen footprint radius is about 1.725 m; the separate
0.35 m required clearance leaves the 1 m doorway usable, so occupants can
retreat toward the opposite stair. The full 160-agent reproduction finishes
with everyone out, including all 13 R106 occupants. This is a model regression,
not evidence that a real doorway beside a fire is safe.

The default suite checks this case with 13 R106 occupants. It also checks that
retaining the larger hard disc produces a genuinely separate, unreachable room,
that the soft-distance cost never makes a feasible path impossible, and that
stair arrivals do not overwrite the reported fire-clearance assumption.

Paired reproduction with the same scenario and seed: progress commit `af311c6`
has 147 evacuated / 13 no-route traps; this change has 160 evacuated / 0 trapped.
All 13 R106 occupants use an upward stair transfer and eventually exit. Existing
recordings are not modified. Wider scenario outcomes can change: the 300-agent
real-office lobby test has 298 evacuated and two early no-route outcomes in
surviving isolated regions; neither outcome is flame or smoke exposure. This
is not a guarantee that every placement has a reachable exit.

Verification: `LLM_PROVIDER=off OPENBLAS_NUM_THREADS=1 python -m sim.smoke_test
--slow` passes (229.3 s). This includes the new doorway regression, original
upstairs crossover/no-route/LLM checks, full-size keep-out comparison, and office
and clinic scale checks. Paired reproduction used the same example scenario,
160 occupants and seed 1 on both the progress commit and the updated code.

## Merged with main (D25 spread, C23 and C27 keep-out, A12 crowd)

- Both cut modes stay. Legacy mode (any other ignition room, or
  `buildingRouting: false`) keeps C21/C23's `keepout_cut` on the largest walkable
  piece: the radius fallbacks, the 0.4 m gap rule and the closing of hairline
  strips. Building-routing mode uses `hazard_cut` over every walkable piece, with
  no largest-region shortcut. `sim.run.uses_building_routing` makes the choice,
  and `sim.sweep`'s keep-out check follows it: corridor and lobby rooms form the
  sweep's "building" class and are checked against the hazard cut.
- The mandatory exclusion is sized from the ignition room's own heat curve. D25's
  spread rooms add heat to `fire.hrr()` but no flame footprint, so their total
  must not widen the disc. That would turn the C1 kitchen fire's 1.725 m into
  about 3.7 m by 400 s.
- D25 acts on door ids and floor ids, never on regions. The doors of a room that
  catches fire close for every region, its occupants are trapped as "burning
  room" in whichever region of the floor they stand, and a doorless stair room
  that catches fire closes its stair group. Either kind of closure resets route
  memory, like any newly blocked door.
- Routes are filtered before the rules and before A12's model decisions (mixed
  and all-LLM batches, 30 s wait). A missing or invalid answer falls back to the
  rules over the same filtered options.

Measured after the merge (seed 1, D's FireModel, drywall unless noted):

| Run | Evacuated | Trapped | Notes |
|---|---:|---:|---|
| Example C1 fire at (18.91, 8.07), spread off | 160 | 0 | Same as the branch. All 13 R106 occupants go F1 -> F2 by SA, down SB, out. F1 has 2 regions |
| Same, D25 spread on (default) | 150 | 10 | All 10 at 180 s, when C1's 11 neighbours ignite, including both F1 stair rooms and both exits: 7 "burning room", 3 "no route". The 13 R106 occupants still cross over upstairs, and 8 are out by then |
| Same fire, `buildingRouting: false` | 132 | 28 | All 28 "untenable", with or without spread |
| Example R101 kitchen (legacy) | 159 | 1 | Events and frames identical to `contracts/run.example.json` (t90 120.73) |
| Office R143, wood (legacy) | 217 | 33 | Events identical to the demo's `run-office-R143-wood` (23 "burning room", 10 "no route") |

`sim.smoke_test --slow` passes after the merge (2344 s on this machine, part of
it alongside `tools/check_all.py`). The office lobby scale check is unchanged at
298 of 300 out, with two early no-route outcomes. The full-size lobby keep-out
comparison is 50 -> 2 trapped. Office corridor R201 runs clean in both modes:
the C23 hairline repro with the legacy keep-out, and 250 of 250 out with
building routing.

Recordings made before this merge keep legacy routing for corridor and lobby
fires (in the demo: the example's L1 pair; batches include lobby rooms). The
spread also means hallway fires can still trap people who are slow to leave:
building routing finds a complete route, not a fast one.
