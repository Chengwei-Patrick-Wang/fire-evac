"""Multi-floor evacuation with width-limited FIFO stair transfers (spec §7.2).

C owns this module (stair transfer, brain, reroutes, blocked doors).

    python -m sim.run BUILDING SCENARIO OUT

Behavior:
- Occupants are split over rooms (not corridor/stair/restroom/storage) by area, or
  scenario.occupants.perRoom; profile, v0 and startDelay come from sim.profiles.
- One CollisionFreeSpeedModel sim per floor. Stages: every exit on the floor, plus
  connected downward stairs. Arrivals wait for a clear spot before re-entry.
- Each agent heads for the nearest exit, or stair on floors without exits, and stands still
  (desired_speed 0) until alarmTime + startDelay.
- Every 1 s: fire.step(t), smoke slows agents, untenable cells trap them.
"""
from __future__ import annotations

from collections import Counter, deque
import argparse
import json
import math
import sys
import time
from pathlib import Path

import jupedsim as jps
import numpy as np
import shapely
from shapely.geometry import Point, Polygon

from fire.stub import NoFire
from sim.profiles import PROFILES
from sim.floors import StairNet, find_spot, reachable_zone

DT = 0.01
FRAME_EVERY = 50     # steps (0.5 s)
FIRE_EVERY = 100     # steps (1 s)
SMOKE_EVERY = 200    # steps (2 s)
FRAME_INTERVAL = 0.5
SMOKE_INTERVAL = 2
NO_OCCUPANTS = {"corridor", "stair", "restroom", "storage"}
WALL_CLEARANCE = 0.3   # spawn inside (room ∩ walkable).buffer(-0.3)
MIN_SPACING = 0.5      # spawn points at least this far apart
STOPPED = 0.0          # desired_speed before the start delay is over (1.4.2 accepts 0)
MIN_SMOKE_SPEED = 0.2


def _warn(msg: str) -> None:
    print(f"WARNING (sim): {msg}", file=sys.stderr)


def floor_walkable(floor: dict) -> Polygon:
    """The floor's walkable polygon (the largest piece if the normalizer left several)."""
    polys = []
    for w in floor["walkable"]:
        poly = Polygon(w["outer"], w["holes"])
        if not poly.is_valid:
            _warn(f"{floor['id']}: repairing invalid walkable polygon with buffer(0)")
            poly = poly.buffer(0)
        polys.extend([poly] if poly.geom_type == "Polygon" else poly.geoms)
    polys = sorted((p for p in polys if not p.is_empty and p.area > 0), key=lambda p: p.area, reverse=True)
    if not polys:
        raise ValueError(f"floor {floor['id']} has no walkable area")
    if len(polys) > 1:
        dropped = 1 - polys[0].area / sum(p.area for p in polys)
        _warn(f"{floor['id']}: {len(polys)} walkable pieces; dropped area {dropped:.1%}; simulating the largest only")
    return polys[0]


def _largest_remainder(total: int, weights: list[float]) -> list[int]:
    w = np.asarray(weights, dtype=float)
    if total <= 0 or w.sum() <= 0:
        return [0] * len(w)
    quota = total * w / w.sum()
    counts = np.floor(quota).astype(int)
    rest = int(total - counts.sum())
    order = np.argsort(-(quota - counts), kind="stable")
    counts[order[:rest]] += 1
    return counts.tolist()


def _sample_points(region, n: int, rng: np.random.Generator, taken: list, label: str) -> list[tuple]:
    """Rejection-sample n points (rounded to 0.01) inside region, >= MIN_SPACING from taken and each other."""
    out: list[tuple] = []
    if n <= 0:
        return out
    minx, miny, maxx, maxy = region.bounds
    min_d, tries, max_tries = MIN_SPACING, 0, 2000 + 400 * n
    while len(out) < n:
        cand = np.round(rng.uniform((minx, miny), (maxx, maxy), size=(64, 2)), 2)
        inside = shapely.contains_xy(region, cand[:, 0], cand[:, 1])
        for (x, y), ok in zip(cand.tolist(), inside):
            if not ok:
                continue
            if taken and min((x - px) ** 2 + (y - py) ** 2 for px, py in taken) < min_d ** 2:
                continue
            taken.append((x, y))
            out.append((x, y))
            if len(out) == n:
                break
        tries += 64
        if len(out) < n and tries > max_tries:
            if min_d > 0.42:
                _warn(f"room {label}: crowded, spacing spawn points at 0.42 m instead of {MIN_SPACING} m")
                min_d, tries = 0.42, 0
            else:
                raise ValueError(f"cannot fit {n} agents in room {label}")
    return out


