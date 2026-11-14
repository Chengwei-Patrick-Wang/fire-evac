import type { Building } from '../data/types'

// Hand-made fallback: 12 x 8 m room, closing point repeated, one duplicated point, a 1 x 1 m pillar hole.
export const SAMPLE_BUILDING: Building = {
  version: 'building/v0',
  id: 'sample',
  name: 'Sample room (built in)',
  source: 'synthetic',
  credits: 'Built-in sample room.',
  floors: [
    {
      id: 'F1',
      level: 0,
      elevation: 0,
      height: 3,
      walkable: [
        {
          outer: [[0, 0], [12, 0], [12, 0], [12, 8], [0, 8], [0, 0]],
          holes: [[[5.5, 3.5], [6.5, 3.5], [6.5, 4.5], [5.5, 4.5]]],
        },
      ],
      rooms: [{ id: 'R1', name: 'Hall', type: 'lobby', polygon: [[0, 0], [12, 0], [12, 8], [0, 8]] }],
      doors: [
        { id: 'D1', a: [12, 5], b: [12, 6], width: 1, state: 'open', rect: [[11.7, 5], [12.3, 5], [12.3, 6], [11.7, 6]], connects: ['R1', 'outside'] },
      ],
      stairs: [{ id: 'S1', group: 'S', room: 'R1', polygon: [[0.2, 0.2], [2, 0.2], [2, 2], [0.2, 2]] }],
      exits: [{ id: 'X1', name: 'Exit', door: 'D1', polygon: [[12.3, 5], [13, 5], [13, 6], [12.3, 6]] }],
    },
  ],
}
