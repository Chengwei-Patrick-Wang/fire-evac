# Ember UI rework and simulated fire spread: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking. Team rule (AGENTS.md): smoke checks, not TDD; no separate review unless something broke.

**Goal:** the Ember UI (team design.md §17) on the current frontend, plus room-to-room fire spread at a material-dependent speed that drives the simulation.

**Architecture:**
- **D** adds a room-graph ignition schedule to `FireModel`.
- **C** closes doors and traps occupants as rooms ignite, and writes `run.fire.rooms` and `run.fire.material`.
- **A** adds the optional contract fields, a frontend fixture, and the wood-against-drywall demo pair, then reruns the precompute.
- **E** reworks the shell, theme, building look, floor views, visibility, agent colors and fire visuals, without changing the frontend architecture.

**Tech stack:** Python 3.12 (JuPedSim 1.4.2, shapely, NumPy, FastAPI); React + TypeScript + React Three Fiber/Drei + Zustand + Recharts + plain CSS, plus `lucide-react`.

**Spec:** `docs/superpowers/specs/2026-11-14-ember-ui-fire-spread-design.md` (approved Sat 14 Nov). The UI reference is `docs/design/ember-ui.md`; the images are in `handoff/design/` on the lead's laptop.

## Global constraints

- **Freeze Sun 2 AM.** Netlify redeploys the public site from `main` on every push, so `main` stays green (`tools/check_all.py`).
- **Contracts:** new optional fields only: scenario `fire.material` (`concrete` | `drywall` | `wood`, default `drywall`); run `fire.rooms: [{room, floor, ignite}]` and `fire.material`.
- **No frontend architecture change.** No Tailwind, no shadcn. `lucide-react` is the only new dependency. No web fonts: the font stack starts with Inter and falls back to system fonts.
- **Keep working:** the guided tour, URL-hash deep links, `npm run qa` with 0 axe violations, keyboard access, the high-contrast theme, static and live mode, and the phone layout.
- **Honest labels:** material presets and the spread are labeled "illustrative". Nothing presents them as engineering units.
- **Folders:** one agent per folder at a time: D `fire/`, C `sim/`, E `frontend/` (not `src/tracer/`), A `backend/` + `tools/` + `contracts/` (and `frontend/src/data/types.ts` by A merge).
- **Commits:** no attribution lines. Push only the workstream branch; the lead merges to `main`.

## Lead rulings (settled before execution)

- **Types:** A11 part 1 adds the shared types to `frontend/src/data/types.ts`: `whatIf: 'material'` on demo runs, an optional `material`, and `fire.rooms` / `fire.material` on runs. E38 imports them and defines no local copies. `findPrecomputedVariant` stays door-only (`'propped'`).
- **Fixture:** A11 part 1 writes `contracts/run.spread.fixture.json` (a run/v0 with `fire.rooms`). E38 uses that file, opened via File > Open or copied by its qa step, wherever its text says `frontend/public/demo/fixtures/fire-spread.run.json`. A11 part 2 keeps the fixture as a test file and does not delete it.
- **The ignition room** is listed in `fire.rooms` (ignite = fire start) but keeps today's doors, keep-out and heat curve, so results for unspread fires stay identical (C27).
- **Sprinklers:** with sprinklers on, the fire stays in the ignition room (D25). `FireModel(spread=False)` turns spread off.
- **Ordering:** the wood-against-drywall data commit (A11 part 2) reaches `main` only together with or after E38. Until E38, the app reads any non-null `whatIf` as a door what-if.
- **Store names:** E37 renames the existing `agentColor` to `colorBy` (`'status' | 'type'`); the view action is `setViewMode`, because `setView` is taken.
- **Speeds:** `tourSpeed` uses 4× where it used 5×. The timeline offers 0.25/0.5/1/2/4/10×.

## Review focus

1. **Runs without `fire.rooms`** (old precomputed runs, the static site before the rerun, an older backend): no spread visuals and no errors. E38 checks this with a run that lacks the field.
2. **Fire on a hidden floor** in single or ghost view: the simulation is unchanged, and the visible floor's agents still react. E37 checks that hiding a floor doesn't change the run data the scene reads.
3. **Wood runs with many trapped people** (corridors ignite at about 90 s from R143): headline, report card and risk ranking still read sensibly. A11 part 2 checks the office pair's headline and card text.
4. **The tour on the new layout,** in static mode on a slow machine: every scene finds its panel and tab. E36 runs the tour end to end in qa.
5. **Small screens:** panels overlay the viewer, the floor strip scrolls, and the timeline stays usable. E36's qa covers a phone-size screen.

## Execution order

1. **A11 part 1** (formats, fixture, types) and **D25** (spread model), in parallel.
2. **C27** after D25, and **E36** after A11 part 1. These run in parallel.
3. **E37** after E36, then **E38** after E37.
4. **A11 part 2** after C27 and E38: the wood pair and the precompute rerun (about 2 h), then the freeze.

---


### Task D25 (P0 · Sat 6 PM): Fire spreads room to room at an illustrative material speed

**Files:** Create `fire/spread.py`. Modify `fire/model.py` (`FireModel.__init__`, `hrr`, `_update`, new `burning_rooms`, `ignition_times`, attribute `material`), `fire/stub.py` (`NoFire.burning_rooms`, `NoFire.ignition_times`), `fire/checks.py` (new `check_spread`, `check_spread_slow`; `check_model` and `check_tuning` build their models with `spread=False`), `fire/README.md`, `docs/superpowers/plans/2026-11-13-ws-d-fire-metrics-batch.md`.

