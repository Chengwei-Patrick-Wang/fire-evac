# Buildings and data sources

## Ready-made buildings (no UMass needed)

| Source | What you get | License | Best use |
| --- | --- | --- | --- |
| NIBS Common BIM Files (on WBDG) | IFC, Revit and PDF files: a duplex apartment; a two-story office based on published sample plans for a mid-size US office; a medical and dental clinic based on a real federal clinic, with redacted drawings. The page also lists a "Barracks 101" project, the closest type to a dorm, so check its files | Free downloads; no license found. Made by the US Army Corps of Engineers' research center (ERDC) | **Main demo building candidate:** the clinic (accessibility angle) or the office |
| VTT example BIM files | A residential building and an office building with three office floors | CC BY-SA 4.0 | Clean license for a public repo |
| Open IFC Model Repository (University of Auckland) | About 130 IFC models | CC BY 3.0, per its re3data entry | Browse for a school or taller building |
| Swiss Dwellings v3.0.0 (Zenodo) | About 3,100 real buildings and 45,176 apartments: walls, doors, windows, rooms and public areas such as staircases, as 2D WKT polygons in meters, per floor; a wheelchair-navigable flag per room; 931.9 MB of CSV | CC BY 4.0 | Show it works on many real multi-floor buildings |
| TU Wien escape route models | 8 IFC models of escape routes (route geometry, not full buildings) from a fictional 5-storey test building | CC BY 4.0 | Check our route graph |
| CubiCasa5K | 5,000 annotated plans, mostly Finnish homes | CC BY-NC 4.0 | Test image tracing |
| Jülich Pedestrian Dynamics Data Archive | Experiment geometries (bottleneck, corner, T-junction, corridor) with trajectories and overhead video | Open access; check each dataset | Calibration chart |
| 3D model marketplaces | Good-looking models | Varies | Looks only: no door or stair labels |

**License rules:**
- CC BY and CC BY-SA: credit the source.
- BY-SA: also share derived models under the same license.
- BY-NC: no commercial use.

## Using an IFC model

1. In the first hour, open 2–3 candidates in a free IFC viewer. Keep the one with rooms (`IfcSpace`), doors (`IfcDoor`) and at least two stairs (`IfcStair`) on every floor.
2. Read storeys, spaces, doors and stairs with IfcOpenShell.
   - Project each product's triangles to 2D and union them into a footprint; spaces are vertical extrusions.
   - Buffer door footprints by 0.15 m so they bridge rooms.
   - Walkable area per floor = union of spaces, doors and stairs.
   - Get the unit scale with `ifcopenshell.util.unit.calculate_unit_scale`.
3. Stairs get the same `group` when their footprints overlap on consecutive floors.
4. Exits are ground-floor doors with only one adjacent space. Add a hand-edited overrides file for fixes.
5. Optional: IfcConvert exports a clean SVG plan per floor: `--plan --model --section-height-from-storeys --door-arcs --print-space-names`. SVG output includes only spaces by default, and slices 1 m above each element's base.
6. Render the original model in the browser with web-ifc (stretch).

## UMass options

| Source | What | Rights | Use |
| --- | --- | --- | --- |
| Student Union study (2007, Timothy Murphy Architects), PDF on CORE | Appendix I, pp. 18–20: lower, main and upper floor plans | Open access, no license stated; credit, don't redistribute | **UMass pick:** three floors, several exits; layout may have changed since 2007 |
| Du Bois Library StackMap and floor directory | Layouts of the 26-story tower, drawn for finding shelves | Public pages | Tall-building scenario; confirm stairs on site |
| Campus Center plan, Breuer Digital Archive (Syracuse), c. 1965–73 | One floor plan | "Copyright Not Evaluated"; non-commercial educational use; publishing needs permission (scrc@syr.edu) | Private testing only |
| Haughton (2012) M.S. thesis, Southwest towers | Original Hugh Stubbins plan figures | All rights reserved | Reference only |
| Residence hall plans on UMass Living | Room-level plans | UMass login | Don't copy or publish |
| Posted evacuation maps | Exits, stairs, extinguishers, pull stations | Photograph only where allowed; keep internal | The "from a photo" input |
| UMass Space Management and Campus Planning GIS | CAD exports from Revit; GIS layers with evacuation planning as a listed use | On request (Space Management tracks 13M+ gross sq ft) | After the hackathon |
