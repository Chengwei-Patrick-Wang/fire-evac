# Ember — Fire & Evacuation Simulation UI

Version: 1.0 | Status: implementation-ready UI specification | Target: desktop web MVP

## 1. Purpose and users
Ember helps architects and building engineers inspect fire spread, simulate occupant evacuation, and identify evacuation chokepoints within a multi-story building. It is a planning and exploratory simulation interface, not a certified life-safety assessment tool. All outputs must clearly distinguish simulated estimates from verified engineering conclusions.

## 2. Design principles
- Minimal light theme; the building is the visual centerpiece.
- Google Docs-style top navigation and contextual toolbar.
- Reveal advanced controls progressively; avoid clutter.
- Separate simulation state from visibility state: hidden floors remain physically simulated.
- Use orange/red for fire and hazards, blue for controls and evacuation routes, green for safe exits/evacuated occupants, yellow for delayed occupants.
- Never rely on color alone; pair with labels/icons and accessible descriptions.

## 3. Screen architecture
1. Projects: create, open, rename, duplicate projects.
2. Blueprint Import: upload PDF/PNG/JPG floor plans, review extracted geometry, confirm scale, floors, stairs and exits. No building geometry editor in MVP; if parsing is wrong, re-upload or abort.
3. Simulation Workspace: top menu, action toolbar, left analytics panel, central 3D viewer, floating right floor/layer controls, bottom playback timeline.
4. Analysis: larger charts, chokepoint timeline and scenario comparisons (comparison may be post-MVP).
5. Settings: modal/dialog with General, Visualization, Simulation, Advanced tabs.

## 4. Desktop layout
Target 1440px+ viewport. Top application header 56px, menu bar 36px, contextual toolbar 56px, bottom timeline 76px. Workspace fills remaining height. Left analytics panel width 300–340px, collapsible to an icon rail. Central WebGL viewer flexes to remaining space. Right floor visibility and legend are floating cards (~250px) overlaying the viewer, collapsible. On smaller screens, collapse analytics and hide nonessential toolbar labels.

### Header and menus
Brand at left: flame mark + Ember; project title next to it. Right: saved state, help, settings/account. Menu labels: File, Edit, View, Simulation, Analysis, Settings.
- File: New, Upload Blueprint, Save, Export.
- Edit: Set Fire Location, Fire Intensity, Undo/Redo for scenario changes.
- View: Floor Visibility, Camera Presets, Layers, Reset Camera.
- Simulation: Start/Pause, Restart, Playback Speed, Scenario Setup.
- Analysis: Evacuation, Chokepoints, Fire Spread, Compare Runs.
- Settings: Open tabbed dialog.

### Contextual toolbar
Upload Blueprint | Set Fire | Intensity | Floors | Visibility | Camera | Run Simulation. Use Lucide icons: upload, flame, sliders-horizontal, layers-3, eye, camera, play, settings-2, chart-no-axes-column, alert-triangle.

## 5. 3D viewer
- Default: isometric perspective, four example floors separated vertically by a small consistent gap, preserving floor alignment and visible stair connections.
- Stacked mode: each floor independently togglable; show-all shortcut.
- Single-floor mode: isolate exactly one floor; dropdown or floor list switches selection.
- Camera: orbit, pan, zoom, fit, reset, top/front/isometric presets.
- Display walls, rooms, doors, staircases, exits; no room-inspector interaction in MVP.
- Click on geometry in Set Fire mode to place ignition marker, show selected floor/location and intensity slider. No ignition by clicking UI overlays.
- Realistic flames and smoke as visualization layers; allow disabling for clarity/performance.
- Occupants shown as small colored dots/circles. Green = moving/safe; amber = delayed; red = exposed/at risk. Exact categories require simulation definitions.
- Blue directional arrows/lines show evacuation routes. Highlight chokepoints with red/orange transparent zones and a marker; clicking an alert focuses camera and floor.
- When a floor is hidden, simulation still includes it; show a note if hidden hazards affect visible occupants.

## 6. Fire scenario
MVP inputs: ignition position and fire intensity (0–100% simplified preset). Explain that intensity must be mapped to a documented physical scenario by the engine; do not present percentage as an engineering unit. User clicks Run; validate geometry, exits, stairs, occupant configuration, and scenario completeness first. Show blocking errors and nonblocking warnings.

