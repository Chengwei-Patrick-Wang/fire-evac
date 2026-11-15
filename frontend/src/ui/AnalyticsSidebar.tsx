import { lazy, Suspense, useEffect, useRef } from 'react'
import { ChevronsLeft, ChevronsLeftRight, ChevronsRight, ChevronsRightLeft, Flame } from 'lucide-react'
import { useApp } from '../store/app'
import ErrorBoundary from './ErrorBoundary'
import { BRAND } from './theme'

const ResultsPanel = lazy(() => import('./ResultsPanel'))

/**
 * The left analytics card. It is always in the DOM and `hidden` while collapsed (its body renders only when open); a narrow edge
 * tab brings it back. Collapsing focuses the edge tab and expanding focuses "Hide analytics", so keyboard focus never drops.
 * "Expand panel" grows it toward the middle of the screen (to min(760px, 55vw), see App.css) so the charts, tables and report read
 * comfortably; the 3D view keeps the rest. A phone's panel is an overlay at full width already, so it has no such button there.
 */
export default function AnalyticsSidebar() {
  const open = useApp((s) => s.sidebarOpen)
  const wide = useApp((s) => s.sidebarWide)
  const name = useApp((s) => s.building?.name)
  const hide = useRef<HTMLButtonElement>(null)
  const tab = useRef<HTMLButtonElement>(null)
  const next = useRef<'hide' | 'tab' | null>(null)

  useEffect(() => {
    const n = next.current
    next.current = null
    if (n === 'hide') hide.current?.focus()
    else if (n === 'tab') tab.current?.focus()
  }, [open])

  const set = (v: boolean) => {
    next.current = v ? 'hide' : 'tab'
    useApp.getState().setSidebarOpen(v)
  }

  return (
    <>
      <aside id="analytics" className="sidebar" aria-label="Analytics" hidden={!open}>
        {open && (
          <>
            <header className="sb-head">
              <div className="sb-title">
                <h1 className="brand">
                  <Flame size={22} strokeWidth={1.75} aria-hidden="true" className="brand-flame" />
                  {BRAND}
                </h1>
                <p className="brand-sub" title={name}>{name}</p>
              </div>
              <button
                type="button"
                className="sb-hide sb-wide-btn"
                aria-label={wide ? 'Shrink panel' : 'Expand panel'}
                title={wide ? 'Shrink panel' : 'Expand panel'}
                aria-pressed={wide}
                aria-controls="analytics"
                onClick={() => useApp.getState().setSidebarWide(!wide)}
              >
                {wide ? <ChevronsRightLeft size={18} strokeWidth={1.75} aria-hidden="true" /> : <ChevronsLeftRight size={18} strokeWidth={1.75} aria-hidden="true" />}
              </button>
              <button
                ref={hide}
                type="button"
                className="sb-hide"
                aria-label="Hide analytics"
                title="Hide analytics"
                aria-expanded="true"
                aria-controls="analytics"
                onClick={() => set(false)}
              >
                <ChevronsLeft size={18} strokeWidth={1.75} aria-hidden="true" />
              </button>
            </header>
            <div className="sb-body">
              <Suspense fallback={<div className="pad dim">Loading…</div>}>
                <ErrorBoundary label="Results">
                  <ResultsPanel />
                </ErrorBoundary>
              </Suspense>
            </div>
          </>
        )}
      </aside>
      {!open && (
        <button
          ref={tab}
          type="button"
          className="edgetab"
          aria-label="Show analytics"
          title="Show analytics"
          aria-expanded="false"
          aria-controls="analytics"
          onClick={() => set(true)}
        >
          <ChevronsRight size={18} strokeWidth={1.75} aria-hidden="true" />
        </button>
      )}
    </>
  )
}
