"""Regenerate the contract examples (scaffold Task S6):

    python tools/build_examples.py

- contracts/building.example.json  <- buildings.normalize(plan.example)
- contracts/run.example.json       <- sim.run(building, scenario.example, ToyFire) + fire.metrics
- contracts/run.spread.fixture.json <- A11 frontend fixture: run.example.json thinned like precompute_demo --thin, with
                                      fire.rooms (D25's wood schedule) and fire.material "wood" added. The agents, smoke
                                      and events do not react to it, so it is a test file: E opens it with File > Open;
                                      sync-demo never copies it, and it is never indexed or published
- contracts/batch.example.json     <- placeholder batch/v0 (seeded random numbers, "placeholder": true);
                                      its doors are named by fire.batch.door_label, as in D's real batches
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from shapely.geometry import Point, Polygon  # noqa: E402

from buildings.normalize import plan_to_building  # noqa: E402
from fire.batch import door_label  # noqa: E402  (D23: the one rule for door names)
from sim.run import run as run_sim  # noqa: E402

CONTRACTS = ROOT / "contracts"
SEEDS = (1, 2, 3)

# D25's wood schedule for the example kitchen fire in R101 (plan 2026-11-14-ember-ui-fire-spread, task D25, "The example"):
# R101 at 0 s, the corridor C1 at 90 s, the ten rooms off C1 (the F1 offices, lobby, lounge and both stairwells) at
# 180 s, then the F2 stairwells at 270 s and its corridor C2 at 360 s. The example run ends at 200 s, so the first
# twelve ignite inside the replay.
SPREAD_FIXTURE_ROOMS = [
    {"room": "R101", "floor": "F1", "ignite": 0.0},
    {"room": "C1", "floor": "F1", "ignite": 90.0},
    *({"room": room, "floor": "F1", "ignite": 180.0}
      for room in ("R102", "L1", "R103", "R104", "R105", "R106", "R107", "R108", "SA1", "SB1")),
    {"room": "SA2", "floor": "F2", "ignite": 270.0},
    {"room": "SB2", "floor": "F2", "ignite": 270.0},
    {"room": "C2", "floor": "F2", "ignite": 360.0},
]
SPREAD_FIXTURE_NOTE = (
    "A11 frontend fixture: fire.rooms and fire.material give D25's wood schedule for this fire; the agents, smoke "
    "and events do not react to it. Not a simulation result; never indexed or published."
)


def load_fire_model():
    try:  # D's real smoke-front model, once it lands on main
        from fire.model import FireModel
        return FireModel, "FireModel (fire/model.py)"
    except Exception:  # noqa: BLE001 - fall back to the placeholder below
        pass
    return _load_placeholder_fire_model()


def _load_placeholder_fire_model():
    try:
        from tools.toy_fire import ToyFire
        return ToyFire, "ToyFire (tools/toy_fire.py)"
    except Exception as exc:  # missing or broken: fall back so the examples still build
        from fire.stub import NoFire
        return NoFire, f"NoFire (fire/stub.py; ToyFire unavailable: {exc!r})"


def load_metrics():
    try:
        from fire.metrics import compute
        return compute
    except Exception as exc:
        print(f"fire.metrics unavailable ({exc!r}): run example keeps the sim metrics only")
        return None


def write_json(path: Path, data: dict, compact: bool = False) -> int:
    text = json.dumps(data, separators=(",", ":")) if compact else json.dumps(data, indent=1)
    path.write_text(text, encoding="utf-8")
    return path.stat().st_size


def thin_run(run: dict) -> dict:
    """The rule of tools/precompute_demo.thin (--thin): every 2nd agent frame, the last one kept so the replay keeps its
    length (frameInterval doubles), and every 3rd smoke frame (interval triples). Events and metrics stay as they were."""
    frames = run["frames"]
    kept = frames[::2]
    if frames and kept[-1] is not frames[-1]:
        kept.append(frames[-1])
    run["frames"] = kept
    run["frameInterval"] = round(run["frameInterval"] * 2, 6)
    for layer in run.get("smoke") or []:
        layer["frames"] = layer["frames"][::3]
        layer["interval"] = round(layer.get("interval", 2) * 3, 6)
    return run


def write_spread_fixture(run: dict, building: dict) -> int:
    """contracts/run.spread.fixture.json: the run it was given, thinned, with the wood fire.rooms on it.
    The run is left as it was."""
    known = {(f["id"], r["id"]) for f in building["floors"] for r in f["rooms"]}
    missing = [e for e in SPREAD_FIXTURE_ROOMS if (e["floor"], e["room"]) not in known]
    if missing:
        raise SystemExit(f"SPREAD_FIXTURE_ROOMS names rooms {building['id']} does not have: {missing}")
    fixture = thin_run(copy.deepcopy(run))
    fixture["fire"].update(rooms=[dict(e) for e in SPREAD_FIXTURE_ROOMS], material="wood")
    head = {"version": fixture["version"], "id": f"{run['id']}-spread-fixture", "fixture": SPREAD_FIXTURE_NOTE}
    fixture = {**head, **{k: v for k, v in fixture.items() if k not in head}}
    return write_json(CONTRACTS / "run.spread.fixture.json", fixture, compact=True)


def _door_kind(door: dict, room_types: dict) -> str:
    if "outside" in door["connects"]:
        return "exit"
    if any(room_types.get(r) == "stair" for r in door["connects"]):
        return "stair"
    return "door"


def make_batch(building: dict, base: dict, heatmaps: list | None) -> dict:
    """Placeholder batch/v0: one ignition per non-corridor room x seeds 1-3, plausible numbers."""
    rng = np.random.default_rng(int(base.get("seed", 1)))
    hot_spots = {}  # floor -> points that hurt most when a fire starts near them (exits, stair doors)
    for f in building["floors"]:
        room_types = {r["id"]: r["type"] for r in f["rooms"]}
        pts = [Point((d["a"][0] + d["b"][0]) / 2, (d["a"][1] + d["b"][1]) / 2)
               for d in f["doors"] if _door_kind(d, room_types) != "door"]
        hot_spots[f["id"]] = pts

    runs, rooms_out = [], []
    for f in building["floors"]:
        for room in f["rooms"]:
            if room["type"] == "corridor":
                continue
            c = Polygon(room["polygon"]).centroid
            dist = min((c.distance(p) for p in hot_spots[f["id"]]), default=20.0)
            impact = max(0.0, 1.0 - dist / 15.0)
            t90s, trapped_s = [], []
            for seed in SEEDS:
                t90 = round(140 + 60 * impact + rng.normal(0, 8), 1)
                t100 = round(t90 + 25 + 20 * impact + abs(rng.normal(0, 6)), 1)
                trapped = int(rng.poisson(0.2 + 3 * impact))
                runs.append({"scenarioId": f"{base['id']}-{room['id']}-s{seed}", "seed": seed,
                             "ignition": {"floor": f["id"], "room": room["id"]},
                             "t90": t90, "t100": t100, "trapped": trapped})
                t90s.append(t90)
                trapped_s.append(trapped)
            rooms_out.append({"id": room["id"], "floor": f["id"], "riskT90": round(float(np.mean(t90s)), 1),
                              "riskTrapped": round(float(np.mean(trapped_s)), 2), "n": len(SEEDS)})

    ranges = {"stair": ((18, 42), (900, 2600)), "exit": ((10, 30), (500, 1600)), "door": ((2, 9), (20, 260))}
    doors_out, meta = [], {}
    for f in building["floors"]:
        room_types = {r["id"]: r["type"] for r in f["rooms"]}
        for d in f["doors"]:
            kind = _door_kind(d, room_types)
            (q0, q1), (w0, w1) = ranges[kind]
            width_factor = min(1.0, 1.0 / max(d.get("width", 1.0), 0.5))  # wide doors queue less
            peak = int(round(rng.uniform(q0, q1) * width_factor))
            wait = round(float(rng.uniform(w0, w1)) * width_factor, 1)
            doors_out.append({"id": d["id"], "floor": f["id"], "meanWait": wait, "peakQueue": peak, "score": 0.0})
            meta[(f["id"], d["id"])] = (kind, door_label(building, f["id"], d["id"])[1])
    max_wait = max(d["meanWait"] for d in doors_out) or 1.0
    max_peak = max(d["peakQueue"] for d in doors_out) or 1
    for d in doors_out:
        d["score"] = round(100 * (0.6 * d["meanWait"] / max_wait + 0.4 * d["peakQueue"] / max_peak), 1)

    top = []
    for d in sorted(doors_out, key=lambda d: (-d["score"], d["id"]))[:3]:
        kind, label = meta[(d["floor"], d["id"])]
        top.append({"kind": kind, "id": d["id"], "floor": d["floor"], "score": d["score"],
                    "why": f"{label}: {d['peakQueue']} people queued at peak; {d['meanWait']:,.0f} "
                           f"person-seconds of waiting per fire on average across {len(runs)} fires."})

    return {
        "version": "batch/v0",
        "id": f"{base['id']}-batch",
        "buildingId": building["id"],
        "placeholder": True,
        "note": "Placeholder numbers (seeded random), not simulated. fire.batch replaces this file.",
        "base": base,
        "runs": runs,
        "rooms": rooms_out,
        "doors": doors_out,
        "heatmaps": heatmaps or [],
        "top": top,
    }


def main() -> int:
    plan = json.loads((CONTRACTS / "plan.example.json").read_text(encoding="utf-8"))
    scenario = json.loads((CONTRACTS / "scenario.example.json").read_text(encoding="utf-8"))

    building = plan_to_building(plan)
    size = write_json(CONTRACTS / "building.example.json", building)
    print(f"building.example.json: {size / 1024:.0f} KB, floors {[f['id'] for f in building['floors']]}")

    fire_cls, fire_name = load_fire_model()
    print(f"fire model: {fire_name}")
    t0 = time.perf_counter()
    run = run_sim(building, scenario, fire=fire_cls(building, scenario))
    sim_s = time.perf_counter() - t0
    compute = load_metrics()
    if compute is not None:
        run["metrics"] = compute(run, building)
    size = write_json(CONTRACTS / "run.example.json", run, compact=True)
    m = run["metrics"]
    print(f"run.example.json: {size / 1e6:.2f} MB ({'OK' if size < 3e6 else 'OVER 3 MB'}), sim {sim_s:.1f} s, "
          f"{len(run['frames'])} frames, {sum(len(s['frames']) for s in run['smoke'])} smoke frames")
    print(f"  agents {m['agents']}, evacuated {m['evacuated']}, inStairs {m['inStairs']}, trapped {m['trapped']}, "
          f"t50 {m['t50']}, t90 {m['t90']}, t100 {m['t100']}, exits {m['exitCounts']}")
    if "doors" in m:
        worst = sorted(m["doors"], key=lambda d: -d["waitPersonSeconds"])[:3]
        print("  worst doors: " + ", ".join(f"{d['id']} {d['waitPersonSeconds']:.0f} p*s" for d in worst))

    size = write_spread_fixture(run, building)
    in_replay = sum(1 for e in SPREAD_FIXTURE_ROOMS if e["ignite"] <= run["frames"][-1]["t"])
    print(f"run.spread.fixture.json: {size / 1e6:.2f} MB, wood fire.rooms {len(SPREAD_FIXTURE_ROOMS)} "
          f"({in_replay} ignite inside the {run['frames'][-1]['t']:.0f} s replay); a frontend test file, never indexed")

    batch = make_batch(building, scenario, m.get("heatmaps"))
    size = write_json(CONTRACTS / "batch.example.json", batch)
    print(f"batch.example.json: {size / 1024:.0f} KB, {len(batch['runs'])} runs, top: "
          + "; ".join(f"{t['kind']} {t['id']} ({t['score']})" for t in batch["top"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
