import { useEffect } from 'react'
import { useClock } from '../store/clock'

/** The only writer of clock t while playing. Lives outside every Canvas. */
export default function ClockDriver() {
  useEffect(() => {
    let raf = 0
    let prev = performance.now()
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - prev) / 1000)
      prev = now
      const c = useClock.getState()
      if (c.playing) {
        const t = c.t + dt * c.speed
        if (t >= c.duration) useClock.setState({ t: c.duration, playing: false })
        else useClock.setState({ t })
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])
  return null
}
