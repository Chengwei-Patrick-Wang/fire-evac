# IFC candidates

Run `python -m buildings.inspect_ifc data/raw` to reproduce the inspection below. Paths in `data/raw/` are local downloads and are not committed.

No model passes the task's strict rule that every storey have spaces. The tool's closest candidate is:

PICK: data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Office_Concrete_As-Built_Revit.ifc

This is a fallback, not a pickable model. Its unit scale is 0.001 m per model unit. Six storeys contain spaces, but an empty parking storey separates occupied storeys, so B2's contiguous-storey requirement will reject it. The traced building is the fallback described in the plan; do not assume this IFC is ready for extraction.

Runner-up: `data/raw/nibs-clinic/Clinic_Architectural.ifc` (IFC2X3, scale 1): first, second and roof levels have 154, 109 and 6 spaces respectively; its footing storey has none. The clinic's occupied storeys are contiguous, but it does not meet the strict B1 verdict.

Credits for the closest candidate: VTT Technical Research Centre of Finland, Nordic Sustainable Construction example BIM files, CC BY-SA 4.0; share any derived plan under the same license. Source: https://cris.vtt.fi/en/publications/bim-files-to-download/ . The clinic model is a free NIBS Common BIM File by US Army ERDC/CERL; no license was found. Clinic copy: https://github.com/buildingsmart-community/Community-Sample-Test-Files/tree/main/IFC%202.3.0.1%20(IFC%202x3)/Medical-Dental%20Clinic . The NIBS office was not available locally; the clinic was obtained from the public buildingSMART sample mirror. The Open IFC hospital candidate had no spaces.

The table rows below list per-storey counts; totals include any elements not assigned to a storey. `PICKABLE` requires a space on every storey and at least two stairs (or two flights if there are no stairs).

