import type { Agent } from '../../types'
import { nanoToTon, microToUsdt } from './utils'

export function PriceBadge({ agent }: { agent: Agent }) {
  const hasTon = agent.price > 0
  const hasUsdt = agent.priceUsdt != null && agent.priceUsdt > 0
  if (!hasTon && !hasUsdt) return <span>--</span>
  return (
    <>
      {hasTon && <span className="price-ton">{nanoToTon(agent.price)} TON</span>}
      {hasTon && hasUsdt && <span className="price-sep"> / </span>}
      {hasUsdt && <span className="price-usdt">{microToUsdt(agent.priceUsdt!)} USDT</span>}
    </>
  )
}
