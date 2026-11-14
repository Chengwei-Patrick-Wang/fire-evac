# Ember UI rework and simulated fire spread: design

*Sat 14 Nov 2026, afternoon. The freeze is Sun 2 AM. Builds on the main spec `2026-11-13-fire-evac-sim-design.md`.*

## Intent

Make the demo look and work like the team's Ember design (`docs/design/ember-ui.md`, especially §17, plus the UI mockup), with a plain grey, walls-only building like the reference render. Add:
- more ways to view floors;
- controls that make fire and smoke easier to see;
- agents colored by type;
- fire that spreads room to room over time, at a speed set by a building-material setting.

The spreading fire **drives the simulation**: doors close and people get trapped as rooms ignite. That way the picture, the people and every number agree.

Reference images live on the lead's laptop only (gitignored): `handoff/design/mockup-ui.webp` (layout and navigation) and `handoff/design/building-reference.webp` (building look).

## Goals

1. **Layout (design.md §17):**
   - **Top navigation:** collapsed by default behind a centered chevron at the top edge. It opens the menus (File, Edit, View, Simulation, Analysis, Settings) and a contextual toolbar.
   - **Analytics sidebar (left):** it collapses to an edge tab. It holds KPI cards (evacuated %, remaining, chokepoints, evacuation time), the evacuation-progress chart, congestion by floor, and chokepoint alerts that jump to their floor. Tabs (Overview, Risk, Report, Credibility) keep every feature that exists today.
   - **Viewer:** a dominant 3D view in the middle.
   - **Floor strip (bottom):** Whole Building, Floor 1, Floor 2…, scrolling horizontally, with a blue active state.
   - **Timeline:** always visible, with play/pause, restart, scrubber, elapsed/total time and speed.
   - **Right side:** a floating legend card and small icon buttons for the layer and visibility cards. There's no permanent right sidebar.
   - **Focus mode:** nav and sidebar both collapsed. The toggles stay keyboard-accessible.
2. **Light theme** with design.md §11 tokens:
   - colors: canvas #F8FAFC, surfaces #FFFFFF, muted #F1F5F9, text #111827 / #64748B, borders #E5E7EB, primary #2563EB, fire #F97316, severe #DC2626, caution #F59E0B, safe #16A34A;
   - Inter; radii 8 px for controls and 12 px for cards; the subtle shadow from the doc;
   - Lucide icons (`lucide-react`).

   The high-contrast theme stays.
3. **Building look (reference render):**
   - light grey floor slabs and white/light-grey extruded walls;
   - exterior walls as light translucent glass;
   - stairs visible, floors separated vertically;
   - no room color fills by default: room type shows in labels and on hover, and the risk overlay still colors rooms when on.
4. **Floor views**, chosen from the floor strip and the View menu:
   - **Stacked:** today's exploded view with a gap slider.
   - **Single floor:** isolate one floor.
   - **Side by side:** all floors laid flat in a row.
   - **Ghost:** the chosen floor solid, the others at about 15% opacity.

   Hiding a floor never changes the simulation.
5. **Fire and smoke visibility:** a visibility card with:
   - a fire glow and size slider;
   - a smoke opacity slider;
   - fire and smoke toggles;
   - a "High visibility" preset.

   Burning rooms get an orange-to-red floor tint as they ignite.
6. **Agent colors:**
   - **Default, by status (per design.md):** green for moving or out, amber for waiting or delayed, red for trapped or at risk.
   - **Legend toggle "Color by type":** six colorblind-safe profile colors (typical, older, visitor, cane, walker, wheelchair), each labeled in the legend. Color is never the only cue.
7. **Simulated fire spread:** rooms ignite on a schedule set by the material. Doors into burning rooms close to routing, people inside a burning room are trapped, and smoke grows with every burning room. The run lists each room's ignition time, and the viewer shows the spread.
8. **Material hyperparameter:** a new optional scenario field `fire.material`, one of `concrete`, `drywall` (default) or `wood`, labeled illustrative everywhere. The fire-settings popover (Edit menu, Set Fire) gets a dropdown, which runs in live mode. The static demo gets one precomputed material what-if pair on the office: wood against drywall.

## Non-goals

- No change to the frontend architecture: React, TypeScript, React Three Fiber/Drei, Zustand, Recharts and plain CSS stay. No Tailwind or shadcn.
- No projects screen, geometry editor or settings persistence beyond what exists. Fire intensity stays the existing presets.
- No validated or CFD fire spread, and no new building formats.

## Anti-goals

- Fire shown spreading where the simulation doesn't spread it, or the reverse.
- Breaking the guided tour, `npm run qa` (0 axe violations), keyboard and screen-reader access, deep links or the static site.
- Material presets or intensity shown as engineering units.

## Constraints

- Freeze Sun 2 AM. Netlify redeploys the public site from `main` on every push, so `main` must stay green.
- Contracts are frozen except for new optional fields: scenario `fire.material`, and run `fire.rooms: [{room, floor, ignite}]`. Regenerate `contracts/*.example.json` after adding them.
- One agent per folder at a time: `fire/` (D), `sim/` (C), `frontend/` except the tracer (E), and `backend/` + `tools/` + `contracts/` (A).
- Spreading fire changes every demo number, so the demo precompute reruns once, after D and C land. That takes about 2 hours on the laptop.