```text

data\raw\nibs-clinic\Clinic_Architectural.ifc
  schema: IFC2X3; unit scale: 1
  storey | elevation (m) | spaces | doors | stairs | flights
  TOF Footing | -1.000 | 0 | 2 | 0 | 0
  First Floor | -0.000 | 154 | 156 | 3 | 6
  Second Floor | 4.570 | 109 | 96 | 0 | 0
  Roof - Main | 9.250 | 6 | 0 | 0 | 0
  totals: spaces=269, doors=254, stairs=3, flights=6
  NOT PICKABLE

data\raw\openifc\west_riverside_hospital.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Level 1 | 0.000 | 0 | 114 | 14 | 0
  Level 2 | 6.000 | 0 | 57 | 14 | 0
  Level 3 | 11.000 | 0 | 101 | 14 | 0
  Level 4 | 16.000 | 0 | 88 | 12 | 0
  Level 5 | 21.000 | 0 | 74 | 4 | 0
  Level 6 | 26.000 | 0 | 5 | 2 | 0
  Level 7A | 31.000 | 0 | 0 | 0 | 0
  Level 7 | 34.000 | 0 | 1 | 0 | 0
  totals: spaces=0, doors=440, stairs=60, flights=0
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Housing_Concrete_As-Built_Revit.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Sea level | -0.000 | 0 | 0 | 0 | 0
  Foundations | 47.300 | 0 | 0 | 0 | 0
  Basement | 49.070 | 17 | 12 | 3 | 4
  Level_01 | 52.000 | 16 | 14 | 3 | 3
  Level_02 | 54.930 | 25 | 15 | 1 | 2
  Level_03 | 58.030 | 22 | 15 | 1 | 2
  Level_04 | 61.130 | 22 | 15 | 0 | 0
  Roof | 64.035 | 0 | 3 | 30 | 0
  totals: spaces=145, doors=74, stairs=38, flights=11
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Housing_Concrete_BuildingPermit_Revit.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Sea level | -0.000 | 0 | 0 | 0 | 0
  Foundations | 47.300 | 0 | 0 | 0 | 0
  Basement | 49.070 | 16 | 12 | 3 | 4
  Level_01 | 52.000 | 16 | 14 | 3 | 3
  Level_02 | 54.930 | 25 | 15 | 1 | 2
  Level_03 | 58.030 | 22 | 15 | 1 | 2
  Level_04 | 61.130 | 22 | 15 | 0 | 0
  Roof | 64.035 | 0 | 3 | 30 | 0
  totals: spaces=144, doors=74, stairs=38, flights=11
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Housing_Terrain-Concrete_BuildingPermit_Revit.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Sea level | -0.000 | 0 | 0 | 0 | 0
  Foundations | 47.300 | 0 | 0 | 0 | 0
  Basement | 49.070 | 0 | 0 | 0 | 0
  Level_01 | 52.000 | 8 | 0 | 1 | 1
  totals: spaces=8, doors=0, stairs=1, flights=1
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Housing_Terrain-Timber_As-built_Archicad.ifc
  schema: IFC4; unit scale: 1
  storey | elevation (m) | spaces | doors | stairs | flights
  Sea_Level | 0.000 | 0 | 0 | 0 | 0
  Basement | 49.070 | 8 | 0 | 0 | 1
  Level_01 | 52.000 | 0 | 0 | 0 | 0
  totals: spaces=8, doors=0, stairs=0, flights=1
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Housing_Terrain-Timber_BuildingPermit_Revit.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Sea level | -0.000 | 0 | 0 | 0 | 0
  Foundations | 47.300 | 0 | 0 | 0 | 0
  Basement | 49.070 | 0 | 0 | 0 | 0
  Level_01 | 52.000 | 8 | 0 | 1 | 1
  totals: spaces=8, doors=0, stairs=1, flights=1
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Housing_Timber_As-built_Archicad.ifc
  schema: IFC4; unit scale: 1
  storey | elevation (m) | spaces | doors | stairs | flights
  Sea_Level | 0.000 | 0 | 0 | 0 | 0
  Foundations | 47.300 | 0 | 0 | 0 | 0
  Basement | 49.070 | 20 | 13 | 1 | 0
  Level_01 | 52.000 | 20 | 12 | 2 | 0
  Level_02 | 55.144 | 32 | 16 | 3 | 0
  Level_03 | 58.458 | 31 | 15 | 1 | 0
  Level_04 | 61.772 | 31 | 15 | 0 | 0
  Roof | 64.677 | 1 | 1 | 0 | 0
  totals: spaces=135, doors=72, stairs=7, flights=0
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Housing_Timber_As-Built_Revit.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Sea level | -0.000 | 0 | 0 | 0 | 0
  Foundations | 47.300 | 0 | 0 | 0 | 0
  Basement | 49.070 | 18 | 13 | 3 | 4
  Level_01 | 52.000 | 17 | 14 | 3 | 3
  Level_02 | 55.144 | 25 | 16 | 1 | 2
  Level_03 | 58.458 | 22 | 15 | 1 | 2
  Level_04 | 61.772 | 22 | 15 | 0 | 0
  Roof | 64.677 | 0 | 3 | 30 | 0
  totals: spaces=147, doors=76, stairs=38, flights=11
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Housing_Timber_BuildingPermit_Revit.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Sea level | -0.000 | 0 | 0 | 0 | 0
  Foundations | 47.300 | 0 | 0 | 0 | 0
  Basement | 49.070 | 17 | 13 | 3 | 4
  Level_01 | 52.000 | 16 | 14 | 3 | 3
  Level_02 | 55.144 | 25 | 16 | 1 | 2
  Level_03 | 58.458 | 22 | 15 | 1 | 2
  Level_04 | 61.772 | 22 | 15 | 0 | 0
  Roof | 64.677 | 0 | 3 | 30 | 0
  totals: spaces=145, doors=76, stairs=38, flights=11
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Office_Concrete_As-Built_Revit.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Sea Level | -0.000 | 0 | 0 | 0 | 0
  Foundation | 51.000 | 0 | 0 | 0 | 0
  Basement | 51.700 | 39 | 52 | 5 | 8
  Level_01 | 55.500 | 53 | 58 | 3 | 7
  Level_02a_Parking | 58.900 | 0 | 0 | 1 | 1
  Level_02 | 59.700 | 48 | 46 | 2 | 6
  Level_03 | 63.650 | 53 | 48 | 2 | 6
  Level_04 | 67.600 | 53 | 48 | 2 | 6
  Level_05 | 71.920 | 18 | 13 | 1 | 1
  Roof | 77.890 | 0 | 4 | 0 | 0
  totals: spaces=308, doors=269, stairs=16, flights=35
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Office_Concrete_BuildingPermit_Archicad.ifc
  schema: IFC4; unit scale: 1
  storey | elevation (m) | spaces | doors | stairs | flights
  Foundations | 49.070 | 0 | 0 | 0 | 0
  Basement | 51.700 | 50 | 43 | 3 | 0
  Level_01 | 55.500 | 78 | 136 | 5 | 0
  Garage_02 | 58.900 | 0 | 0 | 0 | 0
  Level_02 | 59.700 | 48 | 108 | 2 | 0
  Level_03 | 63.650 | 53 | 116 | 2 | 0
  Level_04 | 67.650 | 53 | 126 | 1 | 0
  Level_05 | 71.920 | 22 | 1 | 0 | 0
  Roof | 75.920 | 0 | 0 | 0 | 0
  totals: spaces=304, doors=530, stairs=13, flights=0
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Office_Concrete_BuildingPermit_Revit.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Sea Level | -0.000 | 0 | 0 | 0 | 0
  Foundation | 51.000 | 0 | 0 | 0 | 0
  Basement | 51.700 | 39 | 52 | 5 | 8
  Level_01 | 55.500 | 53 | 58 | 3 | 7
  Level_02a_Parking | 58.900 | 0 | 0 | 1 | 1
  Level_02 | 59.700 | 48 | 46 | 2 | 6
  Level_03 | 63.650 | 53 | 48 | 2 | 6
  Level_04 | 67.600 | 53 | 48 | 2 | 6
  Level_05 | 71.920 | 18 | 13 | 1 | 1
  Roof | 77.890 | 0 | 4 | 0 | 0
  totals: spaces=308, doors=269, stairs=16, flights=35
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Office_Terrain_Concrete_BuildingPermit_Archicad.ifc
  schema: IFC4; unit scale: 1
  storey | elevation (m) | spaces | doors | stairs | flights
  Foundations | 49.070 | 0 | 0 | 0 | 0
  totals: spaces=0, doors=0, stairs=0, flights=0
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Office_Terrain_Concrete_BuildingPermit_Revit.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Merenpinta | -0.000 | 0 | 0 | 0 | 0
  00_Kellari | 51.700 | 0 | 0 | 0 | 0
  01_Kerros | 55.500 | 7 | 0 | 0 | 0
  totals: spaces=9, doors=0, stairs=0, flights=0
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Office_Terrain_Timber_BuildingPermit_Revit.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Merenpinta | -0.000 | 0 | 0 | 0 | 0
  00_Kellari | 51.700 | 0 | 0 | 0 | 0
  01_Kerros | 55.500 | 7 | 0 | 0 | 0
  totals: spaces=9, doors=0, stairs=0, flights=0
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Office_Timber_As-Built_Revit.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Sea Level | -0.000 | 0 | 0 | 0 | 0
  Perustukset | 51.000 | 0 | 0 | 0 | 0
  Basement | 51.700 | 39 | 51 | 5 | 8
  Level_01 | 55.500 | 51 | 56 | 3 | 7
  Level_02a_Parking | 58.900 | 0 | 0 | 1 | 1
  Level_02 | 59.700 | 48 | 46 | 2 | 6
  Level_03 | 63.720 | 53 | 48 | 2 | 6
  Level_04 | 67.740 | 53 | 48 | 2 | 2
  Level_05 | 72.305 | 18 | 13 | 1 | 1
  Roof | 78.366 | 0 | 4 | 0 | 0
  totals: spaces=306, doors=266, stairs=16, flights=31
  NOT PICKABLE

data\raw\vtt\ARCH\IFC\ARK_NordicLCA_Office_Timber_BuildingPermit_Revit.ifc
  schema: IFC4; unit scale: 0.001
  storey | elevation (m) | spaces | doors | stairs | flights
  Sea Level | -0.000 | 0 | 0 | 0 | 0
  Foundations | 51.000 | 0 | 0 | 0 | 0
  Basement | 51.700 | 39 | 51 | 5 | 8
  Level_01 | 55.500 | 51 | 56 | 3 | 7
  Level_02a_Parking | 58.900 | 0 | 0 | 1 | 1
  Level_02 | 59.700 | 48 | 46 | 2 | 6
  Level_03 | 63.720 | 53 | 48 | 2 | 6
  Level_04 | 67.740 | 53 | 48 | 2 | 2
  Level_05 | 72.305 | 18 | 13 | 1 | 1
  Roof | 78.366 | 0 | 4 | 0 | 0
  totals: spaces=306, doors=266, stairs=16, flights=31
  NOT PICKABLE
No pickable model: closest is missing spaces on 4 storeys and needs 0 more stairs or flights.
PICK: data/raw/vtt/ARCH/IFC/ARK_NordicLCA_Office_Concrete_As-Built_Revit.ifc
```
