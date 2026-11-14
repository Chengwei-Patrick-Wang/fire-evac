import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useApp } from '../store/app'
import { PROFILE_HEX, PROFILE_LABELS } from './curves'
import { useChartTheme } from '../ui/theme'

type Row = Record<string, number | string>

export default function ExitBars() {
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : null))
  const building = useApp((s) => s.building)
  const ct = useChartTheme()
  const data = useMemo(() => {
    if (!lr) return { rows: [] as Row[], used: [] as number[], any: false }
    const run = lr.run
    const prof = new Map(run.agents.map((a) => [a.idx, Math.max(0, PROFILE_LABELS.indexOf(a.profile))]))
    const ids = new Set<string>()
    for (const f of building?.floors ?? []) for (const e of f.exits ?? []) ids.add(e.id)
    for (const k of Object.keys(run.metrics.exitCounts ?? {})) ids.add(k)
    const rows: Row[] = [...ids].map((id) => ({ id }))
    const byId = new Map(rows.map((r) => [r.id as string, r]))
    let any = false
    let total = 0
    const usedSet = new Set<number>()
    for (const e of run.events) {
      if (e.type !== 'exit' || !e.exit) continue
      let row = byId.get(e.exit)
      if (!row) {
        row = { id: e.exit }
        rows.push(row)
        byId.set(e.exit, row)
      }
      const p = prof.get(e.idx ?? -1) ?? 0
      row['p' + p] = ((row['p' + p] as number) ?? 0) + 1
      usedSet.add(p)
      any = true
      total++
    }
    if (import.meta.env.DEV) {
      console.assert(total === run.metrics.evacuated, `exit bars total ${total} != evacuated ${run.metrics.evacuated}`)
    }
    return { rows, used: [...usedSet].sort(), any }
  }, [lr, building])

  if (!lr) return <div className="empty"><b>Load a run</b><span>Exit use appears once a run is loaded.</span></div>
  if (!data.any) return <div className="empty"><b>No exits used</b><span>No one reached an exit in this run.</span></div>
  return (
    <div role="img" aria-label="Exit use" aria-describedby="exit-summary" style={{ width: '100%', height: 200 }}>
      <p id="exit-summary" className="sr-only">
        {'Exit use: ' + data.rows.map((r) => `${r.id} ${Object.entries(r).reduce((a, [k, v]) => (k === 'id' ? a : a + (v as number)), 0)} people`).join(', ') + '.'}
      </p>
      <ResponsiveContainer>
        <BarChart accessibilityLayer={false} data={data.rows} margin={{ top: 8, right: 12, bottom: 4, left: -20 }}>
          <CartesianGrid stroke={ct.grid} />
          <XAxis dataKey="id" stroke={ct.axis} fontSize={11} />
          <YAxis allowDecimals={false} stroke={ct.axis} fontSize={11} />
          <Tooltip contentStyle={{ background: ct.tipBg, border: `1px solid ${ct.tipBorder}` }} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} />
          {data.used.map((p) => (
            <Bar key={p} dataKey={'p' + p} name={PROFILE_LABELS[p]} stackId="a" fill={PROFILE_HEX[p]} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
