"""Multi-floor evacuation with width-limited stair transfers (spec §7.2).

C owns this module (stair transfer, brain, reroutes, blocked doors).

    python -m sim.run BUILDING SCENARIO OUT

Behavior:
- Occupants are split over rooms (not corridor/stair/restroom/storage) by area, or
  scenario.occupants.perRoom; profile, v0 and startDelay come from sim.profiles.
- One CollisionFreeSpeedModel sim per floor. Stages: every exit on the floor, plus
  connected downward stairs. Assistance waits leave earlier admission slots free;
  arrivals re-enter in arrival-time order once a clear spot is available.
- Each agent chooses a route using travel time and queues, and stands still
  (desired_speed 0) until alarmTime + startDelay, or an earlier cue countdown.
- Fire in the same room, or visibility below 10 m, starts a separate 0–10 s
  cue delay; the first cue wins and the alarm can still start people sooner.
  scenario.premovement overrides profile delay ranges by room type.
- People keep 2.5 m from the burning item where room geometry permits;
  smaller keep-out areas preserve connected escape routes.
- Every 1 s: fire.step(t), smoke slows agents, untenable cells trap them.
- Mid-run blocked interior doors act only through slowdown and trapping.
  Agents in a stairwell (status 2 or 3) are not exposed to fire.
"""
from __future__ import annotations

from collections import Counter
from heapq import heappush, heappop
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
from sim.brain import RuleBrain, route_length, ROUTING_MODE, mobility_options, LLMBrain, load_llm_decider, load_llm_batch_decider
from sim.profiles import PROFILES, CUE_VIS_M, CUE_DELAY
from sim.floors import StairNet, find_spot, reachable_zone, stair_blocked, stair_doors

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
FIRE_KEEPOUT_M = 2.5


def _warn(msg: str) -> None:
    print(f"WARNING (sim): {msg}", file=sys.stderr)


def floor_walkable(floor: dict, blocked=frozenset()) -> Polygon:
    """The floor's walkable polygon (the largest piece if the normalizer left several)."""
    polys = []
    for w in floor["walkable"]:
        poly = Polygon(w["outer"], w["holes"])
        if not poly.is_valid:
            _warn(f"{floor['id']}: repairing invalid walkable polygon with buffer(0)")
            poly = poly.buffer(0)
        for door in floor.get("doors", []):
            if door["id"] in blocked:
                poly = poly.difference(Polygon(door["rect"]))
        polys.extend([poly] if poly.geom_type == "Polygon" else poly.geoms)
    polys = sorted((p for p in polys if not p.is_empty and p.area > 0), key=lambda p: p.area, reverse=True)
    if not polys:
        raise ValueError(f"floor {floor['id']} has no walkable area")
    if len(polys) > 1:
        dropped = 1 - polys[0].area / sum(p.area for p in polys)
        _warn(f"{floor['id']}: {len(polys)} walkable pieces; dropped area {dropped:.1%}; simulating the largest only")
    return polys[0]


def fire_keepout(walk, floor, room, x, y, radius) -> Polygon:
    """Cut a room-clipped fire disc, retaining connected exits and stair zones."""
    if not math.isfinite(radius) or radius < 0:
        raise ValueError("fireKeepout must be finite and nonnegative")
    if radius == 0:
        return walk
    point = Point(x, y)
    origin = next((r for r in floor["rooms"] if r["id"] == room), None)
    if origin is None:
        origin = next((r for r in floor["rooms"] if Polygon(r["polygon"]).covers(point)), None)
    if origin is None:
        return walk
    room_poly = Polygon(origin["polygon"])
    room_area = walk.intersection(room_poly).area
    zones = [Polygon(z["polygon"]) for z in floor["exits"] + floor["stairs"]]
    attached = [z for z in zones if not z.is_empty and z.distance(walk) <= 0.1]
    # Never enlarge an explicitly smaller user-supplied distance on fallback.
    radii = dict.fromkeys([radius] + [r for r in (1.5, 1.0) if r < radius])
    for candidate in radii:
        cut = walk.difference(point.buffer(candidate).intersection(room_poly))
        pieces = [cut] if cut.geom_type == "Polygon" else list(cut.geoms)
        pieces = sorted((p for p in pieces if p.geom_type == "Polygon" and not p.is_empty),
                        key=lambda p: p.area, reverse=True)
        if not pieces or any(p.area > 0.5 for p in pieces[1:]):
            continue
        retained = pieces[0]
        if retained.intersection(room_poly).area < room_area / 4:
            continue
        if any(z.distance(retained) > 0.1 for z in attached):
            continue
        return retained
    _warn(f"{floor['id']}/{origin['id']}: no safe fire keep-out cut; keeping walkable area")
    return walk


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


