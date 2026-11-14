"""Smoke test for fire.metrics and tools.toy_fire. Run from the repo root: python -m fire.smoke_test"""
import base64
import json
from pathlib import Path

from fire.metrics import compute
from tools.toy_fire import ToyFire

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_building():
    """contracts/building.example.json, or a minimal stand-in built from the plan example."""
    path = CONTRACTS / "building.example.json"
    if path.exists():
        return load_json(path), "contracts/building.example.json"
    plan = load_json(CONTRACTS / "plan.example.json")
    floors = []
    for f in plan["floors"]:
        xs = [p[0] for r in f["rooms"] for p in r["polygon"]]
        ys = [p[1] for r in f["rooms"] for p in r["polygon"]]
        outer = [[min(xs), min(ys)], [max(xs), min(ys)], [max(xs), max(ys)], [min(xs), max(ys)]]
        floors.append({"id": f["id"], "doors": f["doors"], "walkable": [{"outer": outer, "holes": []}]})
    return {"version": "building/v0", "id": plan["id"], "floors": floors}, "minimal building from plan.example.json"


def main() -> None:
    building, source = load_building()
    scenario = load_json(CONTRACTS / "scenario.example.json")
    print("building:", source)

    # --- metrics: two agents standing next to door D101 for 10 frames ---
    f1 = building["floors"][0]
    d101 = next(d for d in f1["doors"] if d["id"] == "D101")
    mx = (d101["a"][0] + d101["b"][0]) / 2
    my = (d101["a"][1] + d101["b"][1]) / 2
    frames = [
        {"t": 0.5 * k, "a": [[0, round(mx - 0.5, 2), round(my - 0.5, 2), 0, 1],
                             [1, round(mx + 0.5, 2), round(my + 0.5, 2), 0, 1]]}
        for k in range(10)
    ]
    run = {
        "version": "run/v0", "id": "hand-made", "buildingId": building["id"], "frameInterval": 0.5,
        "floors": [f["id"] for f in building["floors"]], "frames": frames,
        "metrics": {"agents": 2, "evacuated": 0, "trapped": 0, "t50": None, "t90": None, "t100": None, "exitCounts": {}},
    }
    m = compute(run, building)
    json.dumps(m)  # must be plain JSON
    assert m["agents"] == 2, "compute must keep the sim's metrics"
    door = next(d for d in m["doors"] if d["id"] == "D101")
    assert door["floor"] == f1["id"] and door["flow"] is None
    assert door["peakQueue"] == 2, door
    assert door["waitPersonSeconds"] == 10.0, door
    assert len(m["doors"]) == sum(len(f["doors"]) for f in building["floors"])
    assert max(d["peakQueue"] for d in m["doors"]) == 2
    assert all(d["peakQueue"] == 0 and d["waitPersonSeconds"] == 0 for d in m["doors"] if d["floor"] != f1["id"])

    hm = next(h for h in m["heatmaps"] if h["floor"] == f1["id"])
    raw = base64.b64decode(hm["d"])
    assert len(raw) == hm["cols"] * hm["rows"], (len(raw), hm["cols"], hm["rows"])
    assert max(raw) == 100, "the busiest cell is scaled to 100"
    assert len(m["heatmaps"]) == len(building["floors"])
    print("D101: peakQueue=%d waitPersonSeconds=%.1f" % (door["peakQueue"], door["waitPersonSeconds"]))
    print("heatmap %s: %d x %d cells of %.1f m, %d bytes, origin %s" % (
        hm["floor"], hm["cols"], hm["rows"], hm["cell"], len(raw), hm["origin"]))

    # --- toy fire: API shape, smoke grid and visibility at the fire point ---
    fire = ToyFire(building, scenario)
    fp = scenario["fire"]
    assert fire.visibility(fp["floor"], fp["x"], fp["y"]) == 30.0, "clear before the fire grows"
    fire.step(60)
    vis = fire.visibility(fp["floor"], fp["x"], fp["y"])
    assert vis < 3, vis
    snap = fire.snapshot(fp["floor"])
    assert len(base64.b64decode(snap["d"])) == snap["cols"] * snap["rows"]
    assert max(base64.b64decode(snap["d"])) == 80
    other = [f["id"] for f in building["floors"] if f["id"] != fp["floor"]]
    assert all(fire.snapshot(f) is None for f in other)
    assert not fire.untenable(fp["floor"], fp["x"], fp["y"]) and fire.blocked_doors() == set()
    assert abs(fire.hrr(60) - 0.04688 * 60 ** 2) < 1e-9 and fire.hrr(1000) == 1500.0
    print("ToyFire: visibility at the fire point after step(60) = %.2f m, hrr(60) = %.1f kW" % (vis, fire.hrr(60)))
    print("OK")


if __name__ == "__main__":
    main()
