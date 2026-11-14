import { useMemo } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import { useApp } from '../store/app'
import { useThrottledT } from '../store/clock'
import { evacCurve, RUN_COLORS } from './curves'

export default function EvacCurve() {
  const runs = useApp((s) => s.runs)
  const order = useApp((s) => s.runOrder)
  const compare = useApp((s) => s.compareKeys)
  const t = useThrottledT(250)
  const keys = order.filter((k) => compare.includes(k))
  const keyStr = keys.join('|')

  const data = useMemo(() => {
    const maxT = Math.ceil(Math.max(0, ...keys.map((k) => runs[k].index.duration)))
    const times = Array.from({ length: maxT + 1 }, (_, i) => i)
    const cols = keys.map((k) => evacCurve(runs[k].run, times))
    return times.map((x, i) => {
      const row: Record<string, number> = { t: x }
      keys.forEach((k, j) => (row[k] = cols[j][i]))
      return row
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs, keyStr])

  if (order.length === 0) return <p className="dim">Load a run</p>
  const color = (k: string) => RUN_COLORS[order.indexOf(k) % RUN_COLORS.length]
  const toggle = (k: string) =>
    useApp.setState({ compareKeys: compare.includes(k) ? compare.filter((x) => x !== k) : [...compare, k] })

  return (
    <div>
      <div className="legend">
        {order.map((k) => (
          <label key={k} style={{ color: color(k) }}>
            <input type="checkbox" checked={compare.includes(k)} onChange={() => toggle(k)} /> {runs[k].label}
          </label>
        ))}
      </div>
      <div style={{ width: '100%', height: 220 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -12 }}>
            <CartesianGrid stroke="#1e293b" />
            <XAxis dataKey="t" type="number" domain={[0, 'dataMax']} stroke="#94a3b8" fontSize={11} unit=" s" />
            <YAxis domain={[0, 100]} stroke="#94a3b8" fontSize={11} unit="%" />
            {keys.map((k) => (
              <Line key={k} dataKey={k} name={runs[k].label} type="stepAfter" stroke={color(k)} dot={false} isAnimationActive={false} strokeWidth={2} />
            ))}
            <ReferenceLine x={Math.round(t)} stroke="#e2e8f0" strokeDasharray="3 3" />
            {keys.map((k) => {
              const t90 = runs[k].run.metrics.t90
              return t90 == null ? null : (
                <ReferenceLine key={'t90' + k} x={Math.round(t90)} stroke={color(k)} strokeDasharray="2 4" />
              )
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
