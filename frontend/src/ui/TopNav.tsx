import { useRef } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import { Camera, ChevronDown, ChevronUp, Columns2, Eye, Flame, GitCompare, ImageDown, Layers3, Maximize2, PersonStanding, Play, Share2, Upload } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useApp } from '../store/app'
import type { ResultsTab } from '../store/app'
import { SPEEDS, useClock } from '../store/clock'
import { useTour } from '../tour/tour'
import { captureView } from '../scene/capture'
import type { ViewMode } from '../scene/geometry'
import { useA11y } from './a11y'
import MenuBar from './Menu'
import type { MenuDef } from './Menu'

// What each menu item and toolbar button does. Module-level, so a menu item and its toolbar twin can't drift apart.

const app = () => useApp.getState()

function savePng() {
  const b = app().building
  const url = captureView()
  if (!url || !b) return
  const a = document.createElement('a')
  a.href = url
  a.download = `fire-evac-${b.id}-t${Math.round(useClock.getState().t)}s.png`
  document.body.appendChild(a)
  a.click()
  a.remove()
}

function toggleAgentView() {
  const on = !app().pickAgent
  useApp.setState({ pickAgent: on, notice: on ? 'Click a person to see what they see' : null })
}

function openScenario(placing = false) {
  useApp.setState(placing ? { card: 'scenario', placing: true } : { card: 'scenario' })
}

function runSimulation() {
  const s = app()
  s.setCard('scenario')
  if (s.draft && !s.running) void s.runScenario(s.draft)
}

/** Opens the scenario card, then scrolls its What-if box into view and focuses the door select (after the card's own first-control focus). */
function openWhatIf() {
  app().setCard('scenario')
  requestAnimationFrame(() =>
    setTimeout(() => {
      document.querySelector('.scenario .whatif')?.scrollIntoView({ block: 'start' })
      document.querySelector<HTMLSelectElement>('.scenario .whatif select[aria-label="Door"]')?.focus({ preventScroll: true })
    }, 0),
  )
}

function restart() {
  useClock.getState().seek(0)
  useClock.setState({ playing: true })
}

/** Navigation and analytics both collapsed; focus goes to the top toggle, which stays reachable. */
function focusMode() {
  useApp.setState({ navOpen: false, sidebarOpen: false })
  document.getElementById('nav-toggle')?.focus()
}

function toggleTour() {
  const t = useTour.getState()
  if (t.scene !== null) t.stop()
  else t.start()
}

function printReport() {
  useApp.setState({ resultsTab: 'report', sidebarOpen: true })
  app().setPrintView(true)
}

const modeTitle = (mode: string) => (mode === 'live' ? 'Live: the backend runs new simulations' : 'Static: precomputed runs only, no backend')

interface Tool {
  id: string
  label: string
  icon: LucideIcon
  onClick: () => void
  disabled?: boolean
  title?: string
  pressed?: boolean
  expanded?: boolean
  primary?: boolean
}

