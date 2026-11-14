"""Measure saturated door flow: python -m buildings.calibrate_doors [--agents 200]."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from buildings.normalize import plan_to_building
from sim.run import run

ROOT = Path(__file__).resolve().parents[1]
WIDTHS = (0.8, 1.0, 1.2, 1.6)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", type=int, default=200)
    args = parser.parse_args()
    if args.agents < 2:
        parser.error("--agents must be at least 2")
    fixture = ROOT / "buildings/fixtures/one_door.plan.json"
    points = []
    print("width | simulated | simulated per m | IMO | hydraulic | simulated/hydraulic", flush=True)
    for width in WIDTHS:
        plan = json.loads(fixture.read_text(encoding="utf-8-sig"))
        door = plan["floors"][0]["doors"][0]
        door.update(a=[14, 5 - width / 2], b=[14, 5 + width / 2], width=width)
        scenario = {"version": "scenario/v0", "id": f"calib-{width}", "buildingId": "one-door",
                    "seed": 1, "occupants": {"perRoom": {"R1": args.agents}, "mix": {"typical": 1.0}},
                    "fire": {"floor": "F1", "room": "R1", "x": 2, "y": 5, "type": "trash", "start": 0},
                    "sprinklers": False, "doors": {}, "alarmTime": 0, "maxTime": 900}
        result = run(plan_to_building(plan), scenario)
        times = sorted(e["t"] for e in result["events"] if e["type"] == "exit")
        if result["metrics"]["evacuated"] < args.agents or len(times) < args.agents:
            print(f"ERROR: {width:.1f} m: only {len(times)}/{args.agents} evacuated; raise maxTime.")
            return 1
        i10, i90 = int(0.1 * len(times)), int(0.9 * len(times))
        elapsed = times[i90] - times[i10]
        if elapsed <= 0:
            print(f"ERROR: {width:.1f} m: exit times do not span an interval.")
            return 1
        flow = (i90 - i10) / elapsed
        imo, hydraulic = 1.3 * width, 1.3 * (width - 0.3)
        ratio = flow / hydraulic
        print(f"{width:.1f} | {flow:.3f} | {flow / width:.3f} | {imo:.3f} | {hydraulic:.3f} | {ratio:.3f}", flush=True)
        if not 0.5 <= ratio <= 2.0:
            print(f"ERROR: {width:.1f} m: flow outside calibration bounds; check the exit stub.")
            return 1
        points.append({"label": f"{width:.1f} m door", "width": width, "simulated": round(flow, 4),
                       "references": [{"name": "IMO 1.3 persons/(m·s) × width", "value": round(imo, 4)},
                                      {"name": "Hydraulic 1.3 × (width − 0.3)", "value": round(hydraulic, 4)}]})
    output = {"version": "calibration/v0", "title": "Door flow: simulation against published values",
              "source": f"JuPedSim 1.4.2 CollisionFreeSpeedModel, {args.agents} agents, seed 1", "points": points}
    path = ROOT / "data/calibration.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
