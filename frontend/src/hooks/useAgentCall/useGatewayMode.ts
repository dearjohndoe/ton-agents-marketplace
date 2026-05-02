import { useEffect } from 'react'
import { checkGatewayHealth, getConnectionMode } from '../../lib/agentClient'
import type { ConnectionMode } from '../../lib/agentClient'

export function useGatewayMode(
  endpoint: string,
  expanded: boolean,
  setConnMode: (m: ConnectionMode) => void,
) {
  useEffect(() => {
    if (!expanded) return
    checkGatewayHealth().then(() => {
      setConnMode(getConnectionMode(endpoint))
    })
  }, [expanded, endpoint])
}
