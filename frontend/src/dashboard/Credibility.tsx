import { useEffect, useState, type MouseEvent } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { loadCalibration, type Calibration } from '../data/loader'
import { useApp } from '../store/app'
import { readSeedRange, span } from '../model/ranges'
import { useChartTheme } from '../ui/theme'

const COLORS = ['#2563EB', '#C2410C', '#7C3AED', '#15803D']

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

type CalPoint = { label: string; width?: number; simulated: number; references: { name: string; value: number }[] }

function between(points: CalPoint[], noun: string) {
  const c = { between: 0, below: 0, above: 0 }
  for (const p of points) {
    const v = p.references.map((r) => r.value)
    if (!v.length) continue
    if (p.simulated < Math.min(...v)) c.below++
    else if (p.simulated > Math.max(...v)) c.above++
    else c.between++
  }
  const n = points.length
  const parts = (Object.keys(c) as (keyof typeof c)[]).filter((k) => c[k] > 0).map((k) => `${k} at ${c[k]} of ${n} ${noun}`)
  return `Our simulation vs references: ${parts.join(', ') || 'no references'}.`
}

type ChartKind = 'door' | 'corridor'

const SIM_DESCRIPTIONS = {
  door: 'People passing through the door per second in our controlled simulation.',
  corridor: 'Average walking speed measured in our controlled corridor simulation.',
}

function referenceLabel(name: string) {
  if (/IMO/i.test(name)) return 'Clear-width estimate'
  if (/Hydraulic/i.test(name)) return 'Effective-width estimate'
  if (/SFPE/i.test(name)) return 'SFPE reference'
  if (/Weidmann/i.test(name)) return 'Weidmann reference'
  return name
}

function referenceDescription(name: string) {
  if (/IMO/i.test(name)) return 'An IMO-based reference estimate using the full door opening.'
  if (/Hydraulic/i.test(name)) return 'A hydraulic-flow reference estimate allowing 15 cm of unused space on each side of the opening.'
  if (/SFPE/i.test(name)) return 'A Society of Fire Protection Engineers reference formula estimating walking speed as crowding increases.'
  if (/Weidmann/i.test(name)) return 'A pedestrian-research reference curve relating crowd density to walking speed.'
  return 'A reference value supplied with this calibration dataset.'
}

