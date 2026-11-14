import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useApp } from '../store/app'
import { PROFILE_LABELS } from './curves'
import { TYPE_COLORS } from '../replay/Agents'
import { doorLabels } from '../model/spots'
import { useChartTheme } from '../ui/theme'

type Row = Record<string, number | string>

/** A name is wrapped at this many characters a line, on two lines at most; the whole name stays in the label's title and in the bar's tooltip. */
const LINE = 20

interface TickProps {
  x?: number | string
  y?: number | string
  payload?: { value?: string | number }
}

/** Breaks a name at spaces into at most two lines, the second cut with an ellipsis when it still doesn't fit. */
function wrap(name: string): string[] {
  const lines: string[] = []
  let cur = ''
  for (const w of name.split(' ')) {
    if (cur && cur.length + 1 + w.length > LINE) {
      lines.push(cur)
      cur = w
    } else cur = cur ? `${cur} ${w}` : w
  }
  if (cur) lines.push(cur)
  if (lines.length <= 2) return lines
  const rest = lines.slice(1).join(' ')
  return [lines[0], rest.length > LINE ? rest.slice(0, LINE - 1) + '…' : rest]
}

export default function ExitBars() {
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : null))
  const building = useApp((s) => s.building)
  const ct = useChartTheme()
  const data = useMemo(() => {
    if (!lr) return { rows: [] as Row[], used: [] as number[], any: false, ids: new Map<string, string>() }
    const run = lr.run
    const prof = new Map(run.agents.map((a) => [a.idx, Math.max(0, PROFILE_LABELS.indexOf(a.profile))]))
    // An exit is named like its door in the fix list and the door picker ("Exit Main entrance"); an id the building doesn't know stays as it is.
    const labels = building ? doorLabels(building) : null
    const doorOf = new Map<string, string>()
    const ids = new Set<string>()
    for (const f of building?.floors ?? [])
      for (const e of f.exits ?? []) {
        ids.add(e.id)
        doorOf.set(e.id, e.door ?? e.id)
      }
    for (const k of Object.keys(run.metrics.exitCounts ?? {})) ids.add(k)
    const nameOf = (id: string) => labels?.get(doorOf.get(id) ?? id)?.label ?? id
    const rows: Row[] = [...ids].map((id) => ({ id, name: nameOf(id) }))
    const byId = new Map(rows.map((r) => [r.id as string, r]))
    let any = false
    let total = 0
    const usedSet = new Set<number>()
    for (const e of run.events) {
      if (e.type !== 'exit' || !e.exit) continue
      let row = byId.get(e.exit)
      if (!row) {
        row = { id: e.exit, name: nameOf(e.exit) }
        rows.push(row)
        byId.set(e.exit, row)
      }
      const p = prof.get(e.idx ?? -1) ?? 0
      row['p' + p] = ((row['p' + p] as number) ?? 0) + 1
      usedSet.add(p)
      any = true
      total++
    }
    // Two bars never share a label: the second one gets its id.
    const seen = new Set<string>()
    for (const r of rows) {
      if (seen.has(r.name as string)) r.name = `${r.name} (${r.id})`
      seen.add(r.name as string)
    }
    if (import.meta.env.DEV) {
      console.assert(total === run.metrics.evacuated, `exit bars total ${total} != evacuated ${run.metrics.evacuated}`)
    }
    return { rows, used: [...usedSet].sort(), any, ids: new Map(rows.map((r) => [r.name as string, r.id as string])) }
  }, [lr, building])

  if (!lr) return <div className="empty"><b>Load a run</b><span>Exit use appears once a run is loaded.</span></div>
  if (!data.any) return <div className="empty"><b>No exits used</b><span>No one reached an exit in this run.</span></div>
  const tick = ({ x, y, payload }: TickProps) => {
    const full = String(payload?.value ?? '')
    const lines = wrap(full)
    return (
      <text x={x} y={y} textAnchor="end" fontSize={11} fill={ct.axis}>
        <title>{full}</title>
        {lines.map((l, i) => (
          <tspan key={i} x={x} dy={i === 0 ? (lines.length > 1 ? -1 : 4) : 12}>
            {l}
          </tspan>
        ))}
      </text>
    )
  }
  return (
    <div role="img" aria-label="Exit use" aria-describedby="exit-summary" style={{ width: '100%', height: Math.max(110, 44 + 26 * data.rows.length) }}>
      <p id="exit-summary" className="sr-only">
        {'Exit use: ' + data.rows.map((r) => `${r.name} ${Object.entries(r).reduce((a, [k, v]) => (k === 'id' || k === 'name' ? a : a + (v as number)), 0)} people`).join(', ') + '.'}
      </p>
      <ResponsiveContainer>
        <BarChart accessibilityLayer={false} layout="vertical" data={data.rows} margin={{ top: 4, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid stroke={ct.grid} horizontal={false} />
          <XAxis type="number" allowDecimals={false} stroke={ct.axis} fontSize={11} />
          <YAxis type="category" dataKey="name" width={124} stroke={ct.axis} tick={tick} interval={0} />
          <Tooltip
            contentStyle={{ background: ct.tipBg, border: `1px solid ${ct.tipBorder}` }}
            labelStyle={{ color: 'var(--text)' }}
            itemStyle={{ color: 'var(--text)' }}
            labelFormatter={(label) => {
              const name = String(label)
              const id = data.ids.get(name)
              return id && !name.endsWith(`(${id})`) ? `${name} (${id})` : name
            }}
          />
          {data.used.map((p) => (
            <Bar key={p} dataKey={'p' + p} name={PROFILE_LABELS[p]} stackId="a" fill={TYPE_COLORS[p]} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
