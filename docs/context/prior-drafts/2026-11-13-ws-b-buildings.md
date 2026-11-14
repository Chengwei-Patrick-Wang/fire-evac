# Workstream B — Buildings (IFC to building.json) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn an open IFC model into a building/v0 JSON (walkable areas, rooms, doors, stairs, exits per floor) that the sim and the 3D viewer can use; later, support traced plan images.

**Architecture:** `buildings/ifc.py` reads storeys, spaces, doors and stairs with IfcOpenShell, projects their geometry to 2D footprints with Shapely, and unions spaces plus door and stair footprints into each floor's walkable area. Spec: `docs/superpowers/specs/2026-11-13-fire-evac-sim-design.md`.

**Tech Stack:** Python 3.11, ifcopenshell, shapely 2, numpy, matplotlib (previews), opencv-python-headless (P1).

**Hackathon mode:** no TDD; one `smoke_test.py`; commit after every task.

**Owner profile:** Python, comfortable with geometry.

---

### Task B1: Pick the demo building (H+0 to H+1)

- [ ] Download candidates into `data/raw/`: NIBS clinic and office IFC (WBDG "Common BIM Files"), VTT office (CC BY-SA 4.0), 1–2 from the Open IFC Model Repository.
- [ ] Script `buildings/inspect_ifc.py`: per file print counts of `IfcBuildingStorey`, `IfcSpace`, `IfcDoor`, `IfcStair`, `IfcStairFlight`, and the unit scale (`ifcopenshell.util.unit.calculate_unit_scale`).
- [ ] Pick the model with spaces on every storey and at least two stairs. Write the counts and the pick in `buildings/README.md`. Tell A and E.

### Task B2: Footprints from IFC (H+1 to H+4)

**Files:** `buildings/ifc.py`

- [ ] `ifcopenshell.geom.settings()` with world coordinates; for each product, `create_shape`, take triangle vertices, project to XY, and union the triangles with Shapely to get its footprint (spaces are vertical extrusions, so the projection is the floor area).
- [ ] Group spaces, doors and stairs by containing storey (`ifcopenshell.util.element.get_container`).
- [ ] Doors: footprint buffered by 0.15 m so it overlaps the rooms on both sides; width from `OverallWidth` (times unit scale).
- [ ] Walkable per floor = union(spaces, door footprints, stair footprints); keep the largest connected polygon and warn about leftovers.
- [ ] Shift coordinates so each building's minimum x and y are 0; meters throughout.

### Task B3: Rooms, stairs, exits and JSON (H+4 to H+6)

- [ ] Rooms from spaces: `id` = GlobalId short form, `name` from `LongName` or `Name`, `type` guessed from the name (kitchen, office, stair, corridor…).
- [ ] Stairs: footprints per storey; give footprints that overlap in XY across consecutive storeys the same `group`.
- [ ] Exits: ground-floor doors with only one adjacent space (the other side is outside). Allow `buildings/overrides/<id>.json` to add or remove exits and stair groups by hand.
- [ ] CLI: `python -m buildings.ifc data/raw/clinic.ifc data/buildings/clinic.json`.

### Task B4: Preview and fix-ups (H+6 to H+8) (parallel with B3)

- [ ] `python tools/plot_building.py data/buildings/clinic.json` renders one PNG per floor (walkable, rooms, doors, stairs, exits); share in team chat.
- [ ] `buildings/smoke_test.py`: ≥1 floor, walkable area > 0, ≥1 exit on level 0, every stair group spans ≥2 floors.
- [ ] Hand the JSON to A for the H+8 sync.

### Task B5 (P1): Tracing support (H+12 to H+24)

- [ ] `POST /trace/propose` (with A): image → grayscale → adaptive threshold → thinning → `HoughLinesP` → wall segments in pixels.
- [ ] With E: editor exports building/v0. Walkable = floor outline minus walls buffered by half their thickness, with door rectangles added back; the user marks exits and stairs and sets the scale from one known length.
- [ ] Optional: IfcConvert SVG per floor (`--plan --model --section-height-from-storeys --door-arcs --print-space-names`) as a clean demo image to trace.
