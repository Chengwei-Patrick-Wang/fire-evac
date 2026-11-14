# Demo and visuals

## Visuals

| Visual | What judges see | How | Priority |
| --- | --- | --- | --- |
| Plan-to-3D reveal | Plan or IFC model rising into 3D | Tween wall height 0 → 3 m; for IFC, fade in the real model | Core (opening hook) |
| 3D evacuation replay | Agents colored by profile, glowing fire, thickening smoke | InstancedMesh agents; per-floor smoke DataTexture | Core |
| Density heatmap | Where crowding builds | Counts per 0.5 m cell; color overlay | Core |
| Queue rings at doors | Rings grow with each door's queue, with live counts | Agents within ~2 m of each door per frame | Core |
| Evacuation curve | Share of people out over time, one line per scenario | Recharts or Plotly from exit events | Core |
| What-if split screen | Same fire with a propped stair door, a blocked exit or a widened door, in sync | Two viewports on one clock | Core ("so what") |
| Ignition risk map | Each room colored by how bad a fire starting there would be | From the batch of 20–50 runs | Core (the result that sets you apart) |
| Report card | Top three weak spots, numbers and fixes in plain language | One LLM call on the metrics | Core |
| Exit criticality | Each exit colored by how much evacuation time grows when it's blocked | One blocked-exit run per exit | Stretch |
| Accessibility lens | Only agents with mobility needs; timers over people waiting for help | Filter by profile | Stretch (accessibility prize) |
| Trails | Faded paths people took | Line strips from recent positions | Stretch |
| Agent's-eye view | First-person camera as visibility drops | Camera on an agent; fog from local smoke | Stretch |
| Calibration chart | Simulated vs measured door flow | Rebuild a Jülich bottleneck experiment | Stretch (credibility) |

## Screen layout

One screen, so the story never needs a tab switch:
- **Top bar:** building picker, upload a plan or load IFC, scenario tabs (baseline, door propped, exit blocked).
- **Left (Scenario):** fire type and size, click to place the fire, occupant count and mix, door states, run or load a saved run.
- **Center (3D replay):** agents by profile, fire and smoke; toggles for heatmap, queue rings and trails; floors stacked or one at a time; split screen.
- **Right (Results):** evacuation curve, exit use by profile, top three weak spots, ignition risk map, report card.
- **Bottom:** time scrubber with play, pause, 1–10× speed, and marks for the alarm and blocked doors.

## Demo script (about 3 minutes)

1. **Hook (20 s):** "Where would people get stuck if this building caught fire? Today that usually takes an engineer and specialist software to answer."
2. **Load (30 s):** drop in the IFC model, or photograph a printed plan; the building rises into 3D.
3. **Judge's fire (50 s):** a judge clicks where the fire starts. Play it: smoke spreads, queues ring the nearest stair, the heatmap glows.
4. **What-if (30 s):** split screen with the stair door propped open. Smoke reaches the stair, agents re-route, and the evacuation curve shifts right.
5. **Risk map and report (30 s):** the map from 30 ignition points and the report card's top three weak spots.
6. **Credibility (20 s):** door-flow calibration, the fire model labeled illustrative, real-building results shared privately.

## Demo-proofing

- Precompute every scenario you plan to show, and keep a screen recording as backup.
- Run only the judge's fire live; 300 agents took 1–10 s to simulate in tests.
- Bring a printed floor plan for the photo-upload moment, if the tracing path works.
- Put the replay behind a link or QR code so judges can scrub it on their phones.
