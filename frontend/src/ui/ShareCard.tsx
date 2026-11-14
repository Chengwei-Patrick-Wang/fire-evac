import { useEffect, useRef, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { useApp } from '../store/app'
import { useDialogFocus } from './a11y'
import { cachedIndexIds, phoneReachable, shareUrl } from '../model/link'

export default function ShareCard() {
  const share = useApp((s) => s.share)
  const building = useApp((s) => s.building)
  const activeRunKey = useApp((s) => s.activeRunKey)
  const [url, setUrl] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  useDialogFocus(cardRef, share)

  useEffect(() => {
    if (!share) return
    setUrl(shareUrl())
    const id = setInterval(() => setUrl(shareUrl()), 1000)
    return () => clearInterval(id)
  }, [share])

  useEffect(() => {
    if (!share) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      useApp.getState().setShare(false)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [share])

  if (!share) return null
  const isPrivate = !!building?.private
  const ids = cachedIndexIds()
  let note: string | null = null
  if (ids && building && !isPrivate) {
    if (!ids.buildings.has(building.id)) note = "This building isn't on the public site"
    else if (!activeRunKey || !ids.runs.has(activeRunKey)) note = "This run isn't on the public site: the link opens the nearest precomputed run"
  }
  const copy = async () => {
    const u = shareUrl()
    if (!u) return
    try {
      await navigator.clipboard.writeText(u)
    } catch {
      try {
        input.current?.select()
        if (!document.execCommand('copy')) throw new Error('copy failed')
      } catch {
        useApp.getState().setNotice(`Copy this link: ${u}`)
        return
      }
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <div className="sharecard" ref={cardRef} role="dialog" aria-label="Share this view">
      <button data-close className="sharex" aria-label="Close" onClick={() => useApp.getState().setShare(false)}>×</button>
      <h3>Share this view</h3>
      {isPrivate || !url ? (
        <p className="dim">Private building: no public links</p>
      ) : (
        <>
          {phoneReachable() ? (
            <div className="qrtile">
              <QRCodeSVG value={url} size={200} level="M" />
            </div>
          ) : (
            <p className="dim">QR code needs a public URL (VITE_SITE_URL) or a LAN address</p>
          )}
          <input ref={input} readOnly value={url} onFocus={(e) => e.currentTarget.select()} aria-label="Link" />
          <button onClick={() => void copy()}>{copied ? 'Copied' : 'Copy link'}</button>
          {note && <p className="dim">{note}</p>}
        </>
      )}
    </div>
  )
}
