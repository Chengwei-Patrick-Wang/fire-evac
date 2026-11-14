# Workstream C — Crowd Simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sim.run.run(building, scenario, fire)` returns a run/v0 in which agents on several floors queue at doors and stairs, choose and change exits, slow down in smoke, wait for help and, as a showcase, can ask an LLM.

**Architecture:** The scaffold's v0 steps one JuPedSim `Simulation` per floor with stairs as sinks. C replaces the sinks with a FIFO stair transfer (`sim/floors.py`), puts exit choice behind a `decide(obs)` brain (`sim/brain.py`), then couples the fire model, adds mobility profiles and an optional LLM brain. run/v0 only gains optional fields.

**Tech Stack:** Python 3.12, jupedsim 1.4.2 (`CollisionFreeSpeedModel`), shapely 2, numpy 2.

**Spec:** docs/superpowers/specs/2026-11-13-fire-evac-sim-design.md

## Start here

- **Owner:** C (Python + algorithms teammate). **Branch:** `ws-c`. **Folder:** `sim/` only; shared files change through small PRs that A merges.
- **Setup:** `git clone https://github.com/Chengwei-Patrick-Wang/fire-evac`, `cd fire-evac`, `git switch -c ws-c`; `python -m venv .venv` (Python 3.12) and activate it (`source .venv/bin/activate`, Windows `.venv\Scripts\activate`); `pip install -r requirements.txt` (JuPedSim pulls in PySide6 and VTK, so start this first).
- **Before the scaffold lands on main (~12:45 AM Sat):** read `docs/context/05-agent-design.md`, `docs/context/07-benchmarks-jupedsim.md` and spec §7.2; write no code. When it lands: `git merge origin/main`, run `python -m sim.smoke_test` (expect `OK`), read `sim/run.py`, `sim/profiles.py`, `sim/smoke_test.py`. Tasks use their names as of Fri 11:30 PM (`_FloorSim`, `place_occupants`, `_frame`, `run`); if the scaffold renamed one, use the real name. Never redo scaffold work.
- **Claude Code on Pro:** Sonnet, medium effort, `acceptEdits`; prompt `Use superpowers:executing-plans on docs/superpowers/plans/2026-11-13-ws-c-crowd-sim.md, Task C1 only`; after its commit and push, `/clear` and start the next task. **Codex:** it reads `AGENTS.md` itself; work this checklist in order and tick the boxes.
- **Dependencies and sync:** until D's `fire/model.py` and B's real building (`data/buildings/<id>.json`) land, use `fire.stub.NoFire`, `tools/toy_fire.py` `ToyFire` and `contracts/building.example.json`. Merge `main` into `ws-c` at each sync (Sat 2 AM, 10 AM, 4 PM, 10 PM); push at least hourly; open a PR at least every 2 h.

## Global Constraints

- **Contracts (spec §6) are frozen:** run/v0 is `{version, id, buildingId, scenarioId, seed, frameInterval: 0.5, floors, agents[], frames[], smoke[], fire, events[], metrics}`. C adds only optional things (event types `stair` and `stuck`, extra event fields, `agents[].llm`, scenario `assistDelay`, `frameInterval`, `smokeInterval`) and tells A in chat.
- **Frames:** every 0.5 s, `[idx, x, y, floorIdx, status]`, meters rounded to 0.01, floor-local; status 0 not moving yet, 1 moving, 2 waiting for help, 3 in a stairwell (drawn at the stair); an agent disappears after its `exit` event. Smoke snapshots every 2 s.
- **Engine:** JuPedSim 1.4.2 `CollisionFreeSpeedModel`, one `Simulation` per floor, stepped together at 0.01 s; check `removed_agents()` after every `iterate()`; exits are zones beyond real door openings, never against a wall.
- **Determinism:** all randomness derives from `scenario.seed` (`numpy.random.default_rng(seed)`, or `default_rng([seed, k])` for a separate stream); key everything by our `idx`, never by JuPedSim ids.
- **Stairs:** 0.55 m/s going down; stair length = 2 × floor height; FIFO per stair; throughput 1.1 persons/s per meter of stair door width. Door flow is 1.3 persons/(m·s).
- **Brain:** re-plans every 1 s and on events; cost `C = d/v + q/F`; seeded softmax over `−C/τ`; switch only if `C_new < 0.8 × C_current`; interface `decide(obs) -> {target, action, reason} | None`, and `None` falls back to rules.
- **Fire coupling** every 1 s: `desired_speed = min(v0, max(0.2, v0 − 0.34·(3 − S)))` with `S = fire.visibility`; `fire.untenable` marks the agent trapped; `fire.blocked_doors()` triggers re-planning. Door states open, closed and propped are passable; `blocked` is not and is removed from the geometry. Use `fire.model.FireModel` when importable, else `fire.stub.NoFire` (same API).
- **Start delay and profiles:** an agent stays put (status 0) until `alarmTime` plus its profile delay. P0 profiles: typical, older, visitor. P1 adds cane, walker, wheelchair.
- **LLM agents (P2) are showcase-only:** never in batch runs or what-if comparisons (`scenario.brain` defaults to `rules`); every decision is logged as an `llm` event with `reason`; a timeout or `None` falls back to rules.
- **Ethics (§12):** no panic mode; long waits are framed as building gaps (a scenario `assistDelay`, not a trait of the person); runs of the traced UMass building stay in `data/private/` or gitignored `data/runs/`, never committed.
- **Hackathon mode:** no TDD; one `sim/smoke_test.py` (`python -m sim.smoke_test`), run before every push and kept under ~4 min (variants use the 160-agent example); stay in `sim/`; Windows and macOS (`pathlib`, no shell-specific code); never read a run JSON whole (`head -c 2000`, `jq`); commit messages never mention AI tools.

