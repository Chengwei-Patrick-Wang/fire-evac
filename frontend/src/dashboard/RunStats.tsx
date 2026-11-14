import { useApp } from '../store/app'
import { rangeCell, readSeedRange } from '../model/ranges'

const fmt = (v: number | null) => (v == null ? 'not reached' : `${v.toFixed(0)} s`)

export default function RunStats() {
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : null))
  if (!lr) return <div className="empty"><b>Load a run</b><span>Run statistics appear here.</span></div>
  const r = lr.run
  const m = r.metrics
  const sr = readSeedRange(r)
  const rows: [string, string, string | null][] = [
    ['Evacuated', `${m.evacuated} of ${m.agents}`, rangeCell(sr?.evacuated, '')],
    ['50 % out (t50)', fmt(m.t50), rangeCell(sr?.t50, ' s')],
    ['90 % out (t90)', fmt(m.t90), rangeCell(sr?.t90, ' s')],
    ['100 % out (t100)', fmt(m.t100), rangeCell(sr?.t100, ' s')],
    ['Trapped', String(m.trapped), rangeCell(sr?.trapped, '')],
    ['Seed', String(r.seed), null],
  ]
  if (m.inStairs) rows.push(['In stairs', String(m.inStairs), null])
  if (m.remaining) rows.push(['Remaining', String(m.remaining), null])
  return (
    <table className="stats">
      {sr && (
        <caption className="dim">
          Seed {r.seed} is one possible night; ranges over {sr.seeds.length} seeds ({Math.min(...sr.seeds)}–{Math.max(...sr.seeds)}).
        </caption>
      )}
      <tbody>
        {rows.map(([k, v, g]) => (
          <tr key={k}>
            <th scope="row" className="dim">{k}</th>
            <td>{v}</td>
            {sr && <td className="dim">{g}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
