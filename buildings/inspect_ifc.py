"""Inspect IFC models and select a candidate for extraction."""

import argparse
from pathlib import Path
import sys

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.unit


CLASSES = ("IfcSpace", "IfcDoor", "IfcStair", "IfcStairFlight")


def storey_of(element):
    """Follow spatial containment and aggregation to a building storey."""
    current = element
    seen = set()
    for _ in range(5):
        if current is None or current.id() in seen:
            break
        seen.add(current.id())
        if current.is_a("IfcBuildingStorey"):
            return current
        current = (ifcopenshell.util.element.get_container(current)
                   or ifcopenshell.util.element.get_aggregate(current))
    if current is not None and current.is_a("IfcBuildingStorey"):
        return current
    return None


def inspect(path):
    model = ifcopenshell.open(str(path))
    scale = ifcopenshell.util.unit.calculate_unit_scale(model)
    storeys = sorted(model.by_type("IfcBuildingStorey"),
                     key=lambda s: (s.Elevation is None, (s.Elevation or 0) * scale, s.id()))
    counts = {storey.id(): {kind: 0 for kind in CLASSES} for storey in storeys}
    totals = {}
    for kind in CLASSES:
        elements = model.by_type(kind)
        totals[kind] = len(elements)
        for element in elements:
            storey = storey_of(element)
            if storey is not None and storey.id() in counts:
                counts[storey.id()][kind] += 1

    empty = [s.Name or str(s.id()) for s in storeys if counts[s.id()]["IfcSpace"] == 0]
    stairs = totals["IfcStair"]
    flights = totals["IfcStairFlight"]
    stair_ok = stairs >= 2 or (stairs == 0 and flights >= 2)
    missing = []
    if not storeys:
        missing.append("no building storeys")
    if empty:
        missing.append("spaces missing on: " + ", ".join(empty))
    if not stair_ok:
        missing.append(f"at least 2 stairs or, if none, 2 flights (found {stairs} stairs, {flights} flights)")

    print(f"\n{path}\nSchema: {model.schema}  Unit scale: {scale:g}")
    print("Storey | Elevation (m) | Spaces | Doors | Stairs | Flights")
    for storey in storeys:
        elevation = "unknown" if storey.Elevation is None else f"{storey.Elevation * scale:.3f}"
        row = counts[storey.id()]
        print(f"{storey.Name or '(unnamed)'} | {elevation} | "
              + " | ".join(str(row[kind]) for kind in CLASSES))
    print("Verdict: " + ("PICKABLE" if not missing else "NOT PICKABLE: " + "; ".join(missing)))
    return {"path": path, "missing": missing, "storeys": len(storeys),
            "with_spaces": len(storeys) - len(empty), "spaces": totals["IfcSpace"],
            "stairs": stairs, "flights": flights}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="IFC files or directories")
    args = parser.parse_args()
    files = set()
    for path in args.paths:
        if path.is_dir():
            files.update(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".ifc")
        elif path.is_file() and path.suffix.lower() == ".ifc":
            files.add(path)
        else:
            print(f"WARNING: no IFC file or directory at {path}", file=sys.stderr)
    results = []
    for path in sorted(files, key=lambda p: str(p).lower()):
        try:
            results.append(inspect(path))
        except Exception as exc:
            print(f"WARNING: could not inspect {path}: {exc}", file=sys.stderr)
    if not results:
        print("No readable IFC models found.", file=sys.stderr)
        return 1
    pickable = [result for result in results if not result["missing"]]
    if pickable:
        chosen = max(pickable, key=lambda r: (r["storeys"], r["spaces"]))
    else:
        chosen = max(results, key=lambda r: (r["with_spaces"], -len(r["missing"]),
                                              r["storeys"], r["spaces"]))
        print("No model is pickable. Missing: " + "; ".join(chosen["missing"]))
    print(f"PICK: {chosen['path'].as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
