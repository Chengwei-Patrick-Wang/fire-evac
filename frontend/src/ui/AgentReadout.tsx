import { useEffect } from 'react'
import { useApp } from '../store/app'
import { PROFILE_NAMES } from '../replay/runIndex'
import { useAgentView } from '../replay/agentView'

export default function AgentReadout() {
  const follow = useApp((s) => s.follow)
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : undefined))
  const { vis, speed, desired, status } = useAgentView()
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
  const color = vis < 3 ? '#f87171' : vis < 10 ? '#fbbf24' : undefined
  return (
    <div className="agentreadout">
      <div>
        <b>Person #{follow}</b> · {profile} · {status}
      </div>
      <div style={{ color }}>Visibility {vis >= 30 ? '30+' : vis.toFixed(1)} m</div>
      <div>
        Walking {speed.toFixed(2)} m/s (wants {desired.toFixed(2)})
      </div>
      <div className="dim" style={{ fontSize: 11 }}>
        Illustrative smoke model
      </div>
      <button onClick={() => useApp.getState().setFollow(null)}>Back to overview (Esc)</button>
    </div>
  )
}
