import { useApp } from '../store/app'
import { buildingBounds } from '../scene/geometry'
import { centroidOf, rampColor, riskRange, roomRiskColor, spotPosition, stairScore } from '../model/spots'
import type { Vec2 } from '../data/types'

/** One floor of the risk map as SVG in plan meters (prints sharp, no WebGL). */
export default function RiskMapSvg({ floor }: { floor: string }) {
  const building = useApp((s) => s.building)
  const batch = useApp((s) => s.batch)
  const metric = useApp((s) => s.riskMetric)
  const f = building?.floors.find((x) => x.id === floor)
  if (!building || !batch || !f) return null
  const b = buildingBounds(building, [floor])
  const fy = (y: number) => b.minY + b.maxY - y
  const pts = (ring: Vec2[]) => ring.map(([x, y], i) => `${i ? 'L' : 'M'}${x} ${fy(y)}`).join(' ') + 'Z'
  const range = riskRange(batch, metric)
  const maxScore = Math.max(1e-9, ...batch.doors.map((d) => d.score))
  const stairRooms = new Set(f.stairs.map((s) => s.room))
  const walk = f.walkable.map((w) => [w.outer, ...w.holes].map(pts).join(' ')).join(' ')
  const pad = 1
  const vb = `${b.minX - pad} ${b.minY - pad} ${b.maxX - b.minX + 2 * pad} ${b.maxY - b.minY + 2 * pad}`
  return (
    <figure className="riskmap">
      <svg viewBox={vb} role="img" aria-label={`Risk map of floor ${floor}`}>
        <path d={walk} fill="#f8fafc" stroke="#334155" strokeWidth={0.15} fillRule="evenodd" />
        {f.rooms
          .filter((r) => r.type !== 'stair' && !stairRooms.has(r.id))
          .map((r) => (
            <path key={r.id} d={pts(r.polygon)} fill={roomRiskColor(batch.rooms.find((x) => x.id === r.id), metric, range)} fillOpacity={0.8} stroke="#334155" strokeWidth={0.05} />
          ))}
        {f.stairs.map((s) => (
          <path key={s.id} d={pts(s.polygon)} fill={rampColor(stairScore(building, batch, s.room) / maxScore)} fillOpacity={0.8} stroke="#334155" strokeWidth={0.05} />
        ))}
        {f.doors.map((d) => {
          const sc = batch.doors.find((x) => x.id === d.id)?.score
          if (sc === undefined) return null
          const [x, y] = d.rect && d.rect.length >= 3 ? centroidOf(d.rect) : [(d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2]
          const v = sc / maxScore
          return <circle key={d.id} cx={x} cy={fy(y)} r={0.4 + 0.8 * v} fill={rampColor(v)} fillOpacity={0.9} stroke="#0f172a" strokeWidth={0.05} />
        })}
        {batch.top.map((t, i) => {
          const p = spotPosition(building, t)
          if (!p || p.floorId !== floor) return null
          return (
            <g key={t.id + i}>
              <circle cx={p.pos[0]} cy={fy(p.pos[1])} r={0.9} fill="#0f172a" stroke="#fff" strokeWidth={0.1} />
              <text x={p.pos[0]} y={fy(p.pos[1])} fill="#fff" fontSize={1.2} fontWeight={700} textAnchor="middle" dominantBaseline="central">{i + 1}</text>
            </g>
          )
        })}
      </svg>
      <figcaption>{floor}</figcaption>
    </figure>
  )
}