## 7. Timeline
Bottom fixed timeline with Restart, Play/Pause, elapsed/total simulated time, scrubber, speed selector (0.25x, 0.5x, 1x, 2x, 4x). Scrubbing reads stored or cached simulation snapshots. Play/Pause state, current time, and speed are synchronized with rendering and analytics. Playback speed affects visualization playback, not the physics of the simulated fire. Provide loading/progress and clear 'Simulation complete' state.

## 8. Analytics sidebar
Collapsible left panel, default open. Summary cards: evacuated percent/count, remaining occupants, detected chokepoints. Evacuation-progress chart over simulated time, congestion by floor bars, fire-affected areas, and alert list. Each chokepoint alert includes floor, location, severity, a measurable reason (e.g. density or queue delay), and jump-to-location interaction. Clicking a point on chart scrubs timeline. Show data provenance and assumptions; do not invent real-world safety guarantees.

## 9. Settings tabs
- General: autosave, default project view, units.
- Visualization: smoke/fire layer, floor transparency, occupant markers, quality/performance, accessible contrast.
- Simulation: duration, default speed, supported occupant presets and scenario defaults.
- Advanced: engine/model selection (only supported engines), spatial/time resolution, diagnostic logs, warnings.
Settings dialog uses tabs, concise descriptions, clear defaults, Cancel/Save where applicable.

## 10. Blueprint import
Upload PDF, PNG or JPG; select/order floors; confirm scale and floor heights; preview detected walls, doors, stairs, and exits; verify connections and evacuation geometry. MVP is read-only after import: no manual editing of walls or doors. If extraction is uncertain, display flagged issues and prevent misleading simulation claims. Provide a replace-upload flow. Architecture should allow future manual correction, but do not expose editor controls now.

## 11. Design tokens
- Canvas: #F8FAFC; surfaces: #FFFFFF; muted surface: #F1F5F9.
- Text: #111827; secondary: #64748B; borders: #E5E7EB.
- Primary blue: #2563EB; hover #1D4ED8.
- Fire orange: #F97316; severe red: #DC2626; caution amber: #F59E0B; safe green: #16A34A.
- Font: Inter or Geist; body 14px; secondary 12px; headings 18–24px.
- Radius: 8px controls, 12px cards; subtle shadow 0 2px 8px rgba(15,23,42,.06).
- Icon set: Lucide, 18–20px, consistent 1.75–2px stroke.
- Spacing: 4/8/12/16/24px scale.

## 12. Component inventory
`AppShell`, `TopHeader`, `MenuBar`, `ContextToolbar`, `AnalyticsSidebar`, `MetricCard`, `EvacuationChart`, `CongestionBars`, `ChokepointAlert`, `BuildingCanvas`, `CameraControls`, `FloorVisibilityCard`, `LayerLegend`, `IgnitionMarker`, `FireSettingsPopover`, `SimulationTimeline`, `SettingsDialog`, `BlueprintUploadWizard`, `ImportValidationPanel`, `EmptyState`, `SimulationStatus`.

## 13. Suggested front-end architecture
React + TypeScript, Tailwind CSS, shadcn/ui, Lucide React, React Three Fiber + Drei, and Recharts. Keep simulation engine separate from rendering. Suggested state: `project`, `geometry`, `floors`, `visibleFloorIds`, `viewMode`, `camera`, `ignition`, `fireIntensity`, `simulationStatus`, `simulatedTime`, `duration`, `playbackSpeed`, `snapshots`, `metrics`, `alerts`, `layers`. Use a small client state store (e.g. Zustand). No fabricated simulation results in production; mock data must be labeled as demo data.

Example contracts:
```ts
type Floor = { id: string; label: string; elevationM: number; geometryRef: string };
type Ignition = { floorId: string; position: [number, number, number]; intensityPreset: number };
type Occupant = { id: string; floorId: string; position: [number, number, number]; status: 'moving'|'delayed'|'at_risk'|'evacuated' };
type Chokepoint = { id: string; floorId: string; position: [number, number, number]; severity: 'warning'|'critical'; reason: string; value?: number; unit?: string };
type SimulationSnapshot = { timeSeconds: number; occupants: Occupant[]; chokepoints: Chokepoint[]; evacuatedCount: number; remainingCount: number; fireVisualizationRef?: string; smokeVisualizationRef?: string };
```