function Toolbar({ tools }: { tools: Tool[] }) {
  // Arrows move between the buttons (and keep the replay's own arrow-key scrubbing from firing while one is focused).
  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.ctrlKey || e.altKey || e.metaKey) return
    const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']
    if (!keys.includes(e.key)) return
    const items = [...e.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')]
    const at = items.indexOf(document.activeElement as HTMLButtonElement)
    if (at < 0 || items.length === 0) return
    const j = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : (at + (e.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length
    e.preventDefault()
    e.stopPropagation()
    items[j].focus()
  }
  return (
    <div className="ctxbar" role="toolbar" aria-label="Tools" onKeyDown={onKeyDown}>
      {tools.map((t) => {
        const Icon = t.icon
        return (
          <button
            key={t.id}
            type="button"
            className={'tool' + (t.pressed ? ' on' : '') + (t.primary ? ' primary' : '')}
            aria-label={t.label}
            title={t.title ?? t.label}
            aria-pressed={t.pressed}
            aria-expanded={t.expanded}
            disabled={t.disabled}
            onClick={t.onClick}
          >
            <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
            <span className="tool-label">{t.label}</span>
          </button>
        )
      })}
    </div>
  )
}

function NavBody({ onSelectBuilding, openFile }: { onSelectBuilding: (id: string) => void; openFile: () => void }) {
  const s = useApp()
  const touring = useTour((t) => t.scene !== null)
  const playing = useClock((c) => c.playing)
  const speed = useClock((c) => c.speed)
  const { contrast, reduceMotion, setContrast, setReduceMotion } = useA11y()
  const { building, buildings, summaries, mode, split, runOrder, activeRunKey, pickAgent, layers, placing, draft, running, card, share, colorBy, viewMode, resultsTab } = s
  const hasRun = activeRunKey !== null
  const nRuns = runOrder.length
  const priv = !!building?.private
  const pngTitle = split ? 'Turn off Split to save the 3D view' : priv ? 'Private building: do not screenshot or publish' : 'Room labels and queue counts are page overlays and are not in the image'
  const set = useApp.setState
  // Side by side and Ghost need a second floor to lay out or to fade.
  const oneFloor = (building?.floors.length ?? 0) < 2

  const menus: MenuDef[] = [
    {
      id: 'file',
      label: 'File',
      items: [
        { kind: 'item', label: 'Open file…', onSelect: openFile },
        { kind: 'item', label: 'Trace a floor plan', onSelect: () => s.setView('tracer') },
        { kind: 'item', label: 'Share link and QR code…', onSelect: () => s.setShare(true) },
        { kind: 'item', label: 'Save 3D view as PNG', onSelect: savePng, disabled: split || priv, title: pngTitle },
        { kind: 'item', label: 'Print report…', onSelect: printReport },
      ],
    },
    {
      id: 'edit',
      label: 'Edit',
      items: [
        { kind: 'item', label: 'Set fire…', onSelect: () => openScenario(true) },
        { kind: 'check', label: 'Place fire by clicking', checked: placing, onSelect: () => s.setPlacing(!placing) },
      ],
    },
    {
      id: 'view',
      label: 'View',
      items: [
        {
          kind: 'radios',
          label: 'Floor view',
          value: viewMode,
          options: [
            { label: 'Stacked', value: 'stacked' },
            { label: 'Single floor', value: 'single' },
            { label: 'Side by side', value: 'side', disabled: oneFloor, title: oneFloor ? 'This building has one floor' : undefined },
            { label: 'Ghost', value: 'ghost', disabled: oneFloor, title: oneFloor ? 'This building has one floor' : undefined },
          ],
          onSelect: (v) => s.setViewMode(v as ViewMode),
        },
        { kind: 'item', label: 'Layers…', onSelect: () => s.setCard('layers'), sepAbove: true },
        { kind: 'item', label: 'Fire and smoke visibility…', onSelect: () => s.setCard('visibility') },
        { kind: 'check', label: 'Room labels', checked: layers.labels, onSelect: () => set((st) => ({ layers: { ...st.layers, labels: !st.layers.labels } })) },
        { kind: 'check', label: 'Split screen', checked: split, disabled: nRuns < 2, onSelect: () => set((st) => ({ split: !st.split })) },
        { kind: 'item', label: "Agent's-eye view", onSelect: toggleAgentView, disabled: split || !hasRun },
        { kind: 'item', label: 'Top view', onSelect: () => set((st) => ({ topView: st.topView + 1 })), sepAbove: true },
        { kind: 'item', label: 'Reset camera', onSelect: () => set((st) => ({ fitView: st.fitView + 1 })) },
        { kind: 'item', label: 'Focus mode', onSelect: focusMode, sepAbove: true },
      ],
    },
    {
      id: 'simulation',
      label: 'Simulation',
      items: [
        { kind: 'item', label: playing ? 'Pause' : 'Play', keys: 'Space', onSelect: () => useClock.getState().toggle() },
        { kind: 'item', label: 'Restart', onSelect: restart },
        {
          kind: 'radios',
          label: 'Playback speed',
          value: String(speed),
          options: SPEEDS.map((v) => ({ label: `${v}×`, value: String(v) })),
          onSelect: (v) => useClock.getState().setSpeed(Number(v)),
          sepAbove: true,
        },
        { kind: 'item', label: 'Scenario setup…', onSelect: () => openScenario(), sepAbove: true },
        { kind: 'item', label: 'Run simulation', onSelect: runSimulation, disabled: !draft || !!running },
        { kind: 'item', label: touring ? 'Stop guided demo' : 'Guided demo', onSelect: toggleTour, sepAbove: true },
      ],
    },
    {
      id: 'analysis',
      label: 'Analysis',
      items: [
        {
          kind: 'radios',
          label: 'Analytics',
          value: resultsTab,
          options: [
            { label: 'Overview', value: 'results' },
            { label: 'Risk', value: 'risk' },
            { label: 'Report', value: 'report' },
            { label: 'Credibility', value: 'cred' },
          ],
          onSelect: (v) => set({ resultsTab: v as ResultsTab, sidebarOpen: true }),
        },
        { kind: 'item', label: 'What-if…', onSelect: openWhatIf, sepAbove: true },
      ],
    },
    {
      id: 'settings',
      label: 'Settings',
      items: [
        { kind: 'check', label: 'High contrast', checked: contrast, onSelect: () => setContrast(!contrast) },
        { kind: 'check', label: 'Reduce motion', checked: reduceMotion, onSelect: () => setReduceMotion(!reduceMotion) },
        { kind: 'check', label: 'Color people by type', checked: colorBy === 'type', onSelect: () => set({ colorBy: colorBy === 'type' ? 'status' : 'type' }) },
      ],
    },
  ]

  const tools: Tool[] = [
    { id: 'open', label: 'Open file', icon: Upload, onClick: openFile },
    { id: 'fire', label: 'Set fire', icon: Flame, onClick: () => openScenario(true) },
    { id: 'run', label: 'Run simulation', icon: Play, onClick: runSimulation, disabled: !draft || !!running, primary: true },
    { id: 'layers', label: 'Layers', icon: Layers3, onClick: () => s.setCard(card === 'layers' ? null : 'layers'), expanded: card === 'layers' },
    { id: 'visibility', label: 'Visibility', icon: Eye, onClick: () => s.setCard(card === 'visibility' ? null : 'visibility'), expanded: card === 'visibility', title: 'Fire and smoke visibility' },
    { id: 'top', label: 'Top view', icon: Camera, onClick: () => set((st) => ({ topView: st.topView + 1 })) },
    { id: 'reset', label: 'Reset camera', icon: Maximize2, onClick: () => set((st) => ({ fitView: st.fitView + 1 })) },
    { id: 'split', label: 'Split', icon: Columns2, onClick: () => set((st) => ({ split: !st.split })), disabled: nRuns < 2, pressed: split, title: nRuns < 2 ? 'Split needs two runs' : 'Compare two runs side by side' },
    { id: 'agent', label: 'Agent view', icon: PersonStanding, onClick: toggleAgentView, disabled: split || !hasRun, pressed: pickAgent },
    { id: 'whatif', label: 'What-if', icon: GitCompare, onClick: openWhatIf },
    { id: 'png', label: 'Save PNG', icon: ImageDown, onClick: savePng, disabled: split || priv, title: pngTitle },
    { id: 'share', label: 'Share', icon: Share2, onClick: () => s.setShare(!share) },
  ]

  return (
    <>
      <div className="menubar">
        <MenuBar menus={menus} />
        <div className="menubar-right">
          <select aria-label="Building" value={building?.id ?? ''} onChange={(e) => onSelectBuilding(e.target.value)}>
            {building && !buildings.some((b) => b.id === building.id) && <option value={building.id}>{building.name}</option>}
            {buildings.map((b) => (
              <option key={b.id} value={b.id}>
                {summaries[b.id] && summaries[b.id].floors && summaries[b.id].rooms
                  ? `${b.name} · ${summaries[b.id].floors} floors · ${summaries[b.id].rooms} rooms`
                  : `${b.name}${b.floors ? ` · ${b.floors} floors` : ''}`}
                {b.private ? ' (private)' : ''}
              </option>
            ))}
          </select>
          <span className="mode mode-label" title={modeTitle(mode)}>
            {mode}
          </span>
          <button
            type="button"
            className="demo"
            onClick={(e) => {
              toggleTour()
              e.currentTarget.blur()
            }}
          >
            {touring ? 'Stop demo' : 'Demo'}
          </button>
          <button type="button" onClick={() => s.setAbout(true)}>
            About
          </button>
        </div>
      </div>
      <Toolbar tools={tools} />
    </>
  )
}

/**
 * The top navigation: a chevron tab on the top edge that drops the menus and the toolbar down over the viewer (it never resizes
 * the canvas). `#topnav` is always in the DOM and `hidden` while collapsed, so the toggle's aria-controls always points at it;
 * `#open-file` lives outside it so "Open file" works with the nav collapsed.
 */
export default function TopNav({ onSelectBuilding, onOpenFile }: { onSelectBuilding: (id: string) => void; onOpenFile: (f: File) => void }) {
  const navOpen = useApp((s) => s.navOpen)
  const fileRef = useRef<HTMLInputElement>(null)
  const label = navOpen ? 'Collapse navigation' : 'Expand navigation'
  return (
    <>
      <input
        id="open-file"
        ref={fileRef}
        type="file"
        accept=".json,application/json"
        aria-label="Open file"
        tabIndex={-1}
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) onOpenFile(f)
          if (fileRef.current) fileRef.current.value = ''
        }}
      />
      <button
        id="nav-toggle"
        type="button"
        className={'navtoggle' + (navOpen ? ' open' : '')}
        aria-label={label}
        title={label}
        aria-expanded={navOpen}
        aria-controls="topnav"
        onClick={() => useApp.getState().setNavOpen(!navOpen)}
      >
        {navOpen ? <ChevronUp size={18} strokeWidth={1.75} aria-hidden="true" /> : <ChevronDown size={18} strokeWidth={1.75} aria-hidden="true" />}
      </button>
      <div id="topnav" className="topnav" hidden={!navOpen}>
        {navOpen && <NavBody onSelectBuilding={onSelectBuilding} openFile={() => fileRef.current?.click()} />}
      </div>
    </>
  )
}
