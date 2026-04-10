import { useEffect } from 'react'
import { useStore } from '../store/useStore'
import { AgentItem } from '../components/AgentItem'

interface Props {
  sidecarId: string
}

export function AgentDetail({ sidecarId }: Props) {
  const { allAgents, loading, hasMoreOnChain, init, fetchMore } = useStore()

  useEffect(() => { init() }, [])

  const agent = allAgents.find(a => a.sidecarId === sidecarId)

  // Keep fetching pages until agent is found or all transactions exhausted
  useEffect(() => {
    if (!agent && !loading && hasMoreOnChain) {
      fetchMore()
    }
  }, [agent, loading, hasMoreOnChain])

  const searching = !agent && (loading || hasMoreOnChain)

  return (
    <div className="page">
      <div className="hero">
        <p className="m-0 mb-20">
          <a className="link-inline" href={import.meta.env.BASE_URL} onClick={e => { e.preventDefault(); window.history.pushState({}, '', import.meta.env.BASE_URL); window.dispatchEvent(new PopStateEvent('popstate')) }}>
            ← back to marketplace
          </a>
        </p>
        <h1><span className="hero-bracket">&gt; </span>{agent?.name || sidecarId}</h1>
      </div>

      {searching ? (
        <div className="state-msg">Loading agent…</div>
      ) : !agent ? (
        <div className="state-msg">
          <h1>
          Agent not found.{' '}
          </h1>

          <p>
          <a className="link-inline" href={import.meta.env.BASE_URL} onClick={e => { e.preventDefault(); window.history.pushState({}, '', import.meta.env.BASE_URL); window.dispatchEvent(new PopStateEvent('popstate')) }}>
            Go to marketplace
          </a>
          </p>
        </div>
      ) : (
        <AgentItem
          agent={agent}
          expanded
          onToggle={() => {}}
          locked
        />
      )}
    </div>
  )
}
