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
