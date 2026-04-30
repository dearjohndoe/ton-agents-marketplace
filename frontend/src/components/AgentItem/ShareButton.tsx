import { useState } from 'react'

export function ShareButton({ sidecarId }: { sidecarId: string }) {
  const [copied, setCopied] = useState(false)
  function handleShare() {
    const url = `${window.location.origin}${import.meta.env.BASE_URL}agents/${sidecarId}`
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button className="share-btn" onClick={handleShare} title="Copy share link">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
        <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
      </svg>
      <span>{copied ? 'Copied!' : 'Copy link'}</span>
    </button>
  )
}
