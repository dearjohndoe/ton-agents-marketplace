import { useEffect, useRef, useState } from 'react'
import { pingAgent } from '../lib/agentClient'

interface CacheEntry {
  online: boolean
  checkedAt: number
}

const RECHECK_ONLINE_MS = 1 * 60 * 1000 // 1 min
const STORAGE_PREFIX = 'online:'

function readCache(endpoint: string): CacheEntry | null {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + endpoint)
    if (!raw) return null
    return JSON.parse(raw) as CacheEntry
  } catch {
    return null
  }
}

function writeCache(endpoint: string, entry: CacheEntry) {
  try {
    localStorage.setItem(STORAGE_PREFIX + endpoint, JSON.stringify(entry))
  } catch {}
}

export function useAgentOnline(endpoint: string, expanded: boolean): { online: boolean | null; pinging: boolean; recheck: () => void } {
  const [online, setOnline] = useState<boolean | null>(() => readCache(endpoint)?.online ?? null)
  const [pinging, setPinging] = useState(false)
  const inflightRef = useRef(false)

  function doPing() {
    if (inflightRef.current) return
    inflightRef.current = true
    setPinging(true)
    pingAgent(endpoint).then((result) => {
      const entry = { online: result, checkedAt: Date.now() }
      writeCache(endpoint, entry)
      setOnline(result)
      inflightRef.current = false
      setPinging(false)
    })
  }

  useEffect(() => {
    if (!expanded) return

    const entry = readCache(endpoint)
    const now = Date.now()

    const shouldPing = !entry
      || entry.online === false
      || now - entry.checkedAt >= RECHECK_ONLINE_MS

    if (!shouldPing) {
      setOnline(entry!.online)
      return
    }

    doPing()
  }, [endpoint, expanded])

  return { online, pinging, recheck: doPing }
}
