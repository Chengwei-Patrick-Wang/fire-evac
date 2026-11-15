import { useEffect, useMemo, useRef } from 'react'
import { Pause, Play, RotateCcw } from 'lucide-react'
import { useApp } from '../store/app'
import { SPEEDS, useClock } from '../store/clock'

const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`

/** Replaces Scrubber: play and pause, restart, the time, the scrubber with its marks, the speed and the run. Same keys and marks. */
export default function Timeline() {
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : undefined))
  const runOrder = useApp((s) => s.runOrder)
  const runs = useApp((s) => s.runs)
  const activeRunKey = useApp((s) => s.activeRunKey)
  const loading = useApp((s) => s.loading)
  const playing = useClock((s) => s.playing)
  const speed = useClock((s) => s.speed)
  const duration = useClock((s) => s.duration)
  const range = useRef<HTMLInputElement>(null)
  const label = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const paint = (t: number) => {
      if (range.current) {
        range.current.value = String(t)
        range.current.setAttribute('aria-valuetext', `${mmss(t)} of ${mmss(useClock.getState().duration)}`)
      }
      if (label.current) label.current.textContent = `${mmss(t)} / ${mmss(useClock.getState().duration)}`
    }
    paint(useClock.getState().t)
    return useClock.subscribe((s) => paint(s.t))
  }, [duration])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      const tag = el?.tagName
      if (e.code !== 'Space') {
        if (e.ctrlKey || e.altKey || e.metaKey) return
        if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || el?.isContentEditable) return
        const c = useClock.getState()
        if (e.key === 'ArrowLeft') c.seek(Math.max(0, c.t - (e.shiftKey ? 1 : 5)))
        else if (e.key === 'ArrowRight') c.seek(Math.min(c.duration, c.t + (e.shiftKey ? 1 : 5)))
        else if (e.key === 'Home') c.seek(0)
        else if (e.key === 'End') c.seek(c.duration)
        else return
        e.preventDefault()
        return
      }
      if (tag === 'SELECT' || tag === 'TEXTAREA' || tag === 'BUTTON' || (tag === 'INPUT' && (el as HTMLInputElement).type === 'text')) return
      e.preventDefault()
      useClock.getState().toggle()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const marks = useMemo(() => {
    const out: { t: number; label: string; color: string }[] = []
    if (!lr) return out
    const { run, index: ix, scenario } = lr
    let alarm = scenario?.alarmTime
    if (alarm === undefined && ix) {
      const delay = new Map(run.agents.map((a) => [a.idx, a.startDelay]))
      let best = Infinity
      const seen = new Uint8Array(ix.nAgents)
      for (let f = 0; f < ix.nFrames; f++)
        for (let i = 0; i < ix.nAgents; i++)
          if (!seen[i] && ix.st[f * ix.nAgents + i] === 1) {
            seen[i] = 1
            best = Math.min(best, ix.times[f] - (delay.get(i) ?? 0))
          }
      if (isFinite(best)) alarm = Math.max(0, best)
    }
    if (alarm !== undefined) out.push({ t: alarm, label: 'Alarm', color: 'var(--caution)' })
    for (const e of run.events) if (e.type === 'door_blocked') out.push({ t: e.t, label: `Door blocked ${e.door ?? ''}`, color: 'var(--severe)' })
    const tr = run.events.find((e) => e.type === 'trapped')
    if (tr) out.push({ t: tr.t, label: 'First trapped', color: 'var(--severe)' })
    return out
  }, [lr])

  return (
    <div className="timeline">
      <button
        id="play"
        type="button"
        className="playbtn"
        aria-label={playing ? 'Pause' : 'Play'}
        aria-keyshortcuts="Space"
        title={`${playing ? 'Pause' : 'Play'} (Space)`}
        onClick={() => useClock.getState().toggle()}
      >
        {playing ? <Pause size={18} strokeWidth={1.75} fill="currentColor" aria-hidden="true" /> : <Play size={18} strokeWidth={1.75} fill="currentColor" aria-hidden="true" />}
      </button>
      <button
        type="button"
        className="restartbtn"
        aria-label="Restart"
        title="Restart from the beginning"
        onClick={() => {
          useClock.getState().seek(0)
          useClock.setState({ playing: true })
        }}
      >
        <RotateCcw size={18} strokeWidth={1.75} aria-hidden="true" />
      </button>
      <span ref={label} className="time" />
      <div className="track">
        <input
          ref={range}
          type="range"
          min={0}
          max={duration || 1}
          step={0.1}
          defaultValue={0}
          aria-label="Replay time"
          onKeyDown={(e) => {
            const d = e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : e.key === 'PageUp' ? 10 : e.key === 'PageDown' ? -10 : 0
            if (!d) return
            e.preventDefault()
            e.stopPropagation()
            const c = useClock.getState()
            c.seek(Math.min(c.duration, Math.max(0, c.t + d)))
          }}
          onChange={(e) => useClock.getState().seek(+e.target.value)}
        />
        {duration > 0 &&
          marks.map((m, i) => (
            <button
              key={i}
              type="button"
              className="mark"
              title={`${m.label} ${mmss(m.t)}`}
              aria-label={`${m.label} ${mmss(m.t)}`}
              style={{ left: `${Math.min(100, (m.t / duration) * 100)}%`, background: m.color }}
              onClick={() => useClock.getState().seek(m.t)}
            />
          ))}
      </div>
      <div className="tl-sel">
        <span className="cap" aria-hidden="true">Speed</span>
        <select aria-label="Playback speed" value={speed} onChange={(e) => useClock.getState().setSpeed(+e.target.value)}>
          {!SPEEDS.includes(speed) && <option value={speed}>{speed}×</option>}
          {SPEEDS.map((s) => (
            <option key={s} value={s}>{s}×</option>
          ))}
        </select>
      </div>
      <div className="tl-sel">
        <span className="cap" aria-hidden="true">Run</span>
        <select aria-label="Run" value={activeRunKey ?? ''} disabled={runOrder.length === 0} onChange={(e) => useApp.getState().switchRun(e.target.value)}>
          {runOrder.length === 0 && <option value="">No run</option>}
          {runOrder.map((k) => (
            <option key={k} value={k}>{runs[k].label}</option>
          ))}
        </select>
      </div>
      {loading && <span className="spinner" role="status" aria-label="Loading" />}
    </div>
  )
}