**Interfaces:**
- **Consumes:**
  - `FireModel(building, scenario)` today has one smoke source at `source_xy`:
    - `hrr(t) = hrr_kw(params, t - start)`;
    - the arrival table integrates the smoke speed `clip(0.25 + 0.5·Q/1000, 0.25, 1.0)` from that curve over `TABLE_S` (1800 s);
    - `_update(t, dt)` sets density from `min(1, q/1000)`, the flame footprint from `sqrt(q/1000)`, and `_blocked` (doors with an untenable node). `step(t)` calls it every 1 s.
  - building/v0: `doors[].connects` (`[room, room | "outside"]`), room `polygon`s (the example's rooms touch; IFC spaces in the office and clinic stop at the walls), `stairs[]: {group, room}`, floor `level`.
  - Callers, unchanged:
    - `sim/run.py` turns `blocked_doors()` into `blocked` at every 1 s tick (routing through `room_reachable` and `blocking_doors`, plus `door_blocked` events) and records `hrr(t)` in `run.fire.hrr`.
    - `fire.batch._run_one`, `fire.metrics.compute` (exposure), `backend.app.jobs.simulate` and `tools/build_examples.py` call `FireModel(building, scenario)`.
- **Measured** (prototype on the lead's Windows laptop):
  - **Wall gaps.** Office rooms that share a door sit 0.12 m apart (the IFC wall). With a 0.25 m gap tolerance and a 1.0 m minimum shared length:
    - example: 24 door links (2 of them stair links) and 22 wall-only links;
    - office: 91 and 176, built in 0.13 s;
    - clinic: 222 and 347, built in 0.28 s.
  - **Rooms on fire by 400 s,** ignition room included (concrete / drywall / wood):
    - example R101: 2 / 12 / 15;
    - office R143: 9 / 21 / 37; R203c: 5 / 6 / 36; R237b: 4 / 4 / 14;
    - clinic R1AC1: 6 / 31 / 74.
  - **Batch averages.** Over every batch room (no corridors or stairs), the other rooms reached by 400 s average 6.5 in the office and 6.3 in the clinic with drywall, against 19.6 and 21.2 with wood.
  - **Smoke.** A kitchen fire reaches 1 MW at 146 s and 1.5 MW at 179 s; there, smoke density and smoke speed saturate. So drywall's first spread (180 s) leaves kitchen smoke unchanged and changes only `hrr` and `blocked_doors()`. Wood (90 s) makes smoke faster and denser between 90 and 179 s.
  - **Door D in `fixture_building()`.** Smoke alone never closes D within 400 s, with a kitchen fire or a trash fire at (8, 5).
  - **Checks that break under spread.** Two fast checks pin smoke-only numbers past 180 s:
    - `check_model`: `hrr(200) == 1500`;
    - `check_tuning`: `blocked_doors() == {"D101"}` at 180 s, and `set()` for trash and bedroom up to 300 s.
- **Decisions:**
  - **The ignition room keeps today's rules** (see the top of this file).
  - **Sprinklers confine the fire.** With `sprinklers: true`, the schedule holds only the ignition room: the usual confinement assumption for a sprinkler-controlled fire. This keeps the sprinkler what-if believable. It isn't in the design; drop this bullet to let fire spread under sprinklers.
- **Produces:**
  - `fire/spread.py`:
    - `MATERIALS = {"concrete": {"flashover": 600.0, "door": 300.0, "wall": 1200.0}, "drywall": {"flashover": 300.0, "door": 180.0, "wall": 600.0}, "wood": {"flashover": 150.0, "door": 90.0, "wall": 240.0}}` (seconds), `DEFAULT_MATERIAL = "drywall"`, `WALL_GAP_M = 0.25`, `WALL_MIN_M = 1.0`;
    - `material_name(fire: dict) -> str`;
    - `room_links(building) -> dict[(floor, room), dict[(floor, room), "door" | "wall"]]`, cached by object identity like `fire.grid.get_graph`;
    - `origin_room(building, fire) -> (floor, room) | None`;
    - `ignition_schedule(building, scenario) -> list[dict]`;
    - `room_hrr_kw(peak_kw, flashover_s, tau) -> float`;
    - a CLI, `python -m fire.spread BUILDING SCENARIO [--material NAME]`.
  - `FireModel(building, scenario, spread=True)` and `FireModel.material: str`.
  - `burning_rooms(t: float) -> set[tuple[str, str]]`, as (floor_id, room_id).
  - `ignition_times() -> list[dict]`: entries `{"room": str, "floor": str, "ignite": float}`, sorted by ignite, only rooms with ignite <= maxTime, returned as fresh copies.
  - `blocked_doors()` adds every door of a burning room other than the ignition room; `hrr(t)` is the total.
  - `NoFire.burning_rooms(t) -> set()` and `NoFire.ignition_times() -> []`, with no `material` attribute.
  - **Run output:** `sim/run.py` `run()` writes `run["fire"]["rooms"] = fire.ignition_times()` and `run["fire"]["material"] = fire.material` (C27).

- [ ] **Step 1: Presets.** Write `MATERIALS` as above.
  - `material_name`: a missing key gives `"drywall"`. The value must be exactly one of the three names. Anything else (`"Wood"`, `"steel"`, `None`, `3`) raises `ValueError("Unknown fire material 'steel'; valid names: concrete, drywall, wood")`.
  - Tuning for a legible demo is allowed only if two orders hold: wood < drywall < concrete for each of the three values, and door < wall for each material.
- [ ] **Step 2: Room graph.** `room_links(building)`:
  - **Door link:** a door whose `connects` holds two different rooms of its floor.
  - **Wall link:** two rooms of one floor whose polygons are within `WALL_GAP_M` (`Polygon(...).buffer(0)`, candidates from an `STRtree` `dwithin` query), where `min((a.boundary ∩ b.buffer(WALL_GAP_M)).length, (b.boundary ∩ a.buffer(WALL_GAP_M)).length) ≥ WALL_MIN_M`.
  - **Stair link** (counts as a door link): for consecutive floors by `level`, each stair room of a `group` on the lower floor and each stair room of the same group on the upper floor. No other link crosses floors.
  - A pair with both a door and a wall keeps `"door"`. Buildings are immutable after their first lookup (`get_graph`'s rule).
- [ ] **Step 3: Schedule.** `ignition_schedule(building, scenario)`:
  - **Origin:** `(fire.floor, fire.room)` when that room exists; else the room whose polygon covers `(x, y)` on `fire.floor`; else none, and the schedule is empty.
  - **Dijkstra** from the origin at `fire.start` (default 0), with `ignite(n) = ignite(r) + MATERIALS[material][kind]`.
    - Heap key `(time, floor index, room index)`, in building order, so ties come out the same every time.
    - Keep rooms with ignite <= `scenario.get("maxTime", 600)`, the sim's default.
  - `sprinklers: true` keeps only the origin.
  - **Entries:** `{"room": id, "floor": id, "ignite": round(t, 2) + 0.0}`, sorted by the heap key; the origin comes first.
- [ ] **Step 4: Model.** In `FireModel.__init__`:
  - Set `self.material = material_name(fire)`; a bad name fails the run with Step 1's error.
  - Build the schedule. `spread=False` keeps only the origin, with the same start and maxTime rules.
  - Map each room to its doors: ids on its floor whose `connects` names the room, exterior doors included.
  - **Heat:**
    - The origin keeps `hrr_kw(params, t - start)`.
    - Each other room adds `room_hrr_kw(params["peakKw"], flashover, t - ignite)` = `peakKw · min(1, (tau / flashover)²)` for tau ≥ 0. So the room is fully involved at the material's flashover time, capped at the preset's peak.
    - `hrr(t)` is the sum. The arrival table adds the same terms (vectorized with `np.clip`) only when the schedule has a room besides the origin. A schedule with only the origin gives bit-identical arrays and values.
  - **`_update`:** density uses `hrr(t)`; the flame footprint uses the origin's own curve; `_blocked |=` the doors of every non-origin room with ignite <= t.
  - `burning_rooms(t)` returns every `(floor, room)` with ignite <= t, origin included. `ignition_times()` returns copies of the entries.
- [ ] **Step 5: Stub.** Add `NoFire.burning_rooms` and `NoFire.ignition_times`, with docstrings. Add no `material` attribute: the sim writes the new run keys only for a model that has one.
- [ ] **Step 6: Checks.**
  - **Fast `check_spread()`, no sim:**
    - **Presets:** wood < drywall < concrete for flashover, door and wall; door < wall for each material.
    - **Names:** Step 1's `material_name` cases; `FireModel` with `"material": "steel"` raises the same error.
    - **Two-room fixture.** `fixture_building()` has rooms A and B, 0.2 m apart along 6 m, joined by door D. Fire in A at (8, 5), maxTime 1300. `ignition_schedule` gives:
      - drywall: `[{"room": "A", "floor": "F1", "ignite": 0.0}, {"room": "B", "floor": "F1", "ignite": 180.0}]`; wood: B at 90.0; concrete: B at 300.0;
      - without D (wall links only): B at 600.0, 240.0 and 1200.0;
      - start 50: A at 50.0, B at 230.0. maxTime 170: A only. Sprinklers: A only;
      - B cut to `box(10.2, 0, 20.2, 0.6)` with no door (0.6 m of shared wall): A only.
    - **Doors and heat.** Compare a drywall kitchen model with a `spread=False` twin, maxTime 1300:
      - For every whole t from 1 to 179: equal `hrr`, `_density` and `blocked_doors()`.
      - At t = 180: `"D"` is in the model's `blocked_doors()` and not in the twin's.
      - `hrr(330) - twin.hrr(330) == 375.0` and `hrr(480) - twin.hrr(480) == 1500.0`.
      - `_footprint` is equal at every t up to 400.
      - `burning_rooms(179.9) == {("F1", "A")}` and `burning_rooms(180) == {("F1", "A"), ("F1", "B")}`.
      - Clearing the list that `ignition_times()` returned leaves the next call unchanged.
    - **The example.** Contracts building and scenario, kitchen fire in R101 at (8, 3), maxTime 400, `material` set in each case:
      - drywall: R101 0.0; C1 180.0; R102, L1, R103, R104, R105, R106, R107, R108, SA1, SB1 at 360.0 (all on F1);
      - wood: R101 0.0; C1 90.0; the same ten at 180.0; SA2 and SB2 (F2) at 270.0; C2 (F2) at 360.0;
      - concrete: R101 0.0; C1 300.0;
      - drywall with the fire in L1: L1 0.0; C1 180.0; R101, R102, R103, R104, R105, R106, R107, R108, SA1, SB1 at 360.0.
    - **Deterministic:** two calls are equal; a copy with its floors reversed gives the same ignite per room; `json.dumps(..., allow_nan=False)` passes.
    - **`NoFire`:** `burning_rooms(10) == set()`, `ignition_times() == []`, no `material` attribute.
    - **The office** (skipped with a printed line when the file is missing): 91 door-link and 176 wall-only pairs (unordered), built in under 2 s. From R143, 21 rooms by 400 s with drywall, 37 with wood, 9 with concrete.
  - **Slow `check_spread_slow()`.** Run `sim.run.run` with `FireModel` on the example scenario (160 agents, maxTime 400, drywall).
    - Each of C1's 11 doors (D101–D108, DL1, DSA1, DSB1) has a `door_blocked` event at t ≤ 180.0.
    - The 10 doors besides D101 have it at exactly 180.0; smoke closes D101 at or before 180 s.
    - Print the trapped counts by reason.
  - **`check_model` and `check_tuning`** build their models with `spread=False`, because they pin smoke-only numbers. Every assertion stays.
  - **Other slow checks.** Rerun every `*_slow` check. If one fails only because spread now closes doors or traps people, keep the check's intent:
    - pin `fire.material` to `concrete` in that check's scenario when the check tests something else, or re-pin the number;
    - never drop an assertion, and list each change in the commit body.
- [ ] **Step 7: Verify:**
  - `python -m fire.smoke_test` and `python -m fire.checks --slow` print `fire checks OK`.
  - `python -m fire.spread contracts/building.example.json contracts/scenario.example.json` prints the drywall list, one `<ignite> s  <floor> <room> (<name>)` line per room, and ends `12 rooms by 400 s (drywall)`. With `--material wood` it ends `15 rooms by 400 s (wood)`.
  - `python -m sim.smoke_test` (fast) still ends `OK`. If a sim check fails only because spread moved its numbers, leave `sim/` to C27 and add a BLOCKED line asking the lead to merge D25 together with C27.
  - **README section "Fire spread (D25)":**
    - the presets table, labeled illustrative: not engineering values, not validated, not for compliance;
    - the link rules, the heat-release rule, the ignition-room rule and the sprinkler rule;
    - the measured table above.
- [ ] **Step 8: Commit:** `git add fire docs/superpowers/plans/2026-11-13-ws-d-fire-metrics-batch.md && git commit -m "feat(fire): fire spreads room to room at an illustrative material speed"` (no attribution lines). Handoffs in the README:
  - **For C27:**
    - The API above. Doors of rooms that catch fire already come through `blocked_doors()`.
    - The first `ignition_times()` entry is the ignition room.
    - `NoFire` has both methods; `tools/toy_fire.ToyFire` has neither.
  - **For A11:**
    - `fire.spread.ignition_schedule(building, scenario)` is pure and takes milliseconds after the first `room_links` call; the report card uses it. `material_name` validates.
    - Every demo number changes, so rerun without `--resume`.
  - **For E:** a room is fully involved `flashover` seconds after it ignites (600, 300 or 150 s). That makes a natural orange-to-red ramp.
- **Risk:** wood traps many people. From office R143, the corridors R121, R143A and R146 ignite at 90 s, while more than half the occupants are still inside (t50 is 97 s). The presets stay as pinned unless the lead asks to tune them within the order.

### Task C27 (P0 · Sat 7 PM): Rooms that catch fire close their doors and trap the people still inside

Needs D25 on `main`.

**Files:** Modify `sim/run.py` (module docstring; in `run()`: spread setup next to `burning_doors`, the 1 s fire tick, the per-agent 1 s loop, the returned `fire` block), `sim/smoke_test.py` (new `spread_building`, `check_spread`, `check_spread_slow`; a fire-block assertion in `check_core`; registration in `main()`; any slow assertion that Step 6 repairs), `docs/superpowers/plans/2026-11-13-ws-c-crowd-sim.md`.

**Interfaces:**
- **Consumes:**
  - **From D25:**
    - `fire.burning_rooms(t)` (the ignition room included from its start), `fire.ignition_times()` (sorted; the first entry is the ignition room at the fire's start; only rooms with ignite ≤ maxTime), `fire.material`, and `FireModel(..., spread=False)`.
    - `fire.blocked_doors()` already holds every door of a burning room other than the ignition room. So the existing tick closes those doors with no new code: `fire_blocks` → `blocked` → `door_blocked` events, the `no route` trap in `room_reachable`, and `blocking_doors` for exits, and for stairs through `stair_blocked`.
    - `NoFire` has both methods and no `material`. `tools/toy_fire.ToyFire` (used by `check_recording`; A's folder) has neither.
  - **`run()` today:**
    - `fire_room` and the origin keep-out (`keepout_cut`), applied at the start on the fire floor only, because JuPedSim's geometry can't change mid-run;
    - `burning_doors` and `burning_groups` for a burning origin stair, and `closed_groups`;
    - `trap(i, t, fs, pos, reason)`;
    - the per-agent 1 s loop: `fire.untenable` traps as `untenable`, then status 0 cues, then status 1 `choose`;
    - the returned `"fire": {floor, x, y, hrr}`.
- **Measured:**
  - **Example R101, drywall:** C1 ignites at 180 s, the rest of F1 at 360 s, F2's stair rooms at 540 s. The whole building is on fire by 900 s, the smoke suite's maxTime.
  - **FireModel runs in the suite:** `check_keepout` (fast and slow), `check_cues`, `check_keepout_rooms` and `check_runsize` (slow).
  - **Fixture below:** with a trash fire at (2, 3) in room A, room B keeps 30 m visibility through 180 s (a kitchen fire gives 14.3 m). So B's occupant never gets a smoke cue (`CUE_VIS_M` is 10 m).
- **Produces:**
  - Trapped events with `reason: "burning room"`.
  - `run["fire"]["rooms"]` (= `fire.ignition_times()`) and `run["fire"]["material"]`. They're written only when the fire model has a string `material`, so NoFire and ToyFire runs keep today's `fire` block byte for byte.
  - In `sim/smoke_test.py`: `spread_building() -> dict`, `check_spread(building, scenario)` and `check_spread_slow(building, scenario)`.

- [ ] **Step 1: Before.** On `main` with D25 merged and before any edit, save these runs to the ignored `debug/c27-before/`:
  - the example's fast scenario (40 agents) with `FireModel` and maxTime 170;
  - the same with `fire.material` set to `concrete` and maxTime 290;
  - `check_core`'s NoFire run;
  - office R143 like its demo baseline (250 occupants, kitchen, `D$77xsW` closed, seed 1, the room's `representative_point()`), with maxTime 170.
- [ ] **Step 2: Setup.** In `run()`, after the fire model and `burning_doors`:
  - `burning_fn = getattr(fire, "burning_rooms", None)`;
  - `origin`: the `(floor, room)` of the first `fire.ignition_times()` entry, or None when the method is missing or the list is empty;
  - the room polygons by `(floor, room)` and each stair room's group;
  - `spread_seen = set()` and `burning_area = {}`.
- [ ] **Step 3: Each 1 s tick,** right after `fire.step(t)`:
  - `now = burning_fn(t) - {origin}` (empty without `burning_fn`), and `new = now - spread_seen`.
  - A newly burning stair room with no doors adds its group to `closed_groups`, as the origin's doorless stair does today.
  - For each floor with a new room, rebuild `burning_area[floor]`: the prepared union of that floor's polygons in `now`.
  - Doors need no new code: D25's `blocked_doors()` brings them in through `fire_blocks` in this same tick.
- [ ] **Step 4: Traps.** In the per-agent 1 s loop, right after the `untenable` branch: `elif` the agent's `(x, y)` is inside `burning_area[fs.id]` (`shapely.contains_xy`), call `trap(i, t, fs, (x, y), "burning room")`.
  - This catches people of status 0 and 1, so both people waiting to start and people walking.
  - The ignition room never enters `burning_area`: it keeps its keep-out and the `untenable` trap.
  - People in a stairwell (status 2 or 3) stay unexposed, as today.
- [ ] **Step 5: Output and docs.**
  - In the returned `fire` block, after `hrr`: add `rooms` and `material` when `getattr(fire, "material", None)` is a string.
  - Module docstring: rooms catch fire on D25's schedule, their doors close to routing, people inside are trapped as `burning room`, and the ignition room keeps its keep-out.
- [ ] **Step 6: Smoke test.**
  - **`spread_building()`:** a plan/v0 through `plan_to_building`:
    - room A (office) `[[0,0],[60,0],[60,6],[0,6]]` and room B (office) `[[60,0],[70,0],[70,6],[60,6]]`;
    - door D at x = 60 (y 2.5–3.5, 1.0 m wide, `closed`) between them;
    - door E at x = 70 (y 2.5–3.5, 1.0 m wide, `open`) from B to outside. B holds the only exit.
  - **Fast `check_spread(building, scenario)`,** where `building` and `scenario` are the example and its fast scenario:
    - **Fixture scenario:** `perRoom {"A": 1, "B": 1}`, mix `{"typical": 1}`, trash fire in A at (2, 3), start 0, `alarmTime` 1000, maxTime 200, seed 1, brain `rules`.
    - **Drywall:**
      - `fire.rooms == [{"room": "A", "floor": "F1", "ignite": 0.0}, {"room": "B", "floor": "F1", "ignite": 180.0}]` and `fire.material == "drywall"`;
      - A's occupant gets the fire cue and has an `exit` at E before 180 s;
      - `door_blocked` for D and for E, each exactly once, at t == 180.0;
      - exactly one `trapped`: B's occupant, at t == 180.0, with `reason == "burning room"`;
      - `evacuated == 1`, `trapped == 1` and `remaining == inStairs == 0`.
    - **Concrete** (B would ignite at 300 s, after maxTime):
      - `fire.rooms` lists A alone; there is no `door_blocked` and no `trapped`, and `remaining == 1`;
      - the JSON equals the run with `FireModel(..., spread=False)` byte for byte.
    - **Example guard:** the fast scenario with maxTime 170 gives the same JSON with the default `FireModel` and with `spread=False`. `fire.rooms == [{"room": "R101", "floor": "F1", "ignite": 0.0}]`, and no event has reason `burning room`.
    - **`check_core`:** the NoFire run's `fire` keys are exactly `{"floor", "x", "y", "hrr"}`.
  - **Slow `check_spread_slow(building, scenario)`:** the full example (160 agents, maxTime 400), first with drywall, then with wood:
    - each run's `fire.rooms` equals D25's pinned list (12 and 15 rooms);
    - every `burning room` trap is at t ≥ its room's ignite time, and inside that room;
    - every agent has exactly one `exit` or `trapped` (C17's rule), and `remaining == inStairs == 0`;
    - wood traps more people than drywall. Print the trapped counts by reason for both.
  - **Registration:** in `main()`, add the fast check after `fast fire` and the slow one after `full fire`.
  - **Slow-suite repairs.** Rerun the slow suite. If an assertion fails only because spread now traps people (for example `check_keepout`'s protected/unprotected ratio), count only the traps it was written for (reason `untenable` there). Never loosen a bound, and list each repair in the commit body.
- [ ] **Step 7: Verify:**
  - With `LLM_PROVIDER=off OPENBLAS_NUM_THREADS=1`, `python -m sim.smoke_test` ends with `OK` within C9's fast budget, and `--slow` passes.
  - Rerun Step 1's four runs. The NoFire file must match byte for byte. The three FireModel files must match (`cmp`) after removing `fire.rooms` and `fire.material`. Never accept a difference.
  - Run the office R143 baseline at maxTime 400, with drywall and with wood. Put t90, evacuated, trapped counts by reason and `len(fire.rooms)` under this heading; A11's material pair reruns exactly these two runs.
- [ ] **Step 8: Commit:** `git add sim docs/superpowers/plans/2026-11-13-ws-c-crowd-sim.md && git commit -m "feat(sim): rooms that catch fire close their doors and trap the people inside"` (no attribution lines). Handoffs:
  - **For A:** every number from a run with a fire changes, so rerun the precompute after this merges. FireModel runs now carry `fire.rooms` and `fire.material`.
  - **For E:** the new trapped reason `burning room` shows as is in the agent hover.

### Task A11 (P0 · Sat 8 PM; contracts part first, at Sat 5 PM): Material and spread in the formats, a frontend fixture, the wood-vs-drywall pair, and the demo rerun

Part 1 needs nothing. Part 2 needs D25 and C27 on `main`.

**Files:**
- **Part 1:**
  - Modify `contracts/scenario.example.json`; `tools/build_examples.py` (new `SPREAD_FIXTURE_ROOMS` and `write_spread_fixture`, docstring); `docs/superpowers/specs/2026-11-13-fire-evac-sim-design.md` (§6); `frontend/src/data/types.ts` (the shared mirror, which A merges).
  - Generate `contracts/run.spread.fixture.json`.
- **Part 2:**
  - Modify `tools/precompute_demo.py` (`PRESETS["office"]`, `base_scenario`, `build_jobs`, `run_entry`, `write_run`, `order_by_story`, `process_building`), `backend/llm/features.py` (`_batch_facts`, `_run_facts`), `backend/smoke_test.py`, and `tools/build_examples.py` (drop the fixture writer).
  - Delete `contracts/run.spread.fixture.json`.
  - Regenerate `contracts/*.example.json` and `frontend/public/demo/*`.
- **Both parts:** `docs/superpowers/plans/2026-11-13-ws-a-integration.md`.

**Interfaces:**
- **Consumes:**
  - D25's `fire.spread.ignition_schedule`, `material_name` and `MATERIALS`. C27's `run.fire.rooms`, `run.fire.material` and the trapped reason `burning room`.
  - **Backend pass-through.** Two paths carry the scenario dict to the fire model untouched, so `fire.material` already passes through and needs no code change:
    - `post_run(scenario: dict[str, Any])` → `jobs.submit` → `_worker` → `simulate` → `FireModel(building, scenario)`;
    - A4's batch endpoint → `run_many` → `fire.batch._tasks`, which deep-copies `base`.
  - **`tools/precompute_demo.py`:**
    - `PRESETS`; the office uses 250 occupants, the kitchen preset and rooms R143, R203c and R237b;
    - `base_scenario`; `build_jobs` (a `closed` baseline and a `propped` job per room, same seed); `run_entry` (`whatIf: None | "propped"`); `write_run` (`run-ID-ROOM-<variant>.json`); `order_by_story` (kinds base and propped);
    - `run_batch`'s `--resume`, which refuses a checkpoint whose `request.base` differs;
    - `--all` runs example-office, clinic and office, in that order.
  - **Index run entry today:** `{id, buildingId, label, file, whatIf, fire: {floor, room, x, y, type}, doors, metrics: {t50, t90, t100, evacuated, trapped}}`.
  - **Frontend:**
    - `openLocalFile` opens any run/v0 (File > Open), so a fixture needs no index entry.
    - `sync-demo.mjs` copies only `run.example.json`, `scenario.example.json`, `building.example.json` and `batch.example.json` from `contracts/`.
    - `findPrecomputedVariant` (`frontend/src/model/whatif.ts`) and the deep-link path in `App.tsx` read any non-null `whatIf` as a door what-if.
  - **Report card:** `report_card(batch_or_run, building)` → `_batch_facts` / `_run_facts` → `numbers` sentences. `_s(400)` is `"400 s"`; `names.room_label("F1", "R101")` is `"Kitchen (R101)"`.
- **Measured:**
  - D25's table.
  - The example's run ends at 200 s (t100 199.79 s). With wood, its ignitions at 0, 90 and 180 s show inside the replay; with drywall (180 s, then 360 s) the spread barely shows.
- **Produces:**
  - scenario/v0 `fire.material?`; run/v0 `fire.rooms?` and `fire.material?`.
  - Their mirror in `types.ts`: `type Material = 'concrete' | 'drywall' | 'wood'`, `interface FireRoom { room: string; floor: string; ignite: number }`, `Scenario.fire.material?`, `Run.fire.rooms?`, `Run.fire.material?`, `DemoRun.whatIf: null | 'propped' | 'material'`, `DemoRun.material?`.
  - `contracts/run.spread.fixture.json`, in Part 1 only.
  - **Index run entries:** `material` on every entry this tool writes. The wood run's entry: `id` `"office-R143-wood"`, `file` `"run-office-R143-wood.json"`, `label` `"SCIF OPEN OFFICE, wood (illustrative)"`, `whatIf` `"material"`, `material` `"wood"`, `doors` `{"D$77xsW": "closed"}`, and the baseline's fire point.
  - **Report-card sentences:**
    - batch: `Fire spread at illustrative <material> speeds: <mean, 1 decimal> other rooms per fire on average by <maxTime>, at most <n> rooms (fire in <room label>)`;
    - run: `Fire spread at illustrative <material> speeds: <k> other rooms by <last ignite>`, or `Fire spread at illustrative <material> speeds: the fire stayed in its room`.

**Part 1 (Sat 5 PM, before D25):**
- [x] **Step 1: Example field.** Add `"material": "drywall"` to the `fire` of `contracts/scenario.example.json`, after `start`. Today's `FireModel` ignores it, and after D25 it's the default, so no result moves.
- [x] **Step 2: Document.** In spec §6:
  - **scenario/v0:** `fire: {floor, room, x, y, type, growth?, start, material?}`, with a bullet: "`fire.material` (optional): `concrete`, `drywall` (the default when absent) or `wood`, the illustrative room-to-room spread speed (`fire/spread.py`, `fire/README.md`). Any other value is an error."
  - **run/v0:** `fire: {floor, x, y, hrr: [[t, kW], …], rooms?, material?}`, with a bullet: "`fire.rooms` (optional): `[{room, floor, ignite}]`, every room that catches fire by `maxTime`, sorted by `ignite` (s); the first is the ignition room, at the fire's `start`. `fire.material`: the material the run used. `sim/run.py` writes both whenever the run has a fire model. `hrr` is the total of every burning room. A person inside a burning room is trapped with `reason: "burning room"`."
  - Mirror both in `frontend/src/data/types.ts` with the names in Produces. E's tasks import these names and don't redefine them.
- [x] **Step 3: Fixture.** `tools/build_examples.py` writes `contracts/run.spread.fixture.json` right after `run.example.json`:
  - **Base:** a deep copy of the run it just built, thinned like `precompute_demo.thin`: every 2nd frame plus the last (`frameInterval` 1.0), every 3rd smoke frame (`interval` 6). About 0.6 MB.
  - **Labels:** `"id": "example-kitchen-fire-s1-spread-fixture"`, and a top-level `"fixture"` string: "A11 frontend fixture: fire.rooms and fire.material give D25's wood schedule for this fire; the agents, smoke and events do not react to it. Not a simulation result; never indexed or published."
  - **Fire block:** `fire.material: "wood"`, and `fire.rooms` = `SPREAD_FIXTURE_ROOMS`, the 15-entry wood list from D25's check. Each entry is `{"room", "floor", "ignite"}`:
    - on F1: R101 0.0; C1 90.0; R102, L1, R103, R104, R105, R106, R107, R108, SA1, SB1 at 180.0;
    - on F2: SA2 and SB2 at 270.0, then C2 at 360.0.
  - **Why wood:** the run ends at 200 s, and with wood twelve rooms ignite inside the replay. E opens the file with File > Open; `sync-demo.mjs` never copies it.
- [x] **Step 4: Verify Part 1:**
  - `python tools/build_examples.py` prints a `run.spread.fixture.json` line with its size.
  - `git status contracts` shows `scenario.example.json` and the new fixture; note anything else that changed in the commit body.
  - `python tools/check_all.py fire sim frontend privacy` prints `ALL OK`.
- [x] **Step 5: Commit Part 1:** `git add contracts tools/build_examples.py frontend/src/data/types.ts docs/superpowers/specs/2026-11-13-fire-evac-sim-design.md docs/superpowers/plans/2026-11-13-ws-a-integration.md && git commit -m "feat(contracts): optional fire.material and fire.rooms, with a spread fixture for the frontend"` (no attribution lines). Merge to `main` right away, and give E the file and the type names.

**Part 2 (Sat 8 PM, after D25 and C27 merge):**
- [ ] **Step 6: Backend.** `fire.material` already passes through (see Interfaces). In `backend/smoke_test.py`, the real-run check gets two twins:
  - one with `fire.material: "wood"`, whose run has `fire.material == "wood"`;
  - one with `"steel"`, whose job ends in `{"status": "error"}` naming `concrete, drywall, wood`.
- [ ] **Step 7: Material pair.**
  - `PRESETS["office"]["material_pair"] = {"room": "R143", "material": "wood"}`. R143 is the tour's first room; from it, drywall reaches 21 rooms by 400 s and wood 37.
  - `base_scenario` sets `base["fire"].setdefault("material", "drywall")`. The batch's `base` then records the material, and old `--resume` checkpoints are refused.
  - `build_jobs(..., material_pair=None)` adds one job after the pair room's baseline and propped jobs: the baseline's scenario with `fire.material` set to `wood` and id `office-R143-wood`. Seed, people, doors and fire point stay the same.
  - `run_entry` adds `material` to every entry. The wood job gets `whatIf: "material"` and the label in Produces; `write_run` names its file `run-office-R143-wood.json`.
  - `order_by_story` keeps the kinds `("base", "propped", "material")`. The wood entry follows its room's propped entry, so the tour's pairing and `findPrecomputedVariant` still find the propped run first.
  - `process_building` prints `R143, drywall -> wood: t90 <a> -> <b>, trapped <a> -> <b>, rooms on fire <n> -> <m>`.
- [ ] **Step 8: Report cards.** In `backend/llm/features.py`, import `ignition_schedule` lazily from `fire.spread`, and skip the sentence on ImportError.
  - `_batch_facts`: take the material from `base.fire.material` (default `drywall`). For each ignition room in `runs`, count the other rooms with ignite ≤ maxTime in `ignition_schedule(names.building, <base with that fire room>)`, then write the batch sentence from Produces. The first room in run order wins a tie for "at most".
  - `_run_facts`: write the run sentence from `run.fire.rooms` and `run.fire.material` when they're present.
  - `backend/smoke_test.py`:
    - a hand-made example batch (base material `wood`, runs for R101 and L1) gives `Fire spread at illustrative wood speeds: 14.0 other rooms per fire on average by 400 s, at most 14 rooms (fire in Kitchen (R101))`;
    - a drywall run with rooms at 0, 180 and 360 s gives `Fire spread at illustrative drywall speeds: 2 other rooms by 360 s`.
- [ ] **Step 9: Regenerate.** Run `python tools/build_examples.py`: `contracts/run.example.json` now carries C27's `fire.rooms` (D25's 12-room drywall list) and `"material": "drywall"`. Then delete `contracts/run.spread.fixture.json` and its writer; from here E builds on real files.
- [ ] **Step 10: Rerun the demo.** In the background: `OPENBLAS_NUM_THREADS=1 python tools/precompute_demo.py --all --thin > debug/a11-precompute.log 2>&1`.
  - Don't pass `--resume`, except to continue this same rerun.
  - It ends `OK: <n> runs, 3 batches, <x> MB`; seven of the runs are the office's.
  - **Risk:** about 2 h on the shared laptop (per the design), so start by 9 PM. If time runs short, run `--building office` first (it has the pair), then `--building example-office --building clinic`.
- [ ] **Step 11: Verify Part 2:**
  - `python -m backend.smoke_test` passes.
  - `python -c "import json; r=json.load(open('contracts/run.example.json')); print(len(r['fire']['rooms']), r['fire']['material'])"` prints `12 drywall`.
  - In `frontend/public/demo/index.json`, `office-R143-wood` has `"material": "wood"` and `"whatIf": "material"`, and `office-R143-base` has `"material": "drywall"`. Every `run-*.json` has `fire.rooms`.
  - `report-office.md` contains `illustrative drywall speeds`. The prototype predicts about `6.5 other rooms per fire on average by 400 s, at most 20 rooms (fire in SCIF OPEN OFFICE (R143))`.
  - `python tools/check_all.py` prints `ALL OK` (buildings, sim, fire, backend, tracer, frontend, privacy). Its frontend build runs `sync-demo`, which copies the new `run.example.json` into the demo folder; commit that copy with the data.
  - Put the pair's numbers (t90, trapped, rooms on fire), the run time and the folder size under this heading.
- [ ] **Step 12: Commit Part 2:**
  - First the code: `git add tools backend contracts docs/superpowers/plans/2026-11-13-ws-a-integration.md && git commit -m "feat(tools): wood-vs-drywall what-if and fire spread in report cards"` (no attribution lines).
  - Then the data: `git add frontend/public/demo && git commit -m "chore(demo): precompute rerun with simulated fire spread"` (no attribution lines).
  - **Risk:** until E handles `whatIf: "material"`, the current app reads a deep link to the wood run as a door what-if (`door ? propped`). Push the data commit to `main` only with or after E's material handling; Netlify redeploys on every push.

### Task E36 (P0 · Sat 7 PM): Ember theme and shell layout
- **Files:** Create `frontend/src/ui/{theme.ts,Menu.tsx,TopNav.tsx,AnalyticsSidebar.tsx,FloorStrip.tsx,Timeline.tsx,LegendCard.tsx,FloatingCard.tsx,LayersCard.tsx,TracerBar.tsx}`, `frontend/src/dashboard/{Overview.tsx,liveStats.ts}`, `frontend/src/model/floors.ts`; modify `frontend/package.json`, `frontend/package-lock.json`, `frontend/index.html`, `frontend/src/{index.css,App.css,App.tsx}`, `frontend/src/store/app.ts`, `frontend/src/ui/{ResultsPanel,WhatIfCard,AgentReadout,AboutOverlay}.tsx`, `frontend/src/dashboard/{EvacCurve,ExitBars,Credibility}.tsx`, `frontend/src/dashboard/curves.ts`, `frontend/src/scene/{Scene,Building,RiskOverlay,SplitView}.tsx`, `frontend/src/replay/{Agents,QueueRings,AgentCam}.tsx`, `frontend/src/tour/scenes.ts`, `frontend/scripts/qa.mjs`, `docs/superpowers/plans/2026-11-13-ws-e-frontend.md`; delete `frontend/src/ui/{TopBar,Toolbar3D,Scrubber,AgentLegend}.tsx`.
- **Interfaces:**
  - **Consumes:**
    - `App.tsx` today is a grid of:
      - `TopBar`;
      - `ScenarioPanel` (left, 300 px);
      - `<main className="center">`: `Scene` or `SplitView`, `Toolbar3D`, banner, `AgentLegend`, `AgentReadout`, `NewBuildingCard`, `TourCaption`, `ReplaySummary`;
      - `ResultsPanel` (right, 380 px);
      - `Scrubber` (bottom) and `Credits`.

      Phones swap the side panels with local `openPanel` and `.toggles`.
    - `TopBar`: brand, Building select, Replay/Tracer tabs, run tabs (`runOrder`), Demo, Share, About, Display (High contrast, Reduce motion), Open file, mode chip, spinner.
    - `Toolbar3D`:
      - Explode, and the floor select (sets `visibleFloors` and `focus: null`, bumps `fitView`);
      - Labels, and the Smoke/Fire/Heatmap/Queues/Risk map toggles with their disabled reasons;
      - Trails, the six lens buttons, the `agentColor` toggle;
      - Agent view (`pickAgent`), Split, Save PNG (`captureView`), Top view (`topView`), Overview (`fitView`).
    - `Scrubber`: `#play`; speeds 1/2/5/10; the range with Alarm, door-blocked and first-trapped marks; the Space/arrow/Home/End keys.
    - `index.css`: dark tokens (`--bg`, `--panel`, `--line`, `--line-strong`, `--text`, `--muted`, `--accent`, `--accent-line`, `--warn`, `--danger`, `--ok`) and the `data-contrast="high"` override that `useA11y` sets.
    - Dark colours that fail axe on a light page:
      - CSS: `.banner`, `.toolbar3d`, `.agentlegend`, `.tourcap`, `.about-card` (and its links, #93c5fd), `.agentreadout`, `.pane-caption`, `.weak .err`, and `.scenario button.run` (light text on #f97316, 2.8:1).
      - Charts: grid, axis and tooltip colours in EvacCurve, ExitBars and Credibility; series-coloured text in EvacCurve's run legend and Credibility's `<Legend>`.
      - Inline colours: WhatIfCard's result line (#f87171/#4ade80) and AgentReadout's visibility line.
      - In-scene `<Html>` text: Building (rooms, stairs, exits), Agents (timers, hover), QueueRings (counts), RiskOverlay (room tooltip; its dark box sets no text colour).
      - Three.js: the `Scene` background is #0b1220, and `AgentCam` restores #0b1220 after agent view.
    - The tracer's `.tr-page` is `position: fixed; inset: 44px 0 0 0` and styles itself dark (A's `tracer.css`).
    - qa selectors that move: `header.topbar` (About, Share, Display), `.topbar .tabs` (Tracer, Replay), `header.topbar label.file input`, `.toolbar3d` (Save PNG). These stay: `.results [role=tab]`, `#results-panel`, `.scenario .whatif`, `.scenario > button.run`, `main.center canvas`, `#play`.
  - **Produces:**
    - Store fields, each with a setter (`setNavOpen`, `setSidebarOpen`, `setCard`):
      - `navOpen` (false);
      - `sidebarOpen` (true; false when `(max-width: 900px)` matches at start);
      - `card: 'scenario' | 'layers' | null` (null).
    - Helpers:
      - `theme.ts`: `CANVAS`, `sceneBg(contrast)`, `useChartTheme()`;
      - `floors.ts`: `floorsByLevel(b)` and `floorName(b, id)` ("Floor 1", "Floor 2"… by level);
      - `liveStats.ts`: `useLiveStats()`.
    - Components: `TopNav`, `Menu`, `AnalyticsSidebar`, `Overview`, `FloorStrip`, `Timeline`, `LegendCard`, `FloatingCard`, `LayersCard`, `TracerBar`.
    - DOM hooks for qa: `#nav-toggle`, `#topnav`, `.ctxbar`, `#open-file`, `#analytics`, `.edgetab`, `dl.kpis`, `ul.congestion`, `ul.alerts`, `nav.floorstrip`, `footer.dock`, `#play`, `select[aria-label="Playback speed"]`, `select[aria-label="Run"]`, `section.legendcard`, `#card-scenario`, `#card-layers`, `#shell-status`.
- [ ] **Step 1: Light theme.**
  - Run `npm i lucide-react`.
  - In `index.css`, `:root` takes the §11 tokens:
    - `--canvas: #F8FAFC; --surface: #FFFFFF; --surface-2: #F1F5F9; --text: #111827; --text-2: #64748B; --border: #E5E7EB; --border-strong: #CBD5E1;`
    - `--primary: #2563EB; --primary-hover: #1D4ED8; --primary-soft: #EFF6FF; --primary-text: #1D4ED8;`
    - `--fire: #F97316; --fire-text: #C2410C; --severe: #DC2626; --caution: #F59E0B; --caution-text: #B45309; --safe: #16A34A; --safe-text: #15803D; --focus: #2563EB;`
    - `--shadow: 0 2px 8px rgba(15,23,42,.06); --r-ctl: 8px; --r-card: 12px; --s5: 24px; --fs-xl: 18px;`
    - `--font: Inter, "Inter Variable", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`.
  - The old names become aliases, so untouched rules follow: `--bg: var(--canvas); --panel: var(--surface); --line: var(--border); --line-strong: var(--border-strong); --muted: var(--text-2); --accent: var(--primary); --accent-line: var(--primary); --warn: var(--caution-text); --danger: var(--severe); --ok: var(--safe-text); --radius: var(--r-ctl)`.
  - Inter is named first in `--font` but isn't bundled: the plan's global rule is "no web fonts", and lucide-react is the only new package. Machines without Inter get system-ui.
  - Contrast rules (axe, WCAG AA, measured):
    - `--text-2` passes on `--surface` (4.76:1) and `--canvas` (4.55:1), but fails on `--surface-2` (4.34:1) and `--primary-soft` (4.37:1). Text on those two surfaces uses `--text` only.
    - Coloured text uses a `-text` token (each about 5:1 on white). `--fire`, `--caution` and `--safe` are for fills only.
    - White on `--primary` is 5.17:1.
  - High contrast (`:root[data-contrast="high"]`) redefines the new tokens:
    - `--canvas`, `--surface` and `--surface-2` #000; `--text` #fff; `--text-2` #e5e5e5; `--border` and `--border-strong` #fff;
    - `--primary` #0040c0; `--primary-soft` #000; `--primary-text` #ffd400;
    - `--fire-text` #ffb37a; `--severe` #ff6b6b; `--caution-text` #ffd400; `--safe-text` #4ade80; `--focus` #ffd400; `--shadow` none.

    Today's high-contrast rules stay. The new surfaces (`.sidebar`, `.topnav`, `.navtoggle`, `.edgetab`, `.dock`, `.card`, `.legendcard`, `.kpi`, `.floorstrip button`) join the 2 px white border rule.
  - `theme.ts`:
    - `CANVAS = '#F8FAFC'`;
    - `sceneBg(contrast)` returns '#000000' or `CANVAS`;
    - `useChartTheme()` returns `{grid: '#E5E7EB', axis: '#64748B', now: '#111827', tipBg: '#FFFFFF', tipBorder: '#E5E7EB'}`, or in high contrast `{grid: '#333333', axis: '#FFFFFF', now: '#FFD400', tipBg: '#000000', tipBorder: '#FFFFFF'}`.
  - In `index.html`, the title becomes "Ember: fire evacuation simulator".
- [ ] **Step 2: Restyle what stays.** Every dark colour listed under Consumes moves to tokens.
  - **Controls:**
    - Buttons sit on `--surface` with a `--border-strong` border and `--r-ctl`.
    - `button.on` and primary buttons (`.run`, `.demo`, the About dialog's first button) are `--primary` with white text. The orange Run button becomes primary blue, because white or near-white on orange fails contrast.
    - Focus: `outline: 2px solid var(--focus); outline-offset: 2px`.
    - Selects and inputs: `--surface`, a `--border-strong` border, 8 px radius. Ranges: `accent-color: var(--primary)`.
  - **Cards:**
    - `.about-card`, `.sharecard`, `.newbuilding`, `.agentreadout`, `.pane-caption` and `.tourcap`: `--surface`, a 1 px `--border`, `--r-card` and `--shadow`.
    - `.banner` and `.aboutnote`: #FFFBEB with a #F59E0B border and #92400E text.
    - `.about-card a` uses `--primary-text`; `.weak .err` uses `--severe`.
  - **Coloured text becomes classes:** `.better { color: var(--safe-text) }`, `.worse { color: var(--severe) }`, `.caution { color: var(--caution-text) }`. WhatIfCard's result line and AgentReadout's visibility line use them.
  - **Charts** (EvacCurve, ExitBars, Credibility):
    - Grid, axis, current-time line and tooltip colours come from `useChartTheme()`.
    - `RUN_COLORS = ['#2563EB', '#C2410C', '#7C3AED', '#15803D', '#BE185D', '#A16207']`.
    - EvacCurve's run legend and Credibility's `<Legend formatter>` write labels in `var(--text)` after a colour swatch, so no text depends on a series colour.
    - A click on EvacCurve seeks the clock to the clicked second, using `activeLabel` from the click payload; nothing happens when it is absent (design.md §8).
  - **In-scene labels** move from inline styles to classes:
    - `.l3d`: `--text`, 11 px, `text-shadow: 0 0 3px var(--canvas)` (Building room labels). `.l3d.stair` uses `--fire-text`, `.l3d.exit` uses `--safe-text`, and `.l3d.timer` uses `--caution-text` in monospace (Agents).
    - `.l3d.count`: white on a #111827 pill with 8 px radius (QueueRings).
    - `.tip3d`: `--surface`, `--border`, `--text` (the Agents hover card and RiskOverlay's room tooltip).
  - **Scene:**
    - The `Scene` background is `sceneBg(contrast)`.
    - `AgentCam` restores `sceneBg(useA11y.getState().contrast)` instead of #0b1220.
    - Agents' lens `DIM` becomes #CBD5E1.
  - `SplitView`'s container class becomes `.splitview`, because `.split` collides with `.credits.split`.
  - `AboutOverlay`'s heading becomes "Ember"; the rest of its copy stays.
  - Afterwards, grep `App.css` and the `.tsx` files for hex colours. Anything left must be a three.js colour, or a fill and text pair that passes on its own.
- [ ] **Step 3: Shell grid.**
  - **Replay view `.app`:**
    - `height: 100dvh`, `grid-template-columns: var(--sb-col) minmax(0, 1fr)`, `grid-template-rows: minmax(0, 1fr) auto`, areas `'side center' 'dock dock'`.
    - `--sb-col` is 344px, or 0px with `.sb-closed`.
    - Font `var(--font)` at 14 px, background `--canvas`.
    - Add `[hidden] { display: none !important }`, because author `display` rules would override the `hidden` attribute.
  - **Children, in order:**
    - the skip link;
    - `TopNav` (a fixed overlay);
    - `AnalyticsSidebar` (a card, margin `16px 0 12px 16px`);
    - `main.center`: `Scene` or `SplitView` inside `ErrorBoundary`, the banner, the loading cover, `LegendCard` and the right rail, the open card, `AgentReadout`, `NewBuildingCard`, `TourCaption`, `ReplaySummary`;
    - `footer.dock` (a card, margin `0 16px 12px`): `FloorStrip`, then `Timeline`, then `Credits` on one 11 px line;
    - `ClockDriver`, `AboutOverlay`, `ShareCard`, `PrintReport`.
  - **Under 1100 px,** `--sb-col` is 0 and the open sidebar floats over the viewer: absolute, `top: 16px; left: 16px; bottom: 12px; width: min(344px, calc(100vw - 32px))`, z-index 20.
  - **Phones (900 px and under):**
    - One column, areas `'center' 'dock'`. The viewer fills what the dock leaves.
    - The open sidebar is fixed (`inset: 8px 8px auto 8px`, `max-height: calc(100dvh - <dock height> - 16px)`) and scrolls.
    - Cards become sheets above the dock: `left: 8px; right: 8px`, max-height 60dvh.
    - `phone`, `openPanel` and `.toggles` go away.
  - **Inside `.center`:**
    - `.banner` sits at top 36 px, centred, max-width 720 px.
    - `.agentreadout` sits top centre, under the chevron.
    - `LegendCard` sits at the top right (16 px).
    - The scenario card sits at the top left (16 px, 340 px wide). The layers card sits left of the right rail.
    - While `navOpen`, the banner and the cards start below the nav.
    - `.tourcap` stays at the bottom centre.
  - **Tracer view:**
    - `TracerBar` is a 44 px `header.topbar`: flame mark, "Ember" as `h1.brand`, "Tracer", a "Back to 3D replay" button (`setView('replay')`), and the mode chip.
    - It sits above `TracerPage`. `.app.tracing` keeps today's rows (`44px 1fr`), because `.tr-page` assumes a 44 px bar.
- [ ] **Step 4: TopNav and menus.**
  - **`button#nav-toggle.navtoggle`:**
    - A 56 × 24 px tab on `--surface`, fixed at the centre of the top edge, with a 12 px bottom radius, `--shadow` and Lucide `ChevronDown`. While the nav is open, it sits on the nav's bottom edge with `ChevronUp`.
    - `aria-label` and `title` read "Expand navigation" or "Collapse navigation". It has `aria-expanded` and `aria-controls="topnav"`. Focus stays on it when it flips.
  - **`div#topnav.topnav`:**
    - Always in the DOM, `hidden` while collapsed; its children render only when open.
    - A fixed overlay at the top: full width less 16 px margins, `--surface`, `--r-card`, `--shadow`. It never resizes the canvas.
    - Row 1, `.menubar` (44 px): `<nav aria-label="Menus">` with six menu buttons. On the right: the Building select (`aria-label="Building"`, today's option text), the mode chip (today's title), "Demo"/"Stop demo" (primary) and "About".
    - Row 2, `div.ctxbar[role=toolbar][aria-label="Tools"]` (52 px).
  - **`input#open-file`:** `type=file`, `accept=".json,application/json"`, `aria-label="Open file"`, `tabIndex={-1}`, class `sr-only`. It sits outside `#topnav`, so it exists while the nav is collapsed. "Open file" items call its `click()`, and its `onChange` calls `openFile`.
  - **`Menu.tsx`** uses the menu-button pattern. It has no `role=menubar`, which axe would want filled with menuitems.
    - Trigger: `button[aria-haspopup=menu][aria-expanded]`, with `aria-controls` only while open.
    - Menu: `div[role=menu][aria-label=<name>]` holding `button[role=menuitem|menuitemcheckbox|menuitemradio]`. The last two carry `aria-checked`. A radio set sits in `div[role=group][aria-label=…]` with an `aria-hidden` visible caption.
    - Opening focuses the first item. ↑/↓/Home/End move. ←/→ open the neighbouring menu. Escape closes and refocuses the trigger. Tab and outside clicks close.
    - Handled keys call `stopPropagation()`, so the Timeline and tour shortcuts on `window` don't fire.
    - Picking an item closes the menu; the nav stays open.
  - **Where each TopBar and Toolbar3D control goes.** Nothing is dropped.

    | Today | Ember |
    | --- | --- |
    | Brand "Fire evacuation sim" | Sidebar header "Ember" (Step 5); TracerBar |
    | Building select | Menubar, right |
    | Replay / Tracer tabs | File > Trace a floor plan; TracerBar "Back to 3D replay" |
    | Run tabs | Timeline "Run" select |
    | Demo / Stop demo | Menubar, right; Simulation > Guided demo |
    | Share | Toolbar "Share"; File > Share link and QR code… |
    | About | Menubar, right |
    | Display: High contrast, Reduce motion | Settings > High contrast, Reduce motion |
    | Open file | Toolbar "Open file"; File > Open file… |
    | Mode chip; spinner | Menubar, right; Timeline |
    | Explode | Layers card "Floor gap" |
    | Floor select | FloorStrip |
    | Labels | View > Room labels; Layers card |
    | Smoke, Fire, Heatmap, Queues, Risk map | Layers card (same disabled reasons) |
    | Trails; lens buttons | Layers card ("Highlight a profile") |
    | Color: status/profile | LegendCard switch "Color by type"; Settings > Color people by type |
    | Agent view | Toolbar "Agent view"; View > Agent's-eye view |
    | Split | Toolbar "Split"; View > Split screen |
    | Save PNG | Toolbar "Save PNG"; File > Save 3D view as PNG |
    | Top view; Overview | Toolbar "Top view", "Reset camera"; View > Top view, Reset camera |

  - **Menu items** (exact copy):
    - File: Open file…; Trace a floor plan; Share link and QR code…; Save 3D view as PNG; Print report… (switches the sidebar to Report and calls `setPrintView(true)`).
    - Edit: Set fire… (`card: 'scenario'`, `placing: true`); Place fire by clicking (checkbox for `placing`).
    - View: Layers…; Room labels (checkbox); Split screen (checkbox, disabled under 2 runs); Agent's-eye view; Top view; Reset camera; Focus mode.
    - Simulation: Play or Pause; Restart; the radio group "Playback speed" (0.25×, 0.5×, 1×, 2×, 4×, 10×); Scenario setup…; Run simulation (`card: 'scenario'`, then `runScenario(draft)`); Guided demo or Stop guided demo.
    - Analysis: the radio group "Analytics" (Overview, Risk, Report, Credibility; each sets `resultsTab` and `sidebarOpen: true`); What-if… (`card: 'scenario'`, then scrolls `.scenario .whatif` into view and focuses its door select).
    - Settings: High contrast; Reduce motion; Color people by type (all checkboxes).
  - **Toolbar buttons:**
    - Each has a Lucide icon (18 px, stroke 1.75) and a text label. `aria-label` is always set; the text labels hide under 1280 px.
    - In order: Open file (`Upload`), Set fire (`Flame`), Run simulation (`Play`), Layers (`Layers3`), Top view (`Camera`), Reset camera (`Maximize2`), Split (`Columns2`), Agent view (`PersonStanding`), What-if (`GitCompare`), Save PNG (`ImageDown`), Share (`Share2`).
    - Disabled states and titles carry over from Toolbar3D: Split under 2 runs; Agent view and Save PNG in split; Save PNG on private buildings.
    - If the installed lucide-react lacks an icon name, use the nearest one.
  - **Focus mode** sets `navOpen: false` and `sidebarOpen: false`, and moves focus to `#nav-toggle`.
- [ ] **Step 5: Analytics sidebar.**
  - `aside#analytics.sidebar[aria-label="Analytics"]` is always in the DOM and `hidden` while collapsed. Its body renders only when open.
  - **Header:**
    - `h1.brand`: Lucide `Flame` in `--fire` (`aria-hidden`), then "Ember".
    - `p.brand-sub`: the building name.
    - A `ChevronsLeft` button: `aria-label="Hide analytics"`, `aria-expanded="true"`, `aria-controls="analytics"`.
  - **Collapsed:** `button.edgetab` (`aria-label="Show analytics"`, `aria-expanded="false"`, the same title, `ChevronsRight`), 28 × 64 px at the left edge, vertically centred. Collapsing focuses the edge tab; expanding focuses "Hide analytics".
  - **Announcements:** `p#shell-status.sr-only[role=status]` announces "Navigation expanded", "Navigation collapsed", "Analytics shown" and "Analytics hidden".
  - **Body:** `<ResultsPanel/>`, which keeps `.results`, the tablist, `#results-panel` and the disclaimer foot. The tab labels become Overview, Risk, Report and Credibility. The ids stay `results|risk|report|cred` (store, deep links, qa).
  - **`useLiveStats()`** (`dashboard/liveStats.ts`):
    - One computation per active run and frame, shared by its readers, driven by `useThrottledT(500)`.
    - It counts every agent on every floor and never reads `visibleFloors`.
    - It returns `out`, `inside`, `trapped`, `waiting`, `n`, the per-target queue counts (`queueCounts` at `nearestIndex`, over `queueTargets`), the queued people per floor, and the alerts.
  - **Overview tab** (`dashboard/Overview.tsx`):
    - `dl.kpis` holds 2 × 2 white cards (`div.kpi > dt, dd, dd.sub`). Icons are `aria-hidden`. Values are 22 px semibold; subs are 12 px in `--text-2`.
      - Evacuated (`DoorOpen`, `--safe`): "78%", sub "124 of 160 out". Out means exitT < t, as in `ReplaySummary`.
      - Remaining (`Users`): "36", sub "3 trapped · 2 waiting".
      - Chokepoints (`TriangleAlert`, in `--severe` when above 0): the doors and stairs with 5 or more people queued, sub "with 5+ queued".
      - Evacuation time (`Clock`): `run.metrics.t90` as m:ss, sub "90% out · everyone by m:ss" (from t100) or "90% out · not everyone out". It reads "—" when t90 is null.
      - With no run, every value reads "—" with the sub "Load a run".
    - "Evacuation progress": `<EvacCurve/>`.
    - "Congestion by floor": `ul.congestion`, one row per floor by level. Each row has `floorName`, a decorative bar (queued / max(10, largest)) and "12 queued". When empty: "No queues at m:ss."
    - "Chokepoint alerts (n)": `ul.alerts`, up to 5 targets with 5 or more queued, largest first. Each alert is a button:
      - icon `TriangleAlert`, in `--severe` at 15 or more, else `--caution`;
      - title "Floor 2 · Stair SA door": doors through `doorLabels`, stairs as "Stair <group>", never a raw id;
      - reason "12 people queued within 2 m · critical" (15 or more) or "· warning", then `ChevronRight`;
      - critical rows on #FEF2F2 with a #FECACA border, warning rows on #FFFBEB with a #FDE68A border, text in `--text`;
      - a click calls `flyTo(target.floorId, [cx, cy])`, which shows the single floor and the pulse ring.

      When empty: "No chokepoints at m:ss."
    - "More results": today's Exit use (ExitBars), Run (RunStats) and AccessStats.
    - The 5 and 15 thresholds match QueueRings' ring colours.
- [ ] **Step 6: Floor strip, timeline, legend and cards.**
  - **`FloorStrip`** (`nav.floorstrip[aria-label="Floors"]`, horizontal scroll, `scroll-snap-type: x proximity`):
    - Buttons: "Whole building" (`Layers` icon), then one per floor by level, labelled with `floorName`.
    - Each floor button carries a 64 × 36 SVG silhouette of its walkable outer rings (`aria-hidden`, stroke #94A3B8, fill `--surface-2`). An orange dot marks the active run's fire on its floor. Phones drop the silhouettes.
    - `aria-pressed` marks the active item: Whole building when `visibleFloors` is null, Floor N when it is `[id]`.
    - The active look: a 2 px `--primary` border, `--primary-soft` fill and a `--primary-text` label.
    - A click does what Toolbar3D's select did: sets `visibleFloors` and `focus: null`, and bumps `fitView`.
  - **`Timeline`** replaces Scrubber and keeps its keys, marks and `aria-valuetext`:
    - `button#play`: 40 px round, `--primary`, a Play/Pause icon, `aria-label` "Play" or "Pause", `aria-keyshortcuts="Space"`;
    - Restart (`RotateCcw`, `aria-label="Restart"`): seeks to 0 and plays;
    - the time "1:10 / 3:00" (m:ss), then the scrubber;
    - `select[aria-label="Playback speed"]`: 0.25×, 0.5×, 1×, 2×, 4×, 10×;
    - `select[aria-label="Run"]`: the `runOrder` labels; a change calls `switchRun`;
    - the loading spinner (`role=status`, `aria-label="Loading"`).

    Phones wrap the scrubber onto a second row.
  - **`LegendCard`** replaces AgentLegend. It is `section.legendcard[aria-label="Legend"]` at the top right, with a "Hide legend"/"Show legend" button (`aria-expanded`). Each row is a swatch plus a label:
    - people in the current scheme (today's status items, or the profile names);
    - `button[role=switch][aria-checked]` "Color by type" (sets `agentColor: 'profile'`);
    - the four door states; "Queue at a door (ring size = people)"; "Fire"; "Smoke".
  - **Right rail,** under the legend: `button[aria-label="Layers"]` (`Layers3`, `aria-expanded`) sets `card: 'layers'`.
  - **`FloatingCard`:** `section.card#card-<id>[aria-label=<title>]`, with an `h2` title (14 px) and a close button (`X`, `aria-label="Close <title>"`).
    - It is non-modal with no focus trap, and only one card is open at a time.
    - Opening focuses its first control. Escape or close returns focus to the opener.
    - App renders the open card: `scenario` titled "Fire and scenario" holds `<ScenarioPanel/>` unchanged (it still ends with `<WhatIfCard/>`), with `max-height: calc(100% - 32px)` and scrolling.
    - `layers` titled "Layers" holds `LayersCard`:
      - Floor gap (`explode`), Room labels, Room colors (`layers.rooms`);
      - Smoke, Fire, Heatmap, Queues and Risk map, with Toolbar3D's checked, disabled and title logic unchanged;
      - Trails;
      - "Highlight a profile": the six lens buttons, with the same toggling.
- [ ] **Step 7: Tour and deep links.**
  - In `scenes.ts`:
    - `resetStage()` also sets `navOpen: false`, `card: null`, and `sidebarOpen` (true at 901 px and wider, false below), so scenes 5 and 6 show their tabs.
    - `tourSpeed` picks from `[2, 4, 10]`, because 5× is no longer a speed.
  - In `restoreLink`, a link with `tab` also sets `sidebarOpen: true`. This replaces the startup special case that opened the right panel on phones.
  - The hash format doesn't change.
- [ ] **Step 8: qa.**
  - **Helper:** `nav(page, open)` clicks `#nav-toggle` when its `aria-expanded` differs. Every step leaves the nav collapsed.
  - **Moved selectors:**
    - `about`: open the nav, then click the menubar's "About".
    - `share`: `.ctxbar` "Share". `save-png`: `.ctxbar` "Save PNG".
    - `tracer`: File > "Trace a floor plan", then the TracerBar's "Back to 3D replay".
    - Contrast shot: Settings > "High contrast", then the same item again to turn it off.
    - `open-N`: `#open-file`.
    - `whatif-static` and `live-fallback` set `card: 'scenario'` first (`__app.setState`).
  - **New step `shell`,** right after `load`. Report a problem unless all of these hold:
    - In the default state, `#nav-toggle` is named "Expand navigation" with `aria-expanded="false"`, `#topnav` is hidden, "Hide analytics" is visible, and `#play` is visible inside `footer.dock`.
    - The speed select's options read 0.25×, 0.5×, 1×, 2×, 4×, 10×. Choosing 4× sets the `__clock` speed to 4; then set it back to 1.
    - The floor strip's buttons read "Whole building", "Floor 1", "Floor 2", with Whole building pressed, and `section.legendcard` is visible. Shot `shell.png`.
    - Nav: after one toggle click, its name is "Collapse navigation" and the six menus (File, Edit, View, Simulation, Analysis, Settings) exist. View opens a `role=menu` (shot `nav-view.png`). Escape closes it and focuses the View button.
    - Focus mode: View > Focus mode leaves `navOpen` and `sidebarOpen` false and `main.center` at least 1400 px wide (shot `focus-mode.png`). "Show analytics" restores the sidebar.
    - Floor strip: "Floor 2" sets `visibleFloors` to `['F2']` and shows it pressed (shot `floor-2.png`, with a blank check). "Whole building" sets null.
    - Alerts: paused at 60 s, if `ul.alerts button` exists, clicking the first leaves one floor in `visibleFloors` (shot `alert-fly.png`). Otherwise add the line "alerts: none at 60 s", which isn't a problem.
  - **New step `phone`,** in a 390 × 844 context with the same init script:
    - The sidebar starts collapsed ("Show analytics" is present).
    - `#play` and the floor strip are visible, and the strip's `scrollWidth >= clientWidth`. Shot `phone.png`.
    - Opening the sidebar overlaps `main.center`'s box instead of narrowing it. Shot `phone-sidebar.png`.
    - Run axe on `.app`.
  - **`a11y`:** also run axe on `.app` with the nav open and the View menu open, with `card: 'scenario'`, with `card: 'layers'`, and in focus mode.
  - **`deeplink`:** p2 must also reach `sidebarOpen === true`.
- [ ] **Step 9: Verify.**
  - `npm run build` passes with no type errors.
  - `npm run qa` (shim) exits 0 and prints `qa ok: <n> screenshots in frontend/qa/`; every `axe …` line ends in `0 violations`. Then check the screenshots:
    - `qa/shell.png` has the mockup's layout: the analytics card at the left, the chevron at the top centre, the floor strip and timeline at the bottom, and the legend at the top right.
    - `qa/nav-view.png` shows the open menu above the toolbar row.
    - `qa/contrast.png` is black and white with yellow focus.
    - `qa/tracer.png` looks as before.
    - `qa/scene4.png` shows the split what-if with its caption.
    - `qa/phone-sidebar.png` shows the sidebar over the viewer.
  - `python tools/check_all.py frontend privacy` ends with `ALL OK`.
  - Manual, with `npm run dev` at 1440 × 900:
    - `?demo` plays all six scenes in about 3 minutes, and Risk, Report and Credibility show on cue.
    - The keyboard alone can expand and collapse the nav, open every menu, hide and show analytics, and play.
- [ ] **Step 10: Commit** `git add frontend docs/superpowers/plans/2026-11-13-ws-e-frontend.md && git commit -m "feat(frontend): Ember light theme and shell (top nav, analytics sidebar, floor strip, timeline, legend)"` (no attribution lines).

### Task E37 (P0 · Sat 9 PM): Building look, floor views, visibility and agent colors
- **Files:** Create `frontend/src/scene/usePlace.ts`, `frontend/src/ui/VisibilityCard.tsx`; modify `frontend/src/scene/{geometry.ts,Building.tsx,Scene.tsx,CameraRig.tsx,FirePicker.tsx,RiskOverlay.tsx}`, `frontend/src/replay/{Agents,Trails,AgentCam,Fire,Smoke,Heatmap,QueueRings}.tsx`, `frontend/src/store/app.ts`, `frontend/src/ui/{TopNav,FloorStrip,LegendCard,LayersCard}.tsx`, `frontend/src/dashboard/{WeakSpots.tsx,curves.ts}`, `frontend/src/model/link.ts`, `frontend/src/App.tsx`, `frontend/src/tour/scenes.ts`, `frontend/src/App.css`, `frontend/scripts/qa.mjs`, `docs/superpowers/plans/2026-11-13-ws-e-frontend.md`.
- **Interfaces:**
  - **Consumes:**
    - From E36: FloorStrip (writes `visibleFloors`), the View and Settings menus, `card`, the right rail, LegendCard's "Color by type" switch (`agentColor`), and LayersCard ("Floor gap", "Room colors").
    - `floorY(floor, explode) = elevation + explode × level × 4` at every per-floor placement:
      - Building (the floor group);
      - Agents (body, LLM ring, timers, hover), Trails, AgentCam;
      - Fire, Smoke, Heatmap, QueueRings (rings and labels);
      - RiskOverlay (fills; its room tooltip uses `floorY(selFloor, 0)` and so ignores explode);
      - FirePicker (pick planes and the ghost marker; clicks read `fromWorld(e.point)`);
      - CameraRig (the `buildingBounds` fit and the flyTo goal).
    - `visibleFloors` (null means all) filters every layer. `flyTo` sets `[floorId]`, and qa's `fixes` step checks for one floor. WeakSpots' "Show all floors" sets null.
    - `Walls`:
      - one InstancedMesh per floor: 0.15 m boxes on every walkable ring segment, #cbd5e1, full floor height, rising with `reveal`;
      - the walkable outer ring also traces interior walls (example F1: 108 points for 12 rooms);
      - `FlatBatch` fills rooms by `ROOM_COLORS` when `layers.rooms` is on (the default).
    - `explode` starts at 0. Link `x` is written only when non-zero, `resetStage` sets 0, and scene 2 lifts to 0.5.
    - Agents: `agentColor` (`'status' | 'profile'`), `STATUS_COLORS` (5 tints), `PROFILE_COLORS` (not colorblind-safe), and colour keys `k` cached in `keys`.
    - Fire.tsx radius is `0.3 + 0.9·√(kW/1500)`, its light `2 + 6·min(1, kW/1500)`. Smoke.tsx's alpha byte is `min(200, d·1.8)`, decoded once per frame change.
  - **Produces:**
    - Store:
      - `viewMode: 'stacked' | 'single' | 'side' | 'ghost'` ('stacked') and `focusFloor: string | null` (null), with `setViewMode(mode, floor?)`;
      - `colorBy: 'status' | 'type'` ('status'), which replaces `agentColor`;
      - `fireGlow` (1) and `smokeOpacity` (1);
      - `card` gains 'visibility';
      - `DEFAULT_EXPLODE = 0.6`.
    - `geometry.ts`: `ViewMode`, `GHOST = 0.15`, `floorPlace`, `toPlaced`, `fromPlaced`, `classifyWalls`. Also `usePlace()`.
    - `TYPE_COLORS`, the new `STATUS_COLORS`, `VisibilityCard`, and the link parameter `v`.
- [ ] **Step 1: View modes in the store.**
  - `setViewMode(mode, floor?)` always clears `focus`, bumps `fitView` and writes `visibleFloors`:

    | Mode | `focusFloor` | `visibleFloors` |
    | --- | --- | --- |
    | stacked | null | null |
    | single | `floor`, else the current `focusFloor`, else the active run's fire floor, else the lowest floor | `[focusFloor]` |
    | side | null | null |
    | ghost | chosen as for single | null |
  - `flyTo` sets `viewMode: 'single'` and `focusFloor`, with today's `visibleFloors: [floorId]` and focus. `setBuilding` resets to stacked.
  - `visibleFloors` stays the list of drawn floors that every layer already filters by, but nothing writes it directly any more. FloorStrip, WeakSpots' "Show all floors" (stacked), `restoreLink` and `resetStage` call `setViewMode`.
  - `explode` starts at `DEFAULT_EXPLODE` (0.6), because opaque slabs at 0 hide the lower floors. `resetStage` uses it, and scene 2 lifts to 1.0.
  - `layers.rooms` defaults to false, in the store and in `DEFAULT_LAYERS` (`scenes.ts`).
  - Rename `agentColor` to `colorBy`, and its value 'profile' to 'type', in Agents, LegendCard and TopNav. No link or tour reads it.
- [ ] **Step 2: Placement.**
  - **`geometry.ts`:**
    - `floorPlace(b, f, mode, explode)` returns `{dx, y}`:
      - stacked, single and ghost: `{dx: 0, y: floorY(f, explode)}`;
      - side: `{dx: rank × (W + gap), y: 0}`, where rank is the floor's position by level, W is the x extent of `buildingBounds(b)`, and gap is `max(4, 0.15 × W)` m.
    - `toPlaced(p, x, y, h = 0)` returns `[x + p.dx, p.y + h, -y]`. `fromPlaced(p, v)` returns `[v.x - p.dx, -v.z]`.
    - `buildingBounds(b, floorIds?, explode = 0, mode = 'stacked')` places each floor with `floorPlace`.
  - **`usePlace()`** (`scene/usePlace.ts`) subscribes to `building`, `viewMode` and `explode`, and returns `(f) => {dx, y}`. Per-frame code calls `floorPlace` with `useApp.getState()` instead.
  - **Every placement listed under Consumes uses it:**
    - Building's floor group gets `position={[dx, y, 0]}`. So does RiskOverlay's group, and its tooltip now follows explode.
    - The others swap `toWorld(x, y, floorY(f, explode) + h)` for `toPlaced(place(f), x, y, h)`.
    - QueueRings' and Trails' redraw keys add `viewMode` and `focusFloor`.
    - FirePicker puts each pick plane at its floor's `dx` and reads clicks through `fromPlaced`.
    - CameraRig fits with the current mode (overview, top view, building load) and adds `dx` to flyTo's goal.
  - **Ghost:** `alpha` is `GHOST` for every floor except `focusFloor` when `viewMode === 'ghost'`, and 1 otherwise.
    - Walls, glass, rails, slab, stair cores, smoke, heatmap and the fire sphere multiply their opacity by alpha. Remount a material (`key`) when alpha flips, so three.js picks up `transparent` and `depthWrite`.
    - Agents on ghost floors are drawn #CBD5E1.
    - Labels, waiting timers, queue rings, trails and risk fills on ghost floors are hidden.
    - FirePicker listens on the focus floor only.
  - **Side:** all floors lie flat at y 0 in a row along +x, ordered by level. `setViewMode('side')` bumps `fitView`, so the camera frames the row.
- [ ] **Step 3: Building look (reference render).**
  - **`classifyWalls(floor)`** returns `{interior, exterior}`, memoized per floor:
    - Take the segments of every walkable ring (`ringSegments`).
    - Probe 0.6 m to each side of a segment's midpoint, along its normal.
    - A segment is exterior when one probe is inside the walkable area (inside `outer`, not in a hole) and the other is outside every room polygon and outside the walkable area.
    - Hole rings are always interior. A floor with no rooms makes every outer segment exterior.
  - **Interior walls:** an InstancedMesh with `meshStandardMaterial` #F1F5F9, roughness 0.9, `min(1.4, floor.height)` m tall. This cutaway keeps people visible; full-height walls hide the rooms from the isometric camera.
  - **Glass (exterior walls):** an InstancedMesh at full `floor.height`, #BFDBFE, opacity 0.28, `depthWrite={false}`, roughness 0.1, metalness 0.1. A #94A3B8 top rail (a 0.08 m box) runs along the top of each glass segment.
  - **Slab:** the walkable outer ring with its holes as one `ExtrudeGeometry`, 0.15 m thick, with its top face on the floor plane; #E2E8F0, roughness 1. The narrow notches along interior walls stay hidden under the wall boxes.
  - **Stairs:** today's flat footprint, plus a translucent core: the stair polygon extruded `floor.height`, #FDBA74, opacity 0.22, `depthWrite={false}`.
  - **Colours:** `DOOR_COLORS` become open #2563EB, closed #1E3A8A, propped #0891B2 and blocked #DC2626. Exits are #16A34A. The legend follows.
  - **No room fills by default** (`layers.rooms` off). The Layers card's "Room colors" turns today's type fills back on. The risk overlay is unchanged and still colours rooms.
  - **Room labels:** the name (or id) as `.l3d`, plus the room type on a second muted line when the name doesn't already contain it.
  - **Floor tags:** one `<Html>` pill "Floor N" (`.floortag`, pointer-events none) at each drawn floor's front-left corner. The focus floor's pill (single or ghost) is `--primary` with white text.
  - The wall rise (`reveal`) scales the interior walls, glass and rails; the slab doesn't rise.
  - **Lights (`Scene`):** a `hemisphereLight` (#FFFFFF, #CBD5E1, 1.0) replaces the ambient light. The directional light stays at [20, 40, 20], intensity 0.9.
- [ ] **Step 4: View controls.**
  - View menu: the radio group "Floor view" with Stacked, Single floor, Side by side and Ghost (`setViewMode`). Side by side and Ghost are disabled for one-floor buildings.
  - FloorStrip:
    - "Whole building" switches to stacked. In side mode it is already active.
    - "Floor N" isolates the floor (single). In ghost mode it moves the ghost focus instead.
    - The active item is `focusFloor`'s in single and ghost, and Whole building otherwise.
  - Layers card: "Floor gap" is disabled in single and side.
- [ ] **Step 5: Visibility card.** `card: 'visibility'`, titled "Fire and smoke visibility".
  - **Entry points:** the right rail (`Eye`, `aria-label="Fire and smoke visibility"`), the toolbar ("Visibility", `Eye`), and View > Fire and smoke visibility….
  - **Checkboxes:** Fire (`layers.fire`); Smoke (`layers.smoke`, disabled with "This run has no smoke frames", as in the Layers card).
  - **Ranges:** "Fire glow and size" (`fireGlow`, 0–2, step 0.1, readout "1.0×"); "Smoke opacity" (`smokeOpacity`, 0–1.5, step 0.1, readout "100%").
  - **Buttons:**
    - "High visibility" (`aria-pressed` while its values hold) sets `fireGlow: 2` and `smokeOpacity: 1.5`, and turns fire and smoke on.
    - "Reset" sets 1 and 1.
  - **Note:** "Changes the picture only, never the simulation."
  - **Fire.tsx** (reads in `useFrame`): radius × (0.6 + 0.4 × fireGlow), light intensity × fireGlow, `emissiveIntensity` 0.5 + fireGlow.
  - **Smoke.tsx:** the alpha byte is `min(235, round(d × 1.8 × smokeOpacity))`. A change re-uploads the current frame.
- [ ] **Step 6: Agent colors.**
  - **`STATUS_COLORS`** (the default scheme):
    - moving and in a stairwell: #16A34A (stairwell agents stay at 0.6 scale);
    - not moving yet and waiting for help: #F59E0B;
    - trapped: #DC2626.
  - **`TYPE_COLORS`:** Okabe–Ito without yellow (invisible on the slab) and vermillion (it reads as fire).
    - typical #0072B2, older #CC79A7, visitor #56B4E9, cane #009E73, walker #E69F00, wheelchair #000000.
    - They replace `PROFILE_COLORS` and `PROFILE_HEX`, so ExitBars and AccessStats follow.
  - In type mode every drawn agent takes its type colour, whatever its status.
  - **Cues besides colour,** in both schemes:
    - a red ring under trapped agents (#DC2626, `ringGeometry` 0.45–0.62, one InstancedMesh like the LLM ring);
    - the seconds label over waiting agents (as today);
    - smaller stairwell agents;
    - the hover tooltip, which names profile and status.
  - `keys` reset when `colorBy`, `viewMode` or `focusFloor` changes.
  - **LegendCard:**
    - Status rows: "Moving" (green), "In a stairwell" (green, small), "Delayed or waiting" (amber), "Trapped" (red, with a ring).
    - Type rows: the six profile names in their colours, plus "Trapped (red ring)".
    - Footnote: "People who are out leave the view."
    - `button[role=switch]` "Color by type", with `aria-checked` when `colorBy === 'type'`. Settings > Color people by type mirrors it.
- [ ] **Step 7: Deep links and tour.**
  - `link.ts`:
    - New parameter `v`: 'side' or 'ghost'.
    - `readLinkState` writes `v` for those two modes, and `f` = `focusFloor` in single and ghost.
    - `x` is written whenever explode differs from `DEFAULT_EXPLODE`.
  - `restoreLink`: `v=side` restores side, `v=ghost` restores ghost on `f`, and `f` alone restores single.
  - `resetStage`: `setViewMode('stacked')`, `explode: DEFAULT_EXPLODE`, `colorBy: 'status'`, `fireGlow: 1`, `smokeOpacity: 1`.
- [ ] **Step 8: qa.**
  - **New step `views`,** after `replay-60s`, paused at 60 s:
    - For stacked, single F2, side and ghost F2 (through `setViewMode`): wait 1.5 s, take shot `view-<mode>.png`, and blank-check it.
    - Report a problem unless all of these hold:
      - `visibleFloors` is `['F2']` in single and null otherwise, and `focusFloor` is 'F2' in ghost;
      - the pressed floor-strip item is Floor 2 in single and ghost, and Whole building otherwise;
      - `dl.kpis` and `#replay-summary` read the same text in all four modes (hidden floors never change the data);
      - through the UI, View > "Side by side" sets `viewMode: 'side'` and shows `aria-checked="true"`.
  - **New step `colors`:**
    - The legend switch sets `colorBy: 'type'`.
    - The legend then lists typical, older, visitor, cane, walker, wheelchair and "Trapped (red ring)". Shot `colors-type.png`.
    - Switching back shows "Delayed or waiting".
  - **New step `visibility`:**
    - The right-rail button opens `#card-visibility`.
    - "High visibility" sets `fireGlow` to 2 and `smokeOpacity` to 1.5, with `aria-pressed="true"`. Shot `visibility-high.png`.
    - "Reset" restores 1 and 1.
  - **`deeplink`:** pages opened at `#b=<id>&v=side` and at `#b=<id>&v=ghost&f=F2` restore the mode and the focus floor.
  - **`a11y`:** also run axe with the visibility card open, and with `colorBy: 'type'`.
  - `fixes` is unchanged: `flyTo` still leaves one floor in `visibleFloors`.
- [ ] **Step 9: Verify.**
  - `npm run build` passes with no type errors.
  - `npm run qa` (shim) exits 0 with 0 axe violations. Then check the screenshots:
    - `qa/view-stacked.png` looks like the reference: light slabs, white cutaway walls, glass outside, orange stair cores, floors apart.
    - `qa/view-side.png` shows the floors in a row.
    - `qa/view-ghost.png` shows Floor 2 solid and the other floor faint.
    - `qa/colors-type.png` shows six labelled colours.
    - `qa/visibility-high.png` shows a bigger fire and denser smoke.
  - `python tools/check_all.py frontend privacy` ends with `ALL OK`.
  - Manual, with `npm run dev`: the clinic, the biggest building, stays smooth in stacked and side.
- [ ] **Step 10: Commit** `git add frontend docs/superpowers/plans/2026-11-13-ws-e-frontend.md && git commit -m "feat(frontend): walls-and-glass building, four floor views, fire and smoke visibility, agent colors by status or type"` (no attribution lines).

### Task E38 (P0 · Sat 11 PM): Spreading fire on screen and the material setting
- **Files:** Create `frontend/src/model/fireSpread.ts`, `frontend/src/replay/{BurningRooms,BlockedDoors}.tsx`; modify `frontend/src/scene/Scene.tsx`, `frontend/src/store/app.ts`, `frontend/src/model/whatif.ts`, `frontend/src/ui/{ScenarioPanel,WhatIfCard,LegendCard}.tsx`, `frontend/src/dashboard/Overview.tsx`, `frontend/src/App.tsx`, `frontend/src/tour/scenes.ts`, `frontend/src/App.css`, `frontend/scripts/qa.mjs`, `docs/superpowers/plans/2026-11-13-ws-e-frontend.md`.
- **Interfaces:**
  - **Consumes:**
    - Optional contract fields whose names A and D pinned (A11):
      - run `fire.rooms: [{room, floor, ignite}]`: the rooms that ignite before `maxTime`, with `ignite` in seconds from the run start; the ignition room burns from the start;
      - run `fire.material`;
      - scenario `fire.material`: 'concrete', 'drywall' (the default) or 'wood'.

      After A11 part 2 (the precompute rerun), every demo run carries `fire.rooms`, and the demo index gains the office pair: entries with `whatIf: "material"` and `material`.
    - The fixture `frontend/public/demo/fixtures/fire-spread.run.json`, which A creates in A11 part 1:
      - unindexed;
      - a run/v0 for one demo building, with `fire.material` and several `fire.rooms` igniting at different times.

      If it's missing, stop and report BLOCKED on A11 part 1.
    - `src/data/types.ts` is shared:
      - If A11 part 1 added these fields there, use them.
      - Otherwise read them through local types in `model/fireSpread.ts`, and never edit `src/data/`.
      - There, `DemoRun.whatIf` is typed `null | 'propped'`.
    - `findPrecomputedVariant` returns the first entry whose `whatIf` isn't null. A material entry would therefore pose as a door what-if in the static what-if, in tour scene 4 and in `restoreLink`. `nearestPrecomputedRun` and the startup pick take only `whatIf: null`.
    - `runWhatIf` in live mode: today only a refused connection or a timeout falls back. An HTTP error, a run that reports an error, or one past `pollRun`'s 180 s ends in `whatIfError`. E35 closed this gap for `runScenario`.
    - From E37: `usePlace`, `floorPlace`, `toPlaced`, `GHOST`, `fireGlow`, `layers.fire`, `visibleFloors`.
    - From E36: the scenario card (Edit > Set fire…) with `WhatIfCard` at its end, `LegendCard`, `Overview`.
    - Run events of type `door_blocked` (`door`, `t`), which the Timeline already marks.
  - **Produces:**
    - `fireSpread.ts`: `Material`, `MATERIALS`, `readSpread(run)`, `burningAt(spread, t)`, `spreadTint(ignite, t, glow)`, `materialPair(entries, buildingId)`.
    - `BurningRooms`, `BlockedDoors`, and `spreadStats` (`window.__spread` in dev and with `?qa`).
    - Store: `material` ('drywall'), `setMaterial`, `showMaterialPair()`, `whatIfNote`, `whatIfFallback`, and `LoadedRun.whatIf.material?`.
    - qa steps `fire-spread`, `material-pair` and `whatif-fallback`.
- [ ] **Step 1: Read the spread.** In `model/fireSpread.ts`:
  - `Material = 'concrete' | 'drywall' | 'wood'`. `MATERIALS` lists Concrete, Drywall and Wood; the default is drywall.
  - `readSpread(run)` returns `{rooms, material}`, or null:
    - It keeps entries with a string `room` and `floor` and a finite `ignite` ≥ 0, sorted by `ignite`.
    - It returns null when `fire.rooms` is missing or empty.
    - An unknown material reads as null.
  - `burningAt(spread, t)` returns the rooms with `ignite <= t`.
  - `spreadTint(ignite, t, glow)`:
    - The colour runs from #F97316 to #DC2626 over the 60 s after ignition; call that progress k, from 0 to 1.
    - The opacity is `min(0.85, (0.35 + 0.25k) × (0.5 + 0.5 × glow))`.
  - Never extrapolate. A room missing from `fire.rooms` never burns on screen, and a run without `fire.rooms` looks exactly as today.
- [ ] **Step 2: Burning rooms.** `replay/BurningRooms.tsx` mounts in `Scene` after `Fire`, keyed by `runKey` like the other layers. It draws only while `layers.fire` is on.
  - **Tints:**
    - For each spread room on a drawn floor: its polygon (`ShapeGeometry`, built once per run), 0.05 m above the floor through `toPlaced`, with a transparent `meshBasicMaterial` and `depthWrite={false}`.
    - In `useFrame`, a tint is visible once `ignite <= t`. It takes its colour and opacity from `spreadTint` with `fireGlow`, multiplied by `GHOST` on ghost floors.
    - A room id that the building lacks is skipped, with one `console.warn` per run.
  - **Markers:**
    - One InstancedMesh of cones (radius 0.35, height 0.9, emissive #F97316) at `insidePoint(polygon)`, 0.45 m up.
    - Each cone is scaled by `0.6 + 0.4 × fireGlow` and hidden until its room ignites.
    - The room holding `run.fire`'s point gets no cone, because the fire sphere is there.
  - **`spreadStats = { burning, drawn }`,** updated each frame: the rooms burning at t, and the tints visible.
- [ ] **Step 3: Doors close on time.** In `replay/BlockedDoors.tsx`, each `door_blocked` event whose door exists gets a #DC2626 overlay:
  - on `door.rect`, else a 0.3 m strip from `a` to `b`;
  - 0.035 m above the floor;
  - shown from the event's `t`.

  Doors then close on screen when the simulation closes them.
- [ ] **Step 4: Words and legend.**
  - In the Overview, under the KPIs, when the active run has a spread: `p.spreadline` "Fire spread (illustrative, <Material>): 3 rooms burning · 9 by the end of the run".
    - With one room it reads "1 room burning".
    - Without `fire.material` it reads "material not set".
  - LegendCard, when the run has a spread, adds "Burning room (illustrative)" (an orange-to-red ramp swatch), "Fire marker" and "Closed door".
- [ ] **Step 5: Material setting.**
  - **Store:** `material: Material` ('drywall') and `setMaterial`. The choice is kept across buildings.
  - **ScenarioPanel,** after the fire room: a `label` "Building material (illustrative)" around a `select` with Concrete, Drywall (default) and Wood.
  - **Live mode:**
    - `runScenario` sends `fire: {...scenario.fire, material}`.
    - A live run's label adds " · Wood" or " · Concrete" when the material isn't drywall.
    - A live what-if keeps its base run's material (`run.fire.material`, else 'drywall').
  - **Static mode:** the select is disabled, with a `p.dim.note`: "Material needs the live backend. In static mode, What if… shows the precomputed wood and drywall pair where a building has one."
- [ ] **Step 6: The material pair.** It is shown in static and live mode, from the demo index.
  - **`materialPair(entries, buildingId)`:**
    - The wood run is an entry with `whatIf: 'material'` and `material: 'wood'`.
    - Its drywall partner has the same building and fire room and `material: 'drywall'` (with `whatIf` 'material' or null). Failing that, the partner is that room's `whatIf: null` entry.
    - Without both: null.
  - `findPrecomputedVariant` considers only entries with `whatIf === 'propped'`.
  - **Store `showMaterialPair()`:**
    - `whatIfBusy` reads "Loading precomputed pair…".
    - It loads (or switches to) the drywall run, then the wood run with `whatIf: {baselineKey: <drywall id>, door: '', state: 'propped', material: 'wood'}`.
    - It sets `split: true` and `compareKeys: [drywall, wood]`, and keeps the clock time.
    - Errors go to `whatIfError`.
  - **WhatIfCard section `.material`,** shown only when `materialPair` finds a pair for the loaded building:
    - h5 "Building material (illustrative)";
    - a button "Compare wood with drywall";
    - `p.dim.note`: "Precomputed pair, fire in <room name> (<room id>). Spread speeds are illustrative, not engineering values."
  - **Headline:** a material variant's headline is the main line of `pairHeadline(base, variant, 'Wood instead of drywall')`, else "Wood instead of drywall". The t90 and trapped line stays as today. The tour's `variantCaption` uses the same words for a material variant; scene 4 still shows the propped door.
  - **`restoreLink`:** an `r` that names a wood entry loads its drywall partner, then the wood run as above. Split comes from the link.
- [ ] **Step 7: Live what-if fallback,** as E35 did for runs.
  - In `runWhatIf`, any live failure falls through to today's precomputed path, with a `console.warn`.
    - A refused connection or a timeout still ends live mode, with the banner "Backend unreachable: precomputed runs only".
    - Other failures keep live mode.
  - With a precomputed variant, set `whatIfNote` to "Live what-if unavailable: showing the precomputed what-if (<door label> <state>)." and `whatIfFallback: true`. WhatIfCard shows the note as `p.warn[role=status]`.
  - Without one, `whatIfError` is the live failure itself, or "No precomputed what-if for this fire" after a refused connection.
  - `whatIfNote` and `whatIfFallback` reset when a what-if starts and in `setBuilding`.
  - A live what-if that succeeds behaves as before.
- [ ] **Step 8: qa.**
  - **New step `fire-spread`,** in a fresh page. Stay in the stacked view throughout.
    - Read the fixture from disk. If it's missing, report "fire-spread: fixture missing (A11 part 1)" and skip the rest of the step.
    - On the default run, paused at 60 s, `__spread.drawn` must equal that run's own count: the rooms of its `fire.rooms` with `ignite <= 60`. That is 0 for demo runs without `fire.rooms`.
    - If the fixture's `buildingId` isn't the loaded building, pick it in the nav's Building select and wait for `loading === null`.
    - Open the fixture through `#open-file`, and wait until the active run's id is the fixture's.
    - Seek, paused, to the second ignition time plus 1 s. With one room, use the first ignition time; never seek past the duration.
    - Report a problem unless all of these hold:
      - `__spread.burning` equals the number of rooms with `ignite <= t`, and `__spread.drawn` equals those of them whose room exists in the building;
      - `p.spreadline` shows that number and the word "illustrative";
      - the legend shows "Burning room (illustrative)";
      - with `layers.fire` off, `drawn` is 0.
    - Shot `fire-spread.png` (with a blank check), then `fire-spread-high.png` with `fireGlow: 2`.
  - **New step `material-pair`,** in a fresh page:
    - Route `**/demo/index.json` to the real index plus one entry: `{id: 'qa-wood', buildingId: <fixture building>, label: 'Wood (qa fixture)', file: 'fixtures/fire-spread.run.json', whatIf: 'material', material: 'wood', fire: <the fire of that building's first whatIf-null entry>, doors: {}}`.
    - Open `?qa&building=<fixture building>` and set `card: 'scenario'`.
    - Click "Compare wood with drywall". Wait for `split === true`, `activeRunKey === 'qa-wood'` and the partner run loaded.
    - `.whatif` must contain "Wood instead of drywall". Take shot `material-pair.png` and blank-check both panes.
    - On the main page (no route), `.whatif .material` must exist exactly when the real index has a wood entry for the building.
  - **New step `whatif-fallback`,** in a fresh page, with E35's `live-fallback` routes and `Date.now` skew. For each of `http`, `failed`, `slow` and `down`:
    - Switch to the first baseline, set `mode: 'live'` and `card: 'scenario'`, and click `.whatif button.run`. For `slow`, skew the clock 200 s once "Running… N s" shows.
    - Wait for `whatIfBusy === null`.
    - Report a problem unless all of these hold:
      - the active run is that baseline's precomputed `propped` entry from the index;
      - `whatIfNote` starts with "Live what-if unavailable: showing the precomputed what-if", and `whatIfFallback` is true;
      - `whatIfError` is null;
      - `mode` is static for `down` and live otherwise.

    Then:
    - Rename the building id to 'qa-none'. `whatIfError` must read "Request failed (500): qa: backend error", with no note.
    - Shot `whatif-fallback.png`.
    - Console errors from the routed 500 and the refused connection are expected in this page only.
  - **`whatif-static`** also checks that the material select is disabled and that its note says "Material needs the live backend".
- [ ] **Step 9: Verify.**
  - `npm run build` passes with no type errors.
  - `npm run qa` (shim) exits 0 with 0 axe violations. Then check the screenshots:
    - `qa/fire-spread.png` shows orange-to-red rooms with cones, the spread line in the sidebar and the legend row.
    - `qa/material-pair.png` shows the split view, drywall on the left and wood on the right, under the "Wood instead of drywall" headline.
    - `qa/whatif-fallback.png` shows the amber note under "Run what-if".
  - `python tools/check_all.py frontend privacy` ends with `ALL OK`.
  - Manual, if the backend runs (`VITE_API_URL=http://localhost:8000/api npm run dev`, with A's backend passing `fire.material` through):
    - Pick Wood and run.
    - The run label ends " · Wood", and the room tints spread faster than in a drywall run of the same fire.
- [ ] **Step 10: Commit** `git add frontend docs/superpowers/plans/2026-11-13-ws-e-frontend.md && git commit -m "feat(frontend): spreading fire on screen, building material setting and the wood vs drywall pair"` (no attribution lines). Say in the commit body that the demo runs show the spread once A11 part 2 lands.
