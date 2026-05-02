import type { Sku } from '../../types'

export function StockBadge({ sku }: { sku: Sku }) {
  if (sku.stockLeft == null) return null
  if (sku.stockLeft <= 0) {
    return <div className="alert alert-warn">Sold out.</div>
  }
  return <div className="stock-badge">{sku.stockLeft} in stock</div>
}
