import { useApp } from '../store/app'
import { fixLine, fixTarget } from '../model/fixes'
import type { Fix } from '../model/fixes'

interface Props {
  fixes: Fix[]
  skipped?: { id: string; reason: string }[]
  top: { id: string; floor: string }[]
  print?: boolean
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
          const inner = (
            <>
              <span className={f.helps ? 'badge ok' : 'badge warn'}>{f.helps ? 'helps' : 'no gain'}</span> <b>{fixLine(f)}</b>
              {t && <> → {t.rank != null ? `#${t.rank} ${t.id}` : `${t.id} · ${t.floor}`}</>}
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
          <ul>{skipped.map((s) => <li key={s.id}>{s.id}: {s.reason}</li>)}</ul>
        </details>
      )}
    </>
  )
  return print ? <section><h2>Measured fixes</h2>{body}</section> : <><h4>Measured fixes</h4>{body}</>
}
