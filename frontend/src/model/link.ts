import { useEffect } from 'react'
import { useApp } from '../store/app'
import type { Layers, ResultsTab } from '../store/app'
import { useClock } from '../store/clock'
import { loadIndex } from '../data/loader'

export const SITE_URL = (import.meta.env.VITE_SITE_URL as string | undefined) ?? ''

export interface LinkState {
  b: string
  r?: string
  t?: number
  tab?: ResultsTab
  m?: 'riskT90' | 'riskTrapped'
  l?: string[]
  x?: number
  f?: string
  split?: boolean
  cam?: number[]
  ff?: string
  fx?: number
  fy?: number
}

const TABS: ResultsTab[] = ['results', 'risk', 'report', 'cred']
const LAYER_KEYS: (keyof Layers)[] = ['rooms', 'labels', 'smoke', 'fire', 'heatmap', 'queues', 'risk']

const r1 = (n: number) => n.toFixed(1)

export function encodeLink(s: LinkState): string {
  const p = new URLSearchParams()
  p.set('b', s.b)
  if (s.r) p.set('r', s.r)
  if (s.t !== undefined) p.set('t', r1(s.t))
  if (s.tab) p.set('tab', s.tab)
  if (s.m === 'riskTrapped') p.set('m', s.m)
  if (s.l) p.set('l', s.l.join('_'))
  if (s.x) p.set('x', s.x.toFixed(2))
  if (s.f) p.set('f', s.f)
  if (s.split) p.set('split', '1')
  if (s.cam) p.set('cam', s.cam.map(r1).join('_'))
  if (s.ff) p.set('ff', s.ff)
  if (s.fx !== undefined) p.set('fx', r1(s.fx))
  if (s.fy !== undefined) p.set('fy', r1(s.fy))
  return p.toString()
}

const num = (v: string | null): number | undefined => {
  if (v === null || v.trim() === '') return undefined
  const n = Number(v)
  return Number.isFinite(n) ? n : undefined
}

export function decodeLink(hash: string): LinkState | null {
  const p = new URLSearchParams(hash.replace(/^#/, ''))
  const b = p.get('b')
  if (!b) return null
  const out: LinkState = { b }
  const r = p.get('r')
  if (r) out.r = r
  const t = num(p.get('t'))
  if (t !== undefined && t >= 0) out.t = t
  const tab = p.get('tab')
  if (tab && (TABS as string[]).includes(tab)) out.tab = tab as ResultsTab
  const m = p.get('m')
  if (m === 'riskT90' || m === 'riskTrapped') out.m = m
  const l = p.get('l')
  if (l !== null) out.l = l.split('_').filter((k) => (LAYER_KEYS as string[]).includes(k))
  const x = num(p.get('x'))
  if (x !== undefined && x >= 0 && x <= 1) out.x = x
  const f = p.get('f')
  if (f) out.f = f
  if (p.get('split') === '1') out.split = true
  const cam = p.get('cam')
  if (cam) {
    const a = cam.split('_').map((v) => num(v))
    if (a.length === 6 && a.every((v) => v !== undefined)) out.cam = a as number[]
  }
  const ff = p.get('ff')
  if (ff) out.ff = ff
  const fx = num(p.get('fx'))
  if (fx !== undefined) out.fx = fx
  const fy = num(p.get('fy'))
  if (fy !== undefined) out.fy = fy
  return out
}

/** Live camera pose, overwritten in place by CameraRig. */
export const cameraPose = { p: [0, 0, 0], t: [0, 0, 0] }

/** True from decoding a link until restoreLink returns. */
export const linkCtl = { restoring: false }

let idsCache: Promise<{ buildings: Set<string>; runs: Set<string> }> | null = null
export function loadIndexIds() {
  idsCache ??= loadIndex().then((i) => ({ buildings: new Set(i.buildings.map((b) => b.id)), runs: new Set(i.runs.map((r) => r.id)) }))
  return idsCache
}
let ids: { buildings: Set<string>; runs: Set<string> } | null = null
void loadIndexIds().then((v) => (ids = v))
export const cachedIndexIds = () => ids

export function readLinkState(): LinkState | null {
  const s = useApp.getState()
  if (!s.building) return null
  const out: LinkState = { b: s.building.id }
  const active = s.activeRunKey ? s.runs[s.activeRunKey] : null
  if (s.activeRunKey && active && ids?.runs.has(s.activeRunKey)) out.r = s.activeRunKey
  out.t = useClock.getState().t
  out.tab = s.resultsTab
  out.m = s.riskMetric
  out.l = LAYER_KEYS.filter((k) => s.layers[k])
  out.x = s.explode
  if (s.visibleFloors?.length === 1) out.f = s.visibleFloors[0]
  if (s.split) out.split = true
  if (s.follow === null && !s.split) out.cam = [...cameraPose.p, ...cameraPose.t]
  const fire = active?.run.fire
  if (fire) {
    out.ff = fire.floor
    out.fx = fire.x
    out.fy = fire.y
  }
  return out
}

export function phoneReachable(): boolean {
  return !!SITE_URL || !['localhost', '127.0.0.1', '::1', '[::1]'].includes(location.hostname)
}

export function shareUrl(): string | null {
  const s = useApp.getState()
  if (!s.building || s.building.private) return null
  const st = readLinkState()
  if (!st) return null
  const base = SITE_URL ? SITE_URL.replace(/#.*$/, '').replace(/\/?$/, '/') : location.origin + location.pathname
  return base + '#' + encodeLink(st)
}

export function useLinkSync() {
  useEffect(() => {
    const id = setInterval(() => {
      const s = useApp.getState()
      if (linkCtl.restoring || s.view !== 'replay' || s.loading || !s.building) return
      const st = readLinkState()
      if (!st) return
      const h = '#' + encodeLink(st)
      if (h !== location.hash) history.replaceState(null, '', h)
    }, 1000)
    return () => clearInterval(id)
  }, [])
}
