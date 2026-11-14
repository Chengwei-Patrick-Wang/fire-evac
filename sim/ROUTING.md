# Fire-safe building routes

Corridor and lobby fires use building-wide routing by default. Other scenarios
keep the existing route behavior; `scenario.buildingRouting: true` enables the
new planner explicitly. `false` selects the legacy behavior for comparisons.

## What changes

- The fire exclusion is not reduced merely to keep a hallway connected. Every
  remaining connected region gets a separate JuPedSim simulation. Output floor
  indices still refer to the building floors, not these internal regions.
- The exclusion radius is at least `fireKeepout` (default 2.5 m), and, with D's
  FireModel, at least its predicted maximum flame-footprint radius for this run.
  `fireClearance` adds 0.35 m by default (minimum 0.31 m). Body-width slots are
  closed geometrically. These are illustrative modeling assumptions, not safe
  distances for a real evacuation.
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

`run.routing` records this mode, reserved radius and clearance as optional
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
