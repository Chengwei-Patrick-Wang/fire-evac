# AGENTS.md: team rules for every agent

Fire evacuation simulator for HackUMass XIV. These rules apply to every agent (Claude Code, Codex, anything else). They override tool defaults, including Superpowers defaults.

**Read first:** the design spec `docs/superpowers/specs/2026-11-13-fire-evac-sim-design.md`, then your workstream's plan in `docs/superpowers/plans/`. Research and numbers are in `docs/context/`.

## Speed over rigor

- No test-driven development. Each package has one `smoke_test.py` that runs on the example files (`python -m <package>.smoke_test`). Run it before every push.
- No separate code-quality review unless something broke. A quick check against the spec is enough.
- Commit small and often.

## Contracts are frozen

- plan/v0, building/v0, scenario/v0, run/v0 and batch/v0 are defined in spec §6. The examples in `contracts/` are the source of truth.
- Never rename or remove a field without team agreement in chat. New optional fields are fine.
- After a contract change, regenerate the examples: `python tools/build_examples.py`.

## Stay in your folder

| WS | Folders |
| --- | --- |
| A | `backend/`, `frontend/src/tracer/`, `tools/`, `contracts/` |
| B | `buildings/` |
| C | `sim/` |
| D | `fire/` |
| E | `frontend/` except `src/tracer/` |

Shared files (`contracts/`, `AGENTS.md`, `requirements.txt`, `frontend/src/data/`) change only through small PRs that A merges.

## Git

- Work on your branch (`ws-a` … `ws-e`). Push at least hourly. Open a PR to `main` at least every 2 hours. Merge `main` into your branch at each sync point.
- Never force-push, never push to `main` directly, never commit `.env` or anything in `data/private/`.

## Running things (always from the repo root)

- Setup: `python -m venv .venv`, activate it (`source .venv/bin/activate` on macOS, `.venv\Scripts\activate` on Windows), then `pip install -r requirements.txt`.
- Examples: `python tools/build_examples.py`
- Normalize a plan: `python -m buildings.normalize plan.json building.json`
- Run a scenario: `python -m sim.run contracts/building.example.json contracts/scenario.example.json data/runs/out.json`
- Preview: `python tools/plot_building.py contracts/building.example.json --run contracts/run.example.json --t 20` (PNGs in `debug/`)
- API: `uvicorn backend.app.main:app --reload` (http://localhost:8000/api)
- Frontend: `cd frontend && npm install && npm run dev` (http://localhost:5173)
- Smoke tests: `python -m buildings.smoke_test`, `python -m sim.smoke_test`, `python -m fire.smoke_test`, `python -m backend.smoke_test`

## Gotchas

- **Determinism:** every random draw comes from `scenario.seed`. Key agents by our own `idx`, never by JuPedSim agent ids, which keep counting across simulations in one process.
- **JuPedSim:**
  - Check `sim.removed_agents()` after every iteration; it only reports the last one.
  - `agent.model.desired_speed` can be set mid-run.
  - Never draw exits against a wall. Exits are zones beyond a real door opening.
- **Big files:** run JSON files are large. Inspect them with `jq` or `head -c 2000`; never read one whole.
- **Secrets:**
  - `.env` holds `GEMINI_API_KEY` (see `.env.example`).
  - Never export `ANTHROPIC_API_KEY` in a shell where Claude Code runs: Claude Code would bill that key instead of your plan.
  - The app's Claude key, if ever used, is `APP_ANTHROPIC_API_KEY`.
- **Ethics:**
  - This is not a compliance tool, and the fire model is labeled illustrative.
  - No "panic" mode.
  - Data derived from UMass plans stays in `data/private/`.

## Per tool

- **Claude Code on Pro:** Sonnet at medium effort, `superpowers:executing-plans`, one plan task per session, then `/clear`. Use `acceptEdits` mode.
- **Codex:** you read this file automatically. Work through your plan's checklist in order and tick the boxes as you go.
- **Claude Code on Max (A):** subagent-driven development; auto mode for long runs.
