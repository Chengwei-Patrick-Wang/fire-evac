import { useMemo } from 'react'
import { ChevronRight, Clock, DoorOpen, TriangleAlert, Users } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useApp } from '../store/app'
import { floorName, floorsByLevel } from '../model/floors'
import { burningAt, materialName, readSpread } from '../model/fireSpread'
import { busiestExit } from '../model/exitUse'
import { pairVerdict } from '../model/pairVerdict'
import { usePairs } from '../ui/PairCompare'
import EvacCurve from './EvacCurve'
import ExitBars from './ExitBars'
import RunStats from './RunStats'
import AccessStats from './AccessStats'
import { MAX_ALERTS, mmss, useLiveStats } from './liveStats'

const DASH = '—'

interface Kpi {
  label: string
  icon: LucideIcon
  tone?: 'safe' | 'severe'
  value: string
  sub: string
}

export default function Overview() {
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : undefined))
  const building = useApp((s) => s.building)
  const stats = useLiveStats()
  const m = lr?.run.metrics
  const none = 'Load a run'

  const t90 = m?.t90 ?? null
  const kpis: Kpi[] = [
    {
      label: 'Evacuated',
      icon: DoorOpen,
      tone: 'safe',
      value: stats && stats.n > 0 ? `${Math.round((stats.out / stats.n) * 100)}%` : DASH,
      sub: stats ? `${stats.out} of ${stats.n} out` : none,
    },
    {
      label: 'Trapped',
      icon: Users,
      tone: stats && stats.trapped > 0 ? 'severe' : undefined,
      value: stats ? String(stats.trapped) : DASH,
      sub: stats ? `${stats.inside} still inside · ${stats.waiting} waiting` : none,
    },
    {
      label: 'Chokepoints',
      icon: TriangleAlert,
      tone: stats && stats.chokepoints > 0 ? 'severe' : undefined,
      value: stats ? String(stats.chokepoints) : DASH,
      sub: stats ? 'with 5+ queued' : none,
    },
    {
      label: 'Evacuation time',
      icon: Clock,
      value: m && t90 != null ? mmss(t90) : DASH,
      sub: !m ? none : t90 == null ? '90% never out' : m.t100 != null ? `90% out · everyone by ${mmss(m.t100)}` : '90% out · not everyone out',
    },
  ]

  // The spread line: how many rooms burn at the clock time, and how many by the last frame of the run (a run without fire.rooms has none).
  const spread = useMemo(() => readSpread(lr?.run), [lr])
  const burning = spread && stats ? burningAt(spread, stats.t).length : 0
  const byEnd = spread && lr ? burningAt(spread, lr.index.duration).length : 0
  const rooms = (n: number) => `${n} ${n === 1 ? 'room' : 'rooms'}`

  // Two lines of story under the tiles: the exit most people used (the run's exit events, so it does not move with the clock), and for a run that is
  // half of a precomputed pair (wood against drywall, rules against Claude) how the pair came out.
  const busiest = useMemo(() => (lr ? busiestExit(lr.run, building) : null), [lr, building])
  const verdict = pairVerdict(lr?.key, usePairs())

  const floors = building ? floorsByLevel(building) : []
  const queued = (id: string) => stats?.queuedByFloor.get(id) ?? 0
  const total = floors.reduce((n, f) => n + queued(f.id), 0)
  const denom = Math.max(10, ...floors.map((f) => queued(f.id)))
  const at = stats ? mmss(stats.t) : ''

  return (
    <div className="overview">
      <dl className="kpis">
        {kpis.map((k) => {
          const Icon = k.icon
          return (
            <div className="kpi" key={k.label}>
              <dt>
                <Icon size={16} strokeWidth={1.75} aria-hidden="true" className={'kpi-ico' + (k.tone ? ' ' + k.tone : '')} />
                {k.label}
              </dt>
              <dd className={'kpi-val' + (k.tone === 'severe' ? ' severe' : '')}>{k.value}</dd>
              <dd className="sub">{k.sub}</dd>
            </div>
          )
        })}
      </dl>
      {busiest && (
        <p className="exitline">
          Busiest exit: <b>{busiest.name}</b>, {busiest.n} of {busiest.total} people
        </p>
      )}
      {verdict && (
        <p className="pairline">
          <b>{verdict}</b> <span className="dim">(precomputed pair, illustrative)</span>
        </p>
      )}
      {spread && stats && (
        <p className="spreadline dim">
          Fire spread (illustrative, {spread.material ? materialName(spread.material) : 'material not set'}): {rooms(burning)} burning · {byEnd} by the end of the run
        </p>
      )}

      <h4>Evacuation progress</h4>
      <EvacCurve />

      <h4>Congestion by floor</h4>
      {!stats || !building ? (
        <p className="dim">{none}.</p>
      ) : total === 0 ? (
        <p className="dim">No queues at {at}.</p>
      ) : (
        <ul className="congestion">
          {floors.map((f) => (
            <li key={f.id}>
              <span className="cname">{floorName(building, f.id)}</span>
              <span className="cbar" aria-hidden="true">
                <i style={{ width: `${Math.min(100, (queued(f.id) / denom) * 100)}%` }} />
              </span>
              <span className="cn">{queued(f.id)} queued</span>
            </li>
          ))}
        </ul>
      )}

      <h4>Chokepoint alerts ({stats?.alerts.length ?? 0})</h4>
      {!stats ? (
        <p className="dim">{none}.</p>
      ) : stats.alerts.length === 0 ? (
        <p className="dim">No chokepoints at {at}.</p>
      ) : (
        <>
          <ul className="alerts">
            {stats.alerts.map((a) => (
              <li key={a.key}>
                <button className={'alert ' + a.level} onClick={() => useApp.getState().flyTo(a.target.floorId, [a.target.cx, a.target.cy])}>
                  <TriangleAlert size={16} strokeWidth={1.75} aria-hidden="true" className="ico" />
                  <span className="atext">
                    <b>{a.title}</b>
                    <span className="areason">{a.reason}</span>
                  </span>
                  <ChevronRight size={16} strokeWidth={1.75} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
          {stats.chokepoints > MAX_ALERTS && <p className="dim">Showing the {MAX_ALERTS} largest of {stats.chokepoints}.</p>}
        </>
      )}

      <h3>More results</h3>
      <h4>Exit use</h4>
      <ExitBars />
      <h4>Run</h4>
      <RunStats />
      <AccessStats />
    </div>
  )
}
