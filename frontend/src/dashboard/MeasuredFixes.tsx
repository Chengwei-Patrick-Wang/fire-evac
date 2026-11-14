import { useApp } from '../store/app'
import { fixLine, fixTarget, fixVerdict, skippedLine } from '../model/fixes'
import type { Fix, Verdict } from '../model/fixes'
import type { SpotLike } from '../model/spots'

interface Props {
  fixes: Fix[]
  skipped?: { id: string; reason: string }[]
  top: (SpotLike & { floor: string })[]
  print?: boolean
}

const BADGE: Record<Verdict, { cls: string; text: string }> = {
  helps: { cls: 'badge ok', text: 'helps' },
  tradeoff: { cls: 'badge trade', text: 'trade-off' },
  nogain: { cls: 'badge warn', text: 'no gain' },
}

export default function MeasuredFixes({ fixes, skipped = [], top, print = false }: Props) {
  const building = useApp((s) => s.building)
  const activeSpot = useApp((s) => s.activeSpot)
  if (!fixes.length) return null
  const body = (
    <>
      <p className="dim">
        Measured on the same fires and seeds as the batch. Illustrative model: ideas for a fire protection engineer to check, not a design or a compliance result.
      </p>
      <ol className="spots fixes">
        {fixes.map((f) => {
          const t = fixTarget(f, top, building)
          const badge = BADGE[fixVerdict(f)]
          const inner = (
            <>
              <span className={badge.cls}>{badge.text}</span> <b>{fixLine(f)}</b>
              {t && (
                <>
                  {' '}
                  <span className="target">→ {t.rank != null ? `#${t.rank} ${t.label}` : `${print ? 'on' : 'show on'} ${t.floor}`}</span>
                </>
              )}
              <div className="dim">{f.why}</div>
            </>
          )
          return (
            <li key={f.id} className={!print && t && activeSpot === t.id ? 'on' : ''}>
              {!print && t ? (
                <button className="spot" data-spot={t.id} onClick={() => useApp.getState().goToSpot(t.id, t.floor)}>{inner}</button>
              ) : inner}
            </li>
          )
        })}
      </ol>
      {!print && skipped.length > 0 && (
        <details>
          <summary>Not measured ({skipped.length})</summary>
          <ul>{skipped.map((s) => <li key={s.id}>{skippedLine(s)}</li>)}</ul>
        </details>
      )}
    </>
  )
  return print ? <section><h2>Measured fixes</h2>{body}</section> : <><h4>Measured fixes</h4>{body}</>
}
