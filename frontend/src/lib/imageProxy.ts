import { SSL_GATEWAY } from '../config'

const MAX_URL_LEN = 512
const MAX_IMAGES = 5

export function sanitizeImageUrl(raw: unknown): string | null {
  if (typeof raw !== 'string' || !raw || raw.length > MAX_URL_LEN) return null
  let u: URL
  try {
    u = new URL(raw)
  } catch {
    return null
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return null
  const p = u.pathname.toLowerCase()
  if (p.endsWith('.svg') || p.endsWith('.svgz')) return null
  return u.toString()
}

export function sanitizeImageList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  const out: string[] = []
  for (const item of raw) {
    const clean = sanitizeImageUrl(item)
    if (clean) out.push(clean)
    if (out.length >= MAX_IMAGES) break
  }
  return out
}

// Route http images through the ssl-gateway /img endpoint when the page is
// served over https, so mixed-content blocking does not break the UI. If no
// gateway is configured, fall back to the raw URL — the browser will warn.
export function resolveImageSrc(url: string): string {
  let u: URL
  try {
    u = new URL(url)
  } catch {
    return ''
  }
  if (u.protocol === 'http:' && typeof window !== 'undefined' && window.location.protocol === 'https:') {
    if (!SSL_GATEWAY) return ''
    return `${SSL_GATEWAY.replace(/\/+$/, '')}/img?url=${encodeURIComponent(url)}`
  }
  return url
}
