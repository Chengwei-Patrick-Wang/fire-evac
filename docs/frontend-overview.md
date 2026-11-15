# Current frontend overview

Documented November 14, 2026, from the frontend source on branch `Aidan`. This describes the implementation, rather than every feature proposed in the design spec. It is a source inspection, not a fresh browser QA report.

## What the app looks like

The frontend is a dark, full-screen evacuation simulation dashboard. A 3D building occupies the center, scenario controls sit on the left, and charts and analysis sit on the right. A playback timeline spans the bottom, followed by a narrow building-credits strip.

The desktop layout reserves 300 pixels for scenario controls and 380 pixels for results. The center takes the remaining width. The interface uses navy backgrounds, slate borders, light text, blue selection states, and an orange Run button. Controls are compact and emphasize exploration of simulation data.

There are two main views: **Replay**, for scenarios and analysis, and **Tracer**, for turning floor-plan images into building geometry.

## Top bar

The header contains:

- A building selector, with floor and room counts when summary data is available.
- Replay and Tracer view buttons.
- Tabs for loaded runs, allowing users to switch scenarios.
- Demo, Share, About, and Display controls.
- An Open file control for local JSON data.
- A Static or Live mode indicator and loading feedback.

Display settings offer high contrast and reduced motion. Share creates a link to the current public-building view. The About overlay provides project context and limitations.

## Replay: scenario panel

The left panel controls the scenario draft:

| Control | Purpose |
| --- | --- |
| Fire preset | Choose a fire type such as kitchen, bedroom, battery, trash, or liquid. |
| Fire room | Select a room, grouped by floor. |
| Click to place fire | Choose an ignition location directly in the 3D view. |
| Occupants | Set the total population. |
| Population mix | Adjust typical, older, and visitor profile shares. |
| Seed | Set the simulation's random seed. |
| Alarm time | Set the alarm delay in seconds. |
| Door overrides | Add open, closed, propped, or blocked door states. |
| Run | Request a simulation in live mode, or load an available precomputed result in static mode. |

Progress, errors, and fallback explanations appear near the controls or as a banner over the scene. In static mode, editing inputs does not create a new simulation: the app selects an available precomputed run and reports that behavior.

The **What if…** card selects a door and alternative state and offers a sprinkler checkbox in live mode. It compares baseline and variant evacuation time and trapped counts, with a smoke-exposure headline when the data supports one. In static mode, sprinklers are disabled; a note quotes a saved sprinkler comparison when available. Static replay variants are precomputed propped-door scenarios.

## Replay: 3D scene

The center shows building floors, walls, rooms, doors, and animated occupants. Users can orbit and zoom the camera, separate floors with the **Explode** slider, isolate a floor, or return to Top view or Overview.

The scene toolbar controls these layers and views:

- Room labels, smoke, fire marker, heatmap, door queues, and batch risk map.
- Occupant trails and profile lenses for highlighting selected population groups.
- Occupant coloring by movement status or profile.
- Agent view, which lets a user select a person and inspect their perspective.
- Split view for comparing two loaded runs with synchronized playback and cameras.
- Save PNG for the public building's 3D view. This excludes HTML overlays such as room labels and queue counts, and is disabled in split view and for private buildings.

A legend explains occupant colors and door states. Status categories include not moving yet, moving, waiting for help, in a stairwell, and trapped. Layers requiring unavailable data are disabled with an explanation.

The smoke display visualizes saved output from the illustrative smoke model. It is not a detailed fluid-dynamics calculation performed by the browser.

## Replay: results panel

The right panel has four tabs:

| Tab | Current contents |
| --- | --- |
| Results | Evacuation curve, exit-use chart, evacuated and trapped counts, seed, and times for 50%, 90%, and 100% to exit. Additional profile and seed-range information appears when supplied. |
| Risk map | Batch scenario context, room coloring by evacuation time or trapped count, optional crowding across fires, ranked weak spots, stability across seeds, and measured fixes. Clicking a weak spot focuses the scene on it. Live mode also offers Run batch. |
| Report | Saved headline comparisons, weak spots and measured fixes, Markdown report text, and Print report. Live mode offers Generate and Regenerate; static mode loads saved reports. |
| Credibility | Door-flow comparisons and corridor speed-versus-density charts against reference values, when calibration data exists, plus assumptions, scenario settings, model limits, and credits. |

