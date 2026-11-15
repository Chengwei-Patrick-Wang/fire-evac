import { useState } from 'react'
import { useApp } from '../store/app'
import { FIRE_TYPES, insidePoint, roomAt } from '../model/scenarioDraft'
import { DEFAULT_MATERIAL, MATERIALS } from '../model/fireSpread'
import { CROWDS, CROWD_NOTE, DEFAULT_BRAIN, claudeCrowdLimit, crowdOf, crowdTooBig } from '../model/brain'
import type { Brain } from '../model/brain'
import WhatIfCard from './WhatIfCard'
import type { DoorState, Material, Profile } from '../data/types'

const MIX: Profile[] = ['typical', 'older', 'visitor']
const STATES: DoorState[] = ['open', 'closed', 'propped', 'blocked']

export default function ScenarioPanel() {
  const { draft, building, patchDraft, placing, setPlacing, running, runError, runNote, runFallback, runScenario, mode, material, setMaterial } = useApp()
  const [doorPick, setDoorPick] = useState('')
  if (!draft || !building) return <p className="dim">Load a building to set up a scenario.</p>
  const doorIds = building.floors.flatMap((f) => f.doors.map((d) => d.id))
  const doors = draft.doors ?? {}
  const fire = draft.fire
  const room =
    fire.floor && fire.room ? building.floors.find((f) => f.id === fire.floor)?.rooms.find((r) => r.id === fire.room) : null
  const ghost = fire.floor && fire.x !== undefined && fire.y !== undefined ? roomAt(building, fire.floor, fire.x, fire.y) : null
  const fireRooms = [...building.floors]
    .sort((a, b) => a.level - b.level)
    .map((f) => {
      const sr = new Set(f.stairs.map((s) => s.room))
      return { f, rs: f.rooms.filter((r) => r.type !== 'stair' && !sr.has(r.id) && insidePoint(r.polygon) && roomAt(building, f.id, ...(insidePoint(r.polygon) as [number, number]))) }
    })
    .filter((o) => o.rs.length)
  const live = mode === 'live'
  // Only the live backend runs a Claude crowd; static mode always shows the rules' precomputed runs. Everyone asks Claude holds up to 200 people.
  const crowd: Brain = live ? crowdOf(draft.brain) : DEFAULT_BRAIN
  const tooMany = crowdTooBig(draft, live)
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
      <label>
        Fire room
        <select
          value={fire.floor && fire.room ? `${fire.floor}|${fire.room}` : ''}
          onChange={(e) => {
            const [fl, rm] = e.target.value.split('|')
            const r = building.floors.find((f) => f.id === fl)?.rooms.find((x) => x.id === rm)
            const pt = r ? insidePoint(r.polygon) : null
            if (!r || !pt) return
            patchDraft({ fire: { ...fire, floor: fl, room: rm, x: Math.round(pt[0] * 100) / 100, y: Math.round(pt[1] * 100) / 100, start: 0 } })
          }}
        >
          {!(fire.floor && fire.room && fireRooms.some((o) => o.f.id === fire.floor && o.rs.some((r) => r.id === fire.room))) && (
            <option value="">{fire.room ?? 'Pick a room'}</option>
          )}
          {fireRooms.map(({ f, rs }) => (
            <optgroup key={f.id} label={f.id}>
              {rs.map((r) => (
                <option key={r.id} value={`${f.id}|${r.id}`}>{r.name ?? r.id}</option>
              ))}
            </optgroup>
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
        Building material (illustrative)
        <select value={live ? material : DEFAULT_MATERIAL} disabled={!live} onChange={(e) => setMaterial(e.target.value as Material)}>
          {MATERIALS.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
      </label>
      {!live && (
        <p className="dim note">
          Material needs the live backend. In static mode, What if… shows the precomputed wood and drywall pair where a building has one.
        </p>
      )}
      <label>
        Crowd
        <select value={crowd} disabled={!live} onChange={(e) => patchDraft({ brain: e.target.value as Brain })}>
          {CROWDS.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
      {!live && (
        <p className="dim note">
          Claude crowds need the live backend. In static mode, What if… shows the precomputed comparison where one exists.
        </p>
      )}
      {live && crowd !== 'rules' && <p className="dim note">{CROWD_NOTE[crowd]}</p>}
      {tooMany && (
        <p className="warn" id="crowd-limit" role="alert">
          {claudeCrowdLimit(draft.occupants.total)}
        </p>
      )}
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
          <select aria-label={`State of ${id}`} value={st} onChange={(e) => patchDraft({ doors: { ...doors, [id]: e.target.value as DoorState } })}>
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
        <select aria-label="Door to override" value={doorPick} onChange={(e) => setDoorPick(e.target.value)}>
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
      <button className="run" disabled={!!running || tooMany} aria-describedby={tooMany ? 'crowd-limit' : undefined} onClick={() => void runScenario(draft)}>
        {running ?? 'Run'}
      </button>
      {runError && <p className="err">{runError}</p>}
      {runNote && (
        <p className={runFallback ? 'warn' : 'dim'} role="status">
          {runNote}
        </p>
      )}
      <WhatIfCard />
    </div>
  )
}
