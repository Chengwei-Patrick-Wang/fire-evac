import { useApp } from '../store/app'
import { defaultFire } from '../model/scenarioDraft'

export default function NewBuildingCard() {
  const { fromTracer, building, activeRunKey, running, runError, draft } = useApp()
  if (!building || fromTracer !== building.id || activeRunKey) return null
  const go = () => {
    const app = useApp.getState()
    if (!app.draft) return
    let d = app.draft
    if (!d.fire.floor) {
      const f = defaultFire(building)
      if (f) d = { ...d, fire: { ...d.fire, ...f } }
      app.patchDraft({ fire: d.fire })
    }
    void app.runScenario(d)
  }
  return (
    <div className="newbuilding">
      <button className="x" aria-label="Dismiss" onClick={() => useApp.setState({ fromTracer: null })}>×</button>
      <b>{building.name} is ready.</b>
      <p>Click a room to place the fire, or let the app pick the largest room on the lowest floor.</p>
      <button className="run" disabled={!draft || !!running} onClick={go}>{running ?? 'Run a scenario here'}</button>
      {runError && <div className="err">{runError}</div>}
    </div>
  )
}
