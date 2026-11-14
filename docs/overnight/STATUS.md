# Overnight status

## Sat 09:15: D15 merged (office demo batch); lead took over D18

**Merged:** ws-d **D15** (lead takeover), the real office demo batch. It ran 12 rooms x 3 seeds: 252 runs plus a pilot, 0 failed, and every comparison has n=36. Wall time was 49 min on the shared laptop. The command is in `fire/README.md`. The output `data/runs/batch-office.json` is gitignored and sits on the lead's laptop in `../HackUMass-ws-d-lead/data/runs/`. The blocked-exit sweep ran clean, so C13b fixed the old crash.

**Office headline numbers (for the demo, A6 and E's Report tab):**
- Weak spots:
  1. Fire in OPEN OFFICE (R237b): 14.3 people trapped on average; 90% out after 141 s.
  2. Exit Stair S1 (west): 15 people queued at peak; 181 person-seconds of waiting per fire.
  3. Exit Stair S2 (east): 10 people queued at peak; 114 person-seconds.
  4. The door from SECURE DOC ROOM to OPEN OFFICE: 5 people queued at peak; 26 person-seconds, all of them in smoke.

  The top 3 hold in 2 of 3 seeds, and S1 ranks first in 3 of 3.
- What-ifs, per fire:
  - Propped stair doors: +152 person-seconds in smoke (+54%), no change in 90% out.
  - Stair S1 blocked: 90% out 13 s later (slower in 36 of 36), +154 person-seconds in smoke.
  - Sprinklers: 1.2 fewer people trapped.
- Best measured fix: widen Exit Stair S1 (west) from 0.86 m to 1.36 m. 90% are out 2 s sooner, with 6% less time in smoke (faster in 23 of 36 fires).
- The story: the fire's location barely changes 90% out (135-141 s for every room). Nearly everyone trapped comes from the OPEN OFFICE fire, because the SECURE DOC ROOM (R205) has its only door into the open office.

**Needs to know:**
- **D, E, A (sprinklers):** the sprinklers what-if shows +47% time in smoke. That is how smoke time is counted, not harm: the sim drops trapped people from the frames, so their smoke time stops counting. In a paired check, trapped went 12 -> 0 and smoke time went 2,003 -> 3,626 person-seconds. Show sprinklers by people trapped, not by smoke time. The caveat is in `fire/README.md`.
- **C (Althan):** every fire in office room R227 logs `WARNING (sim): F2/R227: no safe fire keep-out cut; keeping walkable area`, so people can still walk through that burning room. Worth a look at 10 AM.
- **Everyone running batches or the precompute:** prefix the command with `OPENBLAS_NUM_THREADS=1`. Each pool worker drops from about 550 MB to about 33 MB with identical results. Memory reached 47.8 of 48.6 GB while two batches ran.
- **D (Aidan):** the lead took over **D18 (headline numbers pack)** at 09:10; it is running now. D20 (run cache, P1) is still yours. The sprinklers what-if and the sprinklers fix rerun the same scenario (about 1/7 of the runtime) and could share one set of runs. `--budget-min 20` gives a 30-35 min batch on a shared laptop.

**Still running:** A5, the demo precompute.

## Sat 08:05: Morning summary (read this first)

**On `main`, by workstream (every check passes):**
- **A (lead):**
  - Done: the API with routers and the `tools/check_all.py` merge gate; the tracer page with a Gemini first pass (it walks a model chain when one model is out of quota); batch endpoints; the Gemini client, report card (`/api/report`) and `decide`/`decide_batch`. API runs carry smoke exposure.
  - Running: A5, the demo precompute (rerun).
  - Open: A6 (Devpost, video, slides), A9 (UMass trace; needs a decision), A10 (personas and the all-LLM showcase; limited by the Gemini quota).
- **B (Jaya), plan complete:** IFC import, normalizer hardening, overrides and validation, the building index, AI room tidy, tracer showcase assets, and every public building validated. The **NIBS office** has readable exit names, the 250-occupant kitchen scenario and clear door widths. The **NIBS clinic** is CC BY 4.0: cite BSI (2020) and list changes.
- **C (Althan), plan complete:**
  - stair transfer between floors;
  - exit choice that weighs queues, visible smoke and unfamiliar exits;
  - the fire keep-out, early start on fire and smoke cues, and waiting beside the stair flow with per-profile metrics;
  - the LLM brain and the all-LLM crowd mode;
  - the robustness sweep and the clinic at 300 agents;
  - flow and walking-speed-in-smoke validation (`data/calibration.json`), seed ranges, smaller run files.
- **D (Aidan):**
  - Done: the smoke-front fire model, metrics, the batch runner, ranking and risk map, RSET/ASET, exit criticality, smoke exposure, the paired what-if sweep, fire-aware chokepoints, measured suggested fixes, seed ranges with top-3 stability, batch timing.
  - The runner went quiet at 04:24. The lead took over D14b (merged) and **D15, the office demo batch, now running**.
  - Open: D17–D21 (sensitivity, headline pack, refresh after C14, run cache, clinic batch).
- **E (Donovan), plan complete:** the full app:
  - 3D replay with smoke, heatmap and queue rings; dashboard; live runs; risk map and weak spots; what-if split screen; report card; credibility panel;
  - guided demo mode, About with QR and phone layout, agent's-eye view, deep links, printable report and PNG export;
  - accessibility pass and results, measured fixes, honest ranges, headline pack, clinic-scale performance, headless visual QA (`npm run qa`).

**Demo buildings:** the synthetic example (2 floors), the NIBS office (2 floors, 99 rooms), the NIBS clinic (2 floors, 252 rooms).

**Overnight findings:**
- Propping the stair doors barely changes evacuation time but raises smoke exposure by about 22%, so the what-if leads with exposure.
- Fixed sim bugs:
  - people routed through flames;
  - wheelchair waits blocking a stair;
  - stair-arrival crashes;
  - a keep-out slot in the clinic;
  - a doorless clinic stair people walked down while it burned.

**Decisions waiting for the lead:**
1. **Gemini billing.** The free tier allows 20 requests per day per model (it resets around 3 AM ET). Enable billing for daytime testing and the live demo, or rely on precomputed reports.
2. **The public Netlify deploy** of the static demo. A5 prepares it; nothing is published without the lead's OK.
3. **Devpost, video and slides (A6).** Credits: NIBS Common BIM Files (ERDC-CERL), buildingSMART (clinic, CC BY 4.0), JuPedSim, three.js / React Three Fiber.
4. **The UMass Student Union trace (A9):** yes or no. Its results stay private either way.

**10 AM sync focus:**
- Run the guided demo end to end on the office: judge's fire → propped stair door → risk map → measured fixes.
- Review the report card text and pick the hero building.
- Split the rest of the day: Devpost and video, demo rehearsal, D17–D21, polish.

Integration notes from the lead's machine, newest first. Read this before each task: it says what's merged into `main`, what failed, and anything your workstream should know. Only the lead's machine edits this file.

## Sat 06:50: integration

- **Merged D14b** (the lead's takeover: fire checks read labels and widths from the office file) and **B13–B16:**
  - a demo-ready office with readable exit names and the 250-occupant kitchen scenario, keeping the same ids;
  - every public building validated in the smoke test;
  - tracer showcase assets;
  - clear door widths.

  All checks pass.
- **D:** B13 and B16 rebuilt `data/buildings/office.json` (readable names, clear widths) and `office.scenario.json` (250 occupants, kitchen). D15's batch and D19's refresh should use them.
- **Lead's machine:** a worktree cleanup briefly broke its Python environment (rebuilt at 06:45). Teammates' branches weren't affected. A's demo precompute (A5) reruns after 08:00.

## Sat 06:20: integration and a takeover

- **Merged:**
  - **C:** C17 robustness sweep, C18 the clinic at demo scale, C19 run-file size, C20 walking speed in smoke.
  - **E:** E28–E31: measured fixes, honest ranges, credibility on measured data, building index, the headline numbers pack.
- **B held:** `ws-b` (B13–B16) fails `python tools/check_all.py fire`, because `check_labels` pins the old office exit names: `AssertionError: ('exit', 'Exit Entry (south)')`. It merges once D14b lands.
- **D: the lead took over D14b,** since your runner has made no commits since about 04:25 while P0 tasks are open. D14b is claimed on `ws-d` with a BLOCKED line, so your runner skips it. D15 and the rest are untouched and still yours. If your runner is alive, carry on.

## Sat 05:00: integration

- **Merged:**
  - **B:** the NIBS clinic as a second building (`data/buildings/clinic.json` plus its scenario), AI room tidy, the building index (`data/buildings/index.json`), the opt-in vertex budget.
  - **C:** C13b (stair arrivals near blocked exits), C14 (smoke-aware exit choice), C15 (flow validation, written to `data/calibration.json`), C16 (seed ranges).
  - **D:** D16, ranges across seeds and top-3 stability.
  - **E:** E24 deep links with QR, E25 printable report and PNG export, E26 accessibility pass, E27 clinic-scale performance.
- **The full check passes on the combined `main`.** Examples were regenerated with the smoke-aware exit choice: 160/160 out, t90 121 s.
- **D:** D15's BLOCKED line is cleared on `ws-d`, because C13b is on `main`, so run the office demo batch now. C14 is on `main` too, so D19's refresh can run.
- **B, C, E:** your next tasks (B13–B16, C17–C20, E28–E31) are being written.

## Sat 04:35: integration

- **Merged:**
  - **C:** C8, the all-LLM crowd mode; C13, the real office at demo scale (safe fire routes, stair arrivals outside the keep-out).
  - **D:** D14 measured suggested fixes; D15 office batch prep (labels, design occupancy).
- **C: please do C13b next** (inserted before C14). D15 is blocked by stair arrivals placed within 0.2 m of the boundary next to a blocked exit; the repro is in the task.
- **D:** D15 stays BLOCKED until C13b merges, and the lead clears its line then. Continue with D16 and D17. D18–D21 are being written.
- **B and E:** your new tasks (B9–B12, E24–E27) are on `main`. Your runner picks them up after its next merge of `main`.

## Sat 04:20: new tasks and rulings

- **C:** C13–C16 are in your plan. C13 covers two crashes found on the real office: a stairwell fire (RS101) crashes `run()` when stair arrivals are drawn inside the fire keep-out, and the keep-out leaves a 0.21 m gap in break room R125 that traps an agent.
- **B:** **B7 is superseded by C15.** The 0.8 m jam is a crowd-model deadlock (about 42–67 of 200 pass, even with no fire), not geometry. Leave B7 BLOCKED; C15 writes `data/calibration.json` with 0.8 m listed under `limits`. B9–B12 are still being written.
- **D:** once C14 (smoke-aware exit choice) is merged, rerun D11's what-if sweep, because people will avoid stairs they can see filling with smoke and the numbers will shift.

## Sat 04:10: integration

- **Merged ws-a (A):** the Gemini client (retries, fallback to `gemini-2.5-flash`), the report card and `/api/report`, and `backend.llm.features.decide(obs)` / `decide_batch(observations)` in the shapes `sim/brain.py` uses. API runs now carry D10's smoke exposure.
- **Gemini quota, everyone:** the key is free tier, with **20 requests per day per model**. Run tests with `LLM_PROVIDER=off`, which gives the template report and rule agents. Save live calls for the demo.
- **C:**
  - **C8 is unblocked;** its BLOCKED line is cleared on `ws-c`. Build and test it with `LLM_PROVIDER=off` (rule fallback), and keep any live all-LLM run to one small showcase.
  - Raise LLMBrain's timeout from 4 s to about 60 s. Live calls measured 5–20 s.
- **E:** raise the report fetch timeout from 20 s to about 120 s. One call took 57 s.
- **B:**
  - Align `data/buildings/office.scenario.json` with D15's demo base: 250 occupants (120 barely queues) and the kitchen preset (the trash fire sits exactly at the 500 kW sprinkler cap, so "sprinklers on" changes nothing).
  - B9–B12 are still being written.
- **Everyone:** IFC door ids contain `$`, so quote them in shell commands.

## Sat 03:50: integration

- **Merged ws-e (E):** headless visual QA (`npm run qa`), the tracer's own layout, accessibility results by mobility profile, smoke exposure leading the what-if, real buildings in the picker. Every agent touching the frontend can now check visuals with `npm run qa`.
- **E:** E24–E27 (deep links, report export, accessibility pass, clinic-scale performance) are being written and land in your plan shortly.
- **B, C, D:** your next tasks are still being written. A's LLM client (A7) is still running.

## Sat 03:25: integration

- **Merged:**
  - **B:** IFC doors and stair groups, normalizer hardening, **the real NIBS office** (`data/buildings/office.json` plus `office.scenario.json`), calibration prep, trace support.
  - **C:** fast default smoke test (87 s here), fire keep-out, early start on fire and smoke cues, waiting beside the flow with per-profile metrics.
  - **D:** smoke exposure, the paired what-if sweep, fire-aware chokepoints, batch timing.
- **Examples regenerated:** 160/160 out, 0 trapped, t50 94 s, t90 123 s, t100 200 s.
- **E:** E19–E23 are in your plan.
- **B, C, D:** your next tasks (B9–B12, C13–C16, D14–D17) are being written and will land in your plans within about 30 minutes. Until then, your runner may wait a round or two.
- **C:** C8 unblocks when A's LLM client (A7, running now) merges. The lead will clear its BLOCKED line then.
- **Everyone:** the real office is on `main`. Use `data/buildings/office.json` wherever a task says "real building".

## Sat 02:55: integration and findings

- **Merged:**
  - **A:** batch endpoints (`POST /api/batch` with `{base}` runs D's `run_many`; 54-run batches work).
  - **B:** Office_A pick, IFC storeys and rooms, overrides and the validation report.
  - **E:** demo-data sync, guided demo mode, the About overlay with QR code and phone layout.
- **New tasks are in your plans:** C9–C12 (final version; replaces the 2:35 draft) and D10–D13.
- **Measured findings (please read):**
  - **C, priority bug:** in a lobby (L1) fire, JuPedSim routes everyone to E1 straight through the flame, trapping 65 of 160. A 2.5 m keep-out disc cuts that to 9 (C10).
  - **C, framing the spec forbids:** one wheelchair user waiting 180 s blocks the whole stair queue, so the other F2 occupants reach 90% out at 323 s instead of 140 s. C12 moves waiting people beside the flow.
  - **D:** until C10 lands, the lobby fire's top rank is an artifact of that bug, so don't put it in a headline.
  - **D, E, A, the demo story:** propping the stair doors barely moves t90 (+0.2 s on average; identical in 29 of 36 paired fires) or trapped (0). It does move **smoke exposure**: +22% person-seconds in smoke, and Stair A on F1 fills 31 s sooner. Headline exposure in the what-if, report card and demo scene 4; D10 adds it to the run metrics.
  - **Performance:** about 90% of sim time is JuPedSim routing (walkable vertices × moving agents). Windows machines run about 5× slower than Macs here.

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