def _sample_points(region, n: int, rng: np.random.Generator, taken: list, label: str, spacing=MIN_SPACING) -> list[tuple]:
    """Rejection-sample n points (rounded to 0.01) inside region, >= MIN_SPACING from taken and each other."""
    out: list[tuple] = []
    if n <= 0:
        return out
    minx, miny, maxx, maxy = region.bounds
    min_d, tries, max_tries = spacing, 0, 2000 + 400 * n
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
            if spacing == MIN_SPACING and min_d > 0.42:
                _warn(f"room {label}: crowded, spacing spawn points at 0.42 m instead of {MIN_SPACING} m")
                min_d, tries = 0.42, 0
            else:
                raise ValueError(f"cannot fit {n} agents in room {label}")
    return out


def place_occupants(building: dict, scenario: dict, rng: np.random.Generator, walkable=None) -> list[dict]:
    """Agents with idx 0..N-1, profile, floor, room, v0, startDelay, radius, x, y."""
    premovement = scenario.get("premovement", {})
    if not isinstance(premovement, dict):
        raise ValueError("premovement must map room types to [lo, hi] ranges")
    for room_type, bounds in premovement.items():
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in bounds)
                or not 0 <= bounds[0] <= bounds[1]):
            raise ValueError(f"premovement {room_type}: expected two finite numbers with 0 <= lo <= hi")
    room_types = {(f["id"], r["id"]): r.get("type")
                  for f in building["floors"] for r in f["rooms"]}
    occ = scenario.get("occupants") or {}
    rooms = []  # (floor id, room, spawn region)
    for floor in building["floors"]:
        walk = floor_walkable(floor) if walkable is None else walkable[floor["id"]]
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
        delay = premovement.get(room_types[a["floor"], a["room"]], spec["startDelay"])
        a["startDelay"] = round(float(rng.uniform(*delay)), 1)
        a["radius"] = spec["radius"]
    if unknown:
        _warn(f"unknown profiles {sorted(unknown)}: using 'typical' parameters")

    spacing = max(MIN_SPACING, 2 * max((a["radius"] for a in agents), default=0.2) + 0.01)
    taken = {f["id"]: [] for f in building["floors"]}
    i = 0
    for (fid, room, region), n in zip(rooms, counts):
        for x, y in _sample_points(region, n, rng, taken[fid], f"{fid}/{room['id']}", spacing):
            agents[i]["x"], agents[i]["y"] = x, y
            i += 1
    return agents


