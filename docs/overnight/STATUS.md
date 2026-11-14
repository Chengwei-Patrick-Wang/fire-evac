# Overnight status

## Sat 17:20: no merges; Aidan's deck is on main

**On main:**
- **Aidan uploaded `FirePass.pptx` (6 slides) and `Architecture.png` to the repo root** through GitHub's web page. They're accurate to the app. The deck names the project "FirePass", while the Ember redesign (E36) puts "Ember" in the header, so the team needs to pick one name for the app, Devpost, slides and video.

**Running on the lead's machine:** D25 (fire spread), E36 (Ember shell) and C23 (every-room sweep). No branch has new commits yet.

**Tracer check (17:10, lead's laptop):** load trace, Export to 3D, and a run in the traced building all work. The Gemini first pass proposed 12 rooms that line up with the example plan in about 30 s. Doors and stair groups stay manual. The public site has no backend, so the AI pass and Export are off there.

## Sat 16:50: A11 part 1 merged; D25, E36 and C23 running

**Merged:**
- **A11 part 1:** new optional fields: scenario `fire.material` (concrete, drywall or wood; default drywall), and run `fire.rooms` (`{room, floor, ignite}`) plus `fire.material`. Also a sample spreading-fire run, `contracts/run.spread.fixture.json` (wood, 15 rooms), and the shared frontend types in `frontend/src/data/types.ts`.

**Running on the lead's machine:**
- **D25** (ws-d): fire spreads room to room at a speed set by the material.
- **E36** (ws-e): the Ember theme and shell layout.
- **C23** (ws-c): the every-room fire sweep. It wraps up by 18:30, then C27 (spread coupling) starts once D25 is merged.

**Notes:**
- **E:** build the fire visuals against `contracts/run.spread.fixture.json`. Keep the file: A11 part 2 doesn't delete it.
- **No new tasks are being written:** the team moved to other work at 14:30, and the Ember plan has enough work queued for the lead's machine.

## Sat 15:50: D23, E34, E35 merged; the Ember redesign is approved

**Merged:**
- **D23:** readable names for unnamed interior doors, such as "Door between CORRIDOR and SCIF OPEN OFFICE".
- **E34:** trade-off badges on measured fixes, and readable labels in the fix list, door picker and tour.
- **E35:** in live mode, a failed or timed-out run loads the nearest precomputed fire, with a note.

**Approved design** (`docs/superpowers/specs/2026-11-14-ember-ui-fire-spread-design.md`, based on `docs/design/ember-ui.md`):
- **UI:** the Ember UI, with a light theme, collapsible top nav, left analytics, bottom floor strip and timeline, and a grey walls-only building.
- **Floor views:** stacked, single, side by side and ghost.
- **Visibility and colors:** fire and smoke visibility controls; agents colored by status or type.
- **Simulated fire spread,** room to room, at concrete/drywall/wood speeds, labeled illustrative.

The lead's machine is writing the plan now. It runs D25 (spread model), C27 (sim coupling), A11 (formats and the demo rerun) and E36 to E38 (UI) tonight. The precompute reruns around 9 to 11 PM, and the freeze is at 2 AM.

## Sat 15:20: D22 merged; C23 to C26 queued

- **Merged:** ws-d **D22**. A measured fix that costs something now reads as a trade-off and names the fires behind the cost. For example: "Trade-off: Keep Exit Main entrance clear (vs blocked): 90% out 58 s sooner…, but 1.3 more trapped per fire (47 of 47 in fires in Lobby (L1), which this exit opens onto)." Five demo fixes become trade-offs; they show on the site after the precompute rerun.
- **Running on the lead's machine:** D23 (readable interior door names), E34 (trade-off badges, readable labels in lists) and **C23**, a fire in every room of the office and the clinic after C21 (hard stop 19:30).
- **Queued for C:** C24 (narrow doors: 0.86 m doors wedge when 200 people push at once, though the real layouts evacuate fully), C25 (faster runs with identical results), C26 (determinism guard).
- **Next for A:** rerun the demo precompute once the fixes that change numbers have landed.

## Sat 14:55: the demo is live at https://fire-evac-sim.netlify.app

- **Static site:** https://fire-evac-sim.netlify.app is public. Netlify builds it from `main` on every push, so each merge redeploys within a couple of minutes. All three buildings load. The About overlay's QR code points at this URL. Publishing gets locked at feature freeze so nothing changes during judging.
- **Merged:**
  - E32: what-if notes pass axe contrast.
  - E33: in static mode the Sprinklers box is disabled and quotes the measured sprinkler what-if instead (example: "Sprinklers on: 90% out 10 s sooner…").
- **Running (lead's machine):** D22 (trade-off wording) and E34 (trade-off badges, readable labels in the fix list and door dropdown). The C23+ writer is still working.
- **Devpost:** use the site URL as the demo link. The repo is still private, so make it public, or add judges, before submitting the code link.

## Sat 14:30: the lead's machine takes over every remaining task

The team is moving to other work, so **you can stop your runners**. The lead's machine claimed every open task on its branch ("BLOCKED: taken over by the lead's machine"), and it runs them one workstream at a time:

- **D:** D22 (running now), then D23, D24, D20, D21 and D17.
- **E:** E32 (running now), then E33 and E34. It works in a new worktree, `../HackUMass-ws-e-lead`.
- **C:** C23 and later are being written now: a post-C21 robustness sweep, live-run speed without changing results, narrow doors, and a determinism guard. The lead runs them when they're ready.
- **A:** after D22 and D23, the demo precompute reruns, so the static demo picks up the new wording, labels and keep-outs.

Merges keep landing on `main` every 30 minutes, as before.

## Sat 14:25: C22 merged; the credibility chart now holds up

- **C (Althan):** **C22** is merged. The corridor speed chart now measures steady walking, and the sim tracks the references:

  | Density | Sim | References |
  | --- | --- | --- |
  | lowest bin | 1.19 m/s | 1.34 and 1.20 |
  | middle bin | 0.86 m/s | 1.01 and 0.99 |
  | highest bin | 0.39 m/s | 0.58 and 0.62 |

  Speed now falls as density rises. The demo copy (`frontend/public/demo/calibration.json`) is synced. That clears both new C tasks: thanks!
- **D, E:** D22, D23 and E32 (P0) haven't started. The lead's machine takes them over at the 14:43 pass if your branch is still quiet.

## Sat 13:55: C21 merged

- **C (Althan):** your runner is back. **C21** is merged: fire keep-outs now fall back to a smaller disc, and seal off rooms where the full disc fails (R227 and similar). Sim, fire and privacy checks pass, and the example outputs are unchanged. C22 is next.
- **D, E:** your new P0s (D22, D23, E32) are waiting. Restart your runners if you haven't. If a branch is still quiet at about 14:30, the lead's machine takes over its next P0.
- **A:** the office demo files predate C21's keep-out change. They get refreshed in the precompute rerun after D22 and D23.

## Sat 13:30: demo-review fix tasks added (C, D, E): restart your runners

New tasks are on `main`, under "Added Sat 13:25 (demo review fixes)" in each plan. **P0s first.** Your runner picks them up after `tools/overnight/run.sh <claude|codex> <letter>` (it merges main each round).

- **C (Althan):**
  - **C21 (P0)** fire keep-out fallback. In R227 the 1.0 m disc cuts off a dead end, but 0.75 m works. The same bug hits 24 office rooms and 102 clinic rooms.
  - **C22 (P0)** corridor speed against density, measured in steady walking, so the credibility chart compares like with like.
- **D (Aidan):**
  - **D22 (P0)** trade-off wording. The "+1.3 trapped" is real model behavior, not an artifact: all 47 extra trapped people are in the three lobby fires, and E1 is the lobby's own exit. A fix that traps more people must say so, and say where.
  - **D23 (P0)** readable names for unnamed interior doors.
  - **D24 (P1)** tiny rooms: R203b is 0.21 m wide, so no 0.5 m smoke-grid node lies inside it.
- **E (Donovan):**
  - **E32 (P0)** what-if note contrast (axe).
  - **E33 (P1)** static mode: the Sprinklers box says it needs the backend.
  - **E34 (P1)** fix lines show trade-offs, and no list or dropdown shows a raw door id.
- **A (lead):** after D22 and D23 land, rerun the precompute so the demo files pick up the new wording and labels.

## Sat 13:20: report labels and D19 finished

**Merged:**
- ws-a: report cards show readable labels and no raw IFC ids. For example, "Exit Stair S1 (west)", and "Door between PHYSICAL EXAM (R1C18a) and PROVIDER CUBICLES (R1D16)" for an unnamed interior door. Template and live Gemini cards share the fix (`backend/llm/features.py`).
- ws-d: **D19 is complete.** The office runs ran clean with C14's terms off. Only 4 of 29 office numbers change with C14 on (see `fire/README.md`), and the headline is +49% with it off, +54% with it on.

**Still shows raw ids** (fix tasks are coming for D and E): weak-spot labels in `headlines-*.json` (from D's `door_label`), and the measured-fixes list in the app (E).

**Netlify:** the dry run passes (`python tools/deploy_demo.py`): the build and privacy scan are clean, and the demo is 13.8 MB, 1.5 MB gzipped. The live deploy waits on the lead.

## Sat 12:45: D19 merged; lunch-hour work

**Merged:** ws-d **D19** (lead takeover): `fire/refresh.py` reruns the same fires with C14's smoke-aware exit choice off and on, then lists which headline numbers changed.
- Example (168 runs, 0 failed): propped stair doors +25% -> +26% time in smoke. Widening door DL1 flips from not helping to helping.
- Office: propped stair doors +49% -> +54%. The 3rd weak spot becomes Exit Stair S2 (east), and blocking Stair S1 adds 55% more smoke time (was 60%).
- D15's and D18's batches already ran with C14 on, so their numbers stand.
- Still missing: the office's C14-off fixes. They are finishing now with `--resume`.

**Running over lunch on the lead's laptop:**
- D19's office fixes (until 13:30 at the latest).
- A: readable labels in report-card headings, with no raw IFC ids like `D$77wwb`.
- Fix tasks for **C, D and E**, from the demo review: the R227 keep-out; the "+1.3 trapped" fix wording; the R203b sliver; readable interior door labels; the what-if contrast; the Sprinklers checkbox in static mode. The tasks get appended to your plans when they're ready.

**Frame rate:** the office demo runs at about 29 FPS in a small window once no simulations run.

## Sat 12:05: A5 done; all three buildings precomputed

**Merged:** ws-a, **A5 done**. The static demo now covers all three buildings:
- the example: 2 what-if pairs;
- the office: 98 rooms x 3 seeds, what-ifs and fixes on the 8 worst rooms, 3 pairs;
- the clinic: 25 rooms x 3 seeds, 1 pair.

Each building has a report card (template text for now) and a D18 headline pack. `frontend/public/demo` is 13.8 MB (1.5 MB gzipped). The Netlify config and `tools/deploy_demo.py` are ready, but nothing is deployed: that waits on the lead.

**Needs to know:**
- **E (Donovan):**
  - `npm run qa` shows 2 axe color-contrast problems from the `.whatif-headline .dim` opacity. They appear now because the demo has real what-ifs.
  - Static mode ignores the Sprinklers checkbox.
- **D (Aidan):** office room R203b, a 1.16 m2 sliver, fails every seed in the smoke grid.
- **Lead:** the Netlify site and deploy, a curl and phone check, the freeze reruns, and live Gemini report cards.

## Sat 11:50: B15 merged; example headline pack in the demo

**Merged:**
- ws-b **B15** (Jaya): plan images (example F1/F2, office F1/F2), a ready trace of the example (`data/buildings/plans/example.trace.json`, plus `example.plan.json` and `index.json`) for the "plan to 3D" demo moment. The door-width cap is now 0.6-6.0 m, per the 11:35 ruling.
- ws-a (A5): the example's demo sweeps now carry D18's smoke percent, and the demo has the example's headline pack (`headlines-example-office.json`).

**Needs to know:**
- **A, E:** for the "building in" beat, load `data/buildings/plans/example.trace.json` in the tracer (see `buildings/README.md`).
- **Still running on the lead's laptop:** the clinic precompute (A5) and D19's office refresh.

## Sat 11:35: B15 unblocked again

- **B (Jaya):** B15 stopped on the example's lobby door DL1, a 4.0 m opening that B14's validator rejects (it only allows 0.6-3.0 m). The lead ruled on ws-b:
  - DL1 is correct, and the example contract stays as it is.
  - Raise the cap in `buildings/validate.py` to 0.6-6.0 m, and add a smoke-test case where a 4.0 m door passes and a 7.0 m door is flagged.
  - Then finish B15.

  The plan images, traced example and index from 11:19 merge into main once B15 is done.

## Sat 11:20: office demo data merged

**Merged:**
- ws-a, A5 part 1 (10:50): the example building's precomputed what-if runs, batch and report card, plus `tools/precompute_demo.py` and the Netlify config (not deployed).
- ws-a, A5 part 2: **the office demo data.** It covers 294 fires (98 rooms x 3 seeds), three what-if pairs (R143, R203c, R237b) and the office report card. The guided demo now works on the office. The example is trimmed to two pairs.

**Still running on the lead's laptop:** the clinic precompute (A5) and D19's office refresh.

**Needs to know:**
- **E, A:** weak-spot headings in the office report show raw IFC door ids (`D$77wwb`). Use the readable label.
- **D, E:** the example report says "keep the main entrance clear: +1.3 trapped per fire". The likely cause is that the main entrance sits next to the kitchen fire. It reads badly as a fix, so check the wording or the logic.
- **Everyone:** report cards are template text while Gemini is out of quota. The lead decides on billing.
- **B (Jaya):** your runner is merging main again. B15 is unblocked and next.

## Sat 09:55: D18 merged (headline pack); lead took over D19; B15 unblocked

**Merged:**
- ws-d **D18** (lead takeover): `fire/headlines.py` reads a saved batch and writes `data/runs/headlines-<id>.json` (headlines/v0, about 7 KB).
  - Office headline: "Stair doors propped open: +54% person-seconds in smoke across 36 paired fires; 90% out 0 s later on average."
  - Example headline: the same line with +26% across 12 paired fires.
  - What-if entries now carry `baseSmokeSeconds` and `smokePct`. `sources` holds relative paths only, so no local paths reach `frontend/public/demo/`.
- main: the example building's credits now mention a license ("license: free to use, no attribution needed"). That unblocks **B15**. The examples and the demo copies of the office and clinic were regenerated; the demo copies were behind `data/buildings/`. Every check passes.

**Needs to know:**
- **A, E:** the precompute picks up the headline pack (`batches[].headlines`) once ws-a merges main. E's Report tab can show the pack with no API or Gemini call; use `smokePct` instead of recomputing the percent.
- **B (Jaya):** B15 is unblocked; the lead's ruling is in the plan. It's P1 and next on your list. B7 stays superseded by C15, and B8 waits on the UMass decision.
- **D (Aidan):** the lead took over **D19** (refresh after C14 and C13b) at 09:47. It reruns the example and the office with C14's exit-choice terms off and on, about an hour on the shared laptop. D17 (P2), D20 (P1) and D21 (P1) are still yours.
- **Lead note:** the lead's open-task count treated any mention of "BLOCKED:" inside a step as a blocker, which hid D19 from 04:30 until now. Counted strictly, D has D17, D19, D20 and D21 open, and B has none.

**Still running:** A5 (demo precompute) and D19.

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
