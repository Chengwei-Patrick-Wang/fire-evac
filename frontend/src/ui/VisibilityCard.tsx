import { useApp } from '../store/app'

/** The two settings "High visibility" sets, and "Reset" clears back to 1. */
const HIGH = { fireGlow: 2, smokeOpacity: 1.5 }

/**
 * "Fire and smoke visibility": switches and two sliders for how fire and smoke are drawn. They change the picture only, never the
 * simulation (nothing in the run reads them).
 */
export default function VisibilityCard() {
  const fire = useApp((s) => s.layers.fire)
  const smoke = useApp((s) => s.layers.smoke)
  const glow = useApp((s) => s.fireGlow)
  const opacity = useApp((s) => s.smokeOpacity)
  const hasSmoke = useApp((s) => {
    const r = s.activeRunKey ? s.runs[s.activeRunKey]?.run : undefined
    return !!r?.smoke?.length
  })
  const set = useApp.setState
  const high = glow === HIGH.fireGlow && opacity === HIGH.smokeOpacity
  const why = hasSmoke ? '' : 'This run has no smoke frames'

  return (
    <div className="visibility">
      <label className="check">
        <input type="checkbox" checked={fire} onChange={(e) => set((s) => ({ layers: { ...s.layers, fire: e.target.checked } }))} />
        Fire
      </label>
      <label className={'check' + (why ? ' off' : '')} title={why || undefined}>
        <input
          type="checkbox"
          disabled={!!why}
          checked={smoke && hasSmoke}
          onChange={(e) => set((s) => ({ layers: { ...s.layers, smoke: e.target.checked } }))}
        />
        Smoke
      </label>
      <div className="vis-row">
        <label htmlFor="vis-glow">Fire glow and size</label>
        <input id="vis-glow" type="range" min={0} max={2} step={0.1} value={glow} onChange={(e) => set({ fireGlow: +e.target.value })} />
        <output htmlFor="vis-glow">{glow.toFixed(1)}×</output>
      </div>
      <div className="vis-row">
        <label htmlFor="vis-smoke">Smoke opacity</label>
        <input id="vis-smoke" type="range" min={0} max={1.5} step={0.1} value={opacity} onChange={(e) => set({ smokeOpacity: +e.target.value })} />
        <output htmlFor="vis-smoke">{Math.round(opacity * 100)}%</output>
      </div>
      <div className="vis-btns">
        <button
          type="button"
          className={high ? 'on' : ''}
          aria-pressed={high}
          onClick={() => set((s) => ({ ...HIGH, layers: { ...s.layers, fire: true, smoke: true } }))}
        >
          High visibility
        </button>
        <button type="button" onClick={() => set({ fireGlow: 1, smokeOpacity: 1 })}>
          Reset
        </button>
      </div>
      <p className="dim note">Changes the picture only, never the simulation.</p>
    </div>
  )
}
