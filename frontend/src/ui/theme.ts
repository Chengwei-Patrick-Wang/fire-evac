import { useA11y } from './a11y'

/** The light canvas (design.md §11); the 3D scene paints the same colour behind the building. */
export const CANVAS = '#F8FAFC'

/** Scene background: black in the high-contrast theme, else the canvas colour. */
export function sceneBg(contrast: boolean): string {
  return contrast ? '#000000' : CANVAS
}

export interface ChartTheme {
  grid: string
  axis: string
  /** the current-time line */
  now: string
  tipBg: string
  tipBorder: string
}

const LIGHT: ChartTheme = { grid: '#E5E7EB', axis: '#64748B', now: '#111827', tipBg: '#FFFFFF', tipBorder: '#E5E7EB' }
const HIGH: ChartTheme = { grid: '#333333', axis: '#FFFFFF', now: '#FFD400', tipBg: '#000000', tipBorder: '#FFFFFF' }

/** Chart colours (Recharts takes literals, not CSS variables, for its axes and grid). */
export function useChartTheme(): ChartTheme {
  return useA11y((s) => (s.contrast ? HIGH : LIGHT))
}
