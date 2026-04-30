import { useState } from 'react'

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button className="copy-btn" onClick={handleCopy} title="Copy address">
      {copied
        ? <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M2 6.5l3.5 3.5 5.5-6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
        : <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><rect x="4.5" y="1" width="7.5" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.3"/><path d="M1 4.5h3m-3 0V12h8V9.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>
      }
    </button>
  )
}
