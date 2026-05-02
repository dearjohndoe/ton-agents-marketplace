import type { Sku } from '../../types'
import { nanoToTon, microToUsdt } from './utils'

export function SkuSelector({ skus, selectedId, onSelect, disabled }: {
  skus: Sku[]
  selectedId: string
  onSelect: (id: string) => void
  disabled: boolean
}) {
  return (
    <div className="sku-selector">
      <span className="meta-label">Variant</span>
      <div className="sku-list">
        {skus.map(s => {
          const soldOut = s.stockLeft != null && s.stockLeft <= 0
          const active = s.id === selectedId
          return (
            <button
              key={s.id}
              type="button"
              className={`sku-item${active ? ' sku-item--active' : ''}${soldOut ? ' sku-item--sold-out' : ''}`}
              onClick={() => !soldOut && !disabled && onSelect(s.id)}
              disabled={disabled || soldOut}
              title={soldOut ? 'Sold out' : ''}
            >
              <span className="sku-title">{s.title || s.id}</span>
              <span className="sku-price">
                {s.priceTon != null && <span className="price-ton">{nanoToTon(s.priceTon)} TON</span>}
                {s.priceTon != null && s.priceUsdt != null && <span className="price-sep"> / </span>}
                {s.priceUsdt != null && <span className="price-usdt">{microToUsdt(s.priceUsdt)} USDT</span>}
              </span>
              <span className="sku-stock">
                {soldOut ? 'Sold out'
                  : s.stockLeft != null ? `${s.stockLeft} left`
                  : '∞'}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
