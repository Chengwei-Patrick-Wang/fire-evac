import { useApp } from '../store/app'
import { readAccess, waitLine, fmtDuration } from '../model/access'
import { PROFILE_HEX } from './curves'
import { PROFILE_NAMES } from '../replay/runIndex'

const KNOWN: readonly string[] = PROFILE_NAMES
const fmtT = (v: number | null) => (v == null ? 'not reached' : `${v.toFixed(0)} s`)
const dur = (v: number | null) => (v == null ? '?' : fmtDuration(v))

export default function AccessStats() {
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : null))
  const building = useApp((s) => s.building)
  if (!lr) return null
  const acc = readAccess(lr.run)
  if (!acc) return null
  const { rows, assist } = acc
  const line = assist ? waitLine(lr.run, building) : null
  return (
    <>
      <h4>By mobility profile</h4>
      {rows.length > 0 && (
        <table className="stats access">
          <thead>
            <tr className="dim">
              <td></td>
              <td>profile</td>
              <td>people</td>
              <td>out</td>
              <td>90 % out</td>
              <td>trapped</td>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td>
                  <span className="swatch" style={{ background: PROFILE_HEX[KNOWN.indexOf(r.name)] ?? '#94a3b8' }} />
                </td>
                <td>{r.name}</td>
                <td>{r.agents}</td>
                <td>{r.evacuated ?? '?'}</td>
                <td>{fmtT(r.t90)}</td>
                <td>{r.trapped ?? '?'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {assist && (
        <div className="assist">
          <h4>Waiting for help</h4>
          <p>
            {assist.waiting} people, {dur(assist.meanWait)} on average (longest {dur(assist.maxWait)}),{' '}
            {assist.personSeconds == null ? '?' : Math.round(assist.personSeconds)} person-seconds
          </p>
          {line && (
            <p>
              <b>{line}</b>
            </p>
          )}
          <p className="dim">
            Long waits point to gaps in the building (no step-free route or refuge on that floor), not to the people
            waiting. Illustrative model.
          </p>
        </div>
      )}
    </>
  )
}