Evacuation thresholds that were not reached display **not reached**. Ranges across seeds are described as a spread of simulated results, not confidence intervals. Failed batch runs are identified when present in the data.

The panel explicitly states: **“Illustrative fire model. Not a compliance tool. One seed is one possible night.”** Calibration charts also state that they do not validate the whole model.

## Playback and guided demo

The bottom timeline provides Play/Pause, 1×, 2×, 5×, and 10× speed, scrubbing, current time, and event markers. Keyboard controls include:

- Space: play or pause.
- Left/right arrows: seek five seconds; Shift plus arrow seeks one second.
- Home/End: go to the beginning or end.
- W: switch between a baseline and its latest what-if, when available.

The Demo button starts a guided presentation with six scenes: Hook, Building in, Judge's fire, What-if, Risk map, and Credibility. Their configured durations total three minutes. The tour uses precomputed demo runs, including when the app is in live mode, and provides captions and scene navigation.

## Tracer editor

Tracer replaces the dashboard with a drawing workspace: a tool strip, a central plan canvas, and an inspector for building, floor, and selection properties.

Users can upload a plan image, calibrate its scale with a known distance, mark a shared reference point, draw rectangular or polygonal rooms, and place doors along room edges. Rooms have names and types; stair rooms can be assigned groups that link floors. Door controls include width, state, fire-door status, and exterior-exit naming.

The editor supports selection and corner editing, undo/redo, fit-to-view, and an aligned outline of the floor below. Gemini's AI first pass proposes **rooms only** as a reviewable draft; users add doors and check the geometry. It requires the backend and configured AI service.

The inspector includes building metadata, source credits, public/private selection, floors, validation messages, and export controls. Users can download plan JSON or save/load a trace without completing backend export. Export sends the plan to the backend for normalization and saving, then offers Open in 3D. Trace saves exclude the plan images.

## Static versus live behavior

| Mode | What it enables |
| --- | --- |
| Static | Loads bundled buildings, runs, batches, headlines, and saved reports from `frontend/public/demo/`. Supports replay and analysis without a backend. Arbitrary input changes cannot generate new simulation results. |
| Live | Uses the reachable FastAPI backend to request new runs, batches, building exports, and reports. AI features additionally require service configuration and availability. |

The frontend reads `VITE_API_URL`, for example `http://localhost:8000/api`. Starting the Python server alone does not configure the frontend to use it. Restart Vite after changing frontend environment settings, then check the mode indicator. If API detection fails, the app can fall back to static mode.

## Responsive behavior and current rough edges

At widths of 900 pixels or less, the replay side panels become toggleable Scenario and Results panels so the 3D scene retains space. The tracer also adapts its layout. Keyboard focus styles, a skip-to-controls button, accessible chart summaries, high contrast, and reduced-motion support are implemented; this is not a claim of complete accessibility conformance.

Some controls and weak-spot headings still expose raw door identifiers. Measured fixes currently show **helps** or **no gain** badges; a dedicated trade-off badge is not implemented in the inspected component, even though newer backend text can describe trade-offs. Report text may come from Gemini or a saved template, so the generic AI-summary label should not be taken as proof that every saved report was AI-generated.

## Implementation map

The UI uses React and TypeScript with Vite, Three.js through React Three Fiber and Drei, Recharts, and Zustand. The browser renders and analyzes simulation output; Python handles live simulation.

| Source | Responsibility |
| --- | --- |
| `frontend/src/App.tsx` | Startup, overall layout, file opening, shared-link restoration, responsive panels. |
| `frontend/src/ui/` | Header, scenario controls, what-if card, timeline, sharing, printing, accessibility controls. |
| `frontend/src/scene/` | Building geometry, camera controls, fire placement, risk overlay, image capture. |
| `frontend/src/replay/` | Occupants, smoke, fire, heatmaps, queues, agent perspective. |
| `frontend/src/dashboard/` | Charts, statistics, weak spots, fixes, reports, credibility information. |
| `frontend/src/tracer/` | Plan drawing, editing, validation, AI draft review, export. |
| `frontend/src/data/loader.ts` | API/static data loading and mode detection. |
| `frontend/src/store/` and `frontend/src/tour/` | Application/playback state and guided presentation. |
