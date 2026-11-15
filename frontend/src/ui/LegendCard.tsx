import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useApp } from '../store/app'
import { STATUS_COLORS, TYPE_COLORS } from '../replay/Agents'
import { PROFILE_NAMES } from '../replay/runIndex'
import { CLOSED_BY_FIRE_COLOR } from '../scene/Building'
import { readSpread } from '../model/fireSpread'
import { claudeIdx } from '../model/brain'

interface Row {
  name: string
  color: string
  /** drawn smaller, as the people in a stairwell are */
  small?: boolean
  /** a dot with the red ring that trapped people get */
  ringed?: boolean
  /** only the red ring, no dot */
  ringOnly?: boolean
  /** only the pink ring of the people who ask Claude */
  claude?: boolean
}

const STATUS_ROWS: Row[] = [
  { name: 'Moving', color: STATUS_COLORS.moving },
  { name: 'In a stairwell', color: STATUS_COLORS.stairwell, small: true },
  { name: 'Delayed or waiting', color: STATUS_COLORS.waiting },
  { name: 'Trapped', color: STATUS_COLORS.trapped, ringed: true },
]
const TYPE_ROWS: Row[] = [
  ...PROFILE_NAMES.map((name, i) => ({ name, color: TYPE_COLORS[i] })),
  { name: 'Trapped (red ring)', color: STATUS_COLORS.trapped, ringOnly: true },
]
/** Shown only for a run in which people ask Claude (its agents flagged `llm`, or `llm` decisions in its events). */
const CLAUDE_ROW: Row = { name: 'Asks Claude (pink ring)', color: '#E879F9', ringOnly: true, claude: true }

/** What the colours in the viewer mean. The "Color by type" switch swaps the people rows between status and mobility type. */
export default function LegendCard() {
  const colorBy = useApp((s) => s.colorBy)
  const hasRun = useApp((s) => s.activeRunKey !== null)
  // A run that carries a spread (fire.rooms) also draws burning rooms, their markers and the doors the fire closes.
  const hasSpread = useApp((s) => readSpread(s.activeRunKey ? s.runs[s.activeRunKey]?.run : undefined) !== null)
  const hasClaude = useApp((s) => claudeIdx(s.activeRunKey ? s.runs[s.activeRunKey]?.run : undefined).length > 0)
  // Open on a desktop; on a phone it starts collapsed, because the card would cover most of the picture.
  const [open, setOpen] = useState(() => !window.matchMedia('(max-width: 900px)').matches)
  if (!hasRun) return null
  const byType = colorBy === 'type'
  const people = [...(byType ? TYPE_ROWS : STATUS_ROWS), ...(hasClaude ? [CLAUDE_ROW] : [])]
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
            {people.map((r) => (
              <li key={r.name}>
                {r.ringOnly ? (
                  <i className={'sw ring ' + (r.claude ? 'claude' : 'red')} />
                ) : (
                  <i className={'sw dot' + (r.small ? ' small' : '') + (r.ringed ? ' ringed' : '')} style={{ background: r.color }} />
                )}
                {r.name}
              </li>
            ))}
          </ul>
          <button
            type="button"
            role="switch"
            aria-checked={byType}
            className="lc-switch"
            onClick={() => useApp.setState({ colorBy: byType ? 'status' : 'type' })}
          >
            <span className="lc-track" aria-hidden="true">
              <span className="lc-thumb" />
            </span>
            Color by type
          </button>
          <ul>
            <li>
              <i className="sw ring" />
              Queue at a door (ring size = people)
            </li>
            <li>
              <i className="sw" style={{ background: '#F97316' }} />
              Fire
            </li>
            {hasSpread && (
              <>
                <li>
                  <i className="sw ramp" />
                  Burning room (illustrative)
                </li>
                <li>
                  <i className="sw cone" />
                  Fire marker
                </li>
                <li>
                  <i className="sw" style={{ background: CLOSED_BY_FIRE_COLOR }} />
                  Closed by fire
                </li>
              </>
            )}
            <li>
              <i className="sw" style={{ background: '#6B7280' }} />
              Smoke
            </li>
          </ul>
          <p className="lc-note">People who are out leave the view.</p>
        </div>
      )}
    </section>
  )
}
