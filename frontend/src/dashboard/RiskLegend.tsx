import { useApp } from '../store/app'
import { NEVER_COLOR, NODATA_COLOR, RISK_NAMES, riskRange } from '../model/spots'

const UNITS = {
  riskT90: `${RISK_NAMES.riskT90}: average seconds when the fire starts here`,
  riskTrapped: `${RISK_NAMES.riskTrapped}: average number when the fire starts here`,
}

export function Stamps() {
  const batch = useApp((s) => s.batch)
  const priv = useApp((s) => s.building?.private)
  return (
    <>
      {batch?.placeholder && <div className="stamp">PLACEHOLDER DATA, not simulated</div>}
      {priv && <div className="stamp">PRIVATE: do not screenshot or publish</div>}
    </>
  )
}

export default function RiskLegend() {
  const batch = useApp((s) => s.batch)
  const metric = useApp((s) => s.riskMetric)
  if (!batch) return null
  const r = riskRange(batch, metric)
  const digits = metric === 'riskT90' ? 0 : 1
  return (
    <div className="risklegend">
      <div className="ramp" />
      <div className="row">
        <span>{r ? r.min.toFixed(digits) : '–'}</span>
        <span>{r ? r.max.toFixed(digits) : '–'}</span>
      </div>
      <p className="dim">{UNITS[metric]}</p>
      <p className="dim">
        <i style={{ background: NEVER_COLOR }} className="sw" /> 90 % never reached <i style={{ background: NODATA_COLOR }} className="sw" /> no fires started here
      </p>
    </div>
  )
}
