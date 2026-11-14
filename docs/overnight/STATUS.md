# Overnight status

Integration notes from the lead's machine, newest first. Read this before each task: it says what's merged into `main`, what failed, and anything your workstream should know. Only the lead's machine edits this file.

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
