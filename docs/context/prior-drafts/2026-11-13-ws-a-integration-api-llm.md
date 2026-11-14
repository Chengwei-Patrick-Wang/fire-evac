# Workstream A — Integration, API and LLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Own `main`, the FastAPI service, the LLM wrapper and the demo, so the other four workstreams plug together at every sync point.

**Architecture:** FastAPI app in `backend/app/` that serves buildings and runs and calls `sim.run` in a process pool; `backend/llm/` wraps Gemini (or Claude) for personas, cached decisions and the report. Spec: `docs/superpowers/specs/2026-11-13-fire-evac-sim-design.md`.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, pydantic, google-genai (or anthropic), concurrent.futures.

**Hackathon mode:** no TDD; one `smoke_test.py`; commit after every task; skip separate code-quality review.

**Owner profile:** backend + LLM APIs, comfortable reviewing others' PRs.

---

### Task A1: Repo and kickoff (H+0 to H+0.5)

- [ ] Create the GitHub repo from this starter, push `main`, add the 4 teammates.
- [ ] Confirm `requirements.txt` installs: `python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`.
- [ ] Everyone runs `python tools/build_examples.py` and sees the metrics line. Everyone creates their worktree: `git worktree add ../fe-ws-x -b ws-x`.
- [ ] Post the contract rule in team chat: field names are frozen; optional additions only.

### Task A2: FastAPI skeleton (H+0.5 to H+3)

**Files:** `backend/app/main.py`, `backend/app/jobs.py`, `backend/smoke_test.py`

- [ ] `GET /buildings` lists `data/buildings/*.json` plus `contracts/building.example.json`; `GET /buildings/{id}` returns one.
- [ ] `POST /runs` takes scenario/v0, returns `{run_id}`; a `ProcessPoolExecutor` runs `sim.run(building, scenario)`; results go to `data/runs/{run_id}.json`. Until C lands, return a copy of `contracts/run.example.json`.
- [ ] `GET /runs/{id}` returns `{status}` while running, the run/v0 JSON when done.
- [ ] CORS for `http://localhost:5173`.
- [ ] Verify: `uvicorn backend.app.main:app --reload`, then `curl -X POST localhost:8000/runs -d @contracts/scenario.example.json -H 'content-type: application/json'` and fetch the run.

### Task A3: LLM wrapper (H+3 to H+6) (parallel with A2 polish)

**Files:** `backend/llm/client.py`, `backend/llm/features.py`, `backend/llm/cache.json` (gitignored)

- [ ] `complete(prompt, json_schema=None, timeout=3.0)`: Gemini via `GEMINI_API_KEY` from `.env`; `LLM_PROVIDER=claude` switches to Anthropic with the key in `APP_ANTHROPIC_API_KEY` (never `ANTHROPIC_API_KEY`, which Claude Code would pick up and bill).
- [ ] `personas(building, n, mix) -> list[dict]`: one call returning `{profile, familiarity, note}` per agent; map to profile parameters in code.
- [ ] `report(metrics, building) -> str`: markdown with the top three weak spots, the numbers behind them, suggested fixes, and a one-line limits note.
- [ ] `decide(obs) -> {action, target, reason} | None`: situation key = `(floor, nearest_node, smoke_level, queue_level, profile)`; read and write `cache.json`; on timeout or bad JSON return `None` so the sim falls back to rules.
- [ ] Verify: `python -m backend.llm.features` prints 5 personas and a report for `contracts/run.example.json` metrics.

### Task A4: Walking-skeleton integration (H+3 sync)

- [ ] Merge B, C, D, E branches; the frontend renders the example building and a run served by the API.
- [ ] Fix contract mismatches on the spot; regenerate examples if a field changed.

### Task A5: Real building end to end (H+8 sync)

- [ ] With B's chosen IFC building in `data/buildings/`, run one scenario through `POST /runs`; E loads it.
- [ ] Record what broke in `docs/notes.md`; assign fixes before the sleep shift.

### Task A6: Batch and report endpoints (H+14 to H+20)

- [ ] `POST /batch` calls D's `fire.batch.run_many`; `GET /batch/{id}` returns metrics/v0.
- [ ] `POST /report` returns `llm.report(...)` for a run or batch.
- [ ] With C: wire `llm.decide` into C's decision hook for agents flagged `llm: true` (10–20 per run); log `llm` events with `reason`.

### Task A7: Demo and Devpost (H+24 to H+34)

- [ ] Precompute demo runs (baseline, door propped, batch) into `frontend/public/demo/`.
- [ ] Rehearse the 3-minute script; record a backup video.
- [ ] Devpost text: problem, what it does, how it works (stack table), limits and validation, credits for every data source and its license.
