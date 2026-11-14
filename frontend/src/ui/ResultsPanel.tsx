import { useState } from 'react'
import EvacCurve from '../dashboard/EvacCurve'
import ExitBars from '../dashboard/ExitBars'
import RunStats from '../dashboard/RunStats'

import ReportCard from '../dashboard/ReportCard'
import Credibility from '../dashboard/Credibility'
import WeakSpots from '../dashboard/WeakSpots'

const TABS = [
  { id: 'results', label: 'Results' },
  { id: 'risk', label: 'Risk map' },
  { id: 'report', label: 'Report' },
  { id: 'cred', label: 'Credibility' },
]

export default function ResultsPanel() {
  const [tab, setTab] = useState<string>('results')
  return (
    <div className="results">
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? 'on' : ''} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'results' && (
        <>
          <h4>Evacuation curve</h4>
          <EvacCurve />
          <h4>Exit use</h4>
          <ExitBars />
          <h4>Run</h4>
          <RunStats />
        </>
      )}
      {tab === 'risk' && <WeakSpots />}
      {tab === 'report' && <ReportCard />}
      {tab === 'cred' && <Credibility />}
      <p className="dim foot">Illustrative fire model. Not a compliance tool. One seed is one possible night.</p>
    </div>
  )
}
