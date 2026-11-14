# Fire Evacuation Simulator — team rules (hackathon mode)

These rules override Superpowers defaults for this repo.

- **Speed over rigor.** Do not use test-driven development. Each module has one `smoke_test.py` that runs on the example files; run it before every push.
- **Subagent-driven development:** do a quick spec check per task; skip the separate code-quality review unless a task broke something.
- **Plans live in** `docs/superpowers/plans/` (one per workstream); the design is `docs/superpowers/specs/2026-11-13-fire-evac-sim-design.md`.
- **Contracts are frozen:** building/v0, scenario/v0, run/v0, metrics/v0 (see `contracts/`). Never rename or remove fields without team agreement; new optional fields are fine. If a contract changes, regenerate examples with `python tools/build_examples.py`.
- **Stay in your folders:** A `backend/`, B `buildings/`, C `sim/`, D `fire/`, E `frontend/`. Shared files change only through small PRs.
- **Branches:** work on `ws-a` … `ws-e` in your own git worktree; commit small and often; push at least hourly; rebase on `main` at each sync point.
- **Determinism:** seed every random draw from `scenario.seed`; key agents by our `idx`, never by JuPedSim agent ids (they keep counting across simulations in one process).
- **JuPedSim:** check `sim.removed_agents()` every iteration (it reports per step); `agent.model.desired_speed` can be set mid-run.
- **Secrets:** the app reads `GEMINI_API_KEY` (or `APP_ANTHROPIC_API_KEY` if you switch providers) from `.env` via python-dotenv. Never export `ANTHROPIC_API_KEY` in a shell where Claude Code runs: Claude Code would bill that key instead of your plan. Never commit keys.
- **Big files:** don't read `contracts/run.example.json` in full (about 245 KB); inspect it with `jq` or `head -c`.
- **Run from the repo root:** `python -m sim.run ...`, `python -m buildings.ifc ...`, `uvicorn backend.app.main:app --reload`, `cd frontend && npm run dev`.