def place_occupants(building: dict, scenario: dict, rng: np.random.Generator) -> list[dict]:
    """Agents with idx 0..N-1, profile, floor, room, v0, startDelay, radius, x, y."""
    occ = scenario.get("occupants") or {}
    rooms = []  # (floor id, room, spawn region)
    for floor in building["floors"]:
        walk = floor_walkable(floor)
        for room in floor["rooms"]:
            region = Polygon(room["polygon"]).intersection(walk).buffer(-WALL_CLEARANCE)
            rooms.append((floor["id"], room, region))

    if occ.get("perRoom"):
        per_room = occ["perRoom"]
        counts = [int(per_room.get(room["id"], 0)) for _, room, _ in rooms]
    else:
        weights = [Polygon(room["polygon"]).area if room.get("type") not in NO_OCCUPANTS and not region.is_empty
                   else 0.0 for _, room, region in rooms]
        counts = _largest_remainder(int(occ.get("total", 0)), weights)
    for (fid, room, region), n in zip(rooms, counts):
        if n and region.is_empty:
            raise ValueError(f"room {fid}/{room['id']} has no room to place {n} agents")

    agents = [{"idx": 0, "floor": fid, "room": room["id"]} for (fid, room, _), n in zip(rooms, counts) for _ in range(n)]
    mix = occ.get("mix") or {"typical": 1.0}
    names = list(mix)
    p = np.array([float(mix[k]) for k in names])
    p = p / p.sum()
    unknown = set()
    for i, a in enumerate(agents):
        a["idx"] = i
        prof = names[int(rng.choice(len(names), p=p))]
        spec = PROFILES.get(prof)
        if spec is None:
            unknown.add(prof)
            spec = PROFILES["typical"]
        a["profile"] = prof
        a["v0"] = round(float(rng.uniform(*spec["v0"])), 2)
        a["startDelay"] = round(float(rng.uniform(*spec["startDelay"])), 1)
        a["radius"] = spec["radius"]
    if unknown:
        _warn(f"unknown profiles {sorted(unknown)}: using 'typical' parameters")

    taken = {f["id"]: [] for f in building["floors"]}
    i = 0
    for (fid, room, region), n in zip(rooms, counts):
        for x, y in _sample_points(region, n, rng, taken[fid], f"{fid}/{room['id']}"):
            agents[i]["x"], agents[i]["y"] = x, y
            i += 1
    return agents


class _FloorSim:
    """One JuPedSim simulation for one floor, plus our jps-id -> idx map."""

    def __init__(self, floor: dict, index: int, net: StairNet):
        self.id = floor["id"]
        self.index = index
        self.walk = floor_walkable(floor)
        self.sim = jps.Simulation(model=jps.CollisionFreeSpeedModel(), geometry=self.walk, dt=DT)
        self.stages: list[dict] = []
        self.jid2idx: dict[int, int] = {}
        widths = {d["id"]: d["width"] for d in floor["doors"]}
        zones = [{"kind": "exit", "id": e["id"], "group": None,
                  "poly": Polygon(e["polygon"]), "to": None,
                  "width": widths.get(e["door"], 1.0)} for e in floor["exits"]]
        zones += [{"kind": "stair", "id": link["stair"], "group": link["group"],
                   "poly": link["polygon"], "to": link["to"], "width": link["width"]}
                  for link in net.links(self.id)]
        for zone in zones:
            if not reachable_zone(zone["poly"], self.walk, f"{self.id} {zone['kind']} {zone['id']}"):
                continue
            stage = self.sim.add_exit_stage(zone["poly"])
            journey = self.sim.add_journey(jps.JourneyDescription([stage]))
            self.stages.append(dict(zone, stage=stage, journey=journey))
        # Agents who have not started yet "park" on a direct-steering stage aimed at their own
        # position: they still stand as obstacles, but skip JuPedSim's per-step routing, which
        # is ~5x the cost of everything else on this geometry.
        self.park_stage = self.sim.add_direct_steering_stage()
        self.park_journey = self.sim.add_journey(jps.JourneyDescription([self.park_stage]))


