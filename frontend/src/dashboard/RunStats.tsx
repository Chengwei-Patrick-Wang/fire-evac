import { useApp } from '../store/app'

const fmt = (v: number | null) => (v == null ? 'not reached' : `${v.toFixed(0)} s`)

export default function RunStats() {
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : null))
  if (!lr) return <div className="empty"><b>Load a run</b><span>Run statistics appear here.</span></div>
  const r = lr.run
  const m = r.metrics
  const rows: [string, string][] = [
    ['Evacuated', `${m.evacuated} of ${m.agents}`],
    ['50 % out (t50)', fmt(m.t50)],
    ['90 % out (t90)', fmt(m.t90)],
    ['100 % out (t100)', fmt(m.t100)],
    ['Trapped', String(m.trapped)],
    ['Seed', String(r.seed)],
  ]
  if (m.inStairs) rows.push(['In stairs', String(m.inStairs)])
  if (m.remaining) rows.push(['Remaining', String(m.remaining)])
  return (
    <table className="stats">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}>
            <td className="dim">{k}</td>
            <td>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
