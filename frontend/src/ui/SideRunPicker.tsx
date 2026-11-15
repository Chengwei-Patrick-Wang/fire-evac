import { useEffect, useState } from 'react'
import { splitKeys, useApp } from '../store/app'
import type { Side } from '../store/app'
import { listDemoRuns } from '../data/loader'
import { runLabel } from '../model/brain'
import type { DemoRun } from '../data/types'

/** The precomputed runs of a building the split view can show (the door what-ifs are gone from the app). */
function useSavedRuns(buildingId: string | undefined): DemoRun[] {
  const [found, setFound] = useState<{ id: string; runs: DemoRun[] } | null>(null)
  useEffect(() => {
    let current = true
    if (buildingId) void listDemoRuns(buildingId).then((rs) => current && setFound({ id: buildingId, runs: rs.filter((r) => r.whatIf !== 'propped') }))
    return () => {
      current = false
    }
  }, [buildingId])
  return found && found.id === buildingId ? found.runs : []
}

/**
 * The top of a side's Fire and scenario card in the split view: the side's building (the right side can pick another one), and a list of
 * the saved runs of that building (the wood and drywall pair, the rules and Claude pair, every fire room). Static mode has nothing but
 * these, and says so: new settings need the live backend.
 */
export default function SideRunPicker({ side }: { side: Side }) {
  const mode = useApp((s) => s.mode)
  const buildings = useApp((s) => s.buildings)
  const loaded = useApp((s) => s.building)
  const rightBuilding = useApp((s) => s.rightBuilding)
  const runs = useApp((s) => s.runs)
  const mine = useApp((s) => splitKeys(s)[side === 'L' ? 'left' : 'right'])
  const other = useApp((s) => splitKeys(s)[side === 'L' ? 'right' : 'left'])
  const busy = useApp((s) => s.pairBusy)
  const err = useApp((s) => s.pairError)
  const b = side === 'R' ? rightBuilding ?? loaded : loaded
  const saved = useSavedRuns(b?.id)
  if (!b) return null
  const name = side === 'L' ? 'left' : 'right'
  const inList = saved.some((e) => e.id === mine)
  return (
    <div className="sidepick">
      {side === 'R' ? (
        <label>
          Building (right side)
          <select value={b.id} disabled={!!busy} onChange={(e) => void useApp.getState().setRightBuilding(e.target.value)}>
            {!buildings.some((x) => x.id === b.id) && <option value={b.id}>{b.name}</option>}
            {buildings.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <p className="where">
          Building: <b>{b.name}</b> <span className="dim">(change it in the top menu)</span>
        </p>
      )}
      <label>
        Saved run ({name} side)
        <select
          value={mine ?? ''}
          onChange={(e) => {
            const entry = saved.find((x) => x.id === e.target.value)
            if (entry) void useApp.getState().pickSideRun(side, entry)
          }}
        >
          {!inList && mine && <option value={mine}>{runs[mine]?.label ?? mine}</option>}
          {saved.map((e) => (
            <option key={e.id} value={e.id} disabled={e.id === other}>
              {runLabel(e.label, e.brain)}
              {e.id === other ? ' (on the other side)' : ''}
            </option>
          ))}
        </select>
      </label>
      {mode !== 'live' && (
        <p className="dim note">
          Static mode shows saved runs only: pick one for each side. New settings (fire size and speed, material, crowd, people) need live mode, which runs the backend.
        </p>
      )}
      {busy && (
        <p className="dim note" role="status">
          {busy}
        </p>
      )}
      {err && <p className="err">{err}</p>}
    </div>
  )
}
