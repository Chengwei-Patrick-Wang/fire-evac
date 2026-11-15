import { useEffect } from 'react'
import { sideDraft, useApp } from '../store/app'
import type { Side } from '../store/app'
import { PLACE_FIRE_FIRST, firePlaced, fromPercent, insidePoint, roomAt, toPercent } from '../model/scenarioDraft'
import { DEFAULT_MATERIAL, MATERIALS } from '../model/fireSpread'
import { CROWDS, CROWD_NOTE, DEFAULT_BRAIN, claudeCrowdLimit, crowdOf, crowdTooBig } from '../model/brain'
import type { Brain } from '../model/brain'
import { FIRE_GROWTHS, FIRE_SIZES, fireGrowthOf, fireSizeOf, withFireGrowth, withFireSize } from '../model/fireSetup'
import type { FireGrowthId, FireSizeId } from '../model/fireSetup'
import { floorName } from '../model/floors'
import PairCompare, { usePairs } from './PairCompare'
import SideRunPicker from './SideRunPicker'
import type { Material, Profile } from '../data/types'

/** The people the card lets you mix, in plain words. The scenario keeps their shares as fractions of 1; the card shows percent. */
const MIX: { id: Profile; label: string }[] = [
  { id: 'typical', label: 'Typical adults' },
  { id: 'older', label: 'Older adults (walk slower)' },
  { id: 'visitor', label: "Visitors (don't know the building)" },
]

/**
 * The Fire and scenario settings. In the split view `side` says which pane they are for: the left is the loaded building's scenario, the
 * right has its own (and its own building, material and run). Without a side it is the one scenario of the single view.
 */
