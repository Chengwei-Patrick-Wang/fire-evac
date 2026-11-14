# Decisions

## Decided (by the team)

| Topic | Decision |
| --- | --- |
| Project | Fire evacuation simulator (committed at 9:44 PM Friday) |
| Buildings | Non-UMass buildings are fine |
| Process | Superpowers in Claude Code; design fast; no rigorous testing |
| Team | 5 people; one workstream and plan each; speed things up with subagents and handoffs |
| Usage | Only Tony has Max; the other four have Pro. Agent-heavy work goes on Tony's account |

## Proposed (planning-session defaults; confirm or change)

| # | Topic | Proposal | Why |
| --- | --- | --- | --- |
| 1 | Building input | **IFC (BIM) models first** (NIBS clinic or office, VTT office). Image tracing (OpenCV proposes walls, a person fixes them in an editor) is a stretch goal. The traced UMass Student Union (2007 plans) is the UMass option | IFC arrives with walls, doors, stairs and rooms labeled; vision models still miss doors and symbols |
| 2 | Crowd engine | **JuPedSim 1.4.2**, `CollisionFreeSpeedModel`. One simulation per floor, stepped together, with stair transfer between floors | Published models, Python API, fast enough (see 07), can be calibrated |
| 3 | Fire | **Own NumPy grid** (0.5 m cells): t-squared growth, smoke turns into visibility, which sets walking speed. CFAST as a stretch; FDS is out | Hours to build; every assumption explainable |
| 4 | Agents | **Rule-based brain** (exit cost, softmax choice, switching threshold) on a JuPedSim body. LLMs for personas, the report, situation-cached decisions and 10–20 live LLM agents | Every agent as a live LLM is too slow, costly, unrepeatable and unvalidated (see 05) |
| 5 | LLM provider | **Gemini behind one wrapper** (eligible for the MLH Gemini prize); Claude as an alternative, paid from Tony's Max monthly API credits | Keeps the prize option; swapping providers is one setting |
| 6 | Frontend | React + Vite + TypeScript, react-three-fiber/drei, Recharts, Zustand. Walls are the extruded boundary of the walkable area; agents are one InstancedMesh; web-ifc as a stretch | Runs from a link; handles thousands of agents |
| 7 | Backend | FastAPI with a process pool; results stored as files; no database unless chasing the MongoDB Atlas prize | Same language as the simulation libraries |
| 8 | Hosting | Static replay site with precomputed runs, plus a laptop backend for live runs | Demo survives bad Wi-Fi |
| 9 | Testing | No TDD; one smoke test per module; skip Superpowers' separate code-quality review | Speed |
| 10 | Determinism | Seed every random draw from `scenario.seed`; key agents by our own `idx`; cache and log LLM decisions | Fair "what-if" comparisons |
| 11 | Scope | **P0:** IFC to building, multi-floor sim, fire coupling, 3D replay with smoke and heatmap, evacuation curve, one what-if. **P1:** batch risk map and ranking, LLM report, personas, LLM agents, split screen, accessibility lens, tracing editor. **P2:** calibration chart, agent's-eye view, trails, exit criticality, CFAST, web-ifc | Demo depends only on P0 |
| 12 | Team split | Workstreams A–E and sync points (see 10) | Parallel work with no waiting |
| 13 | Contracts | building/v0, scenario/v0, run/v0, metrics/v0, frozen at kickoff (see 04) | Lets everyone build against example files |
| 14 | Ethics | Keep weak-spot results for real buildings private; label the fire model illustrative; credit every data license | See 03 |

## Open (answer in brainstorming)

- Who owns workstreams A–E? (Tony fits A: backend and LLM APIs.)
- Gemini or Claude for the app's LLM features?
- Which IFC model is the demo building? Inspect the candidates for spaces, doors and stairs first.
- Add the traced UMass Student Union as a second building, for the Best UMass Hack prize?
- Keep the tracing editor, or cut it?
- Which what-if scenarios to show: stair door propped open, exit blocked, sprinklers on?
- Sync times against the official schedule; who owns Devpost and the video.
- Permissions for overnight agent runs. A proposal is in 10; it has not been applied.
