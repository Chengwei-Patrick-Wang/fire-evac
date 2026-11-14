import { useState } from 'react'
import { useApp } from '../store/app'
import { FIRE_TYPES, roomAt } from '../model/scenarioDraft'
import type { DoorState, Profile } from '../data/types'

const MIX: Profile[] = ['typical', 'older', 'visitor']
const STATES: DoorState[] = ['open', 'closed', 'propped', 'blocked']

export default function ScenarioPanel() {
  const { draft, building, patchDraft, placing, setPlacing, running, runError, runNote, runScenario } = useApp()
  const [doorPick, setDoorPick] = useState('')
  if (!draft || !building) return <p className="dim">Load a building to set up a scenario.</p>
  const doorIds = building.floors.flatMap((f) => f.doors.map((d) => d.id))
  const doors = draft.doors ?? {}
  const fire = draft.fire
  const room =
    fire.floor && fire.room ? building.floors.find((f) => f.id === fire.floor)?.rooms.find((r) => r.id === fire.room) : null
  const ghost = fire.floor && fire.x !== undefined && fire.y !== undefined ? roomAt(building, fire.floor, fire.x, fire.y) : null
  const num = (v: string, d: number) => (Number.isFinite(parseFloat(v)) ? parseFloat(v) : d)

  return (
    <div className="scenario">
      <label>
        Fire
        <select value={fire.type} onChange={(e) => patchDraft({ fire: { ...fire, type: e.target.value } })}>
          {FIRE_TYPES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </label>
      <label className="check">
        <input type="checkbox" checked={placing} onChange={(e) => setPlacing(e.target.checked)} />
        Click a floor to place the fire
      </label>
      <p className="dim">
        {fire.floor ? `Fire: ${(room ?? ghost)?.name ?? fire.room ?? '?'} on ${fire.floor}` : 'No fire placed yet'}
      </p>
      <label>
        Occupants
        <input
          type="number"
          min={1}
          value={draft.occupants.total}
          onChange={(e) =>
            patchDraft({ occupants: { ...draft.occupants, total: Math.max(1, Math.round(num(e.target.value, 1))) } })
          }
        />
      </label>
      {MIX.map((p) => (
        <label key={p}>
          {p}
          <input
            type="number"
            min={0}
            step={0.05}
            value={draft.occupants.mix[p] ?? 0}
            onChange={(e) =>
              patchDraft({
                occupants: { ...draft.occupants, mix: { ...draft.occupants.mix, [p]: Math.max(0, num(e.target.value, 0)) } },
              })
            }
          />
        </label>
      ))}
      <label>
        Seed
        <input type="number" value={draft.seed} onChange={(e) => patchDraft({ seed: Math.round(num(e.target.value, 1)) })} />
      </label>
      <label>
        Alarm time (s)
        <input
          type="number"
          min={0}
          value={draft.alarmTime ?? 30}
          onChange={(e) => patchDraft({ alarmTime: Math.max(0, num(e.target.value, 30)) })}
        />
      </label>
      <h4>Door overrides</h4>
      {Object.entries(doors).map(([id, st]) => (
        <div className="doorrow" key={id}>
          <span>{id}</span>
          <select value={st} onChange={(e) => patchDraft({ doors: { ...doors, [id]: e.target.value as DoorState } })}>
            {STATES.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <button
            onClick={() => {
              const n = { ...doors }
              delete n[id]
              patchDraft({ doors: n })
            }}
            aria-label={`Remove ${id}`}
          >
            ×
          </button>
        </div>
      ))}
      <div className="doorrow">
        <select value={doorPick} onChange={(e) => setDoorPick(e.target.value)}>
          <option value="">Door…</option>
          {doorIds
            .filter((d) => !(d in doors))
            .map((d) => (
              <option key={d}>{d}</option>
            ))}
        </select>
        <button
          disabled={!doorPick}
          onClick={() => {
            patchDraft({ doors: { ...doors, [doorPick]: 'propped' } })
            setDoorPick('')
          }}
        >
          Add
        </button>
      </div>
      <button className="run" disabled={!!running} onClick={() => void runScenario(draft)}>
        {running ?? 'Run'}
      </button>
      {runError && <p className="err">{runError}</p>}
      {runNote && <p className="dim">{runNote}</p>}
    </div>
  )
}
