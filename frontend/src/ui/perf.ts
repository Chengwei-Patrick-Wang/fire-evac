// Frame-rate probe: `await __fps(10)` in the console (dev build or ?perf).
export function measureFps(seconds = 5): Promise<{ avg: number; low1: number }> {
  return new Promise((resolve) => {
    const dts: number[] = []
    let last = 0
    let start = 0
    const tick = (ts: number) => {
      if (!start) start = ts
      if (last) dts.push(ts - last)
      last = ts
      if (ts - start < seconds * 1000) requestAnimationFrame(tick)
      else {
        const sorted = [...dts].sort((a, b) => b - a)
        const worst = sorted.slice(0, Math.max(1, Math.ceil(sorted.length * 0.01)))
        const mean = (a: number[]) => a.reduce((s, v) => s + v, 0) / (a.length || 1)
        resolve({ avg: 1000 / mean(dts), low1: 1000 / mean(worst) })
      }
    }
    requestAnimationFrame(tick)
  })
}

export const perfOn = () => import.meta.env.DEV || new URLSearchParams(location.search).has('perf')

if (typeof window !== 'undefined' && perfOn()) (window as unknown as { __fps: typeof measureFps }).__fps = measureFps
