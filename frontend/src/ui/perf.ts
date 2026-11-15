// Frame-rate probe: `await __fps(10)` in the console (?perf or ?qa; ?perf also shows the Stats overlay).
// `__perf()` returns the last frame's draw calls, triangles, drei <Html> labels and the GL renderer string.
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

/** The frame-rate overlay (drei Stats) shows only with ?perf in the URL, never by default, not even on the dev server. */
export const perfOn = () => new URLSearchParams(location.search).has('perf')
const qaOn = () => new URLSearchParams(location.search).has('qa')

export const perfStats = { calls: 0, triangles: 0 }

let rendererName: string | null = null
function readRenderer(): string {
  if (rendererName !== null) return rendererName
  try {
    const gl = document.querySelector('main.center canvas') as HTMLCanvasElement | null
    const ctx = (gl?.getContext('webgl2') ?? gl?.getContext('webgl')) as WebGLRenderingContext | null
    if (!ctx) return 'unknown'
    const ext = ctx.getExtension('WEBGL_debug_renderer_info')
    rendererName = String(ctx.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : ctx.RENDERER))
  } catch {
    rendererName = 'unknown'
  }
  return rendererName
}

export function perfReport() {
  let html = 0
  document.querySelectorAll('main.center canvas').forEach((c) => {
    const p = c.parentElement
    if (p) html += Math.max(0, p.childElementCount - 1)
  })
  return { calls: perfStats.calls, triangles: perfStats.triangles, html, renderer: readRenderer() }
}

if (typeof window !== 'undefined' && (perfOn() || qaOn())) {
  const w = window as unknown as { __fps: typeof measureFps; __perf: typeof perfReport }
  w.__fps = measureFps
  w.__perf = perfReport
}
