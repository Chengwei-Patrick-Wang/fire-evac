import type { Building } from '../data/types'
import type { LoadedRun } from '../store/app'
import { materialName, readSpread, runMaterial } from './fireSpread'
import { claudeIdx } from './brain'
import { roomAt } from './scenarioDraft'
import { floorName } from './floors'

export interface RunFacts {
  building: string
  fire: string
  material: string
  crowd: string
  people: string
}

/** What a split pane runs, in the words the Fire and scenario card uses: the building, the fire room, the material, who decides for the crowd, and how many people. */
export function runFacts(lr: LoadedRun, building: Building | null): RunFacts {
  const run = lr.run
  const first = readSpread(run)?.rooms[0]
  const floorId = first?.floor ?? run.fire.floor
  const room = first
    ? building?.floors.find((f) => f.id === first.floor)?.rooms.find((r) => r.id === first.room)
    : building && Number.isFinite(run.fire.x) ? roomAt(building, run.fire.floor, run.fire.x, run.fire.y) : null
  const roomName = room?.name ?? first?.room ?? 'one room'
  const where = building && building.floors.length > 1 ? ` (${floorName(building, floorId)})` : ''
  const total = run.metrics?.agents ?? lr.index.nAgents
  const asking = claudeIdx(run).length
  const brain = lr.whatIf?.brain ?? lr.scenario?.brain
  const crowd = brain === 'llm' || (asking > 0 && asking >= total * 0.9) ? 'Claude crowd' : brain === 'mixed' || asking > 0 ? 'Some ask Claude' : 'Rules crowd'
  return {
    building: building?.name ?? 'building',
    fire: `${roomName}${where}`,
    material: materialName(runMaterial(run)),
    crowd,
    people: `${total} ${total === 1 ? 'person' : 'people'}`,
  }
}

/** The one-line form of runFacts a pane header shows. */
export const factsLine = (f: RunFacts): string => `${f.building} · Fire in ${f.fire} · ${f.material} · ${f.crowd} · ${f.people}`
