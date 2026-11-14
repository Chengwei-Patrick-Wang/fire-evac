import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { useApp } from '../store/app'
import { fetchReport } from '../data/loader'

export default function ReportCard() {
  const mode = useApp((s) => s.mode)
  const batch = useApp((s) => s.batch)
  const runKey = useApp((s) => s.activeRunKey)
  const [md, setMd] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const seq = useRef(0)

  const ref = batch ? { batchId: batch.id } : runKey ? { runId: runKey } : null
  const refKey = ref ? JSON.stringify(ref) : ''

  const load = async (refresh = false) => {
    if (!ref) return
    const me = ++seq.current
    setBusy(true)
    setErr(null)
    try {
      const text = await fetchReport(ref, refresh)
      if (me === seq.current) setMd(text)
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

  if (!ref) return <p className="dim">Load a run to see its report.</p>
  return (
    <div className="report">
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
          <Markdown>{md}</Markdown>
        </>
      ) : (
        <p className="dim">No report for this result</p>
      ))}
    </div>
  )
}
