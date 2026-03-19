import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { fetchAgentPage, type Cursor } from '../lib/toncenter'
import { MOCK_AGENTS } from '../lib/mockAgents'

const USE_MOCK = false // import.meta.env.VITE_USE_MOCK === 'true'
import { CACHE_TTL_MS, AGENTS_PER_PAGE, RATINGS_BACKEND } from '../config'
import type { Agent, AgentRating } from '../types'

interface Store {
  allAgents: Agent[]
  visibleCount: number
  loading: boolean
  error: string | null
  hasMoreOnChain: boolean
  cursor: Cursor | null
  lastFetchTime: number | null
  ratings: Record<string, AgentRating>

  init: () => Promise<void>
  loadMore: () => Promise<void>
  loadRatings: () => Promise<void>
}

function mergeAgents(existing: Agent[], incoming: Agent[]): Agent[] {
  const map = new Map(existing.map(a => [a.address, a]))
  for (const a of incoming) {
    const cur = map.get(a.address)
    if (!cur || a.lastHeartbeat > cur.lastHeartbeat) map.set(a.address, a)
  }
  return [...map.values()].sort((a, b) => b.lastHeartbeat - a.lastHeartbeat)
}

export const useStore = create<Store>()(
  persist(
    (set, get) => ({
      allAgents: [],
      visibleCount: AGENTS_PER_PAGE,
      loading: false,
      error: null,
      hasMoreOnChain: true,
      cursor: null,
      lastFetchTime: null,
      ratings: {},

      init: async () => {
        const { lastFetchTime, loading } = get()
        if (loading) return
        const isStale = !lastFetchTime || Date.now() - lastFetchTime > CACHE_TTL_MS
        if (!isStale) return

        set({ loading: true, error: null })
        try {
          let agents, hasMore, nextCursor
          if (USE_MOCK) {
            agents = MOCK_AGENTS; hasMore = false; nextCursor = null
          } else {
            ;({ agents, hasMore, nextCursor } = await fetchAgentPage())
          }
          set({
            allAgents: agents,
            hasMoreOnChain: hasMore,
            cursor: nextCursor,
            lastFetchTime: Date.now(),
            visibleCount: AGENTS_PER_PAGE,
          })
        } catch {
          set({ error: 'Failed to load agents. Check your connection.' })
        } finally {
          set({ loading: false })
        }
      },

      loadMore: async () => {
        const { allAgents, visibleCount, hasMoreOnChain, cursor, loading } = get()
        if (loading) return

        if (visibleCount < allAgents.length) {
          set({ visibleCount: visibleCount + AGENTS_PER_PAGE })
          return
        }

        if (!hasMoreOnChain) return
        set({ loading: true, error: null })
        try {
          const { agents, hasMore, nextCursor } = await fetchAgentPage(cursor ?? undefined)
          set(s => ({
            allAgents: mergeAgents(s.allAgents, agents),
            hasMoreOnChain: hasMore,
            cursor: nextCursor,
            visibleCount: s.visibleCount + AGENTS_PER_PAGE,
          }))
        } catch {
          set({ error: 'Failed to load more agents.' })
        } finally {
          set({ loading: false })
        }
      },

      loadRatings: async () => {
        if (!RATINGS_BACKEND) return
        try {
          const { default: axios } = await import('axios')
          const { data } = await axios.get(`${RATINGS_BACKEND}/agents`)
          const map: Record<string, AgentRating> = {}
          for (const r of data) map[r.address] = { avgScore: r.avg_score, totalRatings: r.total_ratings }
          set({ ratings: map })
        } catch { /* ratings optional */ }
      },
    }),
    {
      name: 'ton-agents-v1',
      partialize: s => ({
        allAgents: s.allAgents,
        lastFetchTime: s.lastFetchTime,
        cursor: s.cursor,
        hasMoreOnChain: s.hasMoreOnChain,
      }),
    }
  )
)
