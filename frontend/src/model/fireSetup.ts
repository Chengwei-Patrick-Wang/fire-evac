import type { Scenario } from '../data/types'

/**
 * A scenario's fire as the backend reads it. `growth` (fire/presets.py honours it over the preset's own) is in the contract (spec §6) but
 * not in the shared Scenario type, so it is carried here; a FireSpec is assignable to and from `Scenario['fire']`.
 */
export type FireSpec = Scenario['fire'] & { growth?: string }

export type FireSizeId = 'small' | 'medium' | 'large'
export type FireGrowthId = 'slow' | 'medium' | 'fast' | 'ultra-fast'

/**
 * The three sizes the scenario card offers. Each is one of the backend's fire presets (they share a smoke factor), told in plain words:
 * the heat numbers stay out of the card.
 */
export const FIRE_SIZES: { id: FireSizeId; type: string; label: string }[] = [
  { id: 'small', type: 'trash', label: 'Small, like a wastebasket' },
  { id: 'medium', type: 'kitchen', label: 'Medium, like a kitchen fire' },
  { id: 'large', type: 'bedroom', label: 'Large, like a burning room' },
]
/** How fast the fire grows; the ids are the backend's growth classes. */
export const FIRE_GROWTHS: { id: FireGrowthId; label: string }[] = [
  { id: 'slow', label: 'Slow' },
  { id: 'medium', label: 'Medium' },
  { id: 'fast', label: 'Fast' },
  { id: 'ultra-fast', label: 'Very fast' },
]
/** What a scenario with no fire type or growth shows: today's default, a kitchen fire (the kitchen preset grows fast). */
export const DEFAULT_FIRE_SIZE: FireSizeId = 'medium'
export const DEFAULT_FIRE_GROWTH: FireGrowthId = 'fast'

/** The backend's spelling of a preset or growth name (fire/presets.py): lower case, "_" and spaces as "-". */
const named = (v: unknown): string => (typeof v === 'string' ? v.trim().toLowerCase().replace(/[_ ]/g, '-') : '')

// Maps, not objects: a type named "constructor" must not find anything.
/** The size shown for a fire type: the preset it is, and for the two presets the card does not offer the nearest size (battery: small, liquid: medium). */
const SIZE_OF_TYPE = new Map<string, FireSizeId>([
  ['trash', 'small'],
  ['kitchen', 'medium'],
  ['bedroom', 'large'],
  ['battery', 'small'],
  ['liquid', 'medium'],
])
/** The growth each preset has of its own, shown when the scenario names none. Liquid's "instant" shows as the fastest class. */
const GROWTH_OF_TYPE = new Map<string, FireGrowthId>([
  ['kitchen', 'fast'],
  ['bedroom', 'medium'],
  ['battery', 'ultra-fast'],
  ['trash', 'fast'],
  ['liquid', 'ultra-fast'],
])
const GROWTH_IDS = new Set<string>(FIRE_GROWTHS.map((g) => g.id))

/** The size the card shows for a fire; a type it does not know shows the default (nothing is ever thrown). */
export function fireSizeOf(fire: Scenario['fire'] | null | undefined): FireSizeId {
  return SIZE_OF_TYPE.get(named(fire?.type)) ?? DEFAULT_FIRE_SIZE
}

/** The growth the card shows: the fire's own `growth` (liquid's "instant" is Very fast), else its preset's, else the default. */
export function fireGrowthOf(fire: Scenario['fire'] | null | undefined): FireGrowthId {
  const own = named((fire as FireSpec | null | undefined)?.growth)
  if (own === 'instant') return 'ultra-fast'
  if (GROWTH_IDS.has(own)) return own as FireGrowthId
  return GROWTH_OF_TYPE.get(named(fire?.type)) ?? DEFAULT_FIRE_GROWTH
}

/** The fire with another size: its type becomes the size's preset, and the growth shown stays (written out, since the new preset may grow differently). */
export function withFireSize(fire: Scenario['fire'], size: FireSizeId): Scenario['fire'] {
  const type = FIRE_SIZES.find((s) => s.id === size)?.type ?? fire.type
  const next: FireSpec = { ...fire, type, growth: fireGrowthOf(fire) }
  return next
}

/** The fire with another growth class. */
export function withFireGrowth(fire: Scenario['fire'], growth: FireGrowthId): Scenario['fire'] {
  const next: FireSpec = { ...fire, growth }
  return next
}
