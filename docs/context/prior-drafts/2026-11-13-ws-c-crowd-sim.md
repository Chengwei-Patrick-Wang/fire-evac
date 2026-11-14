# Workstream C — Crowd Simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sim.run(building, scenario, fire)` returns a run/v0 JSON: agents with profiles leave a multi-floor building through stairs and exits, choose and change exits, slow down in smoke, and wait for help when they can't use stairs.

**Architecture:** One JuPedSim `Simulation` per floor, stepped together. Agents that reach a stair zone are removed and re-added one floor down after a stair delay. A Python "brain" re-scores exits every second or on events and calls `switch_agent_journey`. Start from `tools/build_examples.py`, which already runs F1. Spec: `docs/superpowers/specs/2026-11-13-fire-evac-sim-design.md`.

**Tech Stack:** Python 3.11, jupedsim 1.4.2, shapely 2, numpy.

**Hackathon mode:** no TDD; one `smoke_test.py`; commit after every task.

**Owner profile:** Python and algorithms.

**JuPedSim facts (checked on 1.4.2):** `add_exit_stage`, `add_waypoint_stage`, `add_waiting_set_stage`, `add_queue_stage`, `add_direct_steering_stage`, `switch_agent_journey`, `agents_in_polygon`, `mark_agent_for_removal`; `agent.model.desired_speed` is settable mid-run; `removed_agents()` reports per iteration, so check it every step. Agent ids keep counting across simulations in one process, so key everything by our own `idx`. Same seed gives identical trajectories.

---

### Task C1: Single-floor runner from the contracts (H+0 to H+2)

**Files:** `sim/run.py`, `sim/__init__.py`

- [ ] Port `tools/build_examples.py` into `run(building, scenario, fire=None) -> dict`: agents per room from `occupants`, profiles from `mix`, seeded RNG, frames every 0.5 s as `[idx, x, y, floorIdx, status]`, exit events checked every step, metrics.
- [ ] CLI: `python -m sim.run contracts/building.example.json contracts/scenario.example.json data/runs/out.json`.

### Task C2: Multi-floor via stair transfer (H+2 to H+5)

- [ ] One `Simulation` per floor built from its walkable polygon; upper floors get exit stages on their stair zones.
- [ ] On removal at a stair on floor k: push `(arrival_time, idx)` into that stair group's FIFO; arrival = now + stair length / stair speed (typical 0.55 m/s going down); cap throughput at about 1.1 persons per second per meter of stair width.
- [ ] On arrival, add the agent inside the same stair group's polygon on floor k−1 with a journey to its chosen exit (or the next stair down).
- [ ] Verify: on the example building, agents placed on F2 all get out; frames show them switch floors.

### Task C3: Start delays and profiles (H+5 to H+7) (parallel with C2)

- [ ] Profile table (speed range, stair speed factor, start delay distribution, radius) in `sim/profiles.py`; wheelchair users cannot use stairs alone.
- [ ] Agents not yet moving stay out of JuPedSim and appear in frames with status 0 until their delay ends.

### Task C4: Exit choice and re-planning (H+7 to H+12)

**Files:** `sim/brain.py`

- [ ] Cost per exit (spec formula): route distance (straight-line first, room–door graph if time allows) over speed, plus queue estimate (`agents_in_polygon` around each door or stair divided by its flow), smoke penalty and unfamiliarity penalty. Visitors know only the entrance they came in by.
- [ ] Softmax choice with seeded RNG; switch only if 20% cheaper; re-plan every 1 s and on events; `switch_agent_journey`; log `reroute` events.

### Task C5: Fire coupling (H+12 to H+14)

- [ ] Each second: `desired_speed` from `fire.visibility(...)` using the spec formula; `fire.untenable(...)` marks agents trapped (event, removal); `fire.blocked_doors()` drops those targets, and agents re-plan when the blocked door is within their visibility.
- [ ] Use `fire.stub.NoFire` until D's model lands.

### Task C6: Waiting for help and LLM hook (H+14 to H+20)

- [ ] Wheelchair users on upper floors go to a stair landing (waiting set), status 2, released after `scenario.assistDelay` (default 180 s) and moved down at a slow stair speed.
- [ ] Decision hook: for agents flagged `llm: true`, build `obs` (floor, location, visible smoke, queues, known exits, companions) and call `llm.decide(obs)`; fall back to rules on `None`; log `llm` events with `reason`.

### Task C7: Smoke test (any time)

- [ ] `sim/smoke_test.py`: example scenario → everyone out before `maxTime`, both exits used, F2 agents reach F1. Prints t50, t90, t100.
