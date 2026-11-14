# Fire and smoke model (illustrative, not a compliance tool)

Run from the repository root with the project virtual environment active:
`python -m fire.checks` for the model checks, or
`python -m fire.smoke_test` for those checks plus the existing metrics/toy-fire checks.
`--slow` on the checks runner also enables checks whose names end in `_slow`.

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
| `STAIR_UP_M` | 3 m | Reserved upward stair-link distance (links added in D3) |
| `STAIR_DOWN_M` | 30 m | Reserved downward stair-link distance (links added in D3) |
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
Unreachable nodes have infinite distance. Floors remain separate until the D3
stair links are added. `get_graph` retains at most four graphs by building object
identity; callers must treat a building as immutable after caching it.

## Smoke front (D2)

`FireModel(building, scenario)` implements the `NoFire` query API without changing
the stub. This stage propagates on the ignition floor, with no door penalties or
stair links yet. `blocked_doors()` remains empty until D3.

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

Example verification at 60 s: F1 max density is 14.6 (kitchen R101); F2 is
clear. R102 has max density 5.8 at this stage because D2 deliberately passes no
door penalties. The plan's expectation that R102 stays completely clear depends
on the closed-door delays scheduled for D3; no constants were tuned to hide it.
