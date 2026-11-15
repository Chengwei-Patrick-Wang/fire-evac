import { useEffect, useMemo, useRef, useState } from 'react'
import { BellRing } from 'lucide-react'
import { useApp } from '../store/app'
import { useClock } from '../store/clock'
import { alarmTimeOf } from '../model/alarm'

/**
 * Bottom right of the viewer: a blinking red bell and the word "Alarm" from the time the fire alarm sounds in the replay on. Scrubbing back
 * before it hides the badge again. A screen reader hears "Fire alarm sounding" once per run, not each time the badge comes back. `split` lifts
 * the badge on a phone, clear of the pane captions of the compare view.
 */
export default function AlarmBadge({ split = false }: { split?: boolean }) {
  const key = useApp((s) => s.activeRunKey)
  const lr = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey] : undefined))
  const batch = useApp((s) => s.batch)
  const alarm = useMemo(() => alarmTimeOf(lr, batch), [lr, batch])
  // A boolean selector: the clock ticks every frame, the badge renders only when the alarm time is crossed.
  const on = useClock((s) => alarm !== undefined && s.t >= alarm)
  // The runs already announced, and the run whose announcement is on the status line now.
  const told = useRef(new Set<string>())
  const [heard, setHeard] = useState<string | null>(null)

  useEffect(() => {
    if (!on || !key || told.current.has(key)) return
    told.current.add(key)
    setHeard(key)
  }, [on, key])
  // The announcement is a moment, not a state: clear it so the status line never says "sounding" over a replay scrubbed back before the alarm.
  useEffect(() => {
    if (heard === null) return
    const id = setTimeout(() => setHeard(null), 5000)
    return () => clearTimeout(id)
  }, [heard])

  return (
    <>
      <p id="alarm-status" className="sr-only" role="status">
        {heard !== null && heard === key ? 'Fire alarm sounding' : ''}
      </p>
      {on && (
        <div className={'alarmbadge' + (split ? ' split' : '')} aria-hidden="true">
          <BellRing size={20} strokeWidth={2} />
          <span>Alarm</span>
        </div>
      )}
    </>
  )
}
