import { normalizeDesc } from './utils'

export function AgentDesc({ description, full }: { description: string; full: boolean }) {
  const text = normalizeDesc(description)
  if (full) {
    return <p className="agent-summary-desc agent-summary-desc--full">{text}</p>
  }
  const preview = text.length > 150 ? text.slice(0, 150) + '…' : text
  return <p className="agent-summary-desc">{preview}</p>
}