function CalChart({ points, id, kind }: { points: CalPoint[]; id: string; kind: ChartKind }) {
  const ct = useChartTheme()
  const names = [...new Set(points.flatMap((p) => p.references.map((r) => r.name)))]
  const title = kind === 'door' ? 'How many people can pass through?' : 'How crowding slows walking'
  const xLabel = kind === 'door' ? 'Door width (m)' : 'Crowding (people/m²)'
  const yLabel = kind === 'door' ? 'People per second' : 'Walking speed (m/s)'
  const rows = points.map((p) => {
    const r: Record<string, number | string> = { label: kind === 'door' ? p.width ?? p.label : p.label, simulated: p.simulated }
    for (const ref of p.references) r[ref.name] = ref.value
    return r
  })
  const series = [
    { name: 'Our simulation', description: SIM_DESCRIPTIONS[kind], color: COLORS[0] },
    ...names.map((name, i) => ({ name: referenceLabel(name), description: referenceDescription(name), color: COLORS[(i + 1) % COLORS.length] })),
  ]
  return (
    <section className="cal-chart" aria-labelledby={`${id}-title`}>
      <h4 id={`${id}-title`}>{title}</h4>
      <div role="img" aria-label={title} aria-describedby={id} style={{ width: '100%', height: 260 }}>
        <p id={id} className="sr-only">
          {`${xLabel}; ${yLabel}. `}
          {rows.map((r) => `${r.label}: Our simulation ${r.simulated}, ${names.filter((n) => r[n] !== undefined).map((n) => `${referenceLabel(n)} ${r[n]}`).join(', ')}`).join('; ')}
        </p>
        <ResponsiveContainer>
          <BarChart accessibilityLayer={false} data={rows} margin={{ top: 8, right: 12, bottom: 12, left: 12 }}>
            <CartesianGrid stroke={ct.grid} />
            <XAxis dataKey="label" stroke={ct.axis} fontSize={11} height={44} label={{ value: xLabel, position: 'insideBottom', offset: 0, fill: ct.axis, fontSize: 11 }} />
            <YAxis stroke={ct.axis} fontSize={11} width={50} label={{ value: yLabel, angle: -90, position: 'insideLeft', fill: ct.axis, fontSize: 11, style: { textAnchor: 'middle' } }} />
            <Tooltip contentStyle={{ background: ct.tipBg, border: `1px solid ${ct.tipBorder}` }} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} />
            {/* No Recharts legend: the series list under the chart names and explains each colour, visible without hover. */}
            <Bar dataKey="simulated" name="Our simulation" fill={COLORS[0]} isAnimationActive={false} />
            {names.map((n, i) => (
              <Bar key={n} dataKey={n} name={referenceLabel(n)} fill={COLORS[(i + 1) % COLORS.length]} isAnimationActive={false} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <dl className="cal-legend" aria-label={`${title}: series descriptions`}>
        {series.map((s) => (
          <div key={s.name}>
            <dt><span className="cal-swatch" style={{ backgroundColor: s.color }} aria-hidden="true" />{s.name}</dt>
            <dd>{s.description}</dd>
          </div>
        ))}
      </dl>
      <p className="dim">{between(points, kind === 'door' ? 'widths' : 'densities')}</p>
    </section>
  )
}

function ChartMethods({ title, source, points }: { title: string; source: string; points: CalPoint[] }) {
  const names = [...new Set(points.flatMap((p) => p.references.map((r) => r.name)))]
  return (
    <>
      <h4>{title}</h4>
      <p>Test conditions: {source}</p>
      <ul>{names.map((name) => <li key={name}>{referenceLabel(name)}: {name}</li>)}</ul>
    </>
  )
}

/** Open the methods section in place: the URL hash holds the app's share-link state (model/link.ts), so the anchor must not replace it. */
function openMethods(e: MouseEvent<HTMLAnchorElement>) {
  e.preventDefault()
  const details = document.getElementById('cred-methods')
  if (details instanceof HTMLDetailsElement) {
    details.open = true
    details.scrollIntoView({ block: 'nearest' })
  }
}

export default function Credibility() {
  const [cal, setCal] = useState<{ data: Calibration; example: boolean } | null | undefined>(undefined)

  useEffect(() => {
    let live = true
    loadCalibration().then((c) => live && setCal(c)).catch(() => live && setCal(null))
    return () => {
      live = false
    }
  }, [])

  const sd = cal?.data.speedDensity
  const limits = cal?.data.limits
  return (
    <div className="cred">
      {cal === undefined && <p className="dim">Loading…</p>}
      {cal && (
        <>
          {cal.example && <div className="stamp">EXAMPLE VALUES</div>}
          <CalChart points={cal.data.points} id="cred-summary" kind="door" />
          {sd && Array.isArray(sd.points) && sd.points.length > 0 && (
            <CalChart points={sd.points} id="cred-summary-speed" kind="corridor" />
          )}
          <p className="dim">Controlled movement tests; these comparisons do not validate the whole evacuation model.</p>
          <p className="cal-limits-note">
            {limits?.length ? `${limits.length} known model limitations. ` : ''}
            Review <a href="#cred-methods" onClick={openMethods}>Methods and sources</a> below for test conditions and limitations.
          </p>
          <details id="cred-methods" className="cal-methods">
            <summary>Methods and sources</summary>
            <ChartMethods title={cal.data.title} source={cal.data.source} points={cal.data.points} />
            <p>Our simulation measures door throughput between the 10th and 90th percentile exit events to reduce startup and finishing effects.</p>
            <p>For door width W in metres, the clear-width estimate is 1.3 × W people/s. The effective-width estimate is 1.3 × (W − 0.3) people/s.</p>
            <p>Door references: <a href="https://puc.overheid.nl/doc/PUC_1878_14/1">International Maritime Organization: simplified evacuation-analysis method</a>; <a href="https://files.thunderheadeng.com/femtc/2022_d2-12-arnott-paper.pdf">Arnott (2022), hydraulic model and counterflow, FEMTC</a>.</p>
            {sd && Array.isArray(sd.points) && sd.points.length > 0 && (
              <>
                <ChartMethods title={sd.title} source={sd.source} points={sd.points} />
                <p>Our simulation measures displacement between recorded positions divided by elapsed time, grouped by measured crowd density.</p>
                <p>For density D in people/m², the implemented SFPE reference is max(0, 1.4 × (1 − 0.266 × max(D, 0.54))) m/s. The Weidmann reference is 1.34 × (1 − exp(−1.913 × (1/D − 1/5.4))) m/s for positive D, and 1.34 m/s at zero density.</p>
                <p>Corridor references: the SFPE Handbook of Fire Protection Engineering, hydraulic movement model (<a href="https://www.sfpe.org/publications/fpemagazine/fpeextra/etarchives3/fpeetissue85">SFPE overview</a>); Weidmann, U. (1993), <cite>Transporttechnik der Fussgänger</cite>, ETH Zürich, IVT report 90.</p>
              </>
            )}
            {Array.isArray(limits) && limits.length > 0 && (
              <>
                <h4>Known limits of the crowd model</h4>
                <ul className="limits">{limits.map((l, i) => <li key={i}>{l}</li>)}</ul>
              </>
            )}
          </details>
        </>
      )}
      <Limits />
    </div>
  )
}
