import type { Material, Run } from '../../data/types'
import type { Spread } from '../../model/fireSpread'
import { runMaterial } from '../../model/fireSpread'
import { hrrAt } from '../runIndex'

/**
 * How the fire effects read the run's heat. Everything here is a picture of the run (illustrative): the sizes and brightness follow
 * `fire.hrr` and `fire.rooms`, and nothing on screen shows a unit.
 */

/** Seconds from a room's ignition to its full heat: a mirror of `flashover` in fire/spread.py (MATERIALS), which ramps a room as (tau / flashover)^2. */
const FLASHOVER_S: Record<Material, number> = { concrete: 600, drywall: 300, wood: 150 }

/** A flame's height (m) from a heat release (kW): roughly the 2/5 power (as flame-height correlations go), kept between 0.6 and 2.4 m. */
export function flameHeight(kw: number): number {
  return Math.min(2.4, Math.max(0.6, 0.12 * Math.pow(Math.max(0, kw), 0.4)))
}

/** 0 at `ignite`, 1 after `secs`, smooth in between: how a flame fades in. */
export function fadeIn(t: number, ignite: number, secs = 3): number {
  const k = Math.min(1, Math.max(0, (t - ignite) / secs))
  return k * k * (3 - 2 * k)
}

/** Summed sines between about 4 and 10 Hz around 1 (from 0.75 to 1.25): the flicker of a fire's light. */
export function flicker(time: number, phase = 0): number {
  const p = time + phase
  return 1 + 0.1 * Math.sin(2 * Math.PI * 4.3 * p + 0.4) + 0.07 * Math.sin(2 * Math.PI * 6.1 * p + 1.9) + 0.05 * Math.sin(2 * Math.PI * 8.7 * p + 3.1) + 0.03 * Math.sin(2 * Math.PI * 9.8 * p + 0.8)
}

export interface Heat {
  /** when the ignition room's fire starts: the first room of `fire.rooms`, else the first heat above zero, else 0 */
  ignite: number
  /** the run's total heat release at t (kW) */
  total: (t: number) => number
  /** the ignition fire's own share at t (kW): the total, at most the fire's peak */
  main: (t: number) => number
  /** a room that ignited at `ignite`, at t (kW): the model's ramp, peak × (tau / flashover)^2 */
  room: (ignite: number, t: number) => number
}

/**
 * The heat the effects draw. `fire.hrr` is the total over every burning room (fire/model.py adds each spread room's ramp to the ignition
 * fire), so the ignition fire's peak is estimated as the largest total / (1 + the sum of the spread rooms' ramps) over the curve: exact
 * once the ignition fire is at its peak, a lower bound before.
 */
export function readHeat(run: Run, spread: Spread | null): Heat {
  const hrr = run.fire.hrr ?? []
  const flash = FLASHOVER_S[runMaterial(run)]
  const spreadIgnites = (spread?.rooms ?? []).slice(1).map((r) => r.ignite)
  const ramp = (ignite: number, t: number) => {
    if (t < ignite) return 0
    const k = Math.min(1, (t - ignite) / flash)
    return k * k
  }
  let peak = 0
  for (const [t, kw] of hrr) {
    let sum = 1
    for (const ig of spreadIgnites) sum += ramp(ig, t)
    peak = Math.max(peak, kw / sum)
  }
  const firstHot = hrr.find((p) => p[1] > 0)?.[0]
  const ignite = spread?.rooms[0]?.ignite ?? (firstHot !== undefined ? Math.max(0, firstHot - 2) : 0)
  return {
    ignite,
    total: (t) => hrrAt(hrr, t),
    main: (t) => Math.min(hrrAt(hrr, t), peak > 0 ? peak : Infinity),
    room: (ig, t) => peak * ramp(ig, t),
  }
}