class _FloorSim:
    """One JuPedSim simulation for one floor, plus our jps-id -> idx map."""

    def __init__(self, floor: dict, index: int, net: StairNet, blocked, walk):
        self.id = floor["id"]
        self.index = index
        self.walk = walk
        self.sim = jps.Simulation(model=jps.CollisionFreeSpeedModel(), geometry=self.walk, dt=DT)
        self.stages: list[dict] = []
        self.jid2idx: dict[int, int] = {}
        widths = {d["id"]: d["width"] for d in floor["doors"]}
        zones = [{"kind": "exit", "id": e["id"], "group": None,
                  "poly": Polygon(e["polygon"]), "to": None,
                  "name": e.get("name", e["id"]), "tail": 0.0,
                  "door": e["door"], "width": widths.get(e["door"], 1.0)}
                 for e in floor["exits"] if e["door"] not in blocked]
        zones += [{"kind": "stair", "id": link["stair"], "group": link["group"],
                   "poly": link["polygon"], "to": link["to"], "width": link["width"],
                   "name": link["stair"], "tail": link["tail"]}
                  for link in net.links(self.id)]
        for zone in zones:
            if not reachable_zone(zone["poly"], self.walk, f"{self.id} {zone['kind']} {zone['id']}"):
                continue
            stage = self.sim.add_exit_stage(zone["poly"])
            journey = self.sim.add_journey(jps.JourneyDescription([stage]))
            self.stages.append(dict(zone, stage=stage, journey=journey,
                                    nearby=zone["poly"].buffer(3.0)))
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
        waiting = status[i] == 2
        x, y = entry["wait_pos"] if waiting else entry["pos"]
        floor = entry["floor"] if waiting else entry["to"]
        rows.append([i, round(x, 2), round(y, 2), indices[floor], 2 if waiting else 3])
    rows.sort(key=lambda r: r[0])
    return rows


def _t_share(exit_times: list[float], n_agents: int, share: float):
    if n_agents == 0:
        return None
    need = max(1, math.ceil(share * n_agents - 1e-9))
    return exit_times[need - 1] if len(exit_times) >= need else None


def profile_metrics(agents, events):
    """Summarize outcomes by profile and assistance waits from event durations."""
    by_idx = {a["idx"]: a["profile"] for a in agents}
    counts = Counter(by_idx.values())
    exits = {profile: [] for profile in counts}
    trapped = Counter()
    waits = []
    for event in events:
        kind = event["type"]
        if kind == "exit":
            exits[by_idx[event["idx"]]].append(event["t"])
        elif kind == "trapped":
            trapped[by_idx[event["idx"]]] += 1
        elif kind == "wait":
            waits.append(event["until"] - event["t"])
    profiles = {}
    for profile, count in counts.items():
        times = sorted(exits[profile])
        profiles[profile] = {
            "agents": count, "evacuated": len(times), "trapped": trapped[profile],
            "t50": _t_share(times, count, 0.5),
            "t90": _t_share(times, count, 0.9),
            "t100": _t_share(times, count, 1.0),
        }
    person_seconds = sum(waits)
    assist = {"waiting": len(waits),
              "meanWait": person_seconds / len(waits) if waits else None,
              "maxWait": max(waits) if waits else None,
              "personSeconds": person_seconds}
    return profiles, assist


def smoke_speed(v0, S):
    return min(v0, max(MIN_SMOKE_SPEED, v0 - 0.34 * (3.0 - S)))