def pick_target(fs, pt, exclude=()):
    """Nearest exit, or nearest downward stair if this floor has no exits."""
    options = [st for st in fs.stages if st["id"] not in exclude] or fs.stages
    exits = [st for st in options if st["kind"] == "exit"]
    return min(exits or options, key=lambda st: st["poly"].distance(pt))


class StuckWatch:
    """Track lack of displacement while an agent is moving on one floor."""

    def __init__(self, window=60.0, min_move=0.5):
        self.window, self.min_move = window, min_move
        self.anchors = {}

    def update(self, idx, t, x, y):
        anchor = self.anchors.get(idx)
        if anchor is None or math.hypot(x - anchor[1], y - anchor[2]) >= self.min_move:
            self.anchors[idx] = (t, x, y)
            return False
        if t - anchor[0] >= self.window:
            self.anchors[idx] = (t, x, y)
            return True
        return False


def _interval_steps(scenario, key, default):
    interval = float(scenario.get(key, default))
    if not math.isfinite(interval) or interval < DT or not math.isclose(interval / DT, round(interval / DT)):
        raise ValueError(f"{key} must be a positive multiple of {DT} s")
    return round(interval / DT)


def _frame(sims: list[_FloorSim], trapped: set, status: list[int], transit: dict) -> list[list]:
    rows = []
    for fs in sims:
        for ag in fs.sim.agents():
            i = fs.jid2idx.get(ag.id)
            if i is None or i in trapped or status[i] not in (0, 1):
                continue
            x, y = ag.position
            rows.append([i, round(x, 2) + 0.0, round(y, 2) + 0.0, fs.index, status[i]])
    indices = {fs.id: fs.index for fs in sims}
    for i, entry in transit.items():
        x, y = entry["pos"]
        rows.append([i, round(x, 2), round(y, 2), indices[entry["to"]], 3])
    rows.sort(key=lambda r: r[0])
    return rows


def _t_share(exit_times: list[float], n_agents: int, share: float):
    if n_agents == 0:
        return None
    need = max(1, math.ceil(share * n_agents - 1e-9))
    return exit_times[need - 1] if len(exit_times) >= need else None


