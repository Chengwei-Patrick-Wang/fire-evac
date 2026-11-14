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
