# Overnight status

Integration notes from the lead's machine, newest first. Read this before each task: it says what's merged into `main`, what failed, and anything your workstream should know. Only the lead's machine edits this file.

## Sat 02:20: integration

- **Merged:**
  - **B:** the `inspect_ifc` tool and the IFC candidate table (redo B1 with the new pick rule above).
  - **E:** refreshed demo examples and `tsx` as a devDependency (thanks).
  - **A:** plan ticks.
- **C:** idle since C8, which waits on A's LLM client (A7, after the 3 AM usage reset). New C tasks (C9+) are coming to your plan shortly; C9 makes the sim smoke test fast again.
- **D:** plan complete. New D tasks (D10+) are coming to your plan shortly.

## Sat 02:15: lead's rulings

- **Everyone:** if a plan rule can't be satisfied as written but its intent is clear, follow the intent and explain your reading in the commit message. Mark a task `BLOCKED` only when it truly needs something that doesn't exist yet, such as another workstream's code or a human.
- **B:** your blockers are cleared on `ws-b`.
  - B1's pick rule now ignores storeys without rooms (roof, foundation, footing), since the old rule rejected every real model. **Pick `Office_A_20110811.ifc`** (2 occupied floors, 99 rooms, 102 doors, 2 stairs). `Clinic_Architectural.ifc` is the second building (B8).
  - Redo B1 with the new rule, then continue with B2–B6.
  - B7 may write `data/calibration.json`, since it's generated data.
  - The tracer page (A3) is now on `main`, so B8's tracer export exists.

## Sat 02:05: integration

- **Merged ws-d (D):** coupled-run tuning, metrics v1, batch runner, ranking and risk map, RSET/ASET margins, exit criticality. **Plan D is complete.**
- **Merged ws-c (C):** stair transfer, stuck watchdog, queue-aware exit choice, fire coupling and blocked doors, mobility profiles, LLM brain hook. C8 (all-LLM crowd) waits on A's LLM client (A7), which lands later tonight.
- **Merged ws-a (A):** the tracer page. It was traced and exported against the real API in a browser.
- **Examples were regenerated with the full pipeline:** 159/160 out, 1 trapped, t50 97 s, t90 124 s, smoke on both floors. E: copy `contracts/*.example.json` into `public/demo/` (task E14 automates this).
- **C:** `python -m sim.smoke_test` now takes about 6 minutes, and the merge gate runs it on every pass. Please make the default run under about 60 s and put the 300-agent and performance runs behind `--slow`.
- **E (from A's tracer review):**
  - The tracer renders as a fixed overlay because the side panels stay mounted. In `App.tsx`, render `TracerPage` instead of the replay layout, not on top of it.
  - `onOpenBuilding` fails in static mode, and its errors go uncaught. Catch them and show a message.
- **B:** there's still no `ws-b` branch.

## Sat 01:30: integration

- **Merged ws-d (D):** fire presets, the smoke-front `FireModel`, doors, stairwells and multi-floor smoke. The API now uses it automatically.
- **Merged ws-e (E):** credibility panel, accessibility lens, LLM-agent highlight and trails. Every task in plan E is now on `main`.
- **Examples were regenerated with D's real `FireModel`** (it replaces the placeholder smoke). `contracts/run.example.json` now shows smoke on both floors (F1 55 frames, F2 21, so it climbs the stairwells) and one trapped agent. E: copy the new examples into `public/demo/` if the app serves copies.
- **Runner fix for Codex users:** Codex 0.169 removed `--full-auto`. `tools/overnight/run.sh` now detects `--approve-for-me` or `--full-auto`. A runner that keeps logging `exit 2` needs a restart: press Ctrl+C, commit any changes, run `git merge origin/main`, then `run.sh codex <letter> check`, then start it again.
- **C:** no commits yet, because your runner hit the Codex flag issue above. Restart it as described.
- **B:** there's no `ws-b` branch yet. The IFC models (office, clinic, duplex) can be downloaded without a browser; the lead sent the commands.

## Sat 01:20: integration

- **Merged ws-e (E):** the frontend app (13 commits). It installs and builds cleanly inside `check_all`. Nice work.
- **Merged ws-a (A):** tracer geometry, plan export and validation (`frontend/src/tracer/*.ts`), plus `tools/check_tracer.py`.
- **E:** please add `tsx` as a devDependency in `frontend/package.json`. The tracer check currently downloads it through `npx` on first use, which fails offline. A's `TracerPage.tsx` replaces your placeholder in `src/tracer/` next.
- **Everyone:** `main` now has the frontend. `python tools/check_all.py` also builds it, and the first run installs `node_modules`.
- **B:** there's no `ws-b` branch on GitHub yet, so the runner hasn't started.
- **C, D:** your branches exist, but nothing has been committed yet.

## Sat 00:50: integration

- **Merged ws-a.** The API is split into routers (`backend/app/store.py`, `batch.py`, `report.py`, `trace.py`). `POST /api/buildings/from-plan?public=false` now returns `{id, warnings}`.
- **New for everyone: `python tools/check_all.py`.** One command runs every package check plus a privacy check. You can also name packages: `python tools/check_all.py sim fire`. The lead's merges use it as the gate, so run it before you push.
- **B:** keep the `WARNING (normalize):` prefix on normalizer warnings. The API passes those lines on to the tracer.
- **D:** API runs have no smoke until `fire/model.py` exports `FireModel(building, scenario)`. The API picks it up automatically once it exists.
- **E:** A's tracer code lives in `frontend/src/tracer/` (`geometry.ts`, `plan.ts`, `check.ts`, and later `TracerPage.tsx`). If `frontend/` already contains that folder when you scaffold the Vite app, scaffold into a temporary folder and move the app in, keeping `src/tracer/`. Your app shell mounts `src/tracer/TracerPage.tsx`.
- No teammate branches have been pushed yet.

## Sat 00:20: notes from plan review

- **C:** sim v0 writes rows with status `-1` in the frame where an agent exits. run/v0 allows only 0–3 and says exited agents disappear, so drop those rows when you touch the frame writer. E already hides `-1`, so nothing breaks meanwhile.
- **A:** pin `NODE_VERSION = "22"` in `netlify.toml`, because current Vite needs Node 20.19+ or 22.12+.
- **Everyone:** all five plans are on `main`. Batch `top[].kind` may be `stair` with a door id, so look items up by id, not by kind.

## Sat 00:30: kickoff

- `main` has the walking skeleton:
  - plan normalizer v0 (`buildings/`);
  - per-floor sim v0, where upper-floor stairs are sinks so F2 agents never exit and t90/t100 stay null until C's stair transfer lands (`sim/`);
  - metrics v0 and a placeholder smoke source (`fire/metrics.py`, `tools/toy_fire.py`);
  - API (`backend/`);
  - generated examples (`contracts/`).
- About every 45 minutes the lead's machine merges each `ws-*` branch into `main` if all smoke tests pass on the merged result. Nothing is ever force-pushed.
- If your branch fails a check, the reason appears here under your workstream letter.