def run(building: dict, scenario: dict, fire=None) -> dict:
    """building/v0 + scenario/v0 (+ fire model) -> run/v0."""
    if fire is None:
        fire = NoFire(building, scenario)
    seed = int(scenario.get("seed", 0))
    rng = np.random.default_rng(seed)
    frame_every = _interval_steps(scenario, "frameInterval", FRAME_INTERVAL)
    smoke_every = _interval_steps(scenario, "smokeInterval", SMOKE_INTERVAL)
    frame_interval, smoke_interval = frame_every * DT, smoke_every * DT
    watch = StuckWatch()
    net = StairNet(building, walkable={f["id"]: floor_walkable(f) for f in building["floors"]})
    agents = place_occupants(building, scenario, rng)
    net.check({a["floor"] for a in agents})
    n = len(agents)

    floors = building["floors"]
    sims = [_FloorSim(f, i, net) for i, f in enumerate(floors)]
    by_id = {fs.id: fs for fs in sims}

    status = [0] * n
    target: list[dict | None] = [None] * n
    where: list[tuple | None] = [None] * n
    for a in agents:
        fs = by_id[a["floor"]]
        if not fs.stages:
            raise ValueError(f"floor {fs.id} has occupants but no exits or stairs to go to")
        pt = Point(a["x"], a["y"])
        st = pick_target(fs, pt)
        jid = fs.sim.add_agent(jps.CollisionFreeSpeedModelAgentParameters(
            position=(a["x"], a["y"]), desired_speed=STOPPED, radius=a["radius"],
            journey_id=fs.park_journey, stage_id=fs.park_stage))
        fs.sim.agent(jid).target = (a["x"], a["y"])
        fs.jid2idx[jid] = a["idx"]
        target[a["idx"]] = st
        where[a["idx"]] = (fs, jid)

    alarm = float(scenario.get("alarmTime", 0))
    max_time = float(scenario.get("maxTime", 600))
    start_order = sorted(range(n), key=lambda i: (agents[i]["startDelay"], i))
    next_start = 0

    events: list[dict] = []
    frames: list[dict] = []
    smoke: dict[str, dict] = {}
    hrr: list[list] = []
    trapped: set[int] = set()
    transit = {}
    arrivals = {}

    def enter_stair(i, t, fs, st):
        entry = net.enter(i, t, fs.id, st["group"], rng)
        link = next(link for link in net.links(fs.id) if link["group"] == st["group"])
        entry["arrival"] = link["arrival"]
        entry["group"] = st["group"]
        transit[i] = entry
        arrivals.setdefault((entry["to"], st["group"]), deque()).append(i)
        watch.anchors.pop(i, None)
        status[i] = 3
        where[i] = None
        events.append({"t": t, "type": "stair", "idx": i, "floor": fs.id,
                       "group": st["group"], **{key: entry[key] for key in ("to", "enter", "arrive")}})

    active = n  # agents not yet exited or trapped, including stair transit
    k, t = 0, 0.0
    while True:
        t = round(k * DT, 2)
        while next_start < n and alarm + agents[start_order[next_start]]["startDelay"] <= t + 1e-9:
            i = start_order[next_start]
            next_start += 1
            if status[i] == 0 and i not in trapped:
                fs, jid = where[i]
                fs.sim.switch_agent_journey(jid, target[i]["journey"], target[i]["stage"])
                fs.sim.agent(jid).model.desired_speed = agents[i]["v0"]
                status[i] = 1

        # One queue per destination stair; a blocked head holds all later arrivals.
        for (fid, group), queue in list(arrivals.items()):
            fs = by_id[fid]
            while queue:
                i = queue[0]
                entry = transit[i]
                if entry["arrive"] > t + 1e-9:
                    break
                st = pick_target(fs, entry["arrival"].centroid)
                if st["kind"] == "stair" and st["group"] == group:
                    queue.popleft()
                    enter_stair(i, t, fs, st)
                    continue
                region = entry["arrival"].buffer(-0.3)
                if region.is_empty:
                    region = entry["arrival"].buffer(-0.1)
                positions = [ag.position for ag in fs.sim.agents()]
                pos = find_spot(region, positions, rng)
                if pos is None:
                    break
                jid = fs.sim.add_agent(jps.CollisionFreeSpeedModelAgentParameters(
                    position=pos, desired_speed=agents[i]["v0"], radius=agents[i]["radius"],
                    journey_id=st["journey"], stage_id=st["stage"]))
                fs.jid2idx[jid] = i
                where[i], target[i], status[i] = (fs, jid), st, 1
                queue.popleft()
                del transit[i]

        if k % FIRE_EVERY == 0:
            fire.step(t)
            for fs in sims:
                for ag in list(fs.sim.agents()):
                    i = fs.jid2idx.get(ag.id)
                    if i is None or i in trapped:
                        continue
                    x, y = ag.position
                    if fire.untenable(fs.id, x, y):
                        fs.sim.mark_agent_for_removal(ag.id)
                        trapped.add(i)
                        active -= 1
                        events.append({"t": t, "type": "trapped", "idx": i, "floor": fs.id,
                                       "x": round(x, 2), "y": round(y, 2)})
                    elif status[i] == 1:
                        if watch.update(i, t, x, y):
                            events.append({"t": t, "type": "stuck", "idx": i, "floor": fs.id,
                                           "x": round(x, 2), "y": round(y, 2)})
                            st = pick_target(fs, Point(x, y), exclude={target[i]["id"]})
                            fs.sim.switch_agent_journey(ag.id, st["journey"], st["stage"])
                            target[i] = st
                        v0 = agents[i]["v0"]
                        vis = fire.visibility(fs.id, x, y)
                        ag.model.desired_speed = min(v0, max(MIN_SMOKE_SPEED, v0 - 0.34 * (3.0 - vis)))

        if k % frame_every == 0:
            frames.append({"t": t, "a": _frame(sims, trapped, status, transit)})

        if k % smoke_every == 0:
            for fs in sims:
                snap = fire.snapshot(fs.id)
                if snap is None:
                    continue
                entry = smoke.get(fs.id)
                if entry is None:
                    entry = smoke[fs.id] = {"floor": fs.id, "origin": list(snap["origin"]), "cell": snap["cell"],
                                            "cols": snap["cols"], "rows": snap["rows"],
                                            "interval": smoke_interval, "frames": []}
                entry["frames"].append({"t": t, "d": snap["d"]})
            hrr.append([t, round(float(fire.hrr(t)), 1)])

        if active <= 0 or t >= max_time - 1e-9:
            break

        for fs in sims:
            fs.sim.iterate()
        k += 1
        t_now = round(k * DT, 2)
        for fs in sims:
            for jid in fs.sim.removed_agents():  # last iteration only: check every step
                i = fs.jid2idx.pop(jid, None)
                if i is None or i in trapped:
                    continue
                st = target[i]
                if st["kind"] == "exit":
                    active -= 1
                    status[i] = -1
                    where[i] = None
                    events.append({"t": t_now, "type": "exit", "idx": i, "exit": st["id"]})
                else:
                    enter_stair(i, t_now, fs, st)

    if active <= 0 and frames and frames[-1]["t"] < t:
        # Close the replay with an empty frame on the configured recording grid.
        frames.append({"t": round(math.ceil(t / frame_interval - 1e-9) * frame_interval, 2), "a": []})

    exit_events = [e for e in events if e["type"] == "exit"]
    exit_times = sorted(e["t"] for e in exit_events)
    exit_counts = {e["id"]: 0 for f in floors for e in f["exits"]}
    for e in exit_events:
        exit_counts[e["exit"]] = exit_counts.get(e["exit"], 0) + 1
    metrics = {
        "agents": n,
        "evacuated": len(exit_events),
        "trapped": len(trapped),
        "inStairs": len(transit),
        "remaining": active - len(transit),
        "t50": _t_share(exit_times, n, 0.5),
        "t90": _t_share(exit_times, n, 0.9),
        "t100": _t_share(exit_times, n, 1.0),
        "exitCounts": exit_counts,
    }

    fire_cfg = scenario.get("fire") or {}
    return {
        "version": "run/v0",
        "id": f"{scenario.get('id', 'scenario')}-s{seed}",
        "buildingId": building.get("id"),
        "scenarioId": scenario.get("id"),
        "seed": seed,
        "frameInterval": frame_interval,
        "floors": [f["id"] for f in floors],
        "agents": [{key: a[key] for key in ("idx", "profile", "floor", "room", "v0", "startDelay")} for a in agents],
        "frames": frames,
        "smoke": list(smoke.values()),
        "fire": {"floor": fire_cfg.get("floor"), "x": fire_cfg.get("x"), "y": fire_cfg.get("y"), "hrr": hrr},
        "events": events,
        "metrics": metrics,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("building")
    parser.add_argument("scenario")
    parser.add_argument("out")
    parser.add_argument("--agents", type=int)
    args = parser.parse_args(argv)
    if args.agents is not None and args.agents < 0:
        parser.error("--agents must be nonnegative")
    building = json.loads(Path(args.building).read_text(encoding="utf-8"))
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    if args.agents is not None:
        scenario.setdefault("occupants", {}).pop("perRoom", None)
        scenario["occupants"]["total"] = args.agents
    t0 = time.perf_counter()
    result = run(building, scenario)
    elapsed = time.perf_counter() - t0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(result["metrics"]))
    print("event counts:", dict(Counter(e["type"] for e in result["events"])))
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB, {len(result['frames'])} frames) in {elapsed:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
