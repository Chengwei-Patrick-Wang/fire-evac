import { useMemo } from 'react'
import { Layers } from 'lucide-react'
import { useApp } from '../store/app'
import { floorName, floorsByLevel } from '../model/floors'
import type { Building } from '../data/types'

const W = 64
const H = 36
const PAD = 3

interface Sil {
  d: string
  /** world (x, y) to the silhouette's pixels */
  at: (x: number, y: number) => [number, number]
}

/** One outline per floor from its walkable outer rings, all on one scale so stacked floors line up. */
function silhouettes(b: Building): Map<string, Sil> {
  let x0 = Infinity
  let y0 = Infinity
  let x1 = -Infinity
  let y1 = -Infinity
  for (const f of b.floors)
    for (const w of f.walkable)
      for (const [x, y] of w.outer) {
        x0 = Math.min(x0, x)
        y0 = Math.min(y0, y)
        x1 = Math.max(x1, x)
        y1 = Math.max(y1, y)
      }
  const out = new Map<string, Sil>()
  if (!isFinite(x0)) return out
  const k = Math.min((W - 2 * PAD) / Math.max(1e-6, x1 - x0), (H - 2 * PAD) / Math.max(1e-6, y1 - y0))
  const ox = (W - (x1 - x0) * k) / 2
  const oy = (H - (y1 - y0) * k) / 2
  const at = (x: number, y: number): [number, number] => [ox + (x - x0) * k, H - (oy + (y - y0) * k)]
  for (const f of b.floors) {
    const d = f.walkable
      .map((w) =>
        w.outer
          .map(([x, y], i) => {
            const p = at(x, y)
            return `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`
          })
          .join('') + 'Z',
      )
      .join('')
    out.set(f.id, { d, at })
  }
  return out
}

/** Whole building, then one button per floor by level. A click shows that floor alone (what Toolbar3D's floor select did). */
export default function FloorStrip() {
  const building = useApp((s) => s.building)
  const visible = useApp((s) => s.visibleFloors)
  const fire = useApp((s) => (s.activeRunKey ? s.runs[s.activeRunKey]?.run.fire : undefined))
  const sils = useMemo(() => (building ? silhouettes(building) : new Map<string, Sil>()), [building])
  if (!building || building.floors.length === 0) return null
  const show = (ids: string[] | null) => useApp.setState((s) => ({ visibleFloors: ids, focus: null, fitView: s.fitView + 1 }))
  const whole = visible === null
  return (
    <nav className="floorstrip" aria-label="Floors">
      <button type="button" className={'fs-item' + (whole ? ' on' : '')} aria-pressed={whole} onClick={() => show(null)}>
        <Layers size={20} strokeWidth={1.75} aria-hidden="true" className="fs-ico" />
        <span>Whole building</span>
      </button>
      {floorsByLevel(building).map((f) => {
        const on = !!visible && visible.length === 1 && visible[0] === f.id
        const sil = sils.get(f.id)
        const dot = fire && fire.floor === f.id && sil ? sil.at(fire.x, fire.y) : null
        return (
          <button
            key={f.id}
            type="button"
            className={'fs-item' + (on ? ' on' : '')}
            aria-pressed={on}
            title={dot ? 'The fire starts on this floor' : undefined}
            onClick={() => show([f.id])}
          >
            <span>{floorName(building, f.id)}</span>
            {sil && (
              <svg className="fs-sil" width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true" focusable="false">
                <path d={sil.d} fill="var(--surface-2)" stroke="#94A3B8" strokeWidth={1} strokeLinejoin="round" fillRule="evenodd" />
                {dot && <circle cx={dot[0]} cy={dot[1]} r={3.5} fill="#F97316" stroke="#FFFFFF" strokeWidth={1} />}
              </svg>
            )}
          </button>
        )
      })}
    </nav>
  )
}
