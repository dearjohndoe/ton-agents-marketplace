import type { PersistedAgentState } from './types'
import { PERSIST_KEY } from './constants'

export function readPersisted(): Record<string, PersistedAgentState> {
  if (typeof localStorage === 'undefined') return {}
  try {
    const raw = localStorage.getItem(PERSIST_KEY)
    if (!raw) return {}
    return JSON.parse(raw)
  } catch { return {} }
}

export function writePersisted(map: Record<string, PersistedAgentState>) {
  if (typeof localStorage === 'undefined') return
  try { localStorage.setItem(PERSIST_KEY, JSON.stringify(map)) } catch {}
}