## Approaches

- **UI, picked: rework the current app in place.** It keeps data loading, replay, the tour and the QA and accessibility work. A Tailwind/shadcn rebuild was rejected: a rewrite risks the tour, QA and accessibility the night before submission. Restyle-only was rejected: it misses the requested layout and navigation.
- **Fire spread, picked: a room-to-room ignition schedule.** It's deterministic, cheap and easy to explain. A cell-by-cell fire front was rejected for its compute cost and because it's harder to explain. Visual-only spread was rejected because it disagrees with the simulation (anti-goal).

## How (decided)

### Fire spread (D, `fire/`)
- **Room graph at `FireModel` init:**
  - A door link joins two rooms that share a door.
  - A wall link joins two rooms that share a wall segment of at least 1 m.
  - Floors connect only through stair rooms or stair doors.
- **Schedule:** the ignition room burns from the start and is fully involved at the material's flashover time. Neighbors follow the shortest path (Dijkstra): `ignite(n) = ignite(r) + delay(link, material)`. Only rooms that ignite before `maxTime` are listed.
- **Illustrative presets** (seconds; flashover / door link / wall link), documented in `fire/README.md`:

  | Material | Flashover | Door link | Wall link |
  | --- | --- | --- | --- |
  | concrete | 600 | 300 | 1200 |
  | drywall | 300 | 180 | 600 |
  | wood | 150 | 90 | 240 |

  The builder may tune them for a legible demo, as long as wood is always faster than drywall, which is faster than concrete.
- **Smoke source:** each burning room adds the preset's heat-release curve, shifted by its ignition time and capped.
- **API:**
  - `FireModel.burning_rooms(t) -> set[tuple[str, str]]` (floor, room);
  - `FireModel.ignition_times() -> list[dict]` (`{room, floor, ignite}`);
  - `blocked_doors()` now includes doors of burning rooms.
- **Output:** the run carries `fire.rooms`, the ignition list. Checks cover monotonic material order, door links faster than wall links, and a deterministic schedule.

### Sim coupling (C, `sim/`)
- **Each step:**
  - doors of newly burning rooms join the fire blocks, so routing closes them;
  - agents inside a burning room are marked trapped, with the reason "in a burning room".
- **The origin room keeps today's keep-out**, because JuPedSim's walkable geometry can't change mid-run. Door closures and traps carry the spread.
- **Checks:** a two-room fixture where the neighbor ignites at the scheduled time, its door closes, and an agent left inside is trapped. Results stay identical when the fire doesn't spread before `maxTime`.

### Frontend (E, `frontend/`, not the tracer)
- **New shell components** wrap the existing panels: `TopNav` (chevron, menus, toolbar), `AnalyticsSidebar`, `FloorStrip`, `Timeline`, `LegendCard`, `VisibilityCard`.
- **New store state** goes in the existing Zustand store: `viewMode`, `navOpen`, `sidebarOpen`, `fireGlow`, `smokeOpacity`, `colorBy`, `material`.
- **Scene:** wall, glass and slab materials; the four view modes; burning-room tint from `run.fire.rooms` at time t; fire glow scale; smoke opacity scale; agent color by status or type.
- **Keep working:** the tour scenes, URL-hash deep links, `npm run qa`, accessibility labels (Expand navigation, Collapse navigation, Show analytics, Hide analytics), and the phone layout (panels overlay the viewer).
- **Playback speeds:** 0.25×, 0.5×, 1×, 2×, 4×, plus 10× so the 3-minute tour still fits.
- **Name:** the header brand reads "Ember", with a flame mark and the building name next to it.

### Lead (A, `backend/`, `tools/`, `contracts/`)
- **Contracts:** add `fire.material: "drywall"` to the scenario example and `fire.rooms` to the run example, then regenerate the examples. This lands first, so E and D build against it.
- **Backend:** pass `fire.material` through unchanged.
- **Precompute:** the office gets a material what-if pair (wood against drywall). Rerun every building after D and C land. Report cards name the material and the spread.
- **Then:** rehearsal and the freeze.

## Order and timeline (targets)

1. **A:** contract fields and examples (about 30 minutes). This unblocks D's output shape and E's fire visuals.
2. **In parallel:**
   - D: the fire-spread model, then C: the coupling.
   - E, in sequence: the shell and theme; then the building look and floor views; then visibility, agent colors and the spreading-fire visuals.
3. **A:** precompute rerun once D and C land: start around 9 PM, done around 11 PM. Then a full check on the live site.
4. **Freeze at 2 AM:** lock publishing in Netlify.

## Left to the builder

Exact component boundaries and CSS; the agent-type palette (colorblind-safe); floor-strip thumbnails (simple 2D silhouettes are fine); where existing features sit in the menus; spread-delay tuning within the stated order; and how the material pair is labeled in the tour.
