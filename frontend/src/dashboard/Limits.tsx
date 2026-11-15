import { useApp } from '../store/app'
import { readSeedRange, span } from '../model/ranges'

/** The "not a compliance tool" limits of a run, for the printed report's Assumptions and limits section. */
export function Limits() {
  const building = useApp((s) => s.building)
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : null))
  const sc = lr?.scenario
  const doors = sc?.doors ?? lr?.doors ?? {}
  const t90r = lr ? readSeedRange(lr.run)?.t90 : undefined
  const doorText = Object.entries(doors).map(([k, v]) => `${k}: ${v}`).join(', ')
  const mix = sc?.occupants.mix
    ? Object.entries(sc.occupants.mix).map(([k, v]) => `${k} ${Math.round((v ?? 0) * 100)}%`).join(', ')
    : null
  return (
    <>
      <h4>Limits</h4>
      <ul className="dim">
        <li>Not a compliance tool.</li>
        <li>The fire and smoke model is illustrative (a smoke front, not CFD).</li>
        <li>
          One seed is one possible night
          {t90r && t90r.min != null && t90r.max != null && t90r.median != null && lr
            ? `: over ${readSeedRange(lr.run)?.seeds.length} seeds, t90 ranged ${span({ min: t90r.min, max: t90r.max })} (median ${t90r.median.toFixed(0)} s)`
            : ''}.
        </li>
        {lr && (
          <li>
            This run: {sc ? `${sc.occupants.total} occupants` : `${lr.run.agents.length} agents`}
            {mix ? ` (${mix})` : ''}, seed {sc?.seed ?? lr.run.seed}
            {sc?.alarmTime != null ? `, alarm at ${sc.alarmTime} s` : ''}
            {doorText ? `, doors ${doorText}` : ''}.
          </li>
        )}
      </ul>
      <p className="dim">
        Credits: {building?.credits ?? 'none listed'}. Libraries: JuPedSim, React Three Fiber, three.js, Recharts.
      </p>
    </>
  )
}
