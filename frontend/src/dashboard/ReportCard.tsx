import { useEffect, useRef, useState } from 'react'
import { useApp } from '../store/app'
import ReportMarkdown from './ReportMarkdown'
import WhatIfHeadline from './WhatIfHeadline'
import HeadlinePack from './HeadlinePack'
import MeasuredFixes from './MeasuredFixes'
import { readFixes, readSkipped } from '../model/fixes'
import { fetchReport } from '../data/loader'
import type { Batch } from '../data/types'

export function reportRef(batch: Batch | null, runKey: string | null) {
  const ref = batch ? { batchId: batch.id } : runKey ? { runId: runKey } : null
  return ref ? { ref, key: JSON.stringify(ref) } : null
}

export default function ReportCard() {
  const mode = useApp((s) => s.mode)
  const batch = useApp((s) => s.batch)
  const runKey = useApp((s) => s.activeRunKey)
  const pack = useApp((s) => s.headlines)
  const [md, setMd] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const seq = useRef(0)

  const rr = reportRef(batch, runKey)
  const ref = rr?.ref ?? null
  const refKey = rr?.key ?? ''

  const load = async (refresh = false) => {
    if (!ref) return
    const me = ++seq.current
    setBusy(true)
    setErr(null)
    try {
      const text = await fetchReport(ref, refresh)
      if (me === seq.current) {
        setMd(text)
        useApp.setState({ report: { key: refKey, md: text } })
      }
    } catch {
      if (me === seq.current) setErr('Report unavailable (needs the backend and Gemini)')
    } finally {
      if (me === seq.current) setBusy(false)
    }
  }

  useEffect(() => {
    setMd(null)
    setErr(null)
    if (ref && mode === 'static') void load()
    return () => {
      seq.current++
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refKey, mode])

  const printBtn = <button onClick={() => useApp.getState().setPrintView(true)}>Print report</button>
  if (!ref) return <div className="empty"><b>Load a run</b><span>Its report appears here.</span>{printBtn}</div>
  return (
    <div className="report">
      {printBtn}
      {pack ? <HeadlinePack /> : <WhatIfHeadline />}
      {!pack && batch && <MeasuredFixes fixes={readFixes(batch)} skipped={readSkipped(batch)} top={batch.top} />}
      {mode === 'live' && (
        <button disabled={busy} onClick={() => void load(md !== null)}>
          {busy ? 'Generating…' : md !== null ? 'Regenerate' : 'Generate'}
        </button>
      )}
      {busy && mode === 'static' && <p className="dim">Loading…</p>}
      {err && <p className="dim">{err}</p>}
      {md !== null && !err && (md.trim() ? (
        <>
          <p className="dim">AI-written summary of the numbers shown; check it against them.</p>
          <ReportMarkdown md={md} />
        </>
      ) : (
        <div className="empty"><b>No report for this result</b><span>Reports need a run with a saved report.</span></div>
      ))}
    </div>
  )
}
