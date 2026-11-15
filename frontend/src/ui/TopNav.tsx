import { useRef } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import { Camera, ChevronDown, ChevronUp, Columns2, Eye, Flame, Layers3, Maximize2, Play, Upload } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useApp } from '../store/app'
import type { ResultsTab } from '../store/app'
import { SPEEDS, useClock } from '../store/clock'
import type { ViewMode } from '../scene/geometry'
import { useA11y } from './a11y'
import { claudeCrowdLimit, crowdTooBig } from '../model/brain'
import { PLACE_FIRE_FIRST, firePlaced } from '../model/scenarioDraft'
import MenuBar from './Menu'
import type { MenuDef } from './Menu'

// What each menu item and toolbar button does. Module-level, so a menu item and its toolbar twin can't drift apart.

const app = () => useApp.getState()

function openScenario(placing = false) {
  useApp.setState(placing ? { card: 'scenario', placing: true } : { card: 'scenario' })
}

function runSimulation() {
  const s = app()
  s.setCard('scenario')
  // A run needs the fire placed in a room: the Run buttons are off until it is (the scenario card is open to place it).
  if (s.draft && !s.running && firePlaced(s.draft)) void s.runScenario(s.draft)
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
  const playing = useClock((c) => c.playing)
  const speed = useClock((c) => c.speed)
  const { contrast, reduceMotion, setContrast, setReduceMotion } = useA11y()
  const { building, buildings, summaries, mode, split, runOrder, layers, draft, running, card, viewMode, resultsTab } = s
  const nRuns = runOrder.length
  const set = useApp.setState
  // Everyone asks Claude holds up to 200 people: with more, a live run is refused, and so the Run buttons are off (the scenario card says why).
  const tooMany = crowdTooBig(draft, mode === 'live')
  // And a run needs the fire placed in a room (the backend refuses one without): the Run buttons say to click a room first.
  const noFire = !!draft && !firePlaced(draft)
  const runTitle = tooMany && draft ? claudeCrowdLimit(draft.occupants.total) : noFire ? PLACE_FIRE_FIRST : undefined
  const runOff = !draft || !!running || tooMany || noFire
  // Side by side and Ghost need a second floor to lay out or to fade.
  const oneFloor = (building?.floors.length ?? 0) < 2

  const menus: MenuDef[] = [
    {
      id: 'file',
      label: 'File',
      items: [
        { kind: 'item', label: 'Open file…', onSelect: openFile },
        { kind: 'item', label: 'Trace a floor plan', onSelect: () => s.setView('tracer') },
        { kind: 'item', label: 'Print report…', onSelect: printReport },
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
        { kind: 'item', label: 'Top view', onSelect: () => set((st) => ({ topView: st.topView + 1 })), sepAbove: true },
        { kind: 'item', label: 'Reset camera', onSelect: () => set((st) => ({ fitView: st.fitView + 1 })) },
        { kind: 'item', label: 'Focus mode', onSelect: focusMode, sepAbove: true },
        // The accessibility options (they were the Settings menu).
        { kind: 'check', label: 'High contrast', checked: contrast, onSelect: () => setContrast(!contrast), sepAbove: true },
        { kind: 'check', label: 'Reduce motion', checked: reduceMotion, onSelect: () => setReduceMotion(!reduceMotion) },
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
        { kind: 'item', label: 'Run simulation', onSelect: runSimulation, disabled: runOff, title: runTitle },
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
            { label: 'This fire', value: 'results' },
            { label: 'All fires', value: 'risk' },
            { label: 'Report', value: 'report' },
          ],
          onSelect: (v) => set({ resultsTab: v as ResultsTab, sidebarOpen: true }),
        },
      ],
    },
  ]

  const tools: Tool[] = [
    { id: 'open', label: 'Open file', icon: Upload, onClick: openFile },
    { id: 'fire', label: 'Set fire', icon: Flame, onClick: () => openScenario(true) },
    { id: 'run', label: 'Run simulation', icon: Play, onClick: runSimulation, disabled: runOff, primary: true, title: runTitle },
    { id: 'layers', label: 'Layers', icon: Layers3, onClick: () => s.setCard(card === 'layers' ? null : 'layers'), expanded: card === 'layers' },
    { id: 'visibility', label: 'Visibility', icon: Eye, onClick: () => s.setCard(card === 'visibility' ? null : 'visibility'), expanded: card === 'visibility', title: 'Fire and smoke visibility' },
    { id: 'top', label: 'Top view', icon: Camera, onClick: () => set((st) => ({ topView: st.topView + 1 })) },
    { id: 'reset', label: 'Reset camera', icon: Maximize2, onClick: () => set((st) => ({ fitView: st.fitView + 1 })) },
    { id: 'split', label: 'Split', icon: Columns2, onClick: () => set((st) => ({ split: !st.split })), disabled: nRuns < 2, pressed: split, title: nRuns < 2 ? 'Split needs two runs' : 'Compare two runs side by side' },
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
