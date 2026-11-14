import { ChevronRight, Clock, DoorOpen, TriangleAlert, Users } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useApp } from '../store/app'
import { floorName, floorsByLevel } from '../model/floors'
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
      label: 'Remaining',
      icon: Users,
      value: stats ? String(stats.inside) : DASH,
      sub: stats ? `${stats.trapped} trapped · ${stats.waiting} waiting` : none,
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
