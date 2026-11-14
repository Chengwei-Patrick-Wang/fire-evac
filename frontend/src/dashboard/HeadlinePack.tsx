import { useApp } from '../store/app'
import { readFixes } from '../model/fixes'
import { seedBadge } from '../model/ranges'
import MeasuredFixes from './MeasuredFixes'

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

export default function HeadlinePack() {
  const pack = useApp((s) => s.headlines)
  const batch = useApp((s) => s.batch)
  const activeSpot = useApp((s) => s.activeSpot)
  if (!pack) return null
  const sc = pack.scenario
  const parts: string[] = []
  if (sc) {
    const who = [isNum(sc.occupants) ? `${sc.occupants} occupants` : null, sc.fireType ? `${sc.fireType} fire` : null].filter(Boolean).join(', ')
    const what = isNum(sc.runs)
      ? `${sc.runs} fires${isNum(sc.rooms) ? ` in ${sc.rooms} rooms` : ''}${Array.isArray(sc.seeds) ? ` over ${sc.seeds.length} seeds` : ''}${isNum(sc.failed) ? ` (${sc.failed} failed)` : ''}`
      : ''
    parts.push([who, what].filter(Boolean).join('; '))
  }
  const scenarioLine = parts.filter(Boolean).join('')
  const spots = pack.weakSpots ?? []
  const stab = pack.stability
  const src = pack.sources?.batch?.id
  const date = pack.generated?.slice(0, 10)
  const changed = (pack.changes ?? []).filter((c) => c.changed)
  return (
    <div className="whatif-headline">
      {pack.headline && <div className="main">{pack.headline}</div>}
      {scenarioLine && <div className="dim">{scenarioLine}</div>}
      {changed.map((c) => (
        <div key={c.key} className="dim">Updated for smoke-aware exit choice: {c.why}</div>
      ))}
      {spots.length > 0 && (
        <ol className="spots">
          {spots.map((t, i) => {
            const b = seedBadge(t.kind, t.seedsInTop3, stab?.n)
            return (
              <li key={`${t.kind}-${t.id}-${i}`} className={activeSpot === t.id ? 'on' : ''}>
                <button className="spot" data-spot={t.id} onClick={() => useApp.getState().goToSpot(t.id, t.floor)}>
                  <b>#{t.rank ?? i + 1} {t.label ?? t.id}</b> {b && <span className={b.stable ? 'badge ok' : 'badge warn'}>{b.text}</span>}
                  <div className="dim">{t.why}</div>
                </button>
              </li>
            )
          })}
        </ol>
      )}
      {(pack.whatIf ?? []).length > 0 && (
        <ul>{pack.whatIf!.map((e) => <li key={e.id}>{e.why}</li>)}</ul>
      )}
      <MeasuredFixes fixes={readFixes(pack)} top={spots} />
      {stab && <div className="dim">{stab.why}</div>}
      {pack.sensitivity?.why && <div className="dim">{pack.sensitivity.why}</div>}
      {pack.sensitivity?.note && <div className="dim">{pack.sensitivity.note}</div>}
      {pack.note && <div className="dim">{pack.note}</div>}
      {src && date && (
        <div className="dim">
          Numbers from {src}, {date}
          {batch && batch.id !== src ? `; the Risk map shows ${batch.id}` : ''}
        </div>
      )}
    </div>
  )
}
