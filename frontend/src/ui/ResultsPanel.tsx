import { useApp } from '../store/app'
import type { ResultsTab } from '../store/app'
import EvacCurve from '../dashboard/EvacCurve'
import ExitBars from '../dashboard/ExitBars'
import RunStats from '../dashboard/RunStats'
import AccessStats from '../dashboard/AccessStats'

import ReportCard from '../dashboard/ReportCard'
import Credibility from '../dashboard/Credibility'
import WeakSpots from '../dashboard/WeakSpots'

const TABS: { id: ResultsTab; label: string }[] = [
  { id: 'results', label: 'Results' },
  { id: 'risk', label: 'Risk map' },
  { id: 'report', label: 'Report' },
  { id: 'cred', label: 'Credibility' },
]

export default function ResultsPanel() {
  const tab = useApp((s) => s.resultsTab)
  const setTab = useApp((s) => s.setResultsTab)
  return (
    <div className="results">
      <div className="tabs" role="tablist" aria-label="Results">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            id={`tab-${t.id}`}
            role="tab"
            aria-selected={tab === t.id}
            aria-controls="results-panel"
            tabIndex={tab === t.id ? 0 : -1}
            className={tab === t.id ? 'on' : ''}
            onClick={() => setTab(t.id)}
            onKeyDown={(e) => {
              let j = -1
              if (e.key === 'ArrowRight') j = (i + 1) % TABS.length
              else if (e.key === 'ArrowLeft') j = (i + TABS.length - 1) % TABS.length
              else if (e.key === 'Home') j = 0
              else if (e.key === 'End') j = TABS.length - 1
              if (j < 0) return
              e.preventDefault()
              e.stopPropagation()
              setTab(TABS[j].id)
              document.getElementById(`tab-${TABS[j].id}`)?.focus()
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="results-panel" aria-labelledby={`tab-${tab}`}>
      {tab === 'results' && (
        <>
          <h4>Evacuation curve</h4>
          <EvacCurve />
          <h4>Exit use</h4>
          <ExitBars />
          <h4>Run</h4>
          <RunStats />
          <AccessStats />
        </>
      )}
      {tab === 'risk' && <WeakSpots />}
      {tab === 'report' && <ReportCard />}
      {tab === 'cred' && <Credibility />}
      </div>
      <p className="dim foot">Illustrative fire model. Not a compliance tool. One seed is one possible night.</p>
    </div>
  )
}
