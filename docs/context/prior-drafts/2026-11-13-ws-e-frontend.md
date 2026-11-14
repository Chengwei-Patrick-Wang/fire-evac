# Workstream E — Frontend (3D Replay and Dashboard) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One screen that loads a building and a run, replays the evacuation in 3D with smoke and heatmaps, and shows results: evacuation curve, exit use, weak spots, risk map and report.

**Architecture:** Vite + React + TypeScript; react-three-fiber scene built from building/v0 (walls = extruded boundary rings of `walkable`); agents as one `InstancedMesh` interpolated between run/v0 frames; smoke as a `DataTexture` per floor. Data comes from static files (`public/demo/*.json`) or the API, through one loader. Layout: controls left, 3D center, results right, time scrubber bottom. Spec: `docs/superpowers/specs/2026-11-13-fire-evac-sim-design.md`.

**Tech Stack:** React 18, TypeScript, Vite, three, @react-three/fiber, @react-three/drei, Recharts, Zustand (state).

**Hackathon mode:** no TDD; manual check that the example files load with no console errors; commit after every task.

**Owner profile:** strongest frontend person; a second person can join from H+10 (B after its P0).

---

### Task E1: Scene from the example files (H+0 to H+3)

**Files:** `frontend/src/data/loader.ts`, `frontend/src/scene/Building.tsx`, `frontend/src/scene/Agents.tsx`

- [ ] `npm create vite@latest frontend -- --template react-ts`; add three, fiber, drei, recharts, zustand.
- [ ] Copy `contracts/*.example.json` into `frontend/public/demo/`; TypeScript types for building/v0 and run/v0.
- [ ] Walls: for every segment of every walkable ring, one thin box (0.15 m thick, floor height tall) in an `InstancedMesh`; floors stacked by `elevation` with an "explode floors" slider.
- [ ] Agents: `InstancedMesh` of capsules colored by profile, positions interpolated between frames; hide agents after their exit event.
- [ ] Verify: `npm run dev` shows the example building with agents walking out.

### Task E2: Time, smoke, exits (H+3 to H+8) (subtasks can run in parallel)

- [ ] Zustand clock: play, pause, 1–10× speed, scrubber with event marks (alarm, door blocked).
- [ ] Smoke: per floor, a `DataTexture` from the nearest smoke frame on a translucent plane at 1.6 m; opacity from density.
- [ ] Exits green, stairs orange, the fire as a glowing marker that grows with time.

### Task E3: Dashboard and running scenarios (H+8 to H+14)

- [ ] Right panel: evacuation curve (share out over time, from exit events) and exit-use bars by profile (Recharts).
- [ ] Left panel: building picker, fire type, click on the floor to place the fire, occupant count and mix, door states, Run → `POST /runs`, poll `GET /runs/{id}`, load the result.

### Task E4: Weak spots made visible (H+14 to H+20)

- [ ] Heatmap overlay from metrics/v0 `heatmaps` (or computed from frames client-side).
- [ ] Queue rings at doors: agents within 2 m per frame; ring radius and label grow with the count.
- [ ] Risk map: rooms colored by batch `riskT90` or `riskTrapped`; click a room for its numbers.
- [ ] Split screen: two canvases sharing one clock for baseline vs what-if.

### Task E5: Story polish (H+20 to H+26)

- [ ] Report card panel (markdown from `POST /report`).
- [ ] LLM agents highlighted; hover shows their latest `reason`.
- [ ] Plan-to-3D reveal: wall height tweens from 0 to full on load.
- [ ] Accessibility lens: show only mobility profiles; timers over agents with status 2.

### Task E6 (P1/P2): Extras

- [ ] Tracing editor (with B): Konva canvas over the uploaded image; draw walls, doors, exits, stairs; set scale; export building/v0.
- [ ] web-ifc: render the original IFC as a ghosted overlay aligned to the walls.
