import type { DemoRun, Run, RunEvent, Scenario } from '../data/types'
import { DEFAULT_MATERIAL } from './fireSpread'

/** Who decides where people go (`scenario.brain`): the hard-coded rules, some people asking Claude, or everyone asking Claude. */
export type Brain = NonNullable<Scenario['brain']>

/** The Crowd select's options, in order. */
export const CROWDS: { id: Brain; label: string }[] = [
  { id: 'rules', label: 'Rules (hard-coded)' },
  { id: 'mixed', label: 'Some people ask Claude' },
  { id: 'llm', label: 'Everyone asks Claude' },
]
/** What a scenario without `brain` runs. */
export const DEFAULT_BRAIN: Brain = 'rules'

const isBrain = (v: unknown): v is Brain => CROWDS.some((c) => c.id === v)

/** A scenario's crowd: its `brain`, else the rules. */
export function crowdOf(brain: unknown): Brain {
  return isBrain(brain) ? brain : DEFAULT_BRAIN
}

/** A run where everyone asks Claude holds up to this many people (the backend refuses more). */
export const MAX_CLAUDE_CROWD = 200

/** Why an everyone-asks-Claude scenario cannot run. */
export const claudeCrowdLimit = (people: number): string =>
  `Everyone asks Claude runs up to ${MAX_CLAUDE_CROWD} people, and this scenario has ${people}. Lower the people in the building, or pick another crowd.`

/** True when a live run of this scenario would be refused: everyone asks Claude, with more than 200 people. (Only the live backend runs a Claude crowd.) */
export function crowdTooBig(s: Pick<Scenario, 'brain' | 'occupants'> | null | undefined, live: boolean): boolean {
  return live && !!s && crowdOf(s.brain) === 'llm' && s.occupants.total > MAX_CLAUDE_CROWD
}

/** What the Crowd select says under it, in live mode, for the two Claude crowds. */
export const CROWD_NOTE: Record<Exclude<Brain, 'rules'>, string> = {
  mixed: 'About 8% of people ask Claude where to go; everyone else follows the rules.',
  llm: `Everyone asks Claude, up to ${MAX_CLAUDE_CROWD} people. A run takes several minutes, and Claude's answers can differ from one run to the next.`,
}

/** How long a live run is waited for, in seconds. Claude is asked for every decision (about 1.5 s a simulated second; the 160-person
 *  example took 4.3 minutes in process and 5.3 through the API, measured Sat), so a Claude crowd gets fifteen minutes. */
export const RUN_WAIT_S = 600
export const CLAUDE_RUN_WAIT_S = 900
export const runWaitS = (brain: Brain): number => (brain === 'rules' ? RUN_WAIT_S : CLAUDE_RUN_WAIT_S)

const people = (n: number) => `${n} ${n === 1 ? 'person' : 'people'}`

/** The status of a live run: "Running…", or for a Claude crowd who it is deciding for; `elapsed` (s) follows once the run has been polled. */
export function runStatus(brain: Brain, total: number, elapsed?: number): string {
  const lead = brain === 'llm' ? `Claude is deciding for ${people(total)}…` : brain === 'mixed' ? `Claude is deciding for some of ${people(total)}…` : 'Running…'
  return elapsed === undefined ? lead : `${lead} ${elapsed} s`
}

/**
 * A run's name in the Run select, the split view and the chart, with the crowd named when Claude decides for it (a label that
 * already says so, such as "Kitchen, Claude crowd (illustrative)", is left as it is).
 */
export function runLabel(label: string, brain: Brain | undefined): string {
  if (brain === 'llm') return /claude crowd/i.test(label) ? label : `${label} · Claude crowd`
  if (brain === 'mixed') return /ask claude/i.test(label) ? label : `${label} · Some ask Claude`
  return label
}

/** The headline of the rules-against-Claude pair. */
export const CLAUDE_WORDS = 'Claude crowd instead of rules'

export interface BrainPair {
  claude: DemoRun
  rules: DemoRun
}

const materialOf = (e: DemoRun) => e.material ?? DEFAULT_MATERIAL
const doorKey = (e: DemoRun) => JSON.stringify(Object.entries(e.doors ?? {}).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))