## 14. Key interactions and acceptance criteria
1. Upload blueprint; show processing, preview, and geometry verification; no unverified automatic success.
2. All floors appear separated in the default 3D view.
3. User can toggle any combination of floors in stacked mode, or exactly one in single-floor mode.
4. Hiding floors never changes simulation calculations.
5. Set Fire mode accepts a click on building geometry; shows marker and intensity slider.
6. Run validates inputs and enters running/loading/completed or error states.
7. Play/Pause, restart, speed, and scrubber control playback of snapshots.
8. Analytics metrics and markers update at the selected simulated time.
9. Selecting a chokepoint alert highlights the zone and focuses its floor.
10. Left sidebar, floor controls, and settings can be collapsed or dismissed without losing state.
11. Keyboard focus, tooltips, accessible labels, and reduced-motion settings are supported.
12. UI clearly distinguishes mock/demo output from validated model output.

## 15. Scope and milestones
**MVP:** project shell, blueprint upload/verification, read-only exploded 3D building, floor visibility, fire point/intensity, mock simulation playback integration interface, occupant dots, evacuation arrows, chokepoint overlays, analytics, settings.

**Engine integration:** replace mock snapshots with backend fire/evacuation engine outputs; validate model assumptions and units; performance-test larger buildings.

**Later:** multi-scenario comparison, advanced evacuation presets, exportable reports, model editing/corrections, collaborative review.

## 16. Mockup references
- `mockup-1-engineering-dashboard.png`: data-rich workspace with four floors and left analytics.
- `mockup-2-simulation-workspace.png`: focused simulation with floating fire settings and alerts.
- `mockup-3-minimal-workspace.png`: restrained MVP-oriented dashboard with prominent viewer.

All three images are concept mockups with illustrative values, not functional UI screenshots or engineering simulation outputs.

## 17. Revised minimal layout (November 14, 2026)
This section supersedes any earlier requirement for permanently visible top navigation, toolbars, or right-side panels.

- **Top navigation:** hidden by default. A small centered downward chevron attached to the top edge expands a Google Docs-style menu and contextual toolbar downward. When expanded, the chevron flips upward and collapses the navigation. The control remains accessible in either state.
- **Analytics:** left sidebar only. It can independently collapse to a narrow edge tab and expand without changing the simulation. Contains evacuation KPIs, progress chart, floor congestion, and actionable chokepoint alerts. Clicking an alert focuses the corresponding floor/location.
- **Viewer:** dominant, full-building isometric 3D canvas. Floors are separated slightly vertically; users can orbit, pan, zoom, reset, and select all floors or one floor. Hidden floors remain simulated.
- **Floor navigation:** persistent compact horizontal strip at bottom: Whole Building, Floor 1, Floor 2, etc. Horizontal scrolling supports many floors; selected item has a clear blue active state. A single-floor selection isolates that floor in the viewer.
- **Simulation timeline:** always visible at the bottom, even when both navigation and analytics are collapsed. Includes play/pause, restart, draggable time scrubber, elapsed/total time, and speed selection. Time scrubbing updates the building, occupant dots, fire/smoke, paths, and analytics from the same simulation snapshot.
- **Overlays:** realistic flames/smoke, small green/yellow/red occupant dots, blue evacuation arrows, and red/orange chokepoint highlights. Small floating right-side icons may open layer/floor controls, but no permanently open right sidebar.
- **Default view:** top navigation collapsed; analytics may start expanded for first-time users but its collapse state is retained; Whole Building selected; bottom timeline visible.
- **Focus mode:** navigation collapsed + analytics collapsed. Viewer occupies all available area above the bottom strip. Top toggle and left-edge analytics toggle remain discoverable and keyboard-accessible.
- **Responsive behavior:** on smaller desktops, panels overlay the viewer rather than compressing it; the bottom floor strip scrolls horizontally; timeline remains operable.
- **Accessibility:** arrow controls have descriptive tooltips and accessible names (Expand navigation, Collapse navigation, Show analytics, Hide analytics); keyboard activation, visible focus, and state announcements.

### Updated mockups
- `mockup-1-top-toggle-left-analytics.png`: analytics expanded at left; centered top-edge navigation toggle; whole-building view.
- `mockup-2-focused-left-analytics.png`: focused analysis layout with top-edge chevron and always-visible bottom timeline.
- `mockup-3-minimal-left-analytics.png`: minimalist variant with compact analytics and whole-building/floor strip.

Images are visual design references with illustrative values, not validated simulation results.
