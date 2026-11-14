import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { loadCalibration, type Calibration } from '../data/loader'
import { useApp } from '../store/app'

const COLORS = ['#38bdf8', '#f59e0b', '#a78bfa', '#34d399']

export default function Credibility() {
  const [cal, setCal] = useState<{ data: Calibration; example: boolean } | null | undefined>(undefined)
  const building = useApp((s) => s.building)
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : null))

  useEffect(() => {
    let live = true
    loadCalibration().then((c) => live && setCal(c)).catch(() => live && setCal(null))
    return () => {
      live = false
    }
  }, [])

  const names = cal ? [...new Set(cal.data.points.flatMap((p) => p.references.map((r) => r.name)))] : []
  const rows = cal
    ? cal.data.points.map((p) => {
        const r: Record<string, number | string> = { label: p.label, simulated: p.simulated }
        for (const ref of p.references) r[ref.name] = ref.value
        return r
      })
    : []
  const sc = lr?.scenario
  const doors = sc?.doors ?? lr?.doors ?? {}
  const doorText = Object.entries(doors).map(([k, v]) => `${k}: ${v}`).join(', ')
  const mix = sc?.occupants.mix
    ? Object.entries(sc.occupants.mix).map(([k, v]) => `${k} ${Math.round((v ?? 0) * 100)}%`).join(', ')
    : null

  return (
    <div className="cred">
      {cal === undefined && <p className="dim">Loading…</p>}
      {cal && (
        <>
          <h4>{cal.data.title}</h4>
          {cal.example && <div className="stamp">EXAMPLE VALUES</div>}
          <div style={{ width: '100%', height: 220 }}>
            <ResponsiveContainer>
              <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: -10 }}>
                <CartesianGrid stroke="#1e293b" />
                <XAxis dataKey="label" stroke="#94a3b8" fontSize={11} />
                <YAxis stroke="#94a3b8" fontSize={11} unit=" p/s" />
                <Tooltip contentStyle={{ background: '#111a2e', border: '1px solid #334155' }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="simulated" name="Simulated" fill={COLORS[0]} isAnimationActive={false} />
                {names.map((n, i) => (
                  <Bar key={n} dataKey={n} fill={COLORS[(i + 1) % COLORS.length]} isAnimationActive={false} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="dim">Source: {cal.data.source}</p>
          <p className="dim">Illustrative: door flow only, not a validation of the whole model.</p>
        </>
      )}
      <h4>Limits</h4>
      <ul className="dim">
        <li>Not a compliance tool.</li>
        <li>The fire and smoke model is illustrative (a smoke front, not CFD).</li>
        <li>One seed is one possible night.</li>
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
    </div>
  )
}