/**
 * The rules run to set a Claude run against: a baseline (`whatIf: null`, no Claude crowd) of the same building, fire room and material,
 * the one with the same doors when there are several. Null when there is none.
 */
export function brainPartner(entries: DemoRun[], run: DemoRun): DemoRun | null {
  let best: DemoRun | null = null
  let bestScore = -1
  for (const e of entries) {
    if (e.id === run.id || e.whatIf !== null || (e.brain ?? 'rules') !== 'rules' || e.buildingId !== run.buildingId) continue
    if (e.fire.floor !== run.fire.floor || e.fire.room !== run.fire.room || materialOf(e) !== materialOf(run)) continue
    const score = doorKey(e) === doorKey(run) ? 1 : 0
    if (score > bestScore) {
      best = e
      bestScore = score
    }
  }
  return best
}

/**
 * The precomputed rules-against-Claude pair of a building: the Claude run is an entry with `whatIf: 'brain'` and `brain: 'llm'`.
 * Null when the building has none or no rules partner for it (today's index has neither).
 */
export function brainPair(entries: DemoRun[], buildingId: string): BrainPair | null {
  for (const claude of entries) {
    if (claude.buildingId !== buildingId || claude.whatIf !== 'brain' || claude.brain !== 'llm') continue
    const rules = brainPartner(entries, claude)
    if (rules) return { claude, rules }
  }
  return null
}

/** One decision Claude made for one person (a run/v0 event of type "llm"). A `fallback` one was made by the rules: Claude did not answer in time. */
export interface Decision {
  t: number
  idx: number
  action: string
  reason: string
  fallback: boolean
}
export interface Decisions {
  /** per person, in time order */
  byPerson: Map<number, Decision[]>
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const decisionCache = new WeakMap<RunEvent[], Decisions | null>()

/** Every Claude decision a run logged, or null when it has none (a run of the rules, or from before Claude crowds). Events without a person, time or reason are skipped. */
export function readDecisions(run: Run | undefined): Decisions | null {
  const events = run?.events
  if (!Array.isArray(events)) return null
  if (decisionCache.has(events)) return decisionCache.get(events) ?? null
  const byPerson = new Map<number, Decision[]>()
  for (const e of events) {
    if (e?.type !== 'llm' || !isNum(e.idx) || !isNum(e.t) || typeof e.reason !== 'string') continue
    const list = byPerson.get(e.idx) ?? []
    list.push({ t: e.t, idx: e.idx, action: typeof e.action === 'string' ? e.action : '', reason: e.reason, fallback: e.fallback === true })
    byPerson.set(e.idx, list)
  }
  for (const list of byPerson.values()) list.sort((a, b) => a.t - b.t)
  const out = byPerson.size ? { byPerson } : null
  decisionCache.set(events, out)
  return out
}

/** A person's latest decision at time t (s): the last one made at or before t; null before their first. */
export function decisionAt(d: Decisions | null, idx: number, t: number): Decision | null {
  const list = d?.byPerson.get(idx)
  if (!list) return null
  let lo = 0
  let hi = list.length - 1
  if (list[0].t > t) return null
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (list[mid].t <= t) lo = mid
    else hi = mid - 1
  }
  return list[lo]
}

/** "Claude: <reason>", or for a decision the rules made after Claude failed to answer in time, "Rules (Claude didn't answer in time)". */
export function decisionText(d: Decision): string {
  return d.fallback ? "Rules (Claude didn't answer in time)" : `Claude: ${d.reason}`
}

const claudePeople = new WeakMap<Run, number[]>()

/** The people who ask Claude in a run, by idx: the agents it flags `llm`, and anyone it logged an `llm` decision for. */
export function claudeIdx(run: Run | undefined): number[] {
  if (!run) return []
  let out = claudePeople.get(run)
  if (!out) {
    const set = new Set<number>()
    for (const a of run.agents ?? []) if (a.llm) set.add(a.idx)
    for (const e of run.events ?? []) if ((e.llm || e.type === 'llm') && isNum(e.idx)) set.add(e.idx)
    out = [...set].sort((a, b) => a - b)
    claudePeople.set(run, out)
  }
  return out
}
