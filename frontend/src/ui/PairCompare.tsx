import { useEffect, useState } from 'react'
import { useApp } from '../store/app'
import { compareRuns } from '../model/whatif'
import { pairHeadline } from '../model/exposure'
import { materialPair, materialWords, runMaterial } from '../model/fireSpread'
import type { MaterialPair } from '../model/fireSpread'
import { CLAUDE_WORDS, brainPair } from '../model/brain'
import type { BrainPair } from '../model/brain'
import { listDemoRuns } from '../data/loader'

const fmt = (v: number | null) => (v == null ? 'not reached' : `${v.toFixed(0)} s`)
const signed = (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(0)} s`

/** The loaded building's precomputed wood and drywall pair and rules and Claude crowd pair, from the demo index: each comparison shows only for a building that has one. */
export function usePairs(): { material: MaterialPair | null; claude: BrainPair | null } {
  const buildingId = useApp((s) => s.building?.id)
  const [found, setFound] = useState<{ building: string; material: MaterialPair | null; claude: BrainPair | null } | null>(null)
  useEffect(() => {
    let current = true
    if (buildingId)
      void listDemoRuns(buildingId).then((es) => current && setFound({ building: buildingId, material: materialPair(es, buildingId), claude: brainPair(es, buildingId) }))
    return () => {
      current = false
    }
  }, [buildingId])
  return found && found.building === buildingId ? found : { material: null, claude: null }
}

/** W switches between the run on screen and its comparison partner: the baseline from its variant, a baseline to the latest variant of it. */
export function useCompareKey() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'KeyW' || e.ctrlKey || e.metaKey || e.altKey) return
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
      const s = useApp.getState()
      const a = s.activeRunKey ? s.runs[s.activeRunKey] : null
      if (!a) return
      if (a.whatIf) return s.switchRun(a.whatIf.baselineKey)
      const w = [...s.runOrder].reverse().find((k) => s.runs[k].whatIf?.baselineKey === a.key)
      if (w) s.switchRun(w)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}

/** What the comparison on screen says, when it is a `kind` one: the headline (the people trapped first when the two runs differ in them, then the smoke line), then the t90 and trapped line. */
function Headline({ kind }: { kind: 'material' | 'brain' }) {
  const runs = useApp((s) => s.runs)
  const activeKey = useApp((s) => s.activeRunKey)
  const order = useApp((s) => s.runOrder)
  const active = activeKey ? runs[activeKey] : null
  const base = active?.whatIf ? runs[active.whatIf.baselineKey] : active
  const variant = active?.whatIf ? active : order.map((k) => runs[k]).reverse().find((r) => r.whatIf?.baselineKey === active?.key)
  const material = variant?.whatIf?.material
  const brain = variant?.whatIf?.brain
  if (!variant || !base || !(kind === 'brain' ? brain : material)) return null
  // "Wood instead of drywall" or "Claude crowd instead of rules"; a pair with no numbers to add still names itself.
  const what = kind === 'brain' ? CLAUDE_WORDS : materialWords(material!, runMaterial(base.run))
  const head = pairHeadline(base.run, variant.run, what) ?? { main: what, smoke: null }
  const cmp = compareRuns(base.run, variant.run)
  return (
    <>
      <p className="whatif-card"><b>{head.main}</b></p>
      {head.smoke && <p className="whatif-card">{head.smoke}</p>}
      <p className={'whatif-card' + (cmp.dT90 != null ? (cmp.dT90 > 0 || cmp.dTrapped > 0 ? ' worse' : ' better') : cmp.dTrapped > 0 ? ' worse' : '')}>
        t90 {fmt(cmp.t90[0])} → {fmt(cmp.t90[1])}
        {cmp.dT90 != null ? ` (${signed(cmp.dT90)})` : ''}, trapped {base.run.metrics.trapped} → {variant.run.metrics.trapped}
      </p>
    </>
  )
}

/**
 * One precomputed comparison, shown under the setting it is about in the Fire and scenario card: "Compare wood with drywall" under the
 * building material, "Compare rules with Claude crowd" under the crowd. The button loads the pair's two runs and splits the view; what
 * the pair says follows below it.
 */
export default function PairCompare({ kind, fire, label }: { kind: 'material' | 'brain'; fire: { floor: string; room: string }; label: string }) {
  const building = useApp((s) => s.building)
  const busy = useApp((s) => s.pairBusy)
  const err = useApp((s) => s.pairError)
  const [asked, setAsked] = useState(false)
  const name = building?.floors.find((f) => f.id === fire.floor)?.rooms.find((r) => r.id === fire.room)?.name
  const where = name && name !== fire.room ? `${name} (${fire.room})` : fire.room
  return (
    <div className={kind === 'brain' ? 'paircompare claudepair' : 'paircompare material'}>
      <button
        type="button"
        disabled={!!busy}
        onClick={() => {
          setAsked(true)
          void (kind === 'brain' ? useApp.getState().showBrainPair() : useApp.getState().showMaterialPair())
        }}
      >
        {label}
      </button>
      {kind === 'brain' ? (
        <p className="dim note">
          Illustrative. Precomputed pair, fire in {where}: the rules against one saved run where Claude decides for everyone, with the same doors and seed. Claude's answers can differ from one run to the next.
        </p>
      ) : (
        <p className="dim note">Precomputed pair, fire in {where}. Spread speeds are illustrative, not engineering values.</p>
      )}
      {asked && err && <p className="err">{err}</p>}
      <Headline kind={kind} />
    </div>
  )
}
