import { useEffect, useMemo, useState } from 'react'
import { useApp } from '../store/app'
import { compareRuns, defaultWhatIfDoor, stairDoors } from '../model/whatif'
import { pairHeadline, readWhatIf } from '../model/exposure'
import { doorLabels } from '../model/spots'
import { materialPair, materialWords, runMaterial } from '../model/fireSpread'
import type { MaterialPair } from '../model/fireSpread'
import { CLAUDE_WORDS, WHATIF_RULES_ONLY, brainPair, crowdOf } from '../model/brain'
import type { BrainPair } from '../model/brain'
import { listDemoRuns } from '../data/loader'
import type { DoorState } from '../data/types'

const STATES: DoorState[] = ['propped', 'open', 'closed', 'blocked']
const fmt = (v: number | null) => (v == null ? 'not reached' : `${v.toFixed(0)} s`)
const signed = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(0)} s`

export default function WhatIfCard() {
  const building = useApp((s) => s.building)
  const runs = useApp((s) => s.runs)
  const activeKey = useApp((s) => s.activeRunKey)
  const order = useApp((s) => s.runOrder)
  const busy = useApp((s) => s.whatIfBusy)
  const err = useApp((s) => s.whatIfError)
  const note = useApp((s) => s.whatIfNote)
  const fallback = useApp((s) => s.whatIfFallback)
  const runWhatIf = useApp((s) => s.runWhatIf)
  const showMaterialPair = useApp((s) => s.showMaterialPair)
  const showBrainPair = useApp((s) => s.showBrainPair)
  const switchRun = useApp((s) => s.switchRun)
  const live = useApp((s) => s.mode) === 'live'
  const batch = useApp((s) => s.batch)
  const headlines = useApp((s) => s.headlines)
  const active = activeKey ? runs[activeKey] : null
  const base = active?.whatIf ? runs[active.whatIf.baselineKey] : active
  const fire = base?.run.fire
  const [door, setDoor] = useState('')
  const [state, setState] = useState<DoorState>('propped')
  const [sprinklers, setSprinklers] = useState(false)

  // The building's precomputed wood and drywall pair and rules and Claude crowd pair, from the demo index: each section shows only for a building that has one.
  const [found, setFound] = useState<{ building: string; pair: MaterialPair | null; claude: BrainPair | null } | null>(null)
  const buildingId = building?.id
  useEffect(() => {
    let current = true
    if (buildingId)
      void listDemoRuns(buildingId).then((es) => current && setFound({ building: buildingId, pair: materialPair(es, buildingId), claude: brainPair(es, buildingId) }))
    return () => {
      current = false
    }
  }, [buildingId])
  const pair = found && found.building === buildingId ? found.pair : null
  const pairRoom = pair && building ? building.floors.find((f) => f.id === pair.wood.fire.floor)?.rooms.find((r) => r.id === pair.wood.fire.room) : undefined
  const claude = found && found.building === buildingId ? found.claude : null
  const claudeRoom = claude && building ? building.floors.find((f) => f.id === claude.claude.fire.floor)?.rooms.find((r) => r.id === claude.claude.fire.room) : undefined
  // A door what-if is measured against a rules baseline: a live run of a Claude crowd has no such baseline (the store refuses it too).
  const claudeBase = crowdOf(base?.scenario?.brain) !== 'rules'

  const stair = useMemo(() => (building ? stairDoors(building).map((d) => d.door.id) : []), [building])
  const others = useMemo(
    () => (building ? building.floors.flatMap((f) => f.doors.map((d) => d.id)).filter((id) => !stair.includes(id)) : []),
    [building, stair],
  )
  const def = building && fire ? defaultWhatIfDoor(building, fire) : null
  const chosen = door || def || ''

  // Doors read as words; the id stays each option's value. With several floors the floor tells equal names apart.
  const names = building ? doorLabels(building) : null
  const multi = (building?.floors.length ?? 0) > 1
  const nameOf = (id: string) => names?.get(id)?.label ?? id
  const optionText = (id: string) => {
    const n = names?.get(id)
    return n ? `${n.label}${multi ? ` · ${n.floor}` : ''}` : id
  }

  // Static mode cannot run sprinklers, so quote the measured what-if (the batch's, else the headline pack's).
  const measured = live
    ? undefined
    : [...readWhatIf(batch), ...(headlines?.whatIf ?? [])].find((e) => e.id === 'sprinklers' && typeof e.n === 'number' && e.n > 0)

  // W toggles between the baseline and the latest what-if.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'KeyW' || e.ctrlKey || e.metaKey || e.altKey) return
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
      const s = useApp.getState()
      const a = s.activeRunKey ? s.runs[s.activeRunKey] : null
      if (!a) return
      if (a.whatIf) return switchRun(a.whatIf.baselineKey)
      const w = [...s.runOrder].reverse().find((k) => s.runs[k].whatIf?.baselineKey === a.key)
      if (w) switchRun(w)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [switchRun])

  const variant = active?.whatIf
    ? active
    : order.map((k) => runs[k]).reverse().find((r) => r.whatIf?.baselineKey === active?.key)
  const cmp = variant && base ? compareRuns(base.run, variant.run) : null
  // A material variant reads "Wood instead of drywall", a crowd variant "Claude crowd instead of rules"; a door variant names the door.
  const material = variant?.whatIf?.material
  const brain = variant?.whatIf?.brain
  const head =
    variant?.whatIf && base
      ? brain
        ? { main: pairHeadline(base.run, variant.run, CLAUDE_WORDS)?.main ?? CLAUDE_WORDS }
        : material
          ? { main: pairHeadline(base.run, variant.run, materialWords(material, runMaterial(base.run)))?.main ?? materialWords(material, runMaterial(base.run)) }
          : pairHeadline(base.run, variant.run, variant.whatIf.state === 'propped' ? `Propping ${nameOf(variant.whatIf.door)} open` : `${nameOf(variant.whatIf.door)} ${variant.whatIf.state}`)
      : null

  return (
    <div className="whatif">
      <h4>What if…</h4>
      <div className="doorrow">
        <select value={chosen} onChange={(e) => setDoor(e.target.value)} aria-label="Door" title={optionText(chosen)}>
          <optgroup label="Stair doors">
            {stair.map((id) => (
              <option key={id} value={id}>{optionText(id)}</option>
            ))}
          </optgroup>
          <optgroup label="Other doors">
            {others.map((id) => (
              <option key={id} value={id}>{optionText(id)}</option>
            ))}
          </optgroup>
        </select>
        <select value={state} onChange={(e) => setState(e.target.value as DoorState)} aria-label="State">
          {STATES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={live && sprinklers}
          disabled={!live}
          title={live ? undefined : 'Sprinklers need the live backend'}
          onChange={(e) => setSprinklers(e.target.checked)}
        />
        Sprinklers
      </label>
      {!live && (
        <p className="dim note">
          Sprinklers need the live backend.
          {measured ? ` Measured across ${measured.n} fires: ${measured.why}` : ' This static demo has precomputed propped-door runs only.'}
        </p>
      )}
      <button className="run" disabled={!base || !chosen || !!busy || claudeBase} onClick={() => void runWhatIf(chosen, state, live && sprinklers)}>
        {busy ?? 'Run what-if'}
      </button>
      {claudeBase && <p className="dim note">{WHATIF_RULES_ONLY}</p>}
      {err && <p className="err">{err}</p>}
      {note && (
        <p className={fallback ? 'warn' : 'dim'} role="status">
          {note}
        </p>
      )}
      {pair && (
        <div className="material">
          <h5>Building material (illustrative)</h5>
          <button type="button" disabled={!!busy} onClick={() => void showMaterialPair()}>
            Compare wood with drywall
          </button>
          <p className="dim note">
            Precomputed pair, fire in {pairRoom?.name && pairRoom.name !== pair.wood.fire.room ? `${pairRoom.name} (${pair.wood.fire.room})` : pair.wood.fire.room}. Spread speeds are illustrative, not engineering values.
          </p>
        </div>
      )}
      {claude && (
        <div className="claudepair">
          <h5>Claude crowd (illustrative)</h5>
          <button type="button" disabled={!!busy} onClick={() => void showBrainPair()}>
            Compare rules with Claude crowd
          </button>
          <p className="dim note">
            Precomputed pair, fire in {claudeRoom?.name && claudeRoom.name !== claude.claude.fire.room ? `${claudeRoom.name} (${claude.claude.fire.room})` : claude.claude.fire.room}: the rules against one saved run where Claude decides for everyone, with the same doors and seed. Claude's answers can differ from one run to the next.
          </p>
        </div>
      )}
      {head && <p className="whatif-card"><b>{head.main}</b></p>}
      {cmp && variant && (
        <p className={'whatif-card' + (cmp.dT90 != null ? (cmp.dT90 > 0 || cmp.dTrapped > 0 ? ' worse' : ' better') : cmp.dTrapped > 0 ? ' worse' : '')}>
          t90 {fmt(cmp.t90[0])} → {fmt(cmp.t90[1])}
          {cmp.dT90 != null ? ` (${signed(cmp.dT90)})` : ''}, trapped {base!.run.metrics.trapped} → {variant.run.metrics.trapped}
        </p>
      )}
    </div>
  )
}
