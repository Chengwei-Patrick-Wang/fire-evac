export interface BuildingSummary {
  id: string
  name: string
  floors?: number
  rooms?: number
  credits?: string
  shortCredit?: string
}

const BASE = (import.meta.env.BASE_URL ?? '/') + 'demo/'
let cached: Promise<Record<string, BuildingSummary>> | null = null

export function loadBuildingIndex(): Promise<Record<string, BuildingSummary>> {
  cached ??= (async () => {
    try {
      const res = await fetch(BASE + 'buildings-index.json')
      if (!res.ok) return {}
      const j = await res.json()
      if (j?.version !== 'buildings-index/v0' || !Array.isArray(j.buildings)) return {}
      const out: Record<string, BuildingSummary> = {}
      for (const b of j.buildings) if (b && typeof b.id === 'string' && typeof b.name === 'string') out[b.id] = b
      return out
    } catch {
      return {}
    }
  })()
  return cached
}

const LICENSE_URLS: Record<string, string> = {
  'CC BY 4.0': 'https://creativecommons.org/licenses/by/4.0/',
  'CC BY-SA 4.0': 'https://creativecommons.org/licenses/by-sa/4.0/',
  'CC BY-NC 4.0': 'https://creativecommons.org/licenses/by-nc/4.0/',
}

export function creditParts(credits: string | undefined, shortCredit?: string) {
  const text = credits ?? ''
  const segs = text.split(';').map((x) => x.trim())
  const pick = (k: string) => segs.find((x) => x.toLowerCase().startsWith(k + ':'))?.slice(k.length + 1).trim() ?? null
  const short = shortCredit ?? segs[0] ?? ''
  const urls = [...text.matchAll(/https?:\/\/[^\s;,]+/g)].map((m) => m[0].replace(/[.,;:)]+$/, ''))
  const source = urls.find((u) => !short.includes(u)) ?? null
  const license = pick('license')
  const m = license && Object.keys(LICENSE_URLS).find((k) => k === license)
  const licenseUrl = m ? LICENSE_URLS[m] : license ? LICENSE_URLS[license.replace(/\s+\d.*$/, ' 4.0')] ?? null : null
  return { short, license, changes: pick('changes'), source, licenseUrl }
}
