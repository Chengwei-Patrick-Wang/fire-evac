"""Summarize IFC candidates and pick the most complete multi-storey model."""

import argparse
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.unit


KINDS = ("IfcSpace", "IfcDoor", "IfcStair", "IfcStairFlight")


def storey_of(element):
    """Follow containment or aggregation to a storey, including for spaces."""
    current = element
    seen = set()
    for _ in range(5):
        if current is None or current.id() in seen:
            return None
        seen.add(current.id())
        if current.is_a("IfcBuildingStorey"):
            return current
        current = (ifcopenshell.util.element.get_container(current)
                   or ifcopenshell.util.element.get_aggregate(current))
    return current if current is not None and current.is_a("IfcBuildingStorey") else None


def inspect(path):
    model = ifcopenshell.open(str(path))
    scale = ifcopenshell.util.unit.calculate_unit_scale(model)
    storeys = sorted(model.by_type("IfcBuildingStorey"),
                     key=lambda s: (s.Elevation is None, (s.Elevation or 0) * scale, s.Name or "", s.id()))
    counts = {s.id(): [0] * len(KINDS) for s in storeys}
    totals = []
    for i, kind in enumerate(KINDS):
        elements = model.by_type(kind)
        totals.append(len(elements))
        for element in elements:
            storey = storey_of(element)
            if storey is not None and storey.id() in counts:
                counts[storey.id()][i] += 1
    empty_storeys = [s.Name or str(s.id()) for s in storeys if counts[s.id()][0] == 0]
    missing_spaces = len(empty_storeys)
    stairs = totals[2] if totals[2] else totals[3]
    pickable = bool(storeys) and not missing_spaces and stairs >= 2
    print(f"\n{path}\n  schema: {model.schema}; unit scale: {scale:g}")
    print("  storey | elevation (m) | spaces | doors | stairs | flights")
    for s in storeys:
        elevation = "?" if s.Elevation is None else f"{s.Elevation * scale:.3f}"
        print(f"  {s.Name or '(unnamed)'} | {elevation} | " + " | ".join(map(str, counts[s.id()])))
    print(f"  totals: spaces={totals[0]}, doors={totals[1]}, stairs={totals[2]}, flights={totals[3]}")
    print("  " + ("PICKABLE" if pickable else "NOT PICKABLE"))
    return {"path": path, "storeys": len(storeys), "spaces": totals[0],
            "missing": missing_spaces, "empty_storeys": empty_storeys,
            "stairs": stairs, "pickable": pickable}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    paths = set()
    for path in args.paths:
        if path.is_dir():
            paths.update(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".ifc")
        elif path.is_file() and path.suffix.lower() == ".ifc":
            paths.add(path)
        else:
            parser.error(f"not an IFC file or directory: {path}")
    results = []
    for path in sorted(paths, key=lambda p: str(p).lower()):
        try:
            results.append(inspect(path))
        except Exception as exc:
            print(f"\n{path}\n  ERROR: {exc}")
    if not results:
        parser.exit(1, "No readable IFC models found.\n")
    pickable = [r for r in results if r["pickable"]]
    if pickable:
        pick = max(pickable, key=lambda r: (r["storeys"], r["spaces"]))
    else:
        pick = max(results, key=lambda r: (r["storeys"] - r["missing"], min(r["stairs"], 2), r["spaces"]))
        print(f"No pickable model: closest is missing spaces on {pick['missing']} storeys "
              f"and needs {max(0, 2 - pick['stairs'])} more stairs or flights.")
        if pick["empty_storeys"]:
            print("Storeys without spaces: " + ", ".join(pick["empty_storeys"]))
    print(f"PICK: {pick['path'].as_posix()}")


if __name__ == "__main__":
    main()
