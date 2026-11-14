# Workstream D — Fire, Metrics and Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fast, explainable fire and smoke grid that C can query every second, plus the metrics, batch runs and weak-spot ranking that make the demo's results.

**Architecture:** `fire/model.py` keeps a 0.5 m grid per floor (mask from the walkable polygon), grows heat release as a t-squared curve, spreads smoke through open doors, and turns smoke into visibility. `fire/metrics.py` and `fire/batch.py` turn run/v0 files into metrics/v0. Spec: `docs/superpowers/specs/2026-11-13-fire-evac-sim-design.md` (formulas also in the team report).

**Tech Stack:** Python 3.11, numpy, shapely 2, concurrent.futures, matplotlib (debug PNGs).

**Hackathon mode:** no TDD; one `smoke_test.py`; commit after every task.

**Owner profile:** numerics, NumPy.

---

### Task D1: Stub and API first (H+0 to H+0.5)

- [x] `fire/stub.py`: `NoFire` with the full API ships in the starter. Keep its method names identical in `fire/model.py` so C only swaps the import.

### Task D2: Grid fire and smoke (H+0.5 to H+4)

**Files:** `fire/model.py`

- [ ] Per floor: grid from walkable bounds; mask via `shapely.contains_xy`; door cells from `doors[]`; closed doors pass 5% of the flux, open and propped doors pass all of it.
- [ ] Heat release with alpha from the growth class (slow 0.00293, medium 0.01172, fast 0.04688, ultra-fast 0.1876 kW/s²), capped by the preset peak or a sprinkler toggle; the "liquid" preset jumps straight to peak.
- [ ] Smoke source proportional to heat release at the ignition cells; diffusion step inside the mask; fire cells spread slowly within the ignition room.
- [ ] `visibility`: extinction coefficient from smoke density, visibility S = C/K with C = 3. `untenable`: fire cell, or visibility under 1 m for over 30 s. `blocked_doors`: doors whose cells are untenable.
- [ ] `snapshot(floor)` returns the run/v0 smoke frame format (density 0–100).
- [ ] Verify: `python -m fire.model` steps the example scenario 120 s and saves `debug/smoke_t060.png`, `debug/smoke_t120.png`.

### Task D3: Presets and stairwell smoke (H+4 to H+7) (parallel with D4)

- [ ] Presets in `fire/presets.py`: kitchen (fast), bedroom (medium), lithium-ion (ultra-fast, extra smoke), trash (fast), liquid (instant).
- [ ] Propped stairwell doors let smoke into the stair zone and up to the same stair group on the floor above.

### Task D4: Metrics from one run (H+6 to H+10)

**Files:** `fire/metrics.py`

- [ ] t50/t90/t100, evacuated, trapped by profile, exit counts.
- [ ] Per door and stair: agents within 2 m each frame → peak queue and person-seconds waiting.
- [ ] Heatmap: agent counts per 0.5 m cell per floor, summed over frames.
- [ ] Output a metrics/v0 dict; `python -m fire.metrics data/runs/x.json` prints it.

### Task D5: Batch and ranking (H+10 to H+16)

**Files:** `fire/batch.py`

- [ ] Ignition per room (or 20–50 sampled rooms) × 3–10 seeds; `ProcessPoolExecutor`; reuse `sim.run`.
- [ ] Aggregate: per-room risk (mean t90, trapped), per-door waiting, and a `top` list of the three worst spots with a one-line `why` each.
- [ ] Verify on the example building: completes in minutes and names the kitchen corridor or a stair.

### Task D6 (P1/P2): Calibration check (H+16 to H+20)

- [ ] One-door test geometry with 200 agents: measured flow vs 1.3 persons per meter per second times width; print a table for the demo's credibility slide. Optional: rebuild a Jülich bottleneck experiment and compare.

### Task D7: Smoke test (any time)

- [ ] `fire/smoke_test.py`: smoke near the ignition rises over time; a fast kitchen fire makes its room untenable within the run; the batch returns a non-empty `top`.
