import { useEffect, useMemo, useRef } from 'react'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'

const fmt = (t: number) => {
  const m = Math.floor(t / 60)
  return `${m}:${(t - m * 60).toFixed(1).padStart(4, '0')}`
}

export default function Scrubber() {
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : undefined))
  const playing = useClock((s) => s.playing)
  const speed = useClock((s) => s.speed)
  const duration = useClock((s) => s.duration)
  const range = useRef<HTMLInputElement>(null)
  const label = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const paint = (t: number) => {
      if (range.current) range.current.value = String(t)
      if (label.current) label.current.textContent = `${fmt(t)} / ${fmt(useClock.getState().duration)}`
    }
    paint(useClock.getState().t)
    return useClock.subscribe((s) => paint(s.t))
  }, [duration])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return
      const el = e.target as HTMLElement
      const tag = el?.tagName
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
    if (alarm !== undefined) out.push({ t: alarm, label: 'Alarm', color: '#facc15' })
    for (const e of run.events) if (e.type === 'door_blocked') out.push({ t: e.t, label: `Door blocked ${e.door ?? ''}`, color: '#ef4444' })
    const tr = run.events.find((e) => e.type === 'trapped')
    if (tr) out.push({ t: tr.t, label: 'First trapped', color: '#ef4444' })
    return out
  }, [lr])

  return (
    <div className="scrubber">
      <button onClick={() => useClock.getState().toggle()} title="Space">{playing ? 'Pause' : 'Play'}</button>
      {[1, 2, 5, 10].map((s) => (
        <button key={s} className={s === speed ? 'on' : ''} onClick={() => useClock.getState().setSpeed(s)}>{s}x</button>
      ))}
      <div className="track">
        <input
          ref={range}
          type="range"
          min={0}
          max={duration || 1}
          step={0.1}
          defaultValue={0}
          onChange={(e) => useClock.getState().seek(+e.target.value)}
        />
        {duration > 0 &&
          marks.map((m, i) => (
            <button
              key={i}
              className="mark"
              title={`${m.label} ${fmt(m.t)}`}
              style={{ left: `${Math.min(100, (m.t / duration) * 100)}%`, background: m.color }}
              onClick={() => useClock.getState().seek(m.t)}
            />
          ))}
      </div>
      <span ref={label} className="time" />
    </div>
  )
}
