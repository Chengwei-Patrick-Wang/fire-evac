import { useEffect } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { useApp } from '../store/app'
import { useTour } from '../tour/tour'

const SITE_URL = (import.meta.env.VITE_SITE_URL as string | undefined) ?? ''

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
  try {
    return !localStorage.getItem('fes.aboutSeen')
  } catch {
    return false
  }
}

export default function AboutOverlay() {
  const about = useApp((s) => s.about)
  const credits = useApp((s) => s.building?.credits)

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
  const extra = credits && !/synthetic/i.test(credits) ? credits : null
  return (
    <div className="about-backdrop" role="dialog" aria-modal="true" aria-label="About" onClick={close}>
      <div className="about-card" onClick={(e) => e.stopPropagation()}>
        <h2>Fire evacuation sim</h2>
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
        <h3>Credits</h3>
        <ul>
          <li>IFC models: NIBS Common BIM Files, via buildingSMART</li>
          <li>Example building: synthetic, made by the team</li>
          {extra && <li>{extra}</li>}
          <li>Libraries: JuPedSim, three.js, React Three Fiber, Recharts</li>
        </ul>
        <p className="dim">Shortcuts: Space play/pause, W baseline ↔ what-if, 1–6 demo scenes, Esc stops the demo.</p>
        {SITE_URL && (
          <div className="qr">
            <div className="qrtile">
              <QRCodeSVG value={SITE_URL} size={160} level="M" />
            </div>
            <div>
              <div>Scan to scrub the replay on your phone</div>
              <a href={SITE_URL}>{SITE_URL}</a>
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
          <button onClick={close}>Close</button>
        </div>
      </div>
    </div>
  )
}
