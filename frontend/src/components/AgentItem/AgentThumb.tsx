import { useState } from 'react'
import { resolveImageSrc } from '../../lib/imageProxy'

export function AgentThumb({ url }: { url: string }) {
  const [failed, setFailed] = useState(false)
  const src = resolveImageSrc(url)
  if (!src || failed) return null
  return (
    <img
      className="agent-thumb"
      src={src}
      alt=""
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      crossOrigin="anonymous"
      onError={() => setFailed(true)}
    />
  )
}
