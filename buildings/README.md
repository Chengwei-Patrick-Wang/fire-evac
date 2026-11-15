# IFC candidates

## Normalization overrides

`python -m buildings.normalize plan.json building.json --overrides fixes.json`
applies corrections without changing the input plan. If `--overrides` is omitted,
the command loads `buildings/overrides/<plan id>.json` when present. All keys in
the following format are optional:

```json
{
  "floors": {"remove": ["F3"]},
  "doors": {"add": [{"floor": "F1", "id": "DFIX1", "a": [1, 2], "b": [2, 2], "width": 1.0, "fireDoor": false, "state": "open"}], "remove": ["D2"]},
  "rooms": {"remove": ["R2"]},
  "exits": {"add": ["D1"], "remove": ["D3"]},
  "stairGroups": {"S1": ["R3", "R4"]}
}
```

Door and room removals and door additions apply before normalization. Exit
additions force a door to be exterior; exit removals keep the door but suppress
its exit. Stair groups assign the listed rooms to the same stairwell. Unknown
referenced IDs raise an error. The command prints a connectivity report after
writing the building; upper-level exits are informational warnings.
Floor removals happen first and may only remove top storeys.

## Clinic

`clinic` is the NIBS Medical-Dental Clinic, via buildingSMART International's
sample files, CC BY 4.0; it was converted to 2D plans. Modeling assumptions:
remove roof floor F3, roof spaces R2R01 and R2R02, voids R2AC1-A and R2AC1-B,
elevator RE1, outside-access service rooms R1E17, R1E20, R1E21, R1E22, R1E24,
R1E25 and mechanical yard R1F01, and doorless toilet R1D04. Exit DnBZWSx
opens onto the removed roof and is suppressed. Its two floors have nine exits
and stair groups S1, S2 and S3.

Run `python -m buildings.inspect_ifc data/raw` to reproduce the per-storey counts. Downloads are local and not committed. A model is pickable when at least two storeys have spaces and it has at least two stairs (or two flights if it has no stairs). Empty roof, foundation and footing storeys do not disqualify it. Of pickable models with at least 50 spaces, the smallest file is selected.

PICK: data/raw/team-downloads/Office_A_20110811.ifc

The selected IFC2X3 office has unit scale 1 metre per model unit: Level 1 has 60 spaces, 66 doors, 2 stairs and 4 flights; Level 2 has 39 spaces and 36 doors; the roof has no spaces. Totals: 99 spaces, 102 doors, 2 stairs and 4 flights.

Credits: NIBS Common BIM File, US Army ERDC/CERL, free download; no license found. Source: https://www.wbdg.org/node/9165. The office came from the supplied team download bundle.

Runner-up for the second building: `data/raw/nibs-clinic/Clinic_Architectural.ifc`, IFC2X3, scale 1; 269 spaces, 254 doors, 3 stairs and 6 flights. NIBS Common BIM File by US Army ERDC/CERL, free download; no license found. The local clinic was obtained from the [buildingSMART sample mirror](https://github.com/buildingsmart-community/Community-Sample-Test-Files/tree/main/IFC%202.3.0.1%20(IFC%202x3)/Medical-Dental%20Clinic).

VTT models are from VTT Technical Research Centre of Finland, Nordic Sustainable Construction example BIM files, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); share derived plans under the same license. Source: https://cris.vtt.fi/en/publications/bim-files-to-download/.

Totals include elements not assigned to a storey. The full command prints the per-storey table.

