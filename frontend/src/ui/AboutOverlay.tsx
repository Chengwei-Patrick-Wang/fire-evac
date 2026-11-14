import { useEffect, useRef } from 'react'
import { useDialogFocus } from './a11y'
import { QRCodeSVG } from 'qrcode.react'
import { useApp } from '../store/app'
import { useTour } from '../tour/tour'
import { creditParts } from '../model/buildingIndex'
import { phoneReachable, shareUrl } from '../model/link'
import { spotLabel } from '../model/spots'
import { BRAND } from './theme'

export function markAboutSeen() {
  try {
    localStorage.setItem('fes.aboutSeen', '1')
  } catch {
    /* storage unavailable */
  }
}

export function shouldAutoOpenAbout(): boolean {
  const p = new URLSearchParams(location.search)
  if (p.has('demo') || p.has('sample')) return false
  if (new URLSearchParams(location.hash.replace(/^#/, '')).has('b')) return false
  try {
    return !localStorage.getItem('fes.aboutSeen')
  } catch {
    return false
  }
}

export default function AboutOverlay() {
  const about = useApp((s) => s.about)
  const credits = useApp((s) => s.building?.credits)
  const summaries = useApp((s) => s.summaries)
  const pack = useApp((s) => s.headlines)
  const batch = useApp((s) => s.batch)
  const bname = useApp((s) => s.building?.name)

  const cardRef = useRef<HTMLDivElement>(null)
  useDialogFocus(cardRef, about)

  const close = () => {
    markAboutSeen()
    useApp.getState().setAbout(false)
  }

  useEffect(() => {
    if (!about) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      close()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [about])

  if (!about) return null
  const url = phoneReachable() ? shareUrl() : null
  const sc = pack?.scenario
  const spot0 = pack?.weakSpots?.[0]
  const real = batch && (batch as { placeholder?: boolean }).placeholder !== true && batch.runs?.length > 0 ? batch : null
  const numbers = pack
    ? [
        pack.headline,
        spot0 ? `Top weak spot: ${spotLabel(spot0)}` : null,
        sc && typeof sc.runs === 'number' && typeof sc.rooms === 'number' && Array.isArray(sc.seeds) && typeof sc.occupants === 'number'
          ? `${sc.runs} fires in ${sc.rooms} rooms over ${sc.seeds.length} seeds, ${sc.occupants} occupants`
          : null,
        pack.note,
      ].filter((x): x is string => !!x)
    : real
      ? [`${real.runs.length} fires simulated.${real.top?.[0] ? ` Top weak spot: ${real.top[0].why}` : ''}`]
      : []
  const extra = credits && !/synthetic/i.test(credits) ? credits : null
  return (
    <div className="about-backdrop" role="dialog" aria-modal="true" aria-label="About" onClick={close}>
      <div className="about-card" ref={cardRef} onClick={(e) => e.stopPropagation()}>
        <h2>{BRAND}</h2>
        <p className="pitch">Give us a building, and we'll show where people get stuck before a fire does.</p>
        <h3>How it works</h3>
        <ol>
          <li>A floor plan or an IFC model becomes a walkable 3D building.</li>
          <li>A crowd simulation (JuPedSim) and an illustrative smoke front play out a fire you place.</li>
          <li>Fires in every room add up to a risk map and ranked weak spots, with suggested fixes.</li>
        </ol>
        <p className="aboutnote">
          Not a compliance tool. The fire and smoke model is illustrative (a smoke front, not CFD). Long waits point to gaps in the
          building, not to people.
        </p>
        {numbers.length > 0 && (
          <>
            <h3>{pack?.buildingName ?? bname ?? 'Building'} in numbers</h3>
            {numbers.map((n, i) => <p key={i} className="aboutnum">{n}</p>)}
            <p className="dim">Illustrative model, not a compliance tool.</p>
          </>
        )}
        <h3>Credits</h3>
        <ul>
          {Object.values(summaries).length === 0 && <li>IFC models: NIBS Common BIM Files, via buildingSMART</li>}
          {Object.values(summaries).map((b) => {
            const cp = creditParts(b.credits, b.shortCredit)
            return (
              <li key={b.id}>
                {b.name}: {cp.short}
                {cp.license ? `, ${cp.license}, modified` : ''}
                {cp.source && (
                  <>
                    {' · '}
                    <a href={cp.source} target="_blank" rel="noreferrer">source</a>
                  </>
                )}
              </li>
            )
          })}
          <li>Example building: synthetic, made by the team</li>
          {extra && <li>{extra}</li>}
          <li>Libraries: JuPedSim, three.js, React Three Fiber, Recharts</li>
        </ul>
        <p className="dim">Shortcuts: Space play/pause, ←/→ scrub 5 s, Home/End, W baseline ↔ what-if, 1–6 demo scenes, Esc stops the demo.</p>
        {url && (
          <div className="qr">
            <div className="qrtile">
              <QRCodeSVG value={url} size={160} level="M" />
            </div>
            <div>
              <div>Scan to scrub the replay on your phone</div>
              <a href={url}>{url}</a>
            </div>
          </div>
        )}
        <div className="aboutbtns">
          <button
            onClick={() => {
              close()
              useTour.getState().start()
            }}
          >
            Play the 3-minute demo
          </button>
          <button data-close onClick={close}>Close</button>
        </div>
      </div>
    </div>
  )
}