def run(building: dict, scenario: dict, fire=None) -> dict:
    """building/v0 + scenario/v0 (+ fire model) -> run/v0."""
    if fire is None:
        try:
            from fire.model import FireModel
        except ImportError:
            FireModel = NoFire
        fire = (FireModel if scenario.get("fire") else NoFire)(building, scenario)
    assist_delay = float(scenario.get("assistDelay", 180))
    if not math.isfinite(assist_delay) or assist_delay < 0:
        raise ValueError("assistDelay must be finite and nonnegative")
    seed = int(scenario.get("seed", 0))
    rng = np.random.default_rng(seed)
    frame_every = _interval_steps(scenario, "frameInterval", FRAME_INTERVAL)
    smoke_every = _interval_steps(scenario, "smokeInterval", SMOKE_INTERVAL)
    frame_interval, smoke_interval = frame_every * DT, smoke_every * DT
    watch = StuckWatch()
    brain = RuleBrain(seed)
    distances = {}
    print(f"routing: {ROUTING_MODE}")
    blocked = {key for key, state in scenario.get("doors", {}).items() if state == "blocked"}
    walkable = {f["id"]: floor_walkable(f, blocked) for f in building["floors"]}
    radius = float(scenario.get("fireKeepout", FIRE_KEEPOUT_M))
    if not math.isfinite(radius) or radius < 0:
        raise ValueError("fireKeepout must be finite and nonnegative")
    ignition = scenario.get("fire") or {}
    if radius and ignition and fire.hrr(float(scenario.get("maxTime", 600))) > 0:
        for floor in building["floors"]:
            if floor["id"] == ignition.get("floor"):
                walkable[floor["id"]] = fire_keepout(
                    walkable[floor["id"]], floor, ignition.get("room"),
                    ignition["x"], ignition["y"], radius)
    net = StairNet(building, walkable=walkable, blocked=blocked)
    agents = place_occupants(building, scenario, rng, walkable)
    cue_rng = np.random.default_rng([seed, 3])
    for a in agents:
        a["cueDelay"] = float(cue_rng.uniform(*CUE_DELAY))
    cues = {}
    net.check({a["floor"] for a in agents})
    n = len(agents)
    mode = scenario.get("brain", "rules")
    if mode not in {"rules", "mixed", "llm"}:
        raise ValueError("brain must be rules, mixed or llm")
    flagged = set()
    if mode == "mixed":
        count = min(n, max(10, min(20, round(0.08 * n))))
        flagged = set(np.random.default_rng([seed, 2]).choice(n, count, replace=False).tolist())
    elif mode == "llm":
        if n > 150:
            raise ValueError("all-LLM showcase supports at most 150 agents")
        flagged = set(range(n))
    llm = (LLMBrain(brain, decide_batch=load_llm_batch_decider()) if mode == "llm"
           else LLMBrain(brain, load_llm_decider()) if flagged else None)
    pending_llm = {}
    last_llm = {}
    seen_smoke = set()

    floors = building["floors"]
    sims = [_FloorSim(f, i, net, blocked, walkable[f["id"]]) for i, f in enumerate(floors)]
    by_id = {fs.id: fs for fs in sims}

    status = [0] * n
    target: list[dict | None] = [None] * n
    where: list[tuple | None] = [None] * n
    for a in agents:
        fs = by_id[a["floor"]]
        if not fs.stages:
            raise ValueError(f"floor {fs.id} has occupants but no exits or stairs to go to")
        jid = fs.sim.add_agent(jps.CollisionFreeSpeedModelAgentParameters(
            position=(a["x"], a["y"]), desired_speed=STOPPED, radius=a["radius"],
            journey_id=fs.park_journey, stage_id=fs.park_stage))
        fs.sim.agent(jid).target = (a["x"], a["y"])
        fs.jid2idx[jid] = a["idx"]
        where[a["idx"]] = (fs, jid)

    alarm = float(scenario.get("alarmTime", 0))
    max_time = float(scenario.get("maxTime", 600))
    start_order = sorted(range(n), key=lambda i: (agents[i]["startDelay"], i))
    next_start = 0

    door_floors = {d["id"]: f["id"] for f in floors for d in f["doors"]}
    events: list[dict] = [{"t": 0.0, "type": "door_blocked", "door": door,
                           "floor": door_floors[door]} for door in sorted(blocked) if door in door_floors]
    frames: list[dict] = []
    smoke: dict[str, dict] = {}
    hrr: list[list] = []
    trapped: set[int] = set()
    transit = {}
    arrivals = {}
    assisted = set()

    def zone_queues(t):
        queues = {}
        for fs in sims:
            positions = np.asarray([ag.position for ag in fs.sim.agents()]).reshape(-1, 2)
            for st in fs.stages:
                count = int(shapely.contains_xy(st["nearby"], positions[:, 0], positions[:, 1]).sum())
                if st["kind"] == "stair":
                    count += net.backlog(fs.id, st["group"], t)
                queues[fs.id, st["id"]] = count
        return queues

    queues = zone_queues(0)

    def blocking_doors(fs, st):
        if st is None:
            return set()
        if st["kind"] == "exit":
            return {st["door"]} & blocked
        closed = set()
        for fid in (fs.id, st["to"]):
            floor = floors[by_id[fid].index]
            stair = next(s for s in floor["stairs"] if s["group"] == st["group"])
            if stair_blocked(floor, stair, blocked):
                closed.update(stair_doors(floor, stair))
        return closed

    def choose(i, t, fs, pos, trigger, speed=None):
        current = None if trigger in ("start", "arrive") else (target[i]["id"] if target[i] else None)
        stages = [st for st in fs.stages if not blocking_doors(fs, st)]
        profile = PROFILES.get(agents[i]["profile"], PROFILES["typical"])
        stages = mobility_options(stages, profile["stairs"])
        if not stages:
            return None
        if trigger == "stuck":
            stages = [st for st in stages if st["id"] != current] or stages
        options = []
        for st in stages:
            key = (fs.id, st["id"], round(pos[0] * 2), round(pos[1] * 2))
            if key not in distances:
                goal = st["poly"].intersection(fs.walk).representative_point()
                distances[key] = route_length(fs.walk, pos, (goal.x, goal.y))
            options.append({"id": st["id"], "kind": st["kind"], "name": st["name"],
                            "dist": distances[key], "queue": queues.get((fs.id, st["id"]), 0),
                            "flow": (1.3 if st["kind"] == "exit" else 1.1) * st["width"],
                            "tail": st["tail"], **({"assist": True} if st.get("assist") else {})})
        obs = {"idx": i, "t": t, "floor": fs.id, "x": pos[0], "y": pos[1],
               "profile": agents[i]["profile"], "visibility": fire.visibility(fs.id, *pos),
               "speed": agents[i]["v0"] if speed is None else speed,
               "current": current, "trigger": trigger, "options": options}
        if mode == "llm" and target[i] is None and trigger == "tick":
            trigger = obs["trigger"] = "start"
            current = obs["current"] = None
        llm_trigger = trigger if trigger in {"start", "arrive", "blocked"} else None
        if i in flagged and trigger == "tick":
            if obs["visibility"] < 5 and i not in seen_smoke:
                llm_trigger = "smoke"
            elif any(o["id"] == current and o["queue"] / o["flow"] > 30 for o in options):
                llm_trigger = "queue"
        if mode == "llm":
            if llm_trigger is None and t - last_llm.get(i, -math.inf) >= 15:
                llm_trigger = trigger
            if llm_trigger and t - last_llm.get(i, -math.inf) >= 10:
                obs["trigger"] = llm_trigger
                pending_llm[i] = (obs, fs)
            return target[i] if current is not None else None
        if i in flagged and llm_trigger and t - last_llm.get(i, -math.inf) >= 10:
            obs["trigger"] = llm_trigger
            last_llm[i] = t
            if obs["visibility"] < 5:
                seen_smoke.add(i)
            decision = llm.decide(obs)
            events.append({"t": t, "type": "llm", "idx": i, "floor": fs.id, **decision})
            # Keep rule hysteresis aware of accepted model changes.
            if not decision.get("fallback") and decision["action"] != "wait":
                brain.last_choice[i] = t
                if current is not None and current != decision["target"]:
                    brain.left[i, fs.id, current] = t
                    brain.switches[i] = brain.switches.get(i, 0) + 1
        else:
            decision = brain.decide(obs)
        return apply_choice(i, t, fs, current, trigger, decision)

    def apply_choice(i, t, fs, current, trigger, decision):
        if decision is None or decision["action"] == "wait":
            return target[i] if current is not None else None
        st = next(st for st in fs.stages if st["id"] == decision["target"])
        if current is not None and st["id"] != current:
            reason = decision["reason"]
            if trigger == "blocked":
                reason = "door " + ", ".join(sorted(blocking_doors(fs, target[i]))) + " blocked"
            events.append({"t": t, "type": "reroute", "idx": i, "floor": fs.id,
                           "from": current, "to": st["id"], "reason": reason})
        return st

    def start_agent(i, t):
        if status[i] == 0 and i not in trapped:
            fs, jid = where[i]
            target[i] = choose(i, t, fs, fs.sim.agent(jid).position, "start")
            if target[i] is not None:
                fs.sim.switch_agent_journey(jid, target[i]["journey"], target[i]["stage"])
                fs.sim.agent(jid).model.desired_speed = smoke_speed(
                    agents[i]["v0"], fire.visibility(fs.id, *fs.sim.agent(jid).position))
            status[i] = 1

    def enter_stair(i, t, fs, st):
        profile = PROFILES.get(agents[i]["profile"], PROFILES["typical"])
        until = None
        if not profile["stairs"] and i not in assisted:
            until = t + assist_delay
            assisted.add(i)
        entry = net.enter(i, t, fs.id, st["group"], rng,
                          speed=profile["stairSpeed"], hold_until=until)
        if until is not None:
            events.append({"t": t, "type": "wait", "idx": i, "floor": fs.id,
                           "x": entry["wait_pos"][0], "y": entry["wait_pos"][1], "until": until})
        link = next(link for link in net.links(fs.id) if link["group"] == st["group"])
        entry["arrival"] = link["arrival"]
        entry["group"] = st["group"]
        transit[i] = entry
        heappush(arrivals.setdefault((entry["to"], st["group"]), []), (entry["arrive"], i))
        watch.anchors.pop(i, None)
        status[i] = 2 if until is not None and t < until else 3
        where[i] = None
        events.append({"t": t, "type": "stair", "idx": i, "floor": fs.id,
                       "group": st["group"], **{key: entry[key] for key in ("to", "enter", "arrive")}})

    active = n  # agents not yet exited or trapped, including stair transit
    k, t = 0, 0.0
    while True:
        t = round(k * DT, 2)
        if k % FIRE_EVERY == 0:
            fire.step(t)
            new_blocks = set(fire.blocked_doors()) - blocked
            for door in sorted(new_blocks):
                if door in door_floors:
                    events.append({"t": t, "type": "door_blocked", "door": door,
                                   "floor": door_floors[door]})
            blocked.update(new_blocks)
            queues = zone_queues(t)
        while next_start < n and alarm + agents[start_order[next_start]]["startDelay"] <= t + 1e-9:
            i = start_order[next_start]
            next_start += 1
            start_agent(i, t)

        for i, entry in transit.items():
            if status[i] == 2 and t >= entry["hold_until"] - 1e-9:
                status[i] = 3

        # One queue per destination stair; a blocked head holds all later arrivals.
        for (fid, group), queue in list(arrivals.items()):
            fs = by_id[fid]
            while queue:
                _, i = queue[0]
                entry = transit[i]
                if entry["arrive"] > t + 1e-9:
                    break
                if entry.get("target") is None or blocking_doors(fs, entry["target"]):
                    center = entry["arrival"].centroid
                    entry["target"] = choose(i, t, fs, (center.x, center.y), "arrive")
                st = entry["target"]
                if st is None:
                    break
                if st["kind"] == "stair" and st["group"] == group:
                    heappop(queue)
                    enter_stair(i, t, fs, st)
                    continue
                region = entry["arrival"].buffer(-0.3)
                if region.is_empty:
                    region = entry["arrival"].buffer(-0.1)
                positions = [ag.position for ag in fs.sim.agents()]
                gap = max(MIN_SPACING, agents[i]["radius"] +
                          max((agents[fs.jid2idx[ag.id]]["radius"] for ag in fs.sim.agents()
                               if ag.id in fs.jid2idx), default=0.2) + 0.01)
                pos = find_spot(region, positions, rng, gap=gap)
                if pos is None:
                    break
                jid = fs.sim.add_agent(jps.CollisionFreeSpeedModelAgentParameters(
                    position=pos, desired_speed=agents[i]["v0"], radius=agents[i]["radius"],
                    journey_id=st["journey"], stage_id=st["stage"]))
                fs.jid2idx[jid] = i
                where[i], target[i], status[i] = (fs, jid), st, 1
                heappop(queue)
                del transit[i]

        if k % FIRE_EVERY == 0:
            moving = [(fs, ag) for fs in sims for ag in fs.sim.agents()
                      if ag.id in fs.jid2idx]
            for fs, ag in sorted(moving, key=lambda item: item[0].jid2idx[item[1].id]):
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
                elif status[i] == 0:
                    if i not in cues:
                        if (fire.hrr(t) > 0 and fs.id == ignition.get("floor")
                                and agents[i]["room"] == ignition.get("room")):
                            cues[i] = (t, "fire")
                        elif fire.visibility(fs.id, x, y) < CUE_VIS_M:
                            cues[i] = (t, "smoke")
                    if i in cues and t >= cues[i][0] + agents[i]["cueDelay"]:
                        start_agent(i, t)
                        events.append({"t": t, "type": "start", "idx": i,
                                       "floor": fs.id, "cue": cues[i][1]})
                elif status[i] == 1:
                    stuck = watch.update(i, t, x, y)
                    if stuck:
                        events.append({"t": t, "type": "stuck", "idx": i, "floor": fs.id,
                                       "x": round(x, 2), "y": round(y, 2)})
                    v0 = agents[i]["v0"]
                    vis = fire.visibility(fs.id, x, y)
                    ag.model.desired_speed = smoke_speed(v0, vis)
                    trigger = "blocked" if blocking_doors(fs, target[i]) else ("stuck" if stuck else "tick")
                    st = choose(i, t, fs, (x, y), trigger, ag.model.desired_speed)
                    if st is None:
                        fs.sim.switch_agent_journey(ag.id, fs.park_journey, fs.park_stage)
                        ag.target = (x, y)
                        ag.model.desired_speed = STOPPED
                    elif st is not target[i] or ag.stage_id == fs.park_stage:
                        fs.sim.switch_agent_journey(ag.id, st["journey"], st["stage"])
                        target[i] = st

        if mode == "llm" and k % FIRE_EVERY == 0 and pending_llm:
            batch = [(i, obs, fs) for i, (obs, fs) in sorted(pending_llm.items())
                     if i not in trapped and (where[i] is not None or i in transit)]
            pending_llm.clear()
            for _, obs, _ in batch:
                obs["t"] = t
            decisions = llm.decide_batch([obs for _, obs, _ in batch])
            for (i, obs, fs), decision in zip(batch, decisions):
                last_llm[i] = t
                if obs["visibility"] < 5:
                    seen_smoke.add(i)
                events.append({"t": t, "type": "llm", "idx": i, "floor": fs.id, **decision})
                current = obs["current"]
                if not decision.get("fallback") and decision["action"] != "wait":
                    brain.last_choice[i] = t
                    if current is not None and current != decision["target"]:
                        brain.left[i, fs.id, current] = t
                        brain.switches[i] = brain.switches.get(i, 0) + 1
                st = apply_choice(i, t, fs, current, obs["trigger"], decision)
                if i in transit:
                    transit[i]["target"] = st
                else:
                    target[i] = st
                    _, jid = where[i]
                    ag = fs.sim.agent(jid)
                    if st is not None:
                        fs.sim.switch_agent_journey(jid, st["journey"], st["stage"])
                        ag.model.desired_speed = smoke_speed(agents[i]["v0"],
                                                            fire.visibility(fs.id, *ag.position))
                    else:
                        fs.sim.switch_agent_journey(jid, fs.park_journey, fs.park_stage)
                        ag.target = ag.position
                        ag.model.desired_speed = STOPPED

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

    metrics["profiles"], metrics["assist"] = profile_metrics(agents, events)

    fire_cfg = scenario.get("fire") or {}
    return {
        "version": "run/v0",
        "id": f"{scenario.get('id', 'scenario')}-s{seed}",
        "buildingId": building.get("id"),
        "scenarioId": scenario.get("id"),
        "seed": seed,
        "frameInterval": frame_interval,
        "floors": [f["id"] for f in floors],
        "agents": [{**{key: a[key] for key in ("idx", "profile", "floor", "room", "v0", "startDelay")},
                    **({"llm": True} if a["idx"] in flagged else {})} for a in agents],
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
