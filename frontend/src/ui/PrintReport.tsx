import { useEffect, useRef, useState } from 'react'
import { useDialogFocus } from './a11y'
import { createPortal } from 'react-dom'
import Markdown from 'react-markdown'
import { useApp } from '../store/app'
import { fetchReport } from '../data/loader'
import { reportRef } from '../dashboard/ReportCard'
import { Limits } from '../dashboard/Credibility'
import RiskLegend, { Stamps } from '../dashboard/RiskLegend'
import RiskMapSvg from '../dashboard/RiskMapSvg'
import WhatIfHeadline from '../dashboard/WhatIfHeadline'
import MeasuredFixes from '../dashboard/MeasuredFixes'
import { readFixes } from '../model/fixes'

export default function PrintReport() {
  const building = useApp((s) => s.building)
  const batch = useApp((s) => s.batch)
  const runKey = useApp((s) => s.activeRunKey)
  const mode = useApp((s) => s.mode)
  const report = useApp((s) => s.report)
  const [fetched, setFetched] = useState<{ key: string; md: string } | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  useDialogFocus(rootRef, true)
  const rr = reportRef(batch, runKey)
  const key = rr?.key ?? ''

  useEffect(() => {
    document.body.classList.add('printing')
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        useApp.getState().setPrintView(false)
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => {
      document.body.classList.remove('printing')
      window.removeEventListener('keydown', onKey, true)
    }
  }, [])

  const have = !!report && report.key === key
  useEffect(() => {
    if (!rr || have || mode !== 'static') return
    let live = true
    fetchReport(rr.ref)
      .then((md) => live && setFetched({ key, md }))
      .catch(() => live && setFetched({ key, md: '' }))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, have, mode])

  const md: string | null = have && report ? report.md : fetched && fetched.key === key ? fetched.md : null
  const floors = building ? [...building.floors].sort((a, b) => a.level - b.level) : []
  const failed = batch?.failed?.length
  return createPortal(
    <div className="printreport" ref={rootRef} role="dialog" aria-modal="true" aria-label="Printable report">
      <div className="noprint bar">
        <button onClick={() => window.print()}>Print / Save as PDF</button>
        <button data-close onClick={() => useApp.getState().setPrintView(false)}>Close</button>
      </div>
      <div className="page">
        <h1>Evacuation report: {building?.name ?? ''}</h1>
        <p className="dim">{new Date().toLocaleDateString()}</p>
        <Stamps />
        <section>
          <h2>Report card</h2>
          <p className="dim">AI-written summary of the numbers shown; check it against them.</p>
          {md ? (
            <Markdown>{md}</Markdown>
          ) : md === '' ? (
            <p>No report for this result</p>
          ) : mode === 'static' && rr ? (
            <p className="dim">Loading…</p>
          ) : (
            <p>No report generated yet: press Generate on the Report tab</p>
          )}
        </section>
        <section>
          <h2>Weak spots</h2>
          {batch ? (
            <>
              <p className="dim">
                {batch.runs.length} fires simulated{failed ? `, ${failed} failed` : ''}; {batch.base?.occupants?.total ?? '?'} occupants, alarm at {batch.base?.alarmTime ?? '?'} s.
              </p>
              <WhatIfHeadline />
              <table>
                <thead>
                  <tr><th>Rank</th><th>Kind</th><th>Id</th><th>Floor</th><th>Score</th><th>Why</th></tr>
                </thead>
                <tbody>
                  {batch.top.map((t, i) => (
                    <tr key={t.kind + t.id + i}>
                      <td>{i + 1}</td><td>{t.kind}</td><td>{t.id}</td><td>{t.floor}</td><td>{t.score.toFixed(1)}</td><td>{t.why}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <p>No batch for this building: no risk map or weak spots.</p>
          )}
        </section>
        {batch && <MeasuredFixes print fixes={readFixes(batch)} top={batch.top} />}
        <section>
          <h2>Risk map</h2>
          {batch ? (
            <>
              <RiskLegend />
              {floors.map((f) => <RiskMapSvg key={f.id} floor={f.id} />)}
            </>
          ) : (
            <p>No batch for this building: no risk map or weak spots.</p>
          )}
        </section>
        <section>
          <h2>Assumptions and limits</h2>
          <Limits />
        </section>
      </div>
    </div>,
    document.body,
  )
}
