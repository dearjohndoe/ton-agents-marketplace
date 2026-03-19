import { useEffect, useState } from 'react'
import { useStore } from '../store/useStore'
import { AgentItem } from '../components/AgentItem'

export function AgentList() {
  const { allAgents, visibleCount, loading, error, hasMoreOnChain, ratings, init, loadMore, loadRatings } = useStore()
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    init()
    loadRatings()
  }, [])

  const displayed = allAgents.slice(0, visibleCount)
  const canLoadMore = !loading && (visibleCount < allAgents.length || hasMoreOnChain)

  function toggle(id: string) {
    setExpandedId(prev => prev === id ? null : id)
  }

  return (
    <div className="page">
      <div className="hero">
        <h1>Agent Marketplace</h1>
        <p>AI agents on TON — discover, call or <a href="/add-agent" className="link-inline">add your own</a></p>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {loading && displayed.length === 0 ? (
        <div className="state-msg">Loading agents…</div>
      ) : displayed.length === 0 ? (
        <div className="state-msg">No agents registered yet.</div>
      ) : (
        <>
          <div className="agent-list">
            {displayed.map(agent => (
              <AgentItem
                key={agent.sidecarId}
                agent={agent}
                rating={ratings[agent.address]}
                expanded={expandedId === agent.sidecarId}
                onToggle={() => toggle(agent.sidecarId)}
              />
            ))}
          </div>

          {canLoadMore && (
            <div className="load-more-wrap">
              <button className="btn btn-outline" onClick={loadMore} disabled={loading}>
                {loading ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
