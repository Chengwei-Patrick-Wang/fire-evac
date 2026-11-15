import { useEffect, useRef, useState } from 'react'
import { useApp } from '../store/app'
import ReportMarkdown from './ReportMarkdown'
import { fetchReport } from '../data/loader'
import type { Batch } from '../data/types'

export function reportRef(batch: Batch | null, runKey: string | null) {
  const ref = batch ? { batchId: batch.id } : runKey ? { runId: runKey } : null
  return ref ? { ref, key: JSON.stringify(ref) } : null
}

/**
 * The Report tab: the card's "AI summary (Claude)" first, then the printable report (the rest of the card, with its Print report button under the
 * summary). The weak spots, what-ifs and fixes the card repeats live in the Risk tab and are not copied here.
 */
export default function ReportCard() {
  const mode = useApp((s) => s.mode)
  const batch = useApp((s) => s.batch)
  const runKey = useApp((s) => s.activeRunKey)
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
      if (me === seq.current) setErr('Report unavailable (needs the backend and an AI key)')
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
  const text = md !== null && !err && md.trim() ? md : null
  return (
    <div className="report">
      {mode === 'live' && (
        <button disabled={busy} onClick={() => void load(md !== null)}>
          {busy ? 'Generating…' : md !== null ? 'Regenerate' : 'Generate'}
        </button>
      )}
      {busy && mode === 'static' && <p className="dim">Loading…</p>}
      {err && <p className="dim">{err}</p>}
      {md !== null && !err && !text && (
        <div className="empty"><b>No report for this result</b><span>Reports need a run with a saved report.</span></div>
      )}
      {text ? <ReportMarkdown md={text}>{printBtn}</ReportMarkdown> : printBtn}
    </div>
  )
}