| Model | Schema and scale | Counts | Verdict |
| --- | --- | --- | --- |
| `data/raw/nibs-clinic/Clinic_Architectural.ifc` | IFC2X3, scale 1 | spaces=269, doors=254, stairs=3, flights=6 | PICKABLE |
| `data/raw/openifc/west_riverside_hospital.ifc` | IFC4, scale 0.001 | spaces=0, doors=440, stairs=60, flights=0 | NOT PICKABLE |
| `data/raw/team-downloads/Duplex_A_20110907.ifc` | IFC2X3, scale 1 | spaces=21, doors=14, stairs=2, flights=2 | PICKABLE |
| `data/raw/team-downloads/Office_A_20110811.ifc` | IFC2X3, scale 1 | spaces=99, doors=102, stairs=2, flights=4 | PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Housing_Concrete_As-Built_Revit.ifc` | IFC4, scale 0.001 | spaces=145, doors=74, stairs=38, flights=11 | PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Housing_Concrete_BuildingPermit_Revit.ifc` | IFC4, scale 0.001 | spaces=144, doors=74, stairs=38, flights=11 | PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Housing_Terrain-Concrete_BuildingPermit_Revit.ifc` | IFC4, scale 0.001 | spaces=8, doors=0, stairs=1, flights=1 | NOT PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Housing_Terrain-Timber_As-built_Archicad.ifc` | IFC4, scale 1 | spaces=8, doors=0, stairs=0, flights=1 | NOT PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Housing_Terrain-Timber_BuildingPermit_Revit.ifc` | IFC4, scale 0.001 | spaces=8, doors=0, stairs=1, flights=1 | NOT PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Housing_Timber_As-built_Archicad.ifc` | IFC4, scale 1 | spaces=135, doors=72, stairs=7, flights=0 | PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Housing_Timber_As-Built_Revit.ifc` | IFC4, scale 0.001 | spaces=147, doors=76, stairs=38, flights=11 | PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Housing_Timber_BuildingPermit_Revit.ifc` | IFC4, scale 0.001 | spaces=145, doors=76, stairs=38, flights=11 | PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Office_Concrete_As-Built_Revit.ifc` | IFC4, scale 0.001 | spaces=308, doors=269, stairs=16, flights=35 | PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Office_Concrete_BuildingPermit_Archicad.ifc` | IFC4, scale 1 | spaces=304, doors=530, stairs=13, flights=0 | PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Office_Concrete_BuildingPermit_Revit.ifc` | IFC4, scale 0.001 | spaces=308, doors=269, stairs=16, flights=35 | PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Office_Terrain_Concrete_BuildingPermit_Archicad.ifc` | IFC4, scale 1 | spaces=0, doors=0, stairs=0, flights=0 | NOT PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Office_Terrain_Concrete_BuildingPermit_Revit.ifc` | IFC4, scale 0.001 | spaces=9, doors=0, stairs=0, flights=0 | NOT PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Office_Terrain_Timber_BuildingPermit_Revit.ifc` | IFC4, scale 0.001 | spaces=9, doors=0, stairs=0, flights=0 | NOT PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Office_Timber_As-Built_Revit.ifc` | IFC4, scale 0.001 | spaces=306, doors=266, stairs=16, flights=31 | PICKABLE |
| `data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Office_Timber_BuildingPermit_Revit.ifc` | IFC4, scale 0.001 | spaces=306, doors=266, stairs=16, flights=31 | PICKABLE |

## Demo building

`office` has two occupied floors and six exits on F1. Its source and license
status are given in the credits above and in the building JSON. The IFC has
split spaces sharing open boundaries; validation recognizes those where the
walkable area crosses the shared boundary. The overrides omit the elevator and
add assumed connections from the mechanical room to the corridor and from the
electrical room to storage. These are modeling assumptions, not verified doors.
Regenerate with `python -m buildings.ifc data/raw/team-downloads/Office_A_20110811.ifc data/raw/office.plan.json --id office --name "NIBS Office" --credits "NIBS Common BIM File, US Army ERDC/CERL, free download; no license found. Source: https://www.wbdg.org/node/9165"`, then `python -m buildings.normalize data/raw/office.plan.json data/buildings/office.json`.
Create a scenario with `python -m buildings.make_scenario data/buildings/office.json data/buildings/office.scenario.json` (optional `--total`).

## Tidying AI-proposed rooms

Call `tidy_floor(floor, grid=0.25, min_area=1.0, min_width=0.6)` after
sanitizing a proposed floor. It returns a cleaned copy and notes describing
squaring, merges, trims and dropped rooms; doors and other metadata are kept.
Run `python -m buildings.tidy IN OUT` to process a floor or every floor in a
plan and print the notes. This cleanup is geometric and does not verify doors.

## Building index

`data/buildings/index.json` has version `buildings-index/v0` and a `buildings`
array with each public building's identity, source, full and short credits, file
and scenario names, floor and feature counts, stair groups, walkable area,
vertex count, extents and per-floor counts. It contains no top-level building
ID or floors. Rerun `python -m buildings.summary` after changing any building in
`data/buildings/`; use `python -m buildings.summary --check` to detect a stale
index without writing it. A folder and `--out PATH` may also be supplied.

## Public building validation

Run `python -m buildings.validate FILE...` to list geometry, connectivity,
door, credit and scenario problems. A neighboring `<stem>.scenario.json` is
checked automatically. The command exits 1 if any problem is found; upper-floor
exits are allowed. Python callers can use `problems(building, scenario=None)`.
The buildings smoke test checks every public `building/v0` file in
`data/buildings/` and reports all issues together.

## Vertex budget (B12)

Pass `--max-vertices N` to the normalizer to try reducing walkable vertices per floor. The budget is off by default; committed buildings are not budgeted. The normalizer preserves door openings and checks topology, exit and stair zones, and area; it warns when the target cannot be met.

On the office with a 600-vertex per-floor target, the baseline had 1,173 vertices and ran in 12.3 and 12.7 seconds. The budgeted build had 1,077 vertices (F1: 715 to 619; F2: 458 unchanged) and ran in 10.5 and 10.7 seconds. Both evacuated 119 of 120, with t90 117.57 seconds; F1 could not reach the requested budget. Times are illustrative and machine-dependent.

For the office demo scenario, run `python -m buildings.make_scenario data/buildings/office.json data/buildings/office.scenario.json --total 250 --fire-type kitchen`. IFC doors preserve their original IFC Name in `ifcName` and use a readable `name`.

## Door clear width (B16)

IFC OverallWidth measures the leaf width. For a door open at 90 degrees, clear width subtracts one leaf thickness for SINGLE_SWING and DOUBLE_SWING operations, or two for DOUBLE_DOOR operations. Thickness comes from PSet_Revit_Type_Dimensions.Thickness, defaulting to 0.05 m; unknown operations subtract nothing. The measurement follows ADA and ICC A117.1 404.2.3 (open leaf face to stop). The cut is the shortest midpoint-containing walkable section at three offsets across the wall. Exterior cuts can include exit stubs.

The 0.864 m flow gate evacuated 200/200 at 0.932 persons/s (last exit 214.32 s). The earlier office run evacuated 249/250 at t90 132.3 s; the rebuilt office evacuated 249/250 at t90 133.28 s. The rebuilt clinic evacuated 120/120 at t90 123.81 s.

Baseline report (metres):

```text
data\buildings\office.json:
overall width cut count
0.81 0.81 1.86 3
0.81 0.81 2.80 1
0.81 0.81 2.81 1
0.91 0.91 0.92 22
0.91 0.91 0.93 46
0.91 0.91 0.94 15
0.91 0.91 0.95 1
0.91 0.91 1.97 1
0.91 0.91 2.01 1
0.91 0.91 2.02 1
0.91 0.91 2.03 1
0.92 0.92 0.92 1
0.92 0.92 0.93 2
1.00 1.00 1.01 1
1.00 1.00 1.02 1
1.83 1.83 1.84 1
1.83 1.83 1.85 4
1.83 1.83 1.86 1
interior cut - width: median 0.020 m, maximum 0.029 m
data\buildings\clinic.json:
overall width cut count
0.90 0.90 1.95 4
0.91 0.91 0.92 92
0.91 0.91 0.93 97
0.91 0.91 0.94 19
0.91 0.91 1.92 9
0.91 0.91 1.93 2
0.92 0.92 0.92 2
0.92 0.92 1.92 1
1.00 1.00 1.01 1
1.22 1.22 1.23 2
1.73 1.73 1.74 1
1.80 1.80 1.81 2
1.83 1.83 1.84 2
1.83 1.83 1.85 1
1.83 1.83 1.86 1
interior cut - width: median 0.016 m, maximum 1.024 m
```

Rebuilt report (metres):

```text
data\buildings\office.json:
overall width cut count
0.81 0.79 1.84 1
0.81 0.79 1.85 2
0.81 0.79 2.78 1
0.81 0.79 2.79 1
0.92 0.86 0.86 1
0.92 0.86 0.87 24
0.92 0.86 0.88 50
0.92 0.86 0.89 11
0.92 0.86 0.90 1
0.92 0.89 1.96 1
0.92 0.89 2.00 2
0.92 0.89 2.02 1
1.00 1.00 1.01 1
1.00 1.00 1.02 1
1.83 1.73 1.74 3
1.83 1.73 1.75 2
1.83 1.73 1.76 1
interior cut - width: median 0.019 m, maximum 0.029 m
data\buildings\clinic.json:
overall width cut count
0.90 0.85 1.93 4
0.92 0.86 0.87 102
0.92 0.86 0.88 100
0.92 0.86 0.89 8
0.92 0.86 1.86 1
0.92 0.86 1.87 9
0.92 0.86 1.88 2
1.00 0.95 0.96 1
1.22 1.17 1.18 2
1.73 1.63 1.64 1
1.80 1.70 1.71 2
1.83 1.73 1.73 1
1.83 1.73 1.74 2
1.83 1.73 1.75 1
interior cut - width: median 0.016 m, maximum 1.023 m
```

## Plan images and trace

Run `python -m buildings.plan_images` to regenerate the scale-preserving example and office PNGs and example trace and plan in `data/buildings/plans/`. Run `python -m buildings.plan_images --check` to check the JSON metadata without drawing. The example images are 40 px/m and the office images 30 px/m; each includes a 10 m scale bar. The example trace preserves the source's 4 m interior opening; the public-building validator accepts door widths from 0.6 to 6.0 m.

## Example office + extra stair

`example-office-plus` (`data/buildings/`, synthetic) is the example office with one more stairwell and exit, to compare
side by side. Stair C (group SC, SC1 and SC2) takes the east 4 m of the lounge R106 and the open office R207
(x 18-22, y 9.5-16, on the corridor's mid-point), with a 1 m fire door from each corridor (DSC1, DSC2), and exit E3
("South stair exit", 1 m) in SC1's south wall. All other rooms, doors, stairs and exits keep their coordinates. Its
scenario is the example's with every room's headcount pinned (`perRoom`, still 160 people), so the smaller R106 and R207 do
not move people. Regenerate with `python -m buildings.make_example_plus`, then `python -m buildings.summary`. The kitchen
fire in R101, seed 1, rules crowd: the example gets t90 120.7 s, 159 out, 1 trapped, stair door peak queue 2; the copy
t90 113.9 s, 159 out, 1 trapped, stair peak 4 (DSC1), 58 of the 159 leave by E3. Illustrative, like all times here.
