import { useState } from 'react'
import { resolveImageSrc } from '../../lib/imageProxy'

export function AgentGallery({ images }: { images: string[] }) {
  const [failed, setFailed] = useState<Set<number>>(new Set())
  const visible = images
    .map((url, i) => ({ url, i }))
    .filter(({ i }) => !failed.has(i))
  if (visible.length === 0) return null
  return (
    <div className="agent-gallery">
      {visible.map(({ url, i }) => {
        const src = resolveImageSrc(url)
        if (!src) return null
        return (
          <a
            key={i}
            className="agent-gallery-item"
            href={src}
            target="_blank"
            rel="noopener noreferrer"
          >
            <img
              src={src}
              alt=""
              loading="lazy"
              decoding="async"
              referrerPolicy="no-referrer"
              crossOrigin="anonymous"
              onError={() => setFailed(prev => new Set(prev).add(i))}
            />
          </a>
        )
      })}
    </div>
  )
}
