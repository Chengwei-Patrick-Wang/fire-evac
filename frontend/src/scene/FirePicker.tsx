import { useMemo } from 'react'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { buildingBounds, floorY, fromWorld, toWorld } from './geometry'
import { roomAt } from '../model/scenarioDraft'

export default function FirePicker() {
  const building = useApp((s) => s.building)
  const visible = useApp((s) => s.visibleFloors)
  const explode = useApp((s) => s.explode)
  const placing = useApp((s) => s.placing)
  const risk = useApp((s) => s.layers.risk)
  const draft = useApp((s) => s.draft)
  const bounds = useMemo(() => (building ? buildingBounds(building) : null), [building])
  if (!building || !bounds) return null
  const w = bounds.maxX - bounds.minX + 20
  const h = bounds.maxY - bounds.minY + 20
  const enabled = placing && !risk
  const f = draft?.fire
  const ghostFloor = building.floors.find((x) => x.id === f?.floor)

  return (
    <group>
      {enabled &&
        building.floors
          .filter((fl) => !visible || visible.includes(fl.id))
          .map((fl) => (
            <mesh
              key={fl.id}
              position={toWorld(bounds.cx, bounds.cy, floorY(fl, explode) + 0.02)}
              rotation={[-Math.PI / 2, 0, 0]}
              onClick={(e) => {
                e.stopPropagation()
                const [x, y] = fromWorld(e.point)
                const st = useApp.getState()
                const room = roomAt(building, fl.id, x, y)
                if (!room) return st.setNotice('Click inside a room')
                st.setNotice(null)
                const d = st.draft
                if (d)
                  st.patchDraft({
                    fire: { ...d.fire, floor: fl.id, room: room.id, x: +x.toFixed(2), y: +y.toFixed(2), start: 0 },
                  })
              }}
            >
              <planeGeometry args={[w, h]} />
              <meshBasicMaterial transparent opacity={0} side={THREE.DoubleSide} depthWrite={false} />
            </mesh>
          ))}
      {ghostFloor && f?.x !== undefined && f.y !== undefined && (!visible || visible.includes(ghostFloor.id)) && (
        <mesh position={toWorld(f.x, f.y, floorY(ghostFloor, explode) + 0.4)}>
          <sphereGeometry args={[0.35, 16, 12]} />
          <meshBasicMaterial color="#fb923c" transparent opacity={0.55} />
        </mesh>
      )}
    </group>
  )
}
