import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import { Check } from 'lucide-react'

export type MenuItem =
  | { kind: 'item'; label: string; onSelect: () => void; disabled?: boolean; title?: string; keys?: string; sepAbove?: boolean }
  | { kind: 'check'; label: string; checked: boolean; onSelect: () => void; disabled?: boolean; title?: string; sepAbove?: boolean }
  | { kind: 'radios'; label: string; value: string; options: { label: string; value: string }[]; onSelect: (value: string) => void; sepAbove?: boolean }

export interface MenuDef {
  id: string
  label: string
  items: MenuItem[]
}

const ITEMS = '[role="menuitem"]:not(:disabled), [role="menuitemcheckbox"]:not(:disabled), [role="menuitemradio"]:not(:disabled)'

/**
 * Menu buttons in a nav (the menu-button pattern, not role=menubar, which would demand menuitems as direct children).
 * Opening focuses the first item; arrows move; left and right open the neighbouring menu; Escape closes and refocuses the
 * trigger; Tab and clicks outside close. Keys handled here never reach the window shortcuts (replay scrubbing, demo scenes).
 */
export default function MenuBar({ menus }: { menus: MenuDef[] }) {
  const [open, setOpen] = useState<number | null>(null)
  const nav = useRef<HTMLElement>(null)
  const triggers = useRef<(HTMLButtonElement | null)[]>([])

  // Opening (or moving to a neighbouring menu) focuses its first item. Keyed on `open` alone: the menus array is rebuilt on every
  // render, and re-focusing then would pull focus back from the item the user moved to.
  useEffect(() => {
    if (open === null) return
    nav.current?.querySelector<HTMLElement>('.menu')?.querySelector<HTMLElement>(ITEMS)?.focus()
    const down = (e: MouseEvent) => {
      if (!nav.current?.contains(e.target as Node)) setOpen(null)
    }
    document.addEventListener('mousedown', down)
    return () => document.removeEventListener('mousedown', down)
  }, [open])

  const n = menus.length
  // Picking closes the menu and puts focus back on its trigger first, so an action that moves focus (a card, focus mode) wins.
  const pick = (i: number, fn: () => void) => {
    setOpen(null)
    triggers.current[i]?.focus()
    fn()
  }

  const onTriggerKey = (i: number) => (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (e.ctrlKey || e.altKey || e.metaKey) return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') setOpen(i)
    else if (e.key === 'ArrowRight') triggers.current[(i + 1) % n]?.focus()
    else if (e.key === 'ArrowLeft') triggers.current[(i + n - 1) % n]?.focus()
    else return
    e.preventDefault()
    e.stopPropagation()
  }

  const onMenuKey = (i: number) => (e: ReactKeyboardEvent<HTMLDivElement>) => {
    e.stopPropagation()
    const items = [...e.currentTarget.querySelectorAll<HTMLElement>(ITEMS)]
    const at = items.indexOf(document.activeElement as HTMLElement)
    const go = (j: number) => items[(j + items.length) % items.length]?.focus()
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        go(at + 1)
        break
      case 'ArrowUp':
        e.preventDefault()
        go(at < 0 ? items.length - 1 : at - 1)
        break
      case 'Home':
        e.preventDefault()
        go(0)
        break
      case 'End':
        e.preventDefault()
        go(items.length - 1)
        break
      case 'ArrowRight':
        e.preventDefault()
        setOpen((i + 1) % n)
        break
      case 'ArrowLeft':
        e.preventDefault()
        setOpen((i + n - 1) % n)
        break
      case 'Escape':
        e.preventDefault()
        setOpen(null)
        triggers.current[i]?.focus()
        break
      case 'Tab':
        // Focus the trigger, then let Tab move on from there.
        setOpen(null)
        triggers.current[i]?.focus()
        break
    }
  }

  const mark = (on: boolean, radio?: boolean) => (
    <span className="mi-mark" aria-hidden="true">
      {on && (radio ? <span className="mi-dot" /> : <Check size={14} strokeWidth={2} />)}
    </span>
  )

  return (
    <nav className="menus" aria-label="Menus" ref={nav}>
      {menus.map((m, i) => {
        const isOpen = open === i
        const menuId = `menu-${m.id}`
        return (
          <div className="menuwrap" key={m.id}>
            <button
              type="button"
              ref={(el) => {
                triggers.current[i] = el
              }}
              className={'menubtn' + (isOpen ? ' on' : '')}
              aria-haspopup="menu"
              aria-expanded={isOpen}
              aria-controls={isOpen ? menuId : undefined}
              onClick={() => setOpen(isOpen ? null : i)}
              onKeyDown={onTriggerKey(i)}
            >
              {m.label}
            </button>
            {isOpen && (
              <div id={menuId} role="menu" aria-label={m.label} className="menu" onKeyDown={onMenuKey(i)}>
                {m.items.map((it, j) => {
                  const cls = 'menuitem' + (it.sepAbove ? ' sep' : '')
                  if (it.kind === 'radios')
                    return (
                      <div key={j} role="group" aria-label={it.label} className={'menugroup' + (it.sepAbove ? ' sep' : '')}>
                        <span className="mi-cap" aria-hidden="true">{it.label}</span>
                        {it.options.map((o) => (
                          <button
                            key={o.value}
                            type="button"
                            role="menuitemradio"
                            aria-checked={it.value === o.value}
                            tabIndex={-1}
                            className="menuitem"
                            onClick={() => pick(i, () => it.onSelect(o.value))}
                          >
                            {mark(it.value === o.value, true)}
                            <span className="mi-label">{o.label}</span>
                          </button>
                        ))}
                      </div>
                    )
                  if (it.kind === 'check')
                    return (
                      <button
                        key={j}
                        type="button"
                        role="menuitemcheckbox"
                        aria-checked={it.checked}
                        tabIndex={-1}
                        className={cls}
                        disabled={it.disabled}
                        title={it.title}
                        onClick={() => pick(i, it.onSelect)}
                      >
                        {mark(it.checked)}
                        <span className="mi-label">{it.label}</span>
                      </button>
                    )
                  return (
                    <button
                      key={j}
                      type="button"
                      role="menuitem"
                      tabIndex={-1}
                      className={cls}
                      disabled={it.disabled}
                      title={it.title}
                      aria-keyshortcuts={it.keys}
                      onClick={() => pick(i, it.onSelect)}
                    >
                      {mark(false)}
                      <span className="mi-label">{it.label}</span>
                      {it.keys && <span className="mi-keys" aria-hidden="true">{it.keys}</span>}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </nav>
  )
}
