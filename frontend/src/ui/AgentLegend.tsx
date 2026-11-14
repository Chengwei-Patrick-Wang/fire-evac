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

export default function AgentLegend() {
  const mode = useApp((s) => s.agentColor)
  const hasRun = useApp((s) => s.activeRunKey !== null)
  if (!hasRun) return null
  const items: [string, string][] =
    mode === 'status' ? STATUS_ITEMS : PROFILE_NAMES.map((n, i) => [n, PROFILE_COLORS[i % PROFILE_COLORS.length]])
  return (
    <div className="agentlegend" aria-label="Legend">
      {items.map(([name, c]) => (
        <span key={name}>
          <i style={{ background: c, borderRadius: '50%' }} /> {name}
        </span>
      ))}
      <hr />
      {(Object.keys(DOOR_COLORS) as (keyof typeof DOOR_COLORS)[]).map((k) => (
        <span key={k}>
          <i style={{ background: DOOR_COLORS[k] }} /> door {k}
        </span>
      ))}
    </div>
  )
}
