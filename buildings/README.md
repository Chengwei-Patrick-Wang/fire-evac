# IFC candidates

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