export default function ScenarioPanel({ side }: { side?: Side }) {
  const app = useApp()
  const { placing, setPlacing, running, runError, runNote, runFallback, runScenario, mode } = app
  const right = side === 'R'
  const draft = side ? sideDraft(app, side) : app.draft
  const building = right ? app.rightBuilding ?? app.building : app.building
  const patchDraft = right ? app.patchRightDraft : app.patchDraft
  const material = right ? app.rightMaterial : app.material
  const setMaterial = right ? app.setRightMaterial : app.setMaterial
  // The precomputed comparisons of this building (each shows under its own setting, and only when the demo index has the pair).
  const pairs = usePairs()
  // A card that opens on a draft with no fire yet starts placing: the first click on a room puts the fire there.
  const noFire = !!draft && !draft.fire.floor
  const buildingId = building?.id
  useEffect(() => {
    if (noFire) setPlacing(true)
  }, [noFire, buildingId, setPlacing])
  if (!draft || !building) return <p className="dim">Load a building to set up a scenario.</p>
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
  // A run needs the fire placed in a room (the backend refuses one without), so Run stays off until a click or the room list places it.
  const placed = firePlaced(draft)
  const mixTotal = MIX.reduce((n, p) => n + toPercent(draft.occupants.mix[p.id]), 0)
  const num = (v: string, d: number) => (Number.isFinite(parseFloat(v)) ? parseFloat(v) : d)

  // The precomputed comparisons load a pair of the loaded building's runs into both panes: they are for the left, or a right side on the same building.
  const pairsHere = !(right && app.rightBuilding)
  return (
    <div className="scenario">
      {side && <SideRunPicker side={side} />}
      <label>
        Fire size
        <select value={fireSizeOf(fire)} aria-describedby="sc-hint-size" onChange={(e) => patchDraft({ fire: withFireSize(fire, e.target.value as FireSizeId) })}>
          {FIRE_SIZES.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
      <p className="dim hint" id="sc-hint-size">How big the fire gets.</p>
      <label>
        How fast it grows
        <select value={fireGrowthOf(fire)} aria-describedby="sc-hint-growth" onChange={(e) => patchDraft({ fire: withFireGrowth(fire, e.target.value as FireGrowthId) })}>
          {FIRE_GROWTHS.map((g) => (
            <option key={g.id} value={g.id}>
              {g.label}
            </option>
          ))}
        </select>
      </label>
      <p className="dim hint" id="sc-hint-growth">How quickly it reaches its full size.</p>
      <div className="fireplace">
        <p className="where" role="status">
          {fire.floor ? (
            <>
              Fire in: <b>{(room ?? ghost)?.name ?? fire.room ?? 'a spot'}</b>, {floorName(building, fire.floor)}
            </>
          ) : (
            'No fire placed yet.'
          )}
          {placing && <span className="dim"> Click a room in the building to {fire.floor ? 'move' : 'place'} the fire.</span>}
        </p>
        <button type="button" onClick={() => setPlacing(!placing)}>
          {placing ? 'Cancel' : fire.floor ? 'Move fire' : 'Place fire'}
        </button>
      </div>
      <details className="roompick">
        <summary>Choose a room from a list</summary>
        <label>
          Room
          <select
            value={fire.floor && fire.room ? `${fire.floor}|${fire.room}` : ''}
            onChange={(e) => {
              const [fl, rm] = e.target.value.split('|')
              const r = building.floors.find((f) => f.id === fl)?.rooms.find((x) => x.id === rm)
              const pt = r ? insidePoint(r.polygon) : null
              if (!r || !pt) return
              patchDraft({ fire: { ...fire, floor: fl, room: rm, x: Math.round(pt[0] * 100) / 100, y: Math.round(pt[1] * 100) / 100, start: 0 } })
              setPlacing(false)
            }}
          >
            {!(fire.floor && fire.room && fireRooms.some((o) => o.f.id === fire.floor && o.rs.some((r) => r.id === fire.room))) && (
              <option value="">{fire.room ?? 'Pick a room'}</option>
            )}
            {fireRooms.map(({ f, rs }) => (
              <optgroup key={f.id} label={floorName(building, f.id)}>
                {rs.map((r) => (
                  <option key={r.id} value={`${f.id}|${r.id}`}>{r.name ?? r.id}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
      </details>
      <label>
        Building material (illustrative)
        <select value={live ? material : DEFAULT_MATERIAL} disabled={!live} aria-describedby="sc-hint-material" onChange={(e) => setMaterial(e.target.value as Material)}>
          {MATERIALS.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
      </label>
      <p className="dim hint" id="sc-hint-material">How fast the fire spreads from room to room.</p>
      {!live && (
        <p className="dim note">
          Material needs the live backend. In static mode, the comparison below shows the precomputed wood and drywall pair where a building has one.
        </p>
      )}
      {pairsHere && pairs.material && <PairCompare kind="material" fire={pairs.material.wood.fire} label="Compare wood with drywall" />}
      <label>
        Crowd
        <select value={crowd} disabled={!live} aria-describedby="sc-hint-crowd" onChange={(e) => patchDraft({ brain: e.target.value as Brain })}>
          {CROWDS.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
      <p className="dim hint" id="sc-hint-crowd">Who decides where people go.</p>
      {!live && (
        <p className="dim note">
          Claude crowds need the live backend. In static mode, the comparison below shows the precomputed one where a building has it.
        </p>
      )}
      {live && crowd !== 'rules' && <p className="dim note">{CROWD_NOTE[crowd]}</p>}
      {tooMany && (
        <p className="warn" id="crowd-limit" role="alert">
          {claudeCrowdLimit(draft.occupants.total)}
        </p>
      )}
      {pairsHere && pairs.claude && <PairCompare kind="brain" fire={pairs.claude.claude.fire} label="Compare rules with Claude crowd" />}
      <label>
        People in the building
        <input
          type="number"
          min={1}
          value={draft.occupants.total}
          aria-describedby="sc-hint-people"
          onChange={(e) =>
            patchDraft({ occupants: { ...draft.occupants, total: Math.max(1, Math.round(num(e.target.value, 1))) } })
          }
        />
      </label>
      <p className="dim hint" id="sc-hint-people">How many people are inside when the fire starts.</p>
      <fieldset className="mix">
        <legend>Who is inside</legend>
        {MIX.map((p) => (
          <label key={p.id}>
            {p.label}
            <span className="pct">
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={toPercent(draft.occupants.mix[p.id])}
                onChange={(e) =>
                  patchDraft({
                    occupants: { ...draft.occupants, mix: { ...draft.occupants.mix, [p.id]: fromPercent(num(e.target.value, 0)) } },
                  })
                }
              />
              %
            </span>
          </label>
        ))}
        {mixTotal !== 100 && (
          <p className="caution note">
            {mixTotal === 0 ? 'With none set, everyone counts as a typical adult.' : `These add up to ${mixTotal}%. They are scaled to 100% when you run.`}
          </p>
        )}
      </fieldset>
      <label>
        Variation
        <input type="number" value={draft.seed} aria-describedby="sc-hint-seed" onChange={(e) => patchDraft({ seed: Math.round(num(e.target.value, 1)) })} />
      </label>
      <p className="dim hint" id="sc-hint-seed">Same number, same run; change it to see another possible night.</p>
      <label>
        Alarm sounds after (seconds)
        <input
          type="number"
          min={0}
          value={draft.alarmTime ?? 30}
          aria-describedby="sc-hint-alarm"
          onChange={(e) => patchDraft({ alarmTime: Math.max(0, num(e.target.value, 30)) })}
        />
      </label>
      <p className="dim hint" id="sc-hint-alarm">Seconds after the fire starts.</p>
      <button
        className="run"
        disabled={!!running || tooMany || !placed}
        aria-describedby={[tooMany ? 'crowd-limit' : '', placed ? '' : 'sc-hint-run'].filter(Boolean).join(' ') || undefined}
        title={placed ? undefined : PLACE_FIRE_FIRST}
        onClick={() => void (side ? app.runSide(side) : runScenario(draft))}
      >
        {running ?? (side ? `Run ${side === 'L' ? 'left' : 'right'} side` : 'Run')}
      </button>
      {!placed && (
        <p className="dim hint" id="sc-hint-run">
          {PLACE_FIRE_FIRST}
        </p>
      )}
      {runError && <p className="err">{runError}</p>}
      {runNote && (
        <p className={runFallback ? 'warn' : 'dim'} role="status">
          {runNote}
        </p>
      )}
    </div>
  )
}
