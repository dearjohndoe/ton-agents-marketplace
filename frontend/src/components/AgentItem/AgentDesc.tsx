import { normalizeDesc } from './utils'

export function AgentDesc({ description, full }: { description: string; full: boolean }) {
  const text = normalizeDesc(description)
  if (full) {
    return <p className="agent-summary-desc agent-summary-desc--full">{text}</p>
  }
  let preview = text
  const parts = preview.split('\n')
  if (parts.length > 4) {
    preview = [...parts.slice(0, 3), parts.slice(3).join(' ')].join('\n') + '…'
  }
  if (preview.length > 150) preview = preview.slice(0, 150) + '…'
  return <p className="agent-summary-desc">{preview}</p>
}