## Review Focus

1. Agents re-added on top of each other at a stair: `find_spot` keeps ≥ 0.5 m from everyone and returns None rather than overlapping (Task C1: packed-region check; C2: no two agents < 0.3 m apart in any frame).
2. Gridlock at a stair door: arrivals are strict FIFO per stair with a retry, and the stairwell must keep draining (C2: status-3 time ≤ planned + 5 s per agent; C3: the same with 300 agents, `inStairs == 0`, no `stuck` events).
3. Oscillating exit switching: 20% hysteresis, 15 s dwell, 30 s tabu, 3-switch cap (C4: ≤ 3 `reroute` events per agent and none back to a target left < 30 s ago).
4. An exit blocked mid-run: agents re-plan away at the next tick (C5: `BlockE1` from t = 60 gives a `door_blocked` event, no E1 exits after t = 70, everyone still gets out).
5. Upper-floor agents with no stair route: fail loudly before the run (C1: `check` raises for a building whose F2 stair groups match nothing below; C2: `run` raises `ValueError` naming F2; C3 drops stages and links the walkable area cannot reach, so `check` sees real routes only).

---

### Task C1: Stair network library (P0, target Sat 10 AM)

**Files:** Create `sim/floors.py`. Modify `sim/smoke_test.py` (a new `check_floors()` called first in `main`).

**Interfaces:**
- Consumes: building/v0 `floors[].{id, level, height, stairs[{id, group, room, polygon}], doors[{id, width, connects}], exits[]}`.
- Produces in `sim/floors.py`: `STAIR_SPEED = 0.55`, `STAIR_FLOW = 1.1`, `WALK_SPEED = 1.2`; `class StairNet(building)` with `links(floor_id) -> list[{stair, group, to, width, length, tail, polygon, arrival}]`, `enter(idx, t, floor_id, group, rng, speed=STAIR_SPEED) -> {enter, arrive, to, pos}`, `backlog(floor_id, group, t) -> int` (agents admitted whose `enter` is still after `t`), `check(occupied: set[str]) -> None`; `find_spot(region, others, rng, gap=0.5, tries=64) -> tuple[float, float] | None`.

