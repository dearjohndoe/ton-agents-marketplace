import type { ConnectionMode } from '../../lib/agentClient'

const connLabel: Record<ConnectionMode, string> = {
  direct: 'https', proxy: 'via proxy', insecure: 'http',
}
const connClass: Record<ConnectionMode, string> = {
  direct: 'conn-badge--ok', proxy: 'conn-badge--proxy', insecure: 'conn-badge--warn',
}

export function ConnectionBadge({ mode }: { mode: ConnectionMode }) {
  return <span className={`conn-badge ${connClass[mode]}`} title={
    mode === 'direct' ? 'Direct encrypted connection' :
    mode === 'proxy' ? 'Routed through SSL gateway' : 'Connection is not encrypted'
  }>{connLabel[mode]}</span>
}
