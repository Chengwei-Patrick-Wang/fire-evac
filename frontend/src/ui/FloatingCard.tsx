import { useEffect, useRef } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react'
import { X } from 'lucide-react'
import { useApp } from '../store/app'

const FIRST = 'input:not(:disabled), select:not(:disabled), textarea:not(:disabled), button:not(:disabled), [href]'

/**
 * A card over the viewer. Non-modal, no focus trap, one open at a time (the store's `card`). Opening focuses its first control;
 * Escape or the close button hands focus back to whatever opened it.
 */
export default function FloatingCard({ id, title, className, children }: { id: string; title: string; className?: string; children: ReactNode }) {
  const root = useRef<HTMLElement>(null)
  const opener = useRef<HTMLElement | null>(null)

  useEffect(() => {
    // (A second run of this effect, in dev StrictMode, finds focus already inside the card and keeps the first opener.)
    const a = document.activeElement
    if (a instanceof HTMLElement && a !== document.body && !root.current?.contains(a)) opener.current = a
    const body = root.current?.querySelector<HTMLElement>('.card-body')
    ;(body?.querySelector<HTMLElement>(FIRST) ?? root.current?.querySelector<HTMLElement>('.card-x'))?.focus()
  }, [])

  const close = () => {
    const o = opener.current
    useApp.getState().setCard(null)
    if (o && document.contains(o)) o.focus()
    else document.getElementById('nav-toggle')?.focus()
  }

  const onKeyDown = (e: ReactKeyboardEvent<HTMLElement>) => {
    if (e.key !== 'Escape') return
    e.stopPropagation()
    close()
  }

  return (
    <section ref={root} id={`card-${id}`} className={'card' + (className ? ' ' + className : '')} aria-label={title} onKeyDown={onKeyDown}>
      <header className="card-head">
        <h2>{title}</h2>
        <button type="button" className="card-x" aria-label={`Close ${title}`} onClick={close}>
          <X size={16} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </header>
      <div className="card-body">{children}</div>
    </section>
  )
}