- [x] `links`: a link exists only if the floor with the next lower `level` has a stair of the same `group` (`arrival` = that polygon, `to` = that floor id); `length = 2 × height` of the floor being left; `width` = sum of that stair room's door widths whose `connects` lacks `"outside"`, else 1.0; `tail` = `length/STAIR_SPEED` + (distance from `arrival` to the nearest exit below ÷ `WALK_SPEED`, or, if that floor has no exit, the smallest walk + `tail` over its own links).
- [x] `enter`: FIFO per `(floor_id, group)`: `enter = max(t, last_enter + 1/(STAIR_FLOW × width))`, `arrive = enter + length/speed`, `pos` = a random point in `arrival` from `rng`. `check` raises `ValueError` naming the floor if an occupied floor has no exit and no link, followed recursively, to a floor with an exit.
- [x] `find_spot`: draw `tries` uniform points in `region.bounds` from `rng`, round to 0.01, return the first inside `region` and ≥ `gap` from every row of `others` (an (m, 2) array of one floor's agent positions); otherwise None.
- [x] `check_floors()` on the example building: F2 has links SA2 and SB2 to F1 with width 1.0, length 7.0 and `tail > 12.7`, F1 has none; five `enter` calls at t = 0 for `("F2", "SA")` give `enter` gaps ≥ 0.909 s, `arrive − enter` = 12.73 ± 0.01 and `backlog("F2", "SA", 0.0) == 4`; a copy whose F2 stair groups are renamed `ZZ` makes `check({"F2"})` raise `ValueError` mentioning F2 while `check({"F1"})` passes; **no stacking:** `find_spot` on a 3 × 3 m region with `others` on a 0.45 m grid returns None, and on a half-empty region returns a point ≥ 0.5 m from every other.
- [x] Verify: `python -m sim.smoke_test` prints `floors OK` and still ends with `OK` (v0 assertions untouched).
- [x] Commit locally: `git add sim docs/superpowers/plans/2026-11-13-ws-c-crowd-sim.md && git commit -m "feat(sim): stair network library"`. Push is delegated to the overnight runner per the session instructions.

### Task C2: Stair transfer in the run loop (P0, target Sat 10 AM)

**Files:** Modify `sim/run.py`, `sim/smoke_test.py`.

**Interfaces:**
- Consumes: C1's `StairNet` and `find_spot`; v0 `sim/run.py` (`_FloorSim`: `fs.sim`, `fs.stages` of `{kind, id, group, poly, stage, journey}`, `fs.jid2idx`; `run()`: `status`, `target`, `where`, `events`, `active`; `_frame`); JuPedSim as in v0: `add_exit_stage(poly)`, `add_journey(jps.JourneyDescription([stage]))`, `add_agent(jps.CollisionFreeSpeedModelAgentParameters(position=, desired_speed=, radius=, journey_id=, stage_id=))`, `agents()`, `removed_agents()`.
- Produces: `pick_target(fs, pt, exclude=())` in `sim/run.py` (nearest exit by straight line; the nearest stair if the floor has no exit); event `{t, type: "stair", idx, floor, group, to, enter, arrive}` (`t` = removal on the upper floor, or arrival at a pass-through floor); frame rows `[idx, x, y, lowerFloorIdx, 3]` at `pos` while in transit; `metrics.inStairs` = agents in transit at the end; `evacuated` counts `exit` events only.

- [x] `_FloorSim`: build stair stages from `net.links(floor)` for any floor that has a link (stage dicts gain `to`, `width`), replacing the v0 sinks on "every floor above the lowest". `run()`: build `net = StairNet(building)` first, call `net.check` after placing occupants, and take initial targets from `pick_target` instead of the v0 nearest-stage line.
- [x] On a stair removal: `net.enter(...)`, emit the event, `status[i] = 3`. `active` now counts agents not yet exited or trapped, `remaining` excludes agents in transit; the loop ends when `active == 0` or at `maxTime`.
- [x] Each step, release due arrivals per `(floor, group)` in FIFO order: `pick_target` from the arrival polygon's centroid; if it is a stair of the same group, chain (emit `stair` for that floor, `enter` again, no add); otherwise `find_spot(arrival.buffer(-0.3), positions, rng)` (`.buffer(-0.1)` if empty): None means retry next step and hold later arrivals of that key; else `add_agent(..., desired_speed=v0, journey_id, stage_id)` and update `fs.jid2idx`, `where`, `target`, `status[i] = 1`. Add the in-transit rows to every frame.
- [x] Update `sim/smoke_test.py` (drop the v0 sink assertions; run the example scenario with `maxTime` 900 for these checks): every agent exits and every F2 agent has a `stair` event before its exit; `inStairs == 0`; `evacuated + trapped + inStairs + remaining == agents`; **no stacking:** no two status-0/1 agents on one floor are < 0.3 m apart in any frame; **no gridlock:** per agent, 0.5 s × frames at status 3 ≤ last `arrive` − first stair `t` + 5; **no route:** the `ZZ` building from C1 makes `run` raise `ValueError` mentioning `F2`; same seed twice gives identical events.
- [x] Verify: `python -m sim.smoke_test` prints the transfer count, the longest re-add delay and `OK`; then `python -m sim.run contracts/building.example.json contracts/scenario.example.json data/runs/out.json` and `python tools/plot_building.py contracts/building.example.json --run data/runs/out.json --t 100` show F1 agents coming out of the stair rooms.
- [x] Commit locally: `git add sim docs/superpowers/plans/2026-11-13-ws-c-crowd-sim.md && git commit -m "feat(sim): FIFO stair transfer between floors"`. No push or sync per overnight session instructions; the runner handles those.

**Verification:** all 160 agents exited; 78 transfers; longest observed re-add delay ≤ 0.49 s (0.5 s frame resolution); t90 126.51 s, t100 165.79 s. Smoke checks include collision spacing, no gridlock, repeat-seed events, disconnected F2 rejection, a cutoff with agents in transit, and a three-floor same-group chain. CLI output: 0.67 MB, 333 frames; t=100 previews generated.

**Handoff for A/E:** stair events now carry `{t, type: "stair", idx, floor, group, to, enter, arrive}`. Transit rows use the destination floor index and status 3, then return to status 1 after safe re-entry. `metrics.inStairs` counts current transit, not cumulative transfers; `remaining` excludes transit. Exited agents disappear from frames. A: regenerate `contracts/run.example.json` with `python tools/build_examples.py` after integration (shared contracts left to A).

### Task C3: Real-building run, stuck watchdog, performance (P0, target Sat 10 AM)

**Files:** Modify `sim/run.py`, `sim/floors.py`, `sim/smoke_test.py`.

**Interfaces:**
- Consumes: B's building/v0 in `data/buildings/<id>.json` (the example building if none has landed), `StairNet`, `pick_target`.
- Produces: `StairNet(building, walkable=None)` (`walkable`: floor id → shapely polygon from `floor_walkable`); `class StuckWatch(window=60.0, min_move=0.5)` in `sim/run.py` with `update(idx, t, x, y) -> bool` (the first call anchors; moving ≥ `min_move` from the anchor re-anchors and returns False; `t − anchor_t ≥ window` re-anchors and returns True); event `{t, type: "stuck", idx, floor, x, y}`; CLI `python -m sim.run BUILDING SCENARIO OUT [--agents N]` (`--agents` sets `occupants.total` and drops `perRoom`) printing agents, seconds, MB and event counts; optional scenario `frameInterval` (default 0.5) and `smokeInterval` (default 2) that set `FRAME_EVERY`, `SMOKE_EVERY`, the run's `frameInterval` and `smoke[].interval`.

- [x] Every 1 s tick, `StuckWatch.update` for each status-1 agent; on True log `stuck`, then `pick_target(fs, pos, exclude={current stage id})` (keep the stage if it is the only one) and `switch_agent_journey`.
- [x] Geometry guards (fix in `sim/`; tell B in chat if `buildings/` is at fault): `floor_walkable` applies `buffer(0)` to an invalid polygon; drop with a warning any exit or stair stage whose polygon lies farther than 0.1 m from its floor's walkable area, and (via `StairNet(walkable=...)`) any stair link whose polygon fails that test at either end; print the dropped-area share when a floor has several pieces.
- [x] Real run: copy `contracts/scenario.example.json` to `data/runs/real-scenario.json`, set `buildingId` and a `fire.floor/room/x/y` that exist in B's building, then `python -m sim.run data/buildings/<id>.json data/runs/real-scenario.json data/runs/real.json --agents 300`. Budget ≤ 60 s and ≤ 8 MB; if either is exceeded, set `frameInterval` 1.0 and `smokeInterval` 5 in that scenario (spec §13 fallback), tell A and E, and post the numbers in chat.
- [x] Smoke test: a 300-agent run on the example building (`occupants.total` 300, `maxTime` 900, NoFire): all agents exit, `inStairs == 0`, `remaining == 0`, the C2 re-add rule holds, zero `stuck` events, runtime < 120 s, `len(json.dumps(run)) < 8e6`; a `StuckWatch` fed one motionless agent once per second for t = 0..100 returns True exactly once, at t = 60, and for an agent that moves 0.6 m at t = 30 first returns True at t = 90. Print runtime and MB.
- [x] Verify: `python -m sim.smoke_test` ends with `OK`; the real-building run prints its metrics line and `wrote ... MB ... in ... s`.
- [x] Commit locally: `git add sim docs/superpowers/plans/2026-11-13-ws-c-crowd-sim.md && git commit -m "feat(sim): stuck watchdog and geometry guards"`. No push or sync per overnight session instructions; the runner handles those.

**Verification:** `python -m sim.smoke_test` passed, including the 300-agent NoFire run: all 300 exited, 150 stair transfers, zero stuck events, no stacking or re-add gridlock; 5.65 s and 1.79 MB with default JSON serialization. Watchdog anchors fire at t=60 and t=90 as specified; detached arrival/exit guards, invalid polygon repair, dropped-area reporting and 1 s/5 s recording intervals passed.

**Benchmark fallback / handoff for A/E:** no B building exists in `data/buildings/` yet, so used `contracts/building.example.json` as explicitly allowed. CLI `--agents 300` with `data/runs/real-scenario.json` wrote `data/runs/real.json`: 5.9 s, 1.45 MB compact JSON, 361 frames, t90 155.16 s, t100 179.84 s, 300 evacuated, zero trapped/remaining/inStairs. No reduced recording rate needed. Optional scenario `frameInterval` and `smokeInterval` now control recording (positive multiples of 0.01 s, defaults unchanged); `stuck` events carry `{t, type, idx, floor, x, y}`. Generated benchmark files remain ignored and uncommitted. No normalizer fault found in the example geometry.

### Task C4: Brain, queue-aware exit choice and re-planning (P0, target Sat 4 PM)

**Files:** Create `sim/brain.py`. Modify `sim/run.py`, `sim/smoke_test.py`.

**Interfaces:**
- Consumes: `fs.stages` (`kind, id, poly, to, width`), `StairNet.links(...)[i]["tail"]`, exit door widths (`exits[].door` into `floors[].doors[].width`), `fire.visibility`, `jps.RoutingEngine` if present (else straight line), `switch_agent_journey(jid, journey, stage)`, the 1 s tick (`FIRE_EVERY`).
- Produces in `sim/brain.py`: `obs = {idx, t, floor, x, y, profile, visibility, speed, current, trigger, options}` (keys as in A's plan A10 plus `speed` (v0 at start), `current` (stage id or None), `trigger` (`start`, `arrive`, `tick`, `blocked`, `stuck`) and `options: [{id, kind: "exit" | "stair", name, dist, queue, flow, tail}]`: `dist` m, `queue` persons within 3 m of the zone plus the stair FIFO backlog, `flow` persons/s = 1.3 × door width for exits, 1.1 × width for stairs); `class RuleBrain(seed)` with `decide(obs) -> {"target": option id, "action": "go" | "reroute", "reason": str} | None` (None keeps the current target); `should_switch(c_current, c_new) -> bool`; `route_length(...)`. Event `{t, type: "reroute", idx, floor, from, to, reason}`.

- [x] Run `python -c "import jupedsim as j; print(hasattr(j, 'RoutingEngine'), hasattr(getattr(j, 'RoutingEngine', object), 'compute_waypoints'))"` once. `route_length(floor_poly, p, q)` = sum of segment lengths of `jps.RoutingEngine(floor_poly).compute_waypoints(p, q)` if both are True (print "routing: RoutingEngine"), else `math.dist` (print "routing: straight line"), and straight line on any exception; memoize on `(floor, zone id, round(x*2), round(y*2))`.
- [x] `RuleBrain.decide`: `C = dist/max(speed, 0.2) + queue/flow + tail`; `P ∝ exp(−C/TAU)`, `TAU = 5.0`, drawn from `default_rng([seed, 1])`. No `current`, or `current` missing from `options` (blocked): fresh draw (`"go"`, or `"reroute"` if it had a target). Otherwise draw a candidate and switch only if `should_switch(C_current, C_new)` (`C_new < 0.8 × C_current`), ≥ `MIN_DWELL = 15` s since the agent's last choice, the current option's `dist > COMMIT_DIST = 3.0`, the candidate not left < `TABU = 30` s ago, and ≤ `MAX_SWITCHES = 3` per agent; otherwise None.
- [x] `run()`: choose targets at start (status 0 → 1) and at stair arrival (`obs` position = the arrival polygon's centroid), replacing `pick_target`; each 1 s tick compute zone queues once (count `fs.sim.agents()` positions with `shapely.contains_xy` in `zone.buffer(3.0)`), then re-plan every status-1 agent in idx order; apply a switch with `switch_agent_journey`, update `target[i]`, log `reroute` with the reason. The C3 stuck handler now calls `decide` with `trigger "stuck"` and the current stage removed from `options`.
- [x] Smoke test: `should_switch(10, 7.99)` is True and `should_switch(10, 8.0)` False; **no oscillation:** every agent has ≤ 3 `reroute` events and none goes back to a target within 30 s of leaving it; E1 and E2 both used; identical events on a repeat run; print the routing mode, reroute count and t90.
- [x] Verify: `python -m sim.smoke_test` ends with `OK`.
- [x] Commit locally: `git add sim docs/superpowers/plans/2026-11-13-ws-c-crowd-sim.md && git commit -m "feat(sim): queue-aware exit choice brain"`. No push or sync per overnight session instructions; the runner handles those. Example observation and decision for A are below.

**Verification:** `python -m sim.smoke_test` passed using `.venv/bin/python`. Routing capability probe: `True True`; mode `RoutingEngine`, including a path-around-hole check. All 160 agents exited (E1: 93, E2: 67), 5 reroutes, t90 122.89 s, t100 167.63 s; repeated events and metrics identical. All 300 agents exited in 5.39 s, 1.78 MB (default JSON serialization), 15 reroutes, t90 151.7 s, zero stuck. Both runs passed the three-reroute cap, 30 s tabu, spacing and stair re-entry checks; the three-floor chain still passes. Arrival decisions are retained during safe-placement retries, avoiding repeated draws while the FIFO head waits.

**Handoff for A (A10):** `sim.brain.RuleBrain(seed).decide(obs)` returns a decision or None (keep current). Example interface payload (illustrative values):
```json
{"idx":0,"t":30,"floor":"F1","x":5,"y":5,"profile":"typical","visibility":30,"speed":1.2,"current":null,"trigger":"start","options":[{"id":"E1","kind":"exit","name":"Exit 1","dist":12,"queue":2,"flow":1.3,"tail":0}]}
```
Decision: `{"target":"E1","action":"go","reason":"start: estimated travel and queue time 11.5 s"}`. Triggers implemented here: start, arrive, tick, stuck; blocked integration belongs to C5. `reroute` events include floor, from, to and reason. Distance caching is per run/floor/zone/half-meter position cell; choices use a separate seed-derived RNG stream. No contract examples changed.

### Task C5: Fire coupling and blocked doors (P0, target Sat 4 PM)

**Files:** Modify `sim/run.py`, `sim/floors.py`, `sim/smoke_test.py`.

**Interfaces:**
- Consumes: `fire.model.FireModel(building, scenario)` (D; `step(t)` takes sim seconds and applies `scenario.fire.start` itself; `visibility(floor_id, x, y)`, `untenable(...)`, `blocked_doors() -> set[str]`, `snapshot(floor_id)`, `hrr(t)`), `fire.stub.NoFire`, `tools/toy_fire.py` `ToyFire`; scenario `doors{id: state}`, `alarmTime`.
- Produces: `run(building, scenario, fire=None)` where `None` means `FireModel` if `fire.model` imports (`except ImportError`) and the scenario has `fire`, else `NoFire`; `smoke_speed(v0, S) -> float`; `StairNet(building, walkable=None, blocked=frozenset())`; events `{t, type: "door_blocked", door, floor}` (once per door) and `trapped` (v0); `reroute` reasons "door X blocked".

- [x] `smoke_speed(v0, S) = min(v0, max(0.2, v0 − 0.34·(3 − S)))` replaces the inline formula (status-1 agents, every 1 s); `fire.step(t)` and `fire.hrr(t)` keep sim time `t`.
- [x] Scenario `doors[id] == "blocked"`: `_FloorSim` subtracts that door's `rect` from the walkable polygon (keep the largest piece) and skips exit stages whose `door` is blocked; `StairNet(blocked=...)` drops links whose stair room's doors are all blocked and `check` ignores blocked exits; log `door_blocked` at t = 0 for each. `open`, `closed` and `propped` need no code.
- [x] Mid-run: each 1 s tick compare `fire.blocked_doors()` with the doors already logged; for a new one log `door_blocked`; from that tick the option is gone for every aware agent (`t ≥ alarmTime` or `dist(agent, door midpoint) ≤ fire.visibility(floor, x, y)`; every moving agent is post-alarm, so all are aware) and agents targeting it re-plan at once (`trigger "blocked"`, fresh draw, reason "door X blocked"). Only an exit's door, or all of a stair room's doors, changes options. State in the `sim/run.py` docstring that blocked interior doors act only through slowdown and trapping, and agents in a stairwell (status 2 or 3) are not exposed to fire.
- [x] Smoke test: every earlier smoke run now passes `NoFire(building, scenario)` explicitly (so a real `FireModel` cannot change those checks); `smoke_speed(1.2, 30) == 1.2`, `smoke_speed(1.2, 1.0)` ≈ 0.52, `smoke_speed(1.0, 0.0) == 0.2`; scenario `doors {"E1": "blocked"}`: `exitCounts["E1"] == 0` and everyone exits; **mid-run block:** `class BlockE1(NoFire)` returns `{"E1"}` from t ≥ 60: a `door_blocked` event at t = 60, no `exit` at E1 after t = 70, ≥ 1 `reroute` whose reason mentions "blocked", everyone exits; a fake fire with `visibility() = 1.0` gives `t90 ≥ 1.2 ×` the clear-air `t90`; a fake fire with `untenable` true in R101 from t = 40 gives `trapped` events whose agents never appear in later frames and never exit. Variants use `maxTime` 900.
- [x] Verify: `python -m sim.smoke_test` ends with `OK`; with D's model present, run the example scenario plus `"doors": {"DSB2": "propped"}` through `python -m sim.run` (the propped-door what-if) and check it completes and prints `t90` and `trapped`.
- [x] Commit locally: `git add sim docs/superpowers/plans/2026-11-13-ws-c-crowd-sim.md && git commit -m "feat(sim): fire coupling, blocked doors and exits"`. No push or sync per overnight session instructions; the runner handles those. Handoff for A below.

**Verification:** `.venv/bin/python -m sim.smoke_test` passes the earlier deterministic clear-air runs plus initial E1 closure, blocked stair links at either end, all exits blocked reachability rejection, and loss of all options without exiting. Mid-run E1 closure logs once at t=60 and causes 22 immediate blocked reroutes; all 160 evacuate. Constant 1 m visibility raises t90 from 122.89 s to 161.67 s; the R101 trapping check removes 10 agents from all later frames and exits. The 300-agent regression remains below its runtime/size budgets with zero stuck events.

**Handoff for A:** `run(..., fire=None)` now selects D's `FireModel` for scenarios with fire, falling back to `NoFire` only if the import is unavailable or no fire is configured. Please regenerate the shared examples after integration. The CLI propped-door what-if (`DSB2: propped`) completed with 159 evacuated, 1 trapped, t90 123.95 s, no remaining/in-stair agents, 1.24 MB and 2.0 s runtime. Inputs/output were written under `/tmp`, not committed. Mid-run interior blocked doors affect people only through slowdown and trapping; stairwell transit remains unexposed. No contract fields changed.

### Task C6: Mobility profiles and waiting for help (P1, target Sat 10 PM)

**Files:** Modify `sim/profiles.py`, `sim/floors.py`, `sim/brain.py`, `sim/run.py`, `sim/smoke_test.py`.

**Interfaces:**
- Consumes: `PROFILES`, `StairNet.enter`, `RuleBrain` options, scenario `occupants.mix` and optional `assistDelay` (s, default 180).
- Produces: `PROFILES` gains `cane` (v0 0.7–0.95), `walker` (0.6–0.85), `wheelchair` (0.9–1.1) from `docs/context/03` (cane 0.82–0.91, walker 0.69, wheelchair 1.08 m/s; centers 0.8, 0.7, 1.0), all `startDelay` (20, 90); new keys on every profile: `stairs: bool` (False for wheelchair), `stairSpeed` m/s (typical and visitor 0.55, older and cane 0.45, walker 0.4, wheelchair assisted 0.2); `radius` 0.2 (wheelchair 0.3); `StairNet.enter(..., hold_until=None)` (with `hold_until` the agent is drawn at a random point of the stair polygon on the floor it is leaving, `wait_pos`, until then, and `enter ≥ hold_until`); event `{t, type: "wait", idx, floor, x, y, until}`; frame status 2 while waiting.

- [x] Add the profiles and keys; `enter` takes `speed` from the profile's `stairSpeed`.
- [x] Brain: an agent with `stairs` False gets exits only; if its floor has none, stair options are allowed as `assist`. It walks to the stair zone as usual; at the removal it waits in the stairwell: row `[idx, x, y, upperFloorIdx, 2]` at `wait_pos`, `until = t + assistDelay`, one `wait` event (`x, y` = `wait_pos`), then `enter ≥ until` and the flight at 0.2 m/s; on later floors without exits it keeps going down with no second wait.
- [x] Smoke test (160 agents, `mix {"typical": 0.8, "older": 0.05, "cane": 0.03, "walker": 0.02, "wheelchair": 0.1}`, `maxTime` 900, at least one wheelchair agent on each floor): each wheelchair agent on F2 has one `wait` event with `until − t = 180`, status 2 in every frame from `t` to `until`, and a `stair` event with `enter ≥ until` and `arrive − enter` = 35 ± 0.1 s; wheelchair agents on F1 exit with no `wait`; with `assistDelay` 60 every `until − t = 60`; everyone exits; no unknown-profile warning.
- [x] Verify: `python -m sim.smoke_test` ends with `OK`, printing the number of waiters and the longest wait.
- [x] Commit locally: `git add sim docs/superpowers/plans/2026-11-13-ws-c-crowd-sim.md && git commit -m "feat(sim): mobility profiles and waiting for help"`. No push or sync per overnight instructions; the runner handles those. Handoff for A/E below.

**Verification:** `.venv/bin/python -m sim.smoke_test` passed. Both 160-agent mobility variants evacuate everyone, with eight upper-floor wheelchair agents waiting exactly 180 s (default) or 60 s (override), status-2 rows at their recorded source-floor stair positions, and 35 s assisted flights. Ground-floor wheelchair agents exit without waiting; a three-floor wheelchair run waits once, then continues down both flights. No unknown-profile warnings. Existing deterministic, fire-coupling, re-entry and 300-agent checks pass (300 evacuated, zero stuck, approximately 5.4 s and 1.78 MB).

**Handoff for A/E:** optional scenario `assistDelay` is a finite, nonnegative number of seconds, default 180. `wait` events contain `{t, type, idx, floor, x, y, until}`. Status-2 rows remain at that source-floor position for `t <= frame.t < until`; status 3 follows after assistance, then status 1 after re-entry. Waiting agents count in `inStairs` and remain unexposed to fire, as with existing transit. Strict stair FIFO is retained, so an assistance hold also delays later admissions. Profiles now include cane, walker and wheelchair; profile-specific stair speeds apply to older occupants too. No shared contract examples changed.

### Task C7: LLM agents in a mixed crowd (P2, target Sun 2 AM)

**Files:** Modify `sim/brain.py`, `sim/run.py`, `sim/smoke_test.py`.

**Interfaces:**
- Consumes: A's `backend.llm.features.decide(obs) -> {action, target, reason} | None` (import inside `try/except ImportError`; if missing, warn and use rules; `action` go, reroute or wait; `target` one of `options[].id`) and the C4 `obs`.
- Produces: scenario `brain` in `"rules"` (default) | `"mixed"` | `"llm"`; `class LLMBrain(rule: RuleBrain, decide, timeout=4.0)` whose `decide(obs)` runs `decide` in a `ThreadPoolExecutor` and, on None, timeout, exception or unknown `target`, returns `rule.decide(obs)` and marks the event `fallback: true`; optional `agents[].llm: true`; event `{t, type: "llm", idx, floor, target, action, reason, fallback?}`.

- [x] With `brain == "mixed"`, flag `k = min(N, clamp(round(0.08 × N), 10, 20))` agents drawn with `default_rng([seed, 2])` and set `agents[].llm = true` on them.
- [x] Decision points for flagged agents only: `start`, `arrive`, `blocked`, the first time `visibility < 5`, and `queue/flow > 30` s at the current target (the `trigger` in `obs`); at most one call per agent per 10 s. Everyone else, and every `tick` re-plan, stays rule-based. A decision with a different, known `target` switches through the C4 code; `wait` keeps the current target; log the `llm` event with the model's `reason`.
- [x] Smoke test with stubs, no network: a stub returning the farthest option with reason "stub" yields `llm` events only for flagged agents (10 ≤ flagged ≤ 20) who then follow it; a stub returning None yields `fallback: true` events and everyone still exits; a stub that sleeps 1 s with `timeout=0.2` falls back; `brain` unset and `"rules"` give identical events and no `llm` events (batch and what-if runs stay rule-based).
- [x] Verify: `python -m sim.smoke_test` ends with `OK`.
- [x] Commit locally: `git add sim docs/superpowers/plans/2026-11-13-ws-c-crowd-sim.md && git commit -m "feat(sim): LLM brain for flagged agents"`. No push or sync per overnight instructions; the runner handles those. Live-check handoff for A below.

**Verification:** `.venv/bin/python -m sim.smoke_test` ends with `OK`. The 160-agent mixed scenario selects 13 agents deterministically and logs 17 farthest-option stub decisions; target changes produce matching reroutes and calls are at least 10 simulated seconds apart per agent. All 160 exit with the stub and with None fallback. A 1 s provider times out at 0.2 s without blocking shutdown or queuing further calls while busy; exceptions and unknown targets fall back. Explicit rules and omitted brain produce identical events without importing the provider. Existing fire, mobility, stair, determinism and 300-agent checks pass (5.32 s, 1.78 MB, zero stuck).

**Handoff for A:** `backend.llm.features.decide` is absent on this branch; mixed runs warn and use logged rule fallbacks until it lands. Please run a live `brain: "mixed"` example with `GEMINI_API_KEY` after integration. No network or credentials were used here. Observations use `smoke` and `queue` triggers in addition to start/arrive/blocked; routine ticks and stuck recovery remain rule-based. Optional `agents[].llm` marks selected agents; `llm` events record target/action/reason and `fallback: true` when applicable. A provider must enforce its own network timeout because Python cannot stop a running worker thread. C8's batch calls and showcase cap remain for the next task. Shared contracts were not changed.

### Task C8: Every agent an LLM (P2 stretch, target Sun 2 AM; only if C1–C7 are done)

BLOCKED: A's `backend.llm.features.decide_batch` provider is absent on this branch (`backend/llm/` contains only `__init__.py`), so the required live-backend showcase run cannot be verified. A must supply the provider before C8 can be completed; backend changes are outside WS-C. Stopped per overnight instructions, leaving implementation boxes unchecked.

**Files:** Modify `sim/brain.py`, `sim/run.py`, `sim/smoke_test.py`.

**Interfaces:**
- Consumes: A's `backend.llm.features.decide_batch(observations: list[dict]) -> list[dict | None]` (same length and order; None means rules) and the C4 `obs`.
- Produces: `LLMBrain.decide_batch(observations)` (timeout 12 s; on timeout or exception every entry falls back to rules); scenario `brain: "llm"` (at most 150 agents, else `ValueError`; every `agents[].llm = true`); `llm` events as in C7.

- [ ] On each 1 s tick, collect `obs` for every agent at a decision point (C7 triggers plus a `tick` every 15 s per agent); make one `decide_batch` call if the list is non-empty; apply each decision through the C4 switch code and log one `llm` event with its `reason`; None entries use rules.
- [ ] Smoke test with a stub: calls ≤ number of ticks; some call carries > 1 observation; every stub decision is applied; `N = 151` raises `ValueError`; a stub that raises falls back and everyone still exits; with `brain` unset, behavior equals C4.
- [ ] Verify: `python -m sim.smoke_test` ends with `OK`; with A's backend live, one showcase run (`brain: "llm"`, ≤ 150 agents) through `python -m sim.run`, then hand the run file to A.
- [ ] Commit and push: `git add sim && git commit -m "feat(sim): all-LLM crowd mode" && git push`.
