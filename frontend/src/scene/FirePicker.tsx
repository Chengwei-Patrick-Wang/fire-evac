import { useMemo } from 'react'
import * as THREE from 'three'
import { useApp } from '../store/app'
import { buildingBounds, floorAlpha, fromPlaced, toPlaced } from './geometry'
import { usePlace } from './usePlace'
import { roomAt } from '../model/scenarioDraft'

export default function FirePicker() {
  const building = useApp((s) => s.building)
  const visible = useApp((s) => s.visibleFloors)
  const viewMode = useApp((s) => s.viewMode)
  const focusFloor = useApp((s) => s.focusFloor)
  const place = usePlace()
  const placing = useApp((s) => s.placing)
  const risk = useApp((s) => s.layers.risk)
  const draft = useApp((s) => s.draft)
  // One pick plane per floor, as big as that floor (not the whole building): a plane that reaches past its floor would catch the clicks
  // meant for the floor below it, whose front part shows from under the one above.
  const bounds = useMemo(() => (building ? new Map(building.floors.map((f) => [f.id, buildingBounds(building, [f.id])])) : null), [building])
  if (!building || !bounds) return null
  const enabled = placing && !risk
  const f = draft?.fire
  const ghostFloor = building.floors.find((x) => x.id === f?.floor)

  return (
    <group>
      {enabled &&
        building.floors
          // In ghost view only the solid floor takes clicks.
          .filter((fl) => (!visible || visible.includes(fl.id)) && floorAlpha(viewMode, focusFloor, fl.id) === 1)
          .map((fl) => {
            const b = bounds.get(fl.id)!
            return (
              <mesh
                key={fl.id}
                position={toPlaced(place(fl), b.cx, b.cy, 0.02)}
                rotation={[-Math.PI / 2, 0, 0]}
                onClick={(e) => {
                  e.stopPropagation()
                  const [x, y] = fromPlaced(place(fl), e.point)
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
                <planeGeometry args={[b.maxX - b.minX + 1, b.maxY - b.minY + 1]} />
                <meshBasicMaterial transparent opacity={0} side={THREE.DoubleSide} depthWrite={false} />
              </mesh>
            )
          })}
      {ghostFloor && f?.x !== undefined && f.y !== undefined && (!visible || visible.includes(ghostFloor.id)) && (
        <mesh position={toPlaced(place(ghostFloor), f.x, f.y, 0.4)}>
          <sphereGeometry args={[0.35, 16, 12]} />
          <meshBasicMaterial color="#fb923c" transparent opacity={0.55 * floorAlpha(viewMode, focusFloor, ghostFloor.id)} />
        </mesh>
      )}
    </group>
  )
}
