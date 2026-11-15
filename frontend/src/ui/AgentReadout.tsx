import { useEffect, useMemo } from 'react'
import { useApp } from '../store/app'
import { useThrottledT } from '../store/clock'
import { PROFILE_NAMES } from '../replay/runIndex'
import { useAgentView } from '../replay/agentView'
import { decisionAt, decisionText, readDecisions } from '../model/brain'
import type { Decisions } from '../model/brain'

/** What Claude (or, when Claude did not answer in time, the rules) last decided for this person, at the replay time. Nothing before their first decision. */
function ClaudeLine({ decisions, idx }: { decisions: Decisions; idx: number }) {
  const t = useThrottledT(250)
  const d = decisionAt(decisions, idx, t)
  if (!d) return null
  return (
    <div className={'claude-line' + (d.fallback ? ' rules' : '')}>
      {d.fallback ? (
        decisionText(d)
      ) : (
        <>
          <b>Claude:</b> {d.reason}
        </>
      )}
      {d.action && <span className="action"> · {d.action}</span>}
    </div>
  )
}

export default function AgentReadout() {
  const follow = useApp((s) => s.follow)
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : undefined))
  const { vis, speed, desired, status } = useAgentView()
  // Only a run that logged Claude's decisions has them; any other run reads exactly as before.
  const decisions = useMemo(() => readDecisions(lr?.run), [lr])
  useEffect(() => {
    if (follow === null) return
    const h = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      useApp.getState().setFollow(null)
    }
    window.addEventListener('keydown', h, true)
    return () => window.removeEventListener('keydown', h, true)
  }, [follow])
  if (follow === null) return null
  const profile = lr ? PROFILE_NAMES[lr.index.profile[follow]] ?? 'typical' : ''
  const tone = vis < 3 ? 'worse' : vis < 10 ? 'caution' : undefined
  return (
    <div className="agentreadout">
      <div>
        <b>Person #{follow}</b> · {profile} · {status}
      </div>
      <div className={tone}>Visibility {vis >= 30 ? '30+' : vis.toFixed(1)} m</div>
      <div>
        Walking {speed.toFixed(2)} m/s (wants {desired.toFixed(2)})
      </div>
      {decisions && <ClaudeLine decisions={decisions} idx={follow} />}
      <div className="dim" style={{ fontSize: 11 }}>
        Illustrative smoke model
      </div>
      <button onClick={() => useApp.getState().setFollow(null)}>Back to overview (Esc)</button>
    </div>
  )
}
