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

## Vertex budget (B12)

Pass `--max-vertices N` to the normalizer to try reducing walkable vertices per floor. The budget is off by default; committed buildings are not budgeted. The normalizer preserves door openings and checks topology, exit and stair zones, and area; it warns when the target cannot be met.

On the office with a 600-vertex per-floor target, the baseline had 1,173 vertices and ran in 12.3 and 12.7 seconds. The budgeted build had 1,077 vertices (F1: 715 to 619; F2: 458 unchanged) and ran in 10.5 and 10.7 seconds. Both evacuated 119 of 120, with t90 117.57 seconds; F1 could not reach the requested budget. Times are illustrative and machine-dependent.
