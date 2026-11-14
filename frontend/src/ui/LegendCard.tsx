import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useApp } from '../store/app'
import { PROFILE_COLORS, STATUS_COLORS } from '../replay/Agents'
import { PROFILE_NAMES } from '../replay/runIndex'
import { DOOR_COLORS } from '../scene/Building'

const STATUS_ITEMS: [string, string][] = [
  ['Not moving yet', STATUS_COLORS.notMoving],
  ['Moving', STATUS_COLORS.moving],
  ['Waiting for help', STATUS_COLORS.waiting],
  ['In a stairwell', STATUS_COLORS.stairwell],
  ['Trapped', STATUS_COLORS.trapped],
]

/** What the colours in the viewer mean. Replaces AgentLegend; the "Color by type" switch replaces the Toolbar3D toggle. */
export default function LegendCard() {
  const mode = useApp((s) => s.agentColor)
  const hasRun = useApp((s) => s.activeRunKey !== null)
  // Open on a desktop; on a phone it starts collapsed, because the card would cover most of the picture.
  const [open, setOpen] = useState(() => !window.matchMedia('(max-width: 900px)').matches)
  if (!hasRun) return null
  const people: [string, string][] =
    mode === 'status' ? STATUS_ITEMS : PROFILE_NAMES.map((n, i) => [n, PROFILE_COLORS[i % PROFILE_COLORS.length]])
  const byType = mode === 'profile'
  return (
    <section className={'legendcard' + (open ? '' : ' closed')} aria-label="Legend">
      <div className="lc-head">
        <h2>Legend</h2>
        <button
          type="button"
          className="lc-toggle"
          aria-label={open ? 'Hide legend' : 'Show legend'}
          title={open ? 'Hide legend' : 'Show legend'}
          aria-expanded={open}
          aria-controls="legend-body"
          onClick={() => setOpen(!open)}
        >
          {open ? <ChevronUp size={16} strokeWidth={1.75} aria-hidden="true" /> : <ChevronDown size={16} strokeWidth={1.75} aria-hidden="true" />}
        </button>
      </div>
      {open && (
        <div id="legend-body" className="lc-body">
          <ul>
            {people.map(([name, c]) => (
              <li key={name}>
                <i className="sw dot" style={{ background: c }} />
                {name}
              </li>
            ))}
          </ul>
          <button
            type="button"
            role="switch"
            aria-checked={byType}
            className="lc-switch"
            onClick={() => useApp.setState({ agentColor: byType ? 'status' : 'profile' })}
          >
            <span className="lc-track" aria-hidden="true">
              <span className="lc-thumb" />
            </span>
            Color by type
          </button>
          <ul>
            {(Object.keys(DOOR_COLORS) as (keyof typeof DOOR_COLORS)[]).map((k) => (
              <li key={k}>
                <i className="sw" style={{ background: DOOR_COLORS[k] }} />
                Door {k}
              </li>
            ))}
            <li>
              <i className="sw ring" />
              Queue at a door (ring size = people)
            </li>
            <li>
              <i className="sw" style={{ background: '#F97316' }} />
              Fire
            </li>
            <li>
              <i className="sw" style={{ background: '#6B7280' }} />
              Smoke
            </li>
          </ul>
        </div>
      )}
    </section>
  )
}
